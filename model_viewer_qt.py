# -*- coding: utf-8 -*-
"""Visor independiente de modelos y capturas frame_trace de XXAMI.

No importa DumpAna ni Tkinter. La reconstrucción se delega en xxami_trace.py.
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import traceback
import subprocess
import json
from pathlib import Path

# Priorizar los módulos que se distribuyen junto al visor (o dentro del bundle
# de PyInstaller) frente a copias antiguas instaladas en el entorno.
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QPoint, QUrl, QSettings, QObject, QRunnable, QThreadPool, Signal, QTimer, QSize
from PySide6.QtGui import QAction, QImage, QPixmap, QKeySequence, QPainter, QPen, QColor, QFont, QIcon, QDesktopServices, QMovie
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QLabel, QTextEdit, QFileDialog, QMessageBox,
    QComboBox, QToolBar, QStatusBar, QCheckBox, QScrollArea, QPushButton, QDoubleSpinBox, QMenu,
    QDialog, QTabWidget, QFormLayout, QDialogButtonBox, QSpacerItem, QProgressBar
)
from xxami_logging import configure_crash_logging, log_message

import xxami_trace as X

# Fallar pronto con un diagnóstico claro si se carga una copia incompatible.
if not {"pan_x", "pan_y"}.issubset(__import__("inspect").signature(X.renderizar_malla).parameters):
    raise RuntimeError(
        "La copia de xxami_trace.py cargada no admite desplazamiento de cámara. "
        f"Ruta cargada: {getattr(X, '__file__', 'desconocida')}. "
        "Actualiza xxami_trace.py y vuelve a compilar el visor."
    )

try:
    from xxami_render_backend import create_backend, available_backends
except Exception:
    create_backend = available_backends = None

def application_resource(name):
    """Resuelve recursos de res/ en ejecución normal y en bundles PyInstaller."""
    filename = str(name)
    candidates = []
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(Path(bundle_dir) / "res" / filename)
    candidates.extend((
        Path(__file__).resolve().parent / "res" / filename,
        Path(sys.executable).resolve().parent / "res" / filename,
    ))
    for path in candidates:
        if path.is_file():
            return path
    return None


def application_icon(name):
    """Carga el icono de ventana desde res/, también en builds congelados."""
    candidates = [
        Path(__file__).resolve().parent / "res" / (name + ".png"),
        Path(sys.executable).resolve().parent / "res" / (name + ".png"),
    ]
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.insert(0, Path(bundle_dir) / "res" / (name + ".png"))
    for path in candidates:
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


STYLE = """
QMainWindow,QWidget { background:#202124; color:#e8eaed; font-family:'Segoe UI'; font-size:10pt; }
QTreeWidget,QTextEdit { background:#202226; color:#e8eaed; border:1px solid #41454b; }
QTreeWidget::item:selected { background:#173d30; }
QComboBox { background:#303238; color:#e8eaed; padding:5px; border:1px solid #454950; }
QToolBar,QStatusBar { background:#292b2f; color:#aeb4bd; border:0; }
QToolButton { color:#e8eaed; }
"""

_RE_BUF = re.compile(r"^(?:vb|ib|vbib)_([0-9a-fA-F]+)_\d+\.buf$", re.I)
_RE_PART = re.compile(r"^Part\d+-vb0=([0-9a-fA-F]+)\.buf$", re.I)
_RE_MODEL_DIR = re.compile(r"^Model_\d+$", re.I)
MODES = {"Alambre":"alambre", "Sólido":"solido", "Puntos":"puntos", "Material":"material"}


def is_model_buffer(path):
    name = Path(path).name
    return bool(_RE_BUF.match(name) or _RE_PART.match(name))


class ModelViewport(QLabel):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer

    def mousePressEvent(self, event):
        # Consumir el evento aquí evita que Qt/Windows lo propague al contenedor
        # o lo interprete como una interacción de movimiento de ventana.
        if event.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            self.viewer._mouse_press(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.viewer._mouse_move(event)
        if self.viewer.drag_pos is not None:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            self.viewer._mouse_release(event)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.viewer._mouse_wheel(event)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        gizmo = getattr(self.viewer, "orientation_gizmo", None)
        if gizmo is not None:
            gizmo.move(self.width() - gizmo.width() - 8, 8)
            gizmo.raise_()
        self.viewer._position_details_overlay()
        if self.viewer.mesh is not None:
            self.viewer.redraw(force=True)


class OrientationGizmo(QWidget):
    """Gizmo de orientación 3D superpuesto en la esquina del viewport."""
    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self.setFixedSize(116, 116)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setToolTip(viewer.viewer_text("orientation_tooltip", "Pulsa un eje para orientar la vista"))

    def _axis_points(self):
        yaw, pitch = self.viewer.rot_y, self.viewer.rot_x
        cy, sy = np.cos(yaw), np.sin(yaw)
        cp, sp = np.cos(pitch), np.sin(pitch)
        center = np.array([58.0, 58.0])
        points = {}
        for axis, vec, color in (
            ("X", np.array([1.0, 0.0, 0.0]), QColor("#ff6666")),
            ("Y", np.array([0.0, 1.0, 0.0]), QColor("#72d572")),
            ("Z", np.array([0.0, 0.0, 1.0]), QColor("#669dff")),
        ):
            for sign in (1, -1):
                x, y, z = vec * sign
                xr = cy * x + sy * z
                zr = -sy * x + cy * z
                yr = cp * y - sp * zr
                depth = sp * y + cp * zr
                points[axis + ("+" if sign > 0 else "-")] = (
                    center + np.array([xr, -yr]) * 39.0, depth, color)
        return center, points

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center, points = self._axis_points()
        painter.setPen(QPen(QColor(20, 22, 26, 190), 1))
        painter.setBrush(QColor(20, 22, 26, 175))
        painter.drawEllipse(5, 5, 106, 106)
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        for name, (point, depth, color) in points.items():
            painter.setPen(QPen(color, 4 if depth >= 0 else 2))
            painter.drawLine(int(center[0]), int(center[1]), int(point[0]), int(point[1]))
            painter.setBrush(color if depth >= 0 else QColor(55, 58, 64))
            radius = 5 if depth >= 0 else 4
            painter.drawEllipse(int(point[0]) - radius, int(point[1]) - radius, radius * 2, radius * 2)
            painter.setPen(QPen(QColor("#ffffff") if depth >= 0 else QColor("#aeb4bd"), 1))
            painter.drawText(int(point[0]) - 7, int(point[1]) - 8, name)
        painter.end()

    def mousePressEvent(self, event):
        center, points = self._axis_points()
        pos = np.array([event.position().x(), event.position().y()])
        choices = sorted((float(np.linalg.norm(point - pos)), name, depth)
                         for name, (point, depth, _color) in points.items())
        distance, axis, depth = choices[0]
        if distance <= 17:
            self.viewer.set_axis_view(axis[0], 1 if axis.endswith("+") else -1)
            event.accept()
            return
        super().mousePressEvent(event)



def _viewer_gpu_adapters():
    adapters = []
    if sys.platform == "win32":
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                capture_output=True, text=True, timeout=8, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            adapters.extend(dict.fromkeys(x.strip() for x in result.stdout.splitlines() if x.strip()))
        except Exception: pass
    elif sys.platform.startswith("linux"):
        try:
            result = subprocess.run(["lspci", "-D"], capture_output=True, text=True, timeout=5, check=False)
            for line in result.stdout.splitlines():
                if re.search(r"VGA compatible controller|3D controller|Display controller", line, re.I):
                    match = re.match(r"([0-9a-fA-F:.]+)\s+.*?:\s*(.*)", line)
                    if match:
                        address, name = match.groups()
                        adapters.append((name.strip(), "pci-" + address.replace(":", "_").replace(".", "_")))
        except Exception: pass
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=12, check=False)
            for item in json.loads(result.stdout or "{}").get("SPDisplaysDataType", []):
                name = item.get("sppci_model") or item.get("_name")
                if name: adapters.append(name)
        except Exception: pass
    return adapters


def set_windows_high_performance_preference(executable_path):
    """Solicita a Windows la GPU de alto rendimiento para un ejecutable concreto.

    Es una preferencia del sistema operativo, no una selección de fabricante:
    funciona con controladores híbridos NVIDIA/AMD compatibles y no presupone
    la presencia de una GPU de una marca determinada.
    """
    if sys.platform != "win32":
        raise OSError("La preferencia gráfica de Windows solo está disponible en Windows.")
    import winreg

    executable = os.path.normcase(os.path.abspath(str(executable_path)))
    key_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, key_path, 0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
    ) as key:
        try:
            current, value_type = winreg.QueryValueEx(key, executable)
        except FileNotFoundError:
            current, value_type = "", winreg.REG_SZ
        if value_type != winreg.REG_SZ:
            raise OSError("Windows almacena una preferencia gráfica con un tipo inesperado.")
        entries = [part.strip() for part in str(current).split(";")
                   if part.strip() and not part.strip().casefold().startswith("gpupreference=")]
        entries.append("GpuPreference=2")
        winreg.SetValueEx(key, executable, 0, winreg.REG_SZ, ";".join(entries) + ";")


class ViewerAboutLogo(QLabel):
    """Muestra el logotipo original de res/viewer_logo.png."""
    def __init__(self, parent=None, translate=None):
        super().__init__(parent)
        self._translate = translate or (lambda key, fallback="": fallback)
        self._source_pixmap = QPixmap()
        resource = application_resource("viewer_logo.png")
        if resource is not None:
            self._source_pixmap = QPixmap(str(resource))
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(280, 252)
        self.setMaximumWidth(330)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._update_pixmap()

    def _update_pixmap(self):
        if not self._source_pixmap.isNull():
            self.setPixmap(self._source_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self.setToolTip(self._translate("logo_tooltip", "res/viewer_logo.png"))
        else:
            self.setText(self._translate("logo_missing", "No se encontró res/viewer_logo.png"))
            self.setToolTip(
                "Coloca viewer_logo.png en la carpeta res junto a model_viewer_qt.py "
                "o en res dentro del paquete de la aplicación."
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()


class _GraphicsQuerySignals(QObject):
    finished = Signal(int, object, object, object)


class _GraphicsQueryWorker(QRunnable):
    def __init__(self, generation, gpu_preference, include_adapters):
        super().__init__()
        self.generation = generation
        self.gpu_preference = gpu_preference
        self.include_adapters = include_adapters
        self.signals = _GraphicsQuerySignals()

    def run(self):
        adapters = None
        backends = None
        error = None
        try:
            if self.include_adapters:
                adapters = _viewer_gpu_adapters()
            backends = (available_backends(self.gpu_preference) if available_backends
                        else [{"id": "opengl", "label": "OpenGL 3.3 Core"}])
        except Exception as exc:
            error = str(exc)
        self.signals.finished.emit(self.generation, adapters, backends, error)


class ViewerSettingsDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.setWindowTitle(parent.viewer_text("settings_title", "Configuración del visor 3D"))
        self.setMinimumSize(620, 440)
        self.resize(680, 500)
        self.setMaximumWidth(760)
        self.config = config
        tabs = QTabWidget()
        general = QWidget()
        form = QFormLayout(general)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(15)
        form.setContentsMargins(16, 20, 16, 18)
        self.language = QComboBox()
        self.language.addItem(parent.viewer_text("language_spanish", "Español"), "es")
        self.language.addItem(parent.viewer_text("language_english", "English"), "en")
        saved_language = str(config.value("general/language", "es"))
        self.language.setCurrentIndex(max(0, self.language.findData(saved_language)))
        form.addRow(parent.viewer_text("language", "Idioma") + ":", self.language)
        self._generation = 0
        self._workers = {}
        self._saved_gpu = str(config.value("general/gpu", "default"))
        self._saved_api = str(config.value("general/api", "opengl"))
        self._adapter_query_done = False
        self.gpu = QComboBox()
        self.gpu.addItem(parent.viewer_text("gpu_auto", "Automático (GPU predeterminada)"), "default")
        self.gpu.setEnabled(False)
        form.addRow(parent.viewer_text("gpu_adapter", "Adaptador gráfico de renderizado") + ":", self.gpu)
        self.api = QComboBox()
        self.api.addItem(parent.viewer_text("loading", "Cargando…"), self._saved_api)
        self.api.setEnabled(False)
        form.addRow(parent.viewer_text("render_api", "API utilizada para renderizado") + ":", self.api)
        self.loading_panel = QWidget()
        loading_layout = QVBoxLayout(self.loading_panel)
        loading_layout.setContentsMargins(8, 8, 8, 8)
        loading_layout.setAlignment(Qt.AlignHCenter)
        self.loading_gif_label = QLabel(alignment=Qt.AlignCenter)
        self.loading_movie = QMovie(str(application_resource("loading.gif") or ""))
        if self.loading_movie.isValid():
            self.loading_movie.setScaledSize(QSize(104, 104))
            self.loading_gif_label.setMovie(self.loading_movie)
            self.loading_movie.start()
        else:
            self.loading_gif_label.setText("◌")
        loading_layout.addWidget(self.loading_gif_label, 0, Qt.AlignHCenter)
        self.loading_label = QLabel(parent.viewer_text("loading_adapters", "Cargando adaptadores gráficos…"), alignment=Qt.AlignCenter)
        loading_layout.addWidget(self.loading_label, 0, Qt.AlignHCenter)
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setTextVisible(False)
        self.loading_progress.setFixedHeight(9)
        self.loading_progress.setMaximumWidth(340)
        loading_layout.addWidget(self.loading_progress, 0, Qt.AlignHCenter)
        form.addRow(self.loading_panel)
        self.gpu.currentIndexChanged.connect(self._refresh_api_options)
        QTimer.singleShot(0, self._start_initial_query)
        note = QLabel(parent.viewer_text("settings_note", "Las APIs wgpu (Vulkan, Direct3D 12 y OpenGL) solo aparecen cuando la GPU seleccionada ofrece un adaptador capaz de crear un dispositivo. En Windows, OpenGL nativo y WGPU OpenGL dependen de la GPU que asigne el controlador al proceso. Puedes solicitar a Windows la GPU de alto rendimiento; la elección final corresponde al sistema y al controlador, sin asumir NVIDIA o AMD. El dispositivo wgpu activo se muestra en la barra de estado. Reinicia el visor para aplicar cambios."))
        note.setWordWrap(True)
        note.setMaximumWidth(610)
        form.addRow(note)
        if sys.platform == "win32":
            high_perf_button = QPushButton(parent.viewer_text("high_performance_button", "Solicitar GPU de alto rendimiento en Windows…"))
            high_perf_button.setMinimumHeight(34)
            high_perf_button.clicked.connect(self._request_windows_high_performance)
            form.addRow(high_perf_button)
        form.addItem(QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Expanding))
        tabs.addTab(general, parent.viewer_text("general", "General"))

        about = QWidget()
        about_layout = QHBoxLayout(about)
        about_layout.setContentsMargins(22, 22, 22, 22)
        about_layout.setSpacing(28)
        about_layout.addWidget(ViewerAboutLogo(about, parent.viewer_text), 1)
        description = QLabel(parent.viewer_text("about_description", "AMI 3D Viewer es un visualizador de modelos y trazado de frames, utilizado para la exploración y visualización de volcados generados por el módulo XXAMI (Android Model Importer). AMI 3D Viewer es parte de la suite de analizador, visualizador y modificador de recursos para API Vulkan Android: XXAMI DumpAna. Creado por Kokokuro*"))
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignCenter)
        description.setFont(QFont("Segoe UI", 13, QFont.DemiBold))
        description.setMinimumWidth(250)
        about_layout.addWidget(description, 1)
        tabs.addTab(about, parent.viewer_text("about", "Acerca de"))
        buttons = QDialogButtonBox()
        apply_button = buttons.addButton(parent.viewer_text("apply", "Aplicar"), QDialogButtonBox.ApplyRole)
        accept_button = buttons.addButton(parent.viewer_text("accept", "Aceptar"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(parent.viewer_text("cancel", "Cancelar"), QDialogButtonBox.RejectRole)
        self._apply_button = apply_button
        self._accept_button = accept_button
        self._apply_button.setEnabled(False)
        self._accept_button.setEnabled(False)
        apply_button.clicked.connect(self.apply)
        accept_button.clicked.connect(self.accept_and_apply)
        cancel_button.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _show_loading(self):
        self.loading_panel.setVisible(True)
        self.gpu.setEnabled(False)
        self.api.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._accept_button.setEnabled(False)
        self.loading_label.setText(self.parent().viewer_text("loading_adapters", "Cargando adaptadores gráficos…"))
        self.loading_progress.setRange(0, 0)
        if self.loading_movie.isValid():
            self.loading_movie.start()

    def _start_initial_query(self):
        self._start_query(self._saved_gpu, include_adapters=True)

    def _start_query(self, gpu, include_adapters=False):
        self._generation += 1
        generation = self._generation
        worker = _GraphicsQueryWorker(generation, gpu, include_adapters)
        worker.signals.finished.connect(self._query_finished)
        self._workers[generation] = worker
        self._show_loading()
        QThreadPool.globalInstance().start(worker)

    def _query_finished(self, generation, adapters, backends, error):
        self._workers.pop(generation, None)
        if generation != self._generation:
            return
        if adapters is not None:
            self.gpu.blockSignals(True)
            self.gpu.clear()
            self.gpu.addItem(self.parent().viewer_text("gpu_auto", "Automático (GPU predeterminada)"), "default")
            for adapter in adapters:
                if isinstance(adapter, tuple):
                    self.gpu.addItem(adapter[0], adapter[1])
                else:
                    self.gpu.addItem(adapter, adapter)
            index = self.gpu.findData(self._saved_gpu)
            if index < 0 and self._saved_gpu != "default":
                self.gpu.addItem(self._saved_gpu + " (no detectada)", self._saved_gpu)
                index = self.gpu.count() - 1
            self.gpu.setCurrentIndex(max(0, index))
            self.gpu.blockSignals(False)
            self._adapter_query_done = True
        options = backends or [{"id": "opengl", "label": "OpenGL 3.3 Core"}]
        selected_api = self.api.currentData() or self._saved_api
        self.api.blockSignals(True)
        self.api.clear()
        for backend in options:
            self.api.addItem(backend["label"], backend["id"])
        index = self.api.findData(selected_api)
        if index < 0:
            index = self.api.findData("opengl")
        self.api.setCurrentIndex(max(0, index))
        self.api.blockSignals(False)
        self._saved_api = self.api.currentData() or "opengl"
        self.loading_panel.setVisible(False)
        if self.loading_movie.isValid():
            self.loading_movie.stop()
        self.gpu.setEnabled(True)
        self.api.setEnabled(True)
        self._apply_button.setEnabled(True)
        self._accept_button.setEnabled(True)
        if error:
            self.loading_label.setText(self.parent().viewer_text("adapter_query_error", "Error al consultar adaptadores: {error}").format(error=error))

    def _refresh_api_options(self, *_args):
        if self._adapter_query_done:
            self._start_query(self.gpu.currentData() or "default")

    def accept_and_apply(self):
        self.apply()
        self.accept()

    def _request_windows_high_performance(self):
        executable = str(Path(sys.executable).resolve())
        frozen = bool(getattr(sys, "frozen", False))
        scope_note = (
            self.parent().viewer_text("high_perf_scope_exe", "El ajuste se aplicará al ejecutable del visor.")
            if frozen else
            self.parent().viewer_text("high_perf_scope_python", "Estás ejecutando el visor desde Python: el ajuste se aplicará a este intérprete (python.exe/pythonw.exe) y puede afectar a otros programas que utilicen el mismo intérprete.")
        )
        answer = QMessageBox.question(
            self, self.parent().viewer_text("high_perf_title", "Preferencia gráfica de Windows"),
            self.parent().viewer_text("high_perf_question", "Se solicitará a Windows la GPU de alto rendimiento para:\n{executable}\n\n{scope_note}\n\nWindows y el controlador decidirán qué adaptador de alto rendimiento usar. Esto no garantiza una GPU concreta y requiere reiniciar el visor. ¿Deseas aplicar el ajuste.").format(executable=executable, scope_note=scope_note),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        try:
            set_windows_high_performance_preference(executable)
            QMessageBox.information(
                self, self.parent().viewer_text("high_perf_saved_title", "Preferencia guardada"),
                self.parent().viewer_text("high_perf_saved", "Windows guardó la preferencia de alto rendimiento. Cierra y vuelve a abrir el visor para que el controlador pueda aplicarla. La preferencia es independiente del fabricante (NVIDIA/AMD).")
            )
        except Exception as exc:
            QMessageBox.warning(
                self, self.parent().viewer_text("high_perf_error_title", "No se pudo guardar la preferencia"),
                self.parent().viewer_text("high_perf_error", "No se pudo actualizar la preferencia gráfica de Windows:\n{error}").format(error=exc)
            )

    def apply(self):
        self.config.setValue("general/language", self.language.currentData() or "es")
        self.config.setValue("general/gpu", self.gpu.currentData() or "default")
        self.config.setValue("general/api", self.api.currentData() or "opengl")
        self.config.sync()


class ModelViewer(QMainWindow):
    def __init__(self, root=None, initial_file=None, log_path=None):
        super().__init__()
        self.log_path = Path(log_path).resolve() if log_path else Path(__file__).resolve().with_name("xxami_crash_log.txt")
        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        self.config_path = app_dir / "viewer.ini"
        self.config = QSettings(str(self.config_path), QSettings.IniFormat)
        self.language = str(self.config.value("general/language", "es"))
        self._language_strings = {}
        language_dirs = []
        if getattr(sys, "frozen", False):
            # Los catálogos son externos al bundle y deben permanecer junto al EXE.
            language_dirs.append(Path(sys.executable).resolve().parent / "lang" / "viewer_lang")
            # Compatibilidad con builds anteriores que aún empaquetaban lang/.
            bundle_dir = getattr(sys, "_MEIPASS", None)
            if bundle_dir:
                language_dirs.append(Path(bundle_dir) / "lang" / "viewer_lang")
        else:
            language_dirs.append(Path(__file__).resolve().parent / "lang" / "viewer_lang")
        for language_dir in language_dirs:
            language_file = language_dir / f"{self.language}.json"
            try:
                self._language_strings = json.loads(
                    language_file.read_text(encoding="utf-8")
                ).get("strings", {})
                break
            except (OSError, ValueError, TypeError):
                continue
        for key, value in (("general/language", "es"), ("general/gpu", "default"), ("general/api", "opengl")):
            if self.config.value(key) is None: self.config.setValue(key, value)
        self.config.sync()
        self._apply_gpu_preference()
        self.setWindowTitle(self.viewer_text("window_title", "AMI: 3D Viewer"))
        self.setWindowIcon(application_icon("viewer_icon"))
        self.resize(1450, 900)
        self.setMinimumSize(1180, 620)
        self.setStyleSheet(STYLE)
        self.root_path = Path(root).resolve() if root else None
        self.index = X.IndiceRecursos()
        self.traces = {}
        self.trace = None
        self.draw = None
        self.mesh = None
        self.current_buffer = None
        self.rot_x, self.rot_y, self.zoom = .5, .6, 1.0
        self.pan_x, self.pan_y = 0.0, 0.0
        self.drag_pos = None
        self.pan_drag = False
        self.material_types = ("Ignorar", "Albedo", "Lightmap", "Normal", "Metallic", "Roughness", "Emission", "AO", "Opacity")
        self.material_entries = []
        self.material_paths = []
        self.selected_material_entry = None
        self.last_image = None
        self._material_cache_key = None
        self._material_cache_image = None
        self.render_backend = None
        self.gl_context = None  # Referencias de compatibilidad/diagnóstico OpenGL
        self.gl_renderer = None
        self.gl_error_reported = False
        self._build_ui()
        if initial_file:
            self.open_path(initial_file, root=self.root_path)
        elif self.root_path and self.root_path.is_dir():
            self.scan_root(self.root_path)

    def viewer_text(self, key, fallback=""):
        return self._language_strings.get(key, fallback)

    def open_settings(self):
        dialog = ViewerSettingsDialog(self, self.config)
        dialog.exec()
        self.config.sync()
        self._apply_gpu_preference()
        if self.render_backend is not None:
            self.statusBar().showMessage(self.viewer_text("restart_graphics", "Preferencias guardadas. Reinicia el visor para recrear el dispositivo gráfico."), 7000)

    def _apply_gpu_preference(self):
        selected = str(self.config.value("general/gpu", "default"))
        if selected == "default":
            os.environ.pop("DRI_PRIME", None)
            os.environ.pop("__NV_PRIME_RENDER_OFFLOAD", None)
            os.environ.pop("__GLX_VENDOR_LIBRARY_NAME", None)
        elif sys.platform.startswith("linux"):
            if selected.startswith("pci-"): os.environ["DRI_PRIME"] = selected
            elif "nvidia" in selected.casefold():
                os.environ["__NV_PRIME_RENDER_OFFLOAD"] = "1"
                os.environ["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"

    def open_log_file(self):
        if not self.log_path.is_file():
            QMessageBox.information(self, self.viewer_text("diagnostics", "Diagnóstico"), self.viewer_text("no_log", "Todavía no existe un registro de errores."))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path)))

    def export_log_file(self):
        if not self.log_path.is_file():
            QMessageBox.information(self, self.viewer_text("diagnostics", "Diagnóstico"), self.viewer_text("no_log", "Todavía no existe un registro de errores."))
            return
        target, _ = QFileDialog.getSaveFileName(self, self.viewer_text("export_log", "Exportar registro"), str(Path.home() / "xxami_crash_log.txt"), self.viewer_text("log_filter", "Registro de texto (*.txt)"))
        if not target:
            return
        try:
            Path(target).write_bytes(self.log_path.read_bytes())
            self.statusBar().showMessage(self.viewer_text("log_exported", "Registro exportado correctamente"), 4000)
        except Exception as exc:
            QMessageBox.critical(self, self.viewer_text("export_log", "Exportar registro"), str(exc))

    def _build_ui(self):
        menu = self.menuBar().addMenu(self.viewer_text("file_menu", "Archivo"))
        self._action(menu, self.viewer_text("open_file", "Abrir archivo…"), self.open_dialog, QKeySequence.Open)
        self._action(menu, self.viewer_text("open_folder", "Abrir carpeta…"), self.folder_dialog, "Ctrl+Shift+O")
        menu.addSeparator()
        self._action(menu, self.viewer_text("export_obj_menu", "Exportar modelo como OBJ…"), self.export_obj, "Ctrl+E")
        self._action(menu, self.viewer_text("refresh_folder", "Actualizar carpeta"), self.refresh, "F5")
        menu.addSeparator()
        self._action(menu, self.viewer_text("exit", "Salir"), self.close, "Ctrl+Q")

        diagnostics = self.menuBar().addMenu(self.viewer_text("diagnostics", "Diagnóstico"))
        self._action(diagnostics, self.viewer_text("open_error_log", "Abrir registro de errores"), self.open_log_file)
        self._action(diagnostics, self.viewer_text("export_log_menu", "Exportar registro…"), self.export_log_file)
        settings_menu = self.menuBar().addMenu(self.viewer_text("settings_menu", "Configuración"))
        self._action(settings_menu, self.viewer_text("preferences", "Preferencias…"), self.open_settings)

        bar = QToolBar(self.viewer_text("toolbar_title", "Visor"))
        self.addToolBar(bar)
        for label, callback in ((self.viewer_text("open", "Abrir"), self.open_dialog), (self.viewer_text("folder", "Carpeta"), self.folder_dialog),
                                (self.viewer_text("export_obj", "Exportar OBJ"), self.export_obj)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            bar.addAction(action)
        bar.addSeparator()
        bar.addWidget(QLabel(" " + self.viewer_text("visualization", "Visualización: ") + " "))
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        self.mode.currentTextChanged.connect(self.redraw)
        self.mode.setMinimumWidth(120)
        bar.addWidget(self.mode)
        self.fit_button = QAction(self.viewer_text("reset_view", "Restablecer vista"), self)
        self.fit_button.triggered.connect(self.reset_view)
        bar.addAction(self.fit_button)

        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([self.viewer_text("tree_header", "Capturas, modelos y recursos")])
        self.tree.setMinimumWidth(290)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        split.addWidget(self.tree)

        workspace = QSplitter(Qt.Horizontal)
        material_panel = QWidget()
        material_panel.setMinimumWidth(220)
        material_layout = QVBoxLayout(material_panel)
        material_layout.setContentsMargins(6, 6, 6, 6)
        material_layout.addWidget(QLabel(self.viewer_text("model_textures", "Texturas del modelo")))
        self.add_texture_button = QPushButton(self.viewer_text("add_texture", "Añadir textura…"))
        self.add_texture_button.clicked.connect(self.add_material_texture)
        material_layout.addWidget(self.add_texture_button)
        self.material_list_widget = QWidget()
        self.material_list_layout = QVBoxLayout(self.material_list_widget)
        self.material_list_layout.setContentsMargins(2, 2, 2, 2)
        self.material_list_layout.setSpacing(4)
        self.material_list_layout.addStretch()
        self.material_scroll = QScrollArea()
        self.material_scroll.setWidgetResizable(True)
        self.material_scroll.setWidget(self.material_list_widget)
        material_layout.addWidget(self.material_scroll, 1)

        material_layout.addWidget(QLabel(self.viewer_text("texture_preview", "Previsualización de textura")))
        self.texture_preview = QLabel(self.viewer_text("select_texture", "Selecciona una textura de la lista"))
        self.texture_preview.setAlignment(Qt.AlignCenter)
        self.texture_preview.setMinimumHeight(150)
        self.texture_preview.setMaximumHeight(230)
        self.texture_preview.setStyleSheet("background:#111315;border:1px solid #41444a;border-radius:4px;color:#9aa0a6;")
        self.texture_preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self.texture_preview.customContextMenuRequested.connect(self._texture_preview_context_menu)
        material_layout.addWidget(self.texture_preview)
        workspace.addWidget(material_panel)

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(3)
        center_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewport = ModelViewport(self)
        self.viewport.setText(self.viewer_text("empty_viewport", "Abre un frame_trace.json, un .buf de geometría o una carpeta de volcado"))
        self.viewport.setAlignment(Qt.AlignCenter)
        self.viewport.setMinimumSize(320, 240)
        self.viewport.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewport.setStyleSheet("background:#111111;border:1px solid #41444a;")
        self.viewport.setMouseTracking(True)
        self.viewport.setAttribute(Qt.WA_NoMousePropagation, True)
        self.viewport.setFocusPolicy(Qt.StrongFocus)
        self.viewport.setToolTip(self.viewer_text("camera_tooltip", "Izquierdo: orbitar · derecho/central: desplazar · rueda: zoom · WASD/flechas: orbitar · Q/E: roll · +/-: zoom · 0: restablecer"))
        self.orientation_gizmo = OrientationGizmo(self.viewport, self)
        self.orientation_gizmo.move(self.viewport.width() - 122, 6)
        self.orientation_gizmo.raise_()

        # Panel flotante de información: anclado a la esquina inferior derecha,
        # independiente del gizmo y superpuesto al viewport.
        self.details_overlay = QWidget(self.viewport)
        self.details_overlay.setObjectName("modelDetailsOverlay")
        self.details_overlay.setAttribute(Qt.WA_StyledBackground, True)
        self.details_overlay.setStyleSheet(
            "#modelDetailsOverlay { background:rgba(25,28,32,218); "
            "border:1px solid rgba(39,181,154,170); border-radius:7px; }"
        )
        overlay_layout = QVBoxLayout(self.details_overlay)
        overlay_layout.setContentsMargins(7, 5, 7, 7)
        overlay_layout.setSpacing(4)
        self.details_toggle = QPushButton("⌄  " + self.viewer_text("model_information", "Información del modelo"))
        self.details_toggle.setCursor(Qt.PointingHandCursor)
        self.details_toggle.setStyleSheet(
            "QPushButton { text-align:left; color:#e8eaed; font-weight:600; "
            "background:rgba(39,181,154,45); border:0; border-radius:4px; padding:6px; }"
        )
        self.details_toggle.clicked.connect(self._toggle_details_overlay)
        overlay_layout.addWidget(self.details_toggle)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumWidth(230)
        self.details.setStyleSheet(
            "QTextEdit { background:rgba(12,14,17,145); color:#e8eaed; "
            "border:1px solid rgba(255,255,255,35); border-radius:4px; padding:4px; }"
        )
        self.details.setFixedHeight(164)
        overlay_layout.addWidget(self.details)
        self.details_overlay.setFixedWidth(330)
        self.details_overlay.adjustSize()
        self.details_overlay.raise_()
        center_layout.addWidget(self.viewport, 1)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel(self.viewer_text("position", "Posición:")))
        self.position_combo = QComboBox()
        self.position_combo.currentIndexChanged.connect(self.rebuild_trace_mesh)
        selector_row.addWidget(self.position_combo, 1)
        selector_row.addWidget(QLabel(self.viewer_text("uv", "UV:")))
        self.uv_combo = QComboBox()
        self.uv_combo.currentIndexChanged.connect(self.rebuild_trace_mesh)
        selector_row.addWidget(self.uv_combo, 1)
        center_layout.addLayout(selector_row)

        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel(self.viewer_text("rotation_x", "Rot X")))
        self.rot_x_control = QDoubleSpinBox()
        self.rot_x_control.setRange(-360.0, 360.0)
        self.rot_x_control.setSingleStep(5.0)
        self.rot_x_control.setSuffix("°")
        self.rot_x_control.setValue(28.65)
        self.rot_x_control.setMaximumWidth(82)
        camera_row.addWidget(self.rot_x_control)
        camera_row.addWidget(QLabel(self.viewer_text("rotation_y", "Rot Y")))
        self.rot_y_control = QDoubleSpinBox()
        self.rot_y_control.setRange(-360.0, 360.0)
        self.rot_y_control.setSingleStep(5.0)
        self.rot_y_control.setSuffix("°")
        self.rot_y_control.setValue(34.38)
        self.rot_y_control.setMaximumWidth(82)
        camera_row.addWidget(self.rot_y_control)
        camera_row.addWidget(QLabel(self.viewer_text("scale", "Escala")))
        self.zoom_control = QDoubleSpinBox()
        self.zoom_control.setRange(0.1, 20.0)
        self.zoom_control.setSingleStep(0.1)
        self.zoom_control.setValue(1.0)
        self.zoom_control.setMaximumWidth(82)
        camera_row.addWidget(self.zoom_control)
        camera_row.addWidget(QLabel(self.viewer_text("pan_x", "Despl. X")))
        self.pan_x_control = QDoubleSpinBox()
        self.pan_x_control.setRange(-2000, 2000)
        self.pan_x_control.setSingleStep(10)
        self.pan_x_control.setMaximumWidth(82)
        camera_row.addWidget(self.pan_x_control)
        camera_row.addWidget(QLabel(self.viewer_text("pan_y", "Y")))
        self.pan_y_control = QDoubleSpinBox()
        self.pan_y_control.setRange(-2000, 2000)
        self.pan_y_control.setSingleStep(10)
        self.pan_y_control.setMaximumWidth(82)
        camera_row.addWidget(self.pan_y_control)
        self.floor_grid_checkbox = QCheckBox(self.viewer_text("floor_grid", "Piso cuadriculado"))
        self.floor_grid_checkbox.setToolTip(self.viewer_text("floor_grid_tooltip", "Mostrar una cuadrícula de referencia detrás del modelo"))
        self.floor_grid_checkbox.toggled.connect(self.redraw)
        camera_row.addWidget(self.floor_grid_checkbox)
        for control in (self.rot_x_control, self.rot_y_control, self.zoom_control,
                        self.pan_x_control, self.pan_y_control):
            control.valueChanged.connect(self._camera_changed)
        camera_row.addStretch(1)
        center_layout.addLayout(camera_row)
        workspace.addWidget(center_panel)

        workspace.setSizes([260, 1080])
        workspace.setStretchFactor(0, 0)
        workspace.setStretchFactor(1, 1)

        split.addWidget(workspace)
        split.setSizes([280, 1160])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(self.viewer_text("ready", "Listo"))

    def _position_details_overlay(self):
        overlay = getattr(self, "details_overlay", None)
        if overlay is None:
            return
        margin = 10
        x = max(margin, self.viewport.width() - overlay.width() - margin)
        y = max(margin, self.viewport.height() - overlay.height() - margin)
        overlay.move(x, y)
        overlay.raise_()

    def _toggle_details_overlay(self):
        expanded = self.details.isVisible()
        self.details.setVisible(not expanded)
        self.details_toggle.setText(("›  " if expanded else "⌄  ") + self.viewer_text("model_information", "Información del modelo"))
        self.details_overlay.adjustSize()
        self._position_details_overlay()

    def _action(self, menu, label, callback, shortcut=None):
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.viewer_text("open_resource_title", "Abrir recurso XXAMI"), str(self.root_path or Path.home()),
            self.viewer_text("resource_filter", "Recursos XXAMI (frame_trace.json *.buf);;Todos los archivos (*)"))
        if path:
            self.open_path(path)

    def folder_dialog(self):
        path = QFileDialog.getExistingDirectory(self, self.viewer_text("open_dump_folder", "Abrir carpeta de volcado"),
                                                str(self.root_path or Path.home()))
        if path:
            self.scan_root(path)

    def refresh(self):
        if self.root_path and self.root_path.is_dir():
            self.scan_root(self.root_path)

    def _root_for_file(self, path):
        path = Path(path).resolve()
        if path.name == "frame_trace.json" and path.parent.name.lower().startswith("frame_trace"):
            return path.parent.parent
        return path.parent

    def open_path(self, path, root=None):
        path = Path(path).expanduser().resolve()
        if not path.exists():
            QMessageBox.warning(self, self.viewer_text("open_resource_title", "Abrir recurso"), self.viewer_text("missing_file", "No existe el archivo:\n{path}").format(path=path))
            return
        base = Path(root).resolve() if root and Path(root).is_dir() else self._root_for_file(path)
        self.scan_root(base, initial=path)

    def scan_root(self, root, initial=None):
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            QMessageBox.warning(self, self.viewer_text("open_dump_folder", "Carpeta"), self.viewer_text("missing_folder", "No existe la carpeta:\n{path}").format(path=root))
            return
        self.root_path = root
        self.index.escanear(root)
        self.traces = {}
        self.tree.clear()
        self.trace_nodes = {}
        self.model_nodes = {}
        self.buffer_nodes = {}

        root_item = QTreeWidgetItem([f"Carpeta: {root.name}"])
        root_item.setData(0, Qt.UserRole, ("root", str(root)))
        self.tree.addTopLevelItem(root_item)

        trace_group = QTreeWidgetItem(["Frame Trace"])
        root_item.addChild(trace_group)
        for trace_path in self.index.trazas:
            label = trace_path.parent.name or trace_path.name
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, ("trace", str(trace_path)))
            trace_group.addChild(item)
            self.trace_nodes[str(trace_path)] = item

        models_group = QTreeWidgetItem(["Modelos empaquetados"])
        root_item.addChild(models_group)
        model_dirs = []
        for models_dir in root.rglob("Models"):
            if not models_dir.is_dir():
                continue
            children = sorted((p for p in models_dir.iterdir()
                               if p.is_dir() and _RE_MODEL_DIR.match(p.name)),
                              key=lambda p: p.name.lower())
            if children:
                model_dirs.extend(children)
            elif any(_RE_PART.match(p.name) for p in models_dir.glob("*.buf")):
                model_dirs.append(models_dir)
        for folder in sorted(set(model_dirs), key=lambda p: str(p).lower()):
            item = QTreeWidgetItem([str(folder.relative_to(root))])
            item.setData(0, Qt.UserRole, ("model", str(folder)))
            models_group.addChild(item)
            self.model_nodes[str(folder)] = item
            self._populate_model_item(item, folder)

        loose_group = QTreeWidgetItem(["Buffers de geometría"])
        root_item.addChild(loose_group)
        for path in sorted(root.rglob("*.buf"), key=lambda p: str(p).lower()):
            if not is_model_buffer(path):
                continue
            # Los PartNN se muestran bajo su modelo empaquetado para no duplicarlos.
            if _RE_PART.match(path.name) and any(path.is_relative_to(m) for m in model_dirs):
                continue
            item = QTreeWidgetItem([str(path.relative_to(root))])
            item.setData(0, Qt.UserRole, ("buffer", str(path)))
            loose_group.addChild(item)
            self.buffer_nodes[str(path)] = item

        root_item.setExpanded(True)
        trace_group.setExpanded(True)
        models_group.setExpanded(True)
        loose_group.setExpanded(True)
        self.statusBar().showMessage(self.viewer_text("frame_scan_status", "{traces} captura(s) · {buffers} buffer(s) reconocible(s)").format(traces=len(self.index.trazas), buffers=len(self.buffer_nodes)))
        if initial:
            p = str(Path(initial).resolve())
            item = self.trace_nodes.get(p) or self.buffer_nodes.get(p)
            if item is None:
                for model_path, model_item in self.model_nodes.items():
                    if Path(p).parent == Path(model_path) or Path(p).is_relative_to(Path(model_path)):
                        item = model_item
                        break
            if item:
                self.tree.setCurrentItem(item)
                if Path(p).name == "frame_trace.json":
                    self.load_trace(p)
                elif Path(p).suffix.lower() == ".buf":
                    self.load_buffer(p)
            elif Path(p).name == "frame_trace.json":
                self.load_trace(p)
            elif Path(p).suffix.lower() == ".buf":
                self.load_buffer(p)
        elif self.index.trazas:
            self.tree.setCurrentItem(self.trace_nodes[str(self.index.trazas[0])])

    def _populate_model_item(self, item, folder):
        for path in sorted((p for p in folder.rglob("*") if p.is_file()), key=lambda p: str(p).lower()):
            child = QTreeWidgetItem([str(path.relative_to(folder))])
            child.setData(0, Qt.UserRole, ("part_file", str(path)))
            item.addChild(child)

    def on_tree_selection(self):
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.UserRole)
        if not data:
            return
        kind, value = data
        if kind == "trace":
            self.load_trace(value)
        elif kind == "buffer":
            self.load_buffer(value)
        elif kind == "model":
            folder = Path(value)
            parts = sorted((p for p in folder.rglob("*.buf") if _RE_PART.match(p.name)),
                           key=lambda p: p.name.lower())
            if parts:
                self.load_part(parts[0])
            else:
                self.details.setPlainText("No se encontraron buffers PartNN-vb0 en este modelo.")
        elif kind == "draw":
            self.on_draw_selected(int(value))
        elif kind == "pass":
            if self.trace:
                render_pass = next((p for p in self.trace.pases if p["indice"] == int(value)), None)
                if render_pass:
                    self.details.setPlainText(f"Render pass {value} · {render_pass['w']}×{render_pass['h']}\n"
                                              f"Área: {render_pass['x']},{render_pass['y']} · {len(render_pass['draws'])} draws")
        elif kind == "skin":
            self.show_skin(int(value))
        elif kind == "part_file":
            path = Path(value)
            if path.suffix.lower() == ".buf" and _RE_PART.match(path.name):
                self.load_part(path)
            elif path.suffix.lower() in (".ktx2", ".png", ".jpg", ".jpeg"):
                self.details.setPlainText(f"Textura del modelo: {path}\nAbre el recurso con el explorador para visualizarla.")
            else:
                self.details.setPlainText(f"Archivo del modelo: {path}\n{path.stat().st_size:,} bytes")

    def load_trace(self, path):
        try:
            trace = self.traces.get(str(path))
            if trace is None:
                trace = X.Trace(path)
                self.traces[str(path)] = trace
            self.trace = trace
            self.draw = None
            self.mesh = None
            self.current_buffer = None
            for item in self.tree.findItems("", Qt.MatchContains | Qt.MatchRecursive):
                item.setExpanded(False)
            parent_item = self.trace_nodes.get(str(Path(path).resolve()))
            if parent_item:
                parent_item.setExpanded(True)
            self.draw_group = None
            # Populate render passes and draws below the selected trace.
            if parent_item:
                while parent_item.childCount():
                    parent_item.removeChild(parent_item.child(0))
            if parent_item:
                for render_pass in trace.pases:
                    pitem = QTreeWidgetItem([f"Pase {render_pass['indice']} · {render_pass['w']}×{render_pass['h']} · {len(render_pass['draws'])} draws"])
                    pitem.setData(0, Qt.UserRole, ("pass", str(render_pass["indice"])))
                    parent_item.addChild(pitem)
                    for draw in render_pass["draws"]:
                        ditem = QTreeWidgetItem([draw.etiqueta()])
                        ditem.setData(0, Qt.UserRole, ("draw", str(draw.idx)))
                        pitem.addChild(ditem)
                if trace.skins:
                    sk = QTreeWidgetItem([f"Skinning · {len(trace.skins)} dispatches"])
                    parent_item.addChild(sk)
                    for i, event in enumerate(trace.skins):
                        child = QTreeWidgetItem([f"skin #{i} · {event.get('vertex_count', '?')} vértices"])
                        child.setData(0, Qt.UserRole, ("skin", str(i)))
                        sk.addChild(child)
            self.tree.expandItem(parent_item) if parent_item else None
            self.tree.setCurrentItem(parent_item) if parent_item else None
            self.details.setPlainText(
                f"{trace.ruta.parent.name}\nJuego: {trace.paquete} · Capturado: {trace.capturado}\n"
                f"{len(trace.draws)} draws · {len(trace.pases)} render passes · {len(trace.pipelines)} pipelines\n"
                f"{len(trace.shaders)} shaders · {len(trace.texturas)} texturas · {len(trace.modelos)} buffers\n\n" +
                "\n".join("⚠ " + x for x in trace.avisos) +
                "\n\nSelecciona un draw en el árbol para reconstruir su geometría.")
            self.show_empty()
        except Exception as exc:
            log_message(f"Error al leer Frame Trace {path}: {traceback.format_exc()}")
            QMessageBox.critical(self, self.viewer_text("frame_trace_title", "Frame Trace"), self.viewer_text("frame_trace_error", "No se pudo leer la captura:\n{error}").format(error=exc))

    @staticmethod
    def _draws_using_buffer(trace, hash_hex):
        found = []
        for draw in trace.draws:
            geo = draw.geometria
            uses = ((geo.get("index") or {}).get("model") == hash_hex or
                    any(v.get("model") == hash_hex for v in geo.get("vertex", [])) or
                    (draw.indexado and (draw.ib or {}).get("model") == hash_hex))
            bindings = {b.get("binding") for b in (trace.pipelines.get(draw.pipeline) or {}).get("vertex_bindings", [])}
            uses = uses or any(vb.get("model") == hash_hex for n, vb in draw.vbs.items() if n in bindings)
            if uses:
                found.append(draw)
        return found

    def load_buffer(self, path):
        path = Path(path).resolve()
        self.current_buffer = path
        if _RE_PART.match(path.name):
            self.load_part(path)
            return
        match = _RE_BUF.match(path.name)
        if not match:
            self.details.setPlainText(f"{path.name} no sigue el patrón de buffer de geometría XXAMI.")
            self.show_empty()
            return
        hash_hex = match.group(1).lower()
        candidates = sorted(self.index.trazas, key=lambda p: (p.parent != path.parent, p.parent.name))
        matches = []
        for trace_path in candidates:
            try:
                if hash_hex not in trace_path.read_text(encoding="utf-8", errors="ignore"):
                    continue
                trace = self.traces.get(str(trace_path)) or X.Trace(trace_path)
                self.traces[str(trace_path)] = trace
                draws = self._draws_using_buffer(trace, hash_hex)
                if draws:
                    matches.append((trace, draws))
            except Exception:
                continue
        if not matches:
            self.trace = None
            self.draw = self.mesh = None
            self.details.setPlainText(
                f"{path.name} · {path.stat().st_size:,} bytes\n\nNo se encontró un frame_trace.json que use este buffer. "
                "Abre la carpeta raíz completa del volcado o la captura correspondiente para reconstruir su layout.")
            self.show_empty()
            return
        self.trace, draws = matches[0]
        self.draw = draws[0]
        self._populate_trace_tree(self.trace)
        self._show_draw_list_context(path, matches)
        self.build_mesh()

    def _populate_trace_tree(self, trace):
        item = self.trace_nodes.get(str(trace.ruta.resolve()))
        if not item:
            return
        while item.childCount():
            item.removeChild(item.child(0))
        for render_pass in trace.pases:
            pitem = QTreeWidgetItem([f"Pase {render_pass['indice']} · {render_pass['w']}×{render_pass['h']}"])
            item.addChild(pitem)
            for draw in render_pass["draws"]:
                ditem = QTreeWidgetItem([draw.etiqueta()])
                ditem.setData(0, Qt.UserRole, ("draw", str(draw.idx)))
                pitem.addChild(ditem)
        item.setExpanded(True)

    def _show_draw_list_context(self, path, matches):
        total = sum(len(draws) for _, draws in matches)
        self.details.setPlainText(f"Buffer: {path.name}\n{total} draw(s) lo utilizan en {len(matches)} captura(s).\n"
                                  "Se muestra el primer draw encontrado. Selecciona otro draw en el árbol para inspeccionarlo.")

    def show_skin(self, index):
        if not self.trace or index < 0 or index >= len(self.trace.skins):
            return
        event = self.trace.skins[index]
        lines = [f"Skinning #{index} · compute shader {event.get('shader')}",
                 f"Grupos: {event.get('groups')} · vértices: {event.get('vertex_count')}"]
        for key, label in (("source", "Entrada posición/normal/tangente"),
                           ("skin", "Pesos e índices de hueso"), ("bones", "Matrices de huesos")):
            resource = event.get(key) or {}
            value = resource.get("file") if resource.get("status") == "ok" else resource.get("status", "no disponible")
            lines.append(f"{label}: {value}")
        output = event.get("output") or {}
        if output:
            lines.append(f"Salida GPU: buffer {output.get('buffer')} · offset {output.get('offset')} · {output.get('bytes')} bytes · stride {output.get('stride')}")
        lines.append("Los draws que usan esta salida se muestran en pose base (sin aplicar huesos).")
        self.draw = None
        self.mesh = None
        self.show_empty()
        self.details.setPlainText("\n".join(lines))

    def load_part(self, path):
        self.trace = None
        self.draw = None
        self.current_buffer = Path(path)
        self.mesh = X.construir_malla_part(path)
        self._set_mesh_details(self.mesh, Path(path).name)
        self._update_materials((self.mesh.info or {}).get("texturas", []))
        self.redraw(force=True)

    def on_draw_selected(self, draw_index):
        if not self.trace:
            return
        draw = next((d for d in self.trace.draws if d.idx == draw_index), None)
        if draw is None:
            return
        self.draw = draw
        self.build_mesh()

    def build_mesh(self):
        if not self.trace or not self.draw:
            return
        pipe = self.trace.pipelines.get(self.draw.pipeline) or {}
        attrs = X.atributos_del_pipeline(pipe)
        self.position_combo.blockSignals(True)
        self.uv_combo.blockSignals(True)
        self.position_combo.clear()
        self.uv_combo.clear()
        for a in attrs:
            label = f"loc {a.get('location')}: {a.get('format_name', a.get('format'))} @b{a.get('binding')}+{a.get('offset')}"
            self.position_combo.addItem(label, a)
            self.uv_combo.addItem(label, a)
        self.uv_combo.insertItem(0, "(ninguno)", None)
        pos = X.atributo_posicion_por_defecto(attrs)
        uv = X.atributo_uv_por_defecto(attrs, pos) if pos else None
        for i in range(self.position_combo.count()):
            a = self.position_combo.itemData(i)
            if a == pos:
                self.position_combo.setCurrentIndex(i)
            if a == uv:
                self.uv_combo.setCurrentIndex(i)
        self.position_combo.blockSignals(False)
        self.uv_combo.blockSignals(False)
        self.rebuild_trace_mesh()

    def rebuild_trace_mesh(self, *_):
        if not self.trace or not self.draw:
            return
        pos = self.position_combo.currentData()
        uv = self.uv_combo.currentData()
        self.mesh = X.construir_malla(self.trace, self.draw, self.index, attr_pos=pos, attr_uv=uv)
        self._set_mesh_details(self.mesh, self.draw.etiqueta())
        self._update_materials_for_draw()
        self.redraw(force=True)

    def _set_mesh_details(self, mesh, title):
        lines = [title]
        if not mesh.vacia:
            lines.append(f"{len(mesh.pos):,} vértices · {len(mesh.caras):,} triángulos · {len(mesh.lineas):,} líneas")
            if mesh.info:
                lines.append(f"Stride: {mesh.info.get('stride', '?')} · Índices: {getattr(mesh.info.get('ib'), 'name', '?')}")
            if mesh.uv is not None:
                lines.append("Coordenadas UV disponibles")
        else:
            lines.append("No se pudo reconstruir geometría.")
        lines.extend("⚠ " + warning for warning in mesh.avisos)
        if self.trace and self.draw:
            draw = self.draw
            lines.extend(["", self.trace.resumen_draw(draw)])
            render_pass = self.trace.pases[draw.pase]
            lines.append(f"Render pass {render_pass['indice']} · {render_pass['w']}×{render_pass['h']} · command buffer {draw.cb}")
            lines.append(f"Pipeline: {draw.pipeline}")
            lines.append("Shaders:")
            for stage, hash_hex in self.trace.shaders_de(draw):
                info = self.trace.shaders.get(hash_hex) or {}
                name = info.get('file', f'shader_{hash_hex}.spv')
                lines.append(f"  {stage}: {name}" + ("" if self.index.buscar(name, self.trace.carpeta) else " (no encontrado)"))
            lines.append("Texturas enlazadas:")
            textures = self.trace.texturas_de(draw)
            if not textures:
                lines.append("  (ninguna)")
            for descriptor_set, binding, _element, hash_hex, info in textures:
                name = (info or {}).get('file', f'tex_{hash_hex}' if hash_hex else 'imagen sin identificar')
                resolved = self.index.buscar(name, self.trace.carpeta) if hash_hex else None
                if hash_hex and resolved is None:
                    resolved = self.index.buscar_por_hash('tex', hash_hex, self.trace.carpeta)
                lines.append(f"  set {descriptor_set} binding {binding}: {name}" + ("" if resolved else " (no encontrada)"))
            uniforms = self.trace.buffers_uniformes_de(draw)
            if uniforms:
                lines.append("Buffers uniformes / storage:")
                for entry in uniforms:
                    lines.append(f"  set {entry['set']} binding {entry['binding']} · {entry['tipo']} · buffer {entry['buffer']} · offset {entry['offset']} · rango {entry['rango']}")
        self.details.setPlainText("\n".join(lines))

    def _update_materials_for_draw(self):
        candidates = []
        if self.trace and self.draw:
            for _set, _binding, _element, hash_hex, info in self.trace.texturas_de(self.draw):
                if hash_hex is None:
                    continue
                name = (info or {}).get("file", "")
                path = self.index.buscar(name, self.trace.carpeta) if name else None
                path = path or self.index.buscar_por_hash("tex", hash_hex, self.trace.carpeta)
                if path and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".tga", ".dds", ".ktx2"):
                    candidates.append(path)
        self._update_materials(candidates)

    def _clear_material_rows(self):
        while self.material_list_layout.count() > 1:
            item = self.material_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _append_material_entry(self, path, map_type="Ignorar", invert=False):
        path = Path(path)
        if not path.is_file():
            return
        entry = {"path": path, "type": map_type, "invert": bool(invert)}
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(3)
        name = QPushButton(path.name)
        name.setFlat(True)
        name.setCursor(Qt.PointingHandCursor)
        name.setToolTip(self.viewer_text("select_texture_tooltip", "Seleccionar para previsualizar: {path}").format(path=path))
        name.setStyleSheet("QPushButton { text-align:left; padding:4px 6px; border:1px solid transparent; border-radius:3px; color:#e6e6e6; background:transparent; }")
        name.clicked.connect(lambda checked=False, e=entry: self._select_material_entry(e))
        layout.addWidget(name)
        options = QHBoxLayout()
        kind = QComboBox()
        kind.addItems(self.material_types)
        kind.setCurrentText(map_type)
        kind.setMinimumWidth(90)
        options.addWidget(kind, 1)
        invert_box = QCheckBox(self.viewer_text("invert", "Invertir"))
        invert_box.setChecked(bool(invert))
        options.addWidget(invert_box)
        layout.addLayout(options)
        entry.update({"row": row, "name_button": name, "combo": kind, "invert_box": invert_box})
        kind.currentTextChanged.connect(lambda value, e=entry: self._material_entry_changed(e, "type", value))
        invert_box.toggled.connect(lambda value, e=entry: self._material_entry_changed(e, "invert", value))
        self.material_entries.append(entry)
        self.material_list_layout.insertWidget(max(0, self.material_list_layout.count() - 1), row)

    def _select_material_entry(self, entry):
        self.selected_material_entry = entry
        for item in self.material_entries:
            selected = item is entry
            item["row"].setStyleSheet(
                "QWidget { background:#173d30; border:1px solid #27b59a; border-radius:4px; }"
                if selected else "QWidget { background:transparent; border:1px solid transparent; }"
            )
            item["name_button"].setStyleSheet(
                "QPushButton { text-align:left; padding:4px 6px; border:1px solid transparent; border-radius:3px; color:#ffffff; background:transparent; font-weight:600; }"
                if selected else
                "QPushButton { text-align:left; padding:4px 6px; border:1px solid transparent; border-radius:3px; color:#e6e6e6; background:transparent; }"
            )
        self._refresh_texture_preview()

    def _refresh_texture_preview(self):
        entry = self.selected_material_entry
        if entry is None:
            self.texture_preview.setPixmap(QPixmap())
            self.texture_preview.setText(self.viewer_text("select_texture", "Selecciona una textura de la lista"))
            return
        image = self._load_texture_image(entry["path"])
        if image is None:
            self.texture_preview.setPixmap(QPixmap())
            self.texture_preview.setText(self.viewer_text("texture_load_error", "No se pudo cargar la textura"))
            return
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        if entry["invert"]:
            alpha = rgba[..., 3]
            if int(alpha.min()) < 255 or int(alpha.max()) < 255:
                rgba[..., 3] = 255 - alpha
        preview = Image.fromarray(rgba, "RGBA")
        pixmap = QPixmap.fromImage(QImage(
            preview.tobytes("raw", "RGBA"), preview.width, preview.height,
            preview.width * 4, QImage.Format_RGBA8888
        ).copy())
        self.texture_preview.setPixmap(pixmap.scaled(
            self.texture_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        self.texture_preview.setToolTip(
            f"{entry['path'].name} · {preview.width} × {preview.height} px"
        )

    def _texture_preview_context_menu(self, position):
        entry = self.selected_material_entry
        if entry is None:
            return
        menu = QMenu(self.texture_preview)
        action = menu.addAction(self.viewer_text("invert_alpha", "Invertir alfa") if not entry["invert"] else self.viewer_text("restore_alpha", "Restaurar alfa"))
        chosen = menu.exec(self.texture_preview.mapToGlobal(position))
        if chosen is action:
            entry["invert_box"].setChecked(not entry["invert"])

    def _material_entry_changed(self, entry, key, value):
        entry[key] = value
        if entry is self.selected_material_entry and key == "invert":
            self._refresh_texture_preview()
        self._material_cache_key = None
        self._material_cache_image = None
        self.redraw(force=True)

    def _update_materials(self, paths):
        candidates = []
        for path in paths:
            path = Path(path)
            if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".tga", ".dds", ".ktx2") and path not in candidates:
                candidates.append(path)
        self._clear_material_rows()
        self.material_entries = []
        self.selected_material_entry = None
        self.texture_preview.setPixmap(QPixmap())
        self.texture_preview.setText(self.viewer_text("select_texture", "Selecciona una textura de la lista"))
        self.material_paths = candidates
        self._material_cache_key = None
        self._material_cache_image = None
        for index, path in enumerate(candidates):
            # Se muestra cada textura identificada por el frame_trace sin reasignarla
            # silenciosamente a otro recurso. La primera se toma como albedo inicial.
            default_type = "Albedo" if index == 0 else "Ignorar"
            self._append_material_entry(path, default_type, False)
        self.redraw(force=True)

    def add_material_texture(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.viewer_text("add_material_textures", "Añadir texturas al material"), str(self.root_path or Path.home()),
            self.viewer_text("texture_filter", "Texturas (*.png *.jpg *.jpeg *.tga *.dds *.ktx2);;Todos los archivos (*)"))
        changed = False
        for path in paths:
            p = Path(path)
            if p not in [e["path"] for e in self.material_entries]:
                self._append_material_entry(p, "Ignorar", False)
                changed = True
        if changed:
            self._material_cache_key = None
            self._material_cache_image = None
        self.redraw(force=True)


    def _load_texture_image(self, path):
        if not path:
            return None
        path = Path(path)
        try:
            if path.suffix.lower() == ".ktx2":
                import texture_decoder
                class Context:
                    unswizzle_activo = False
                ctx = Context()
                ctx._diagnostico_textura = {}
                tmp = Path(os.getenv("TEMP", "/tmp")) / ("xxami_mv_" + str(abs(hash(str(path)))) + ".png")
                if not tmp.exists() or tmp.stat().st_mtime < path.stat().st_mtime:
                    texture_decoder.textura_a_png(ctx, str(path), str(tmp), rapido=False)
                return Image.open(tmp).convert("RGBA")
            return Image.open(path).convert("RGBA")
        except Exception as exc:
            log_message(f"Error al cargar material {path}: {traceback.format_exc()}")
            self.statusBar().showMessage(self.viewer_text("material_load_error", "No se pudo cargar material {name}: {error}").format(name=path.name, error=exc), 5000)
            return None

    def _material_image(self):
        cache_key = tuple((str(e["path"]), e["type"], e["invert"],
                           e["path"].stat().st_mtime_ns if e["path"].is_file() else None,
                           e["path"].stat().st_size if e["path"].is_file() else None)
                          for e in self.material_entries)
        if cache_key == self._material_cache_key:
            return self._material_cache_image.copy() if self._material_cache_image is not None else None
        assigned = {}
        for entry in self.material_entries:
            kind = entry["type"]
            if kind == "Ignorar":
                continue
            image = self._load_texture_image(entry["path"])
            if image is None:
                continue
            rgba = np.asarray(image.convert("RGBA"), dtype=np.float32).copy()
            if entry["invert"]:
                alpha = rgba[..., 3]
                if float(alpha.min()) < 254.5 or float(alpha.max()) < 254.5:
                    rgba[..., 3] = 255.0 - alpha
            assigned[kind] = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA")
        albedo = assigned.get("Albedo")
        if albedo is None:
            # Sin un albedo explícito, muestra la primera textura marcada como canal.
            albedo = next(iter(assigned.values()), None)
        if albedo is None:
            self._material_cache_key = cache_key
            self._material_cache_image = None
            return None
        base = np.asarray(albedo.convert("RGBA"), dtype=np.float32).copy()
        h, w = base.shape[:2]

        lightmap = assigned.get("Lightmap")
        if lightmap is not None:
            lm = np.asarray(lightmap.resize((w, h), Image.Resampling.BILINEAR).convert("RGB"), dtype=np.float32) / 255.0
            base[..., :3] *= (0.25 + 0.75 * lm)

        ao = assigned.get("AO")
        if ao is not None:
            ao_values = np.asarray(ao.resize((w, h), Image.Resampling.BILINEAR).convert("L"), dtype=np.float32) / 255.0
            base[..., :3] *= (0.2 + 0.8 * ao_values[..., None])

        opacity = assigned.get("Opacity")
        if opacity is not None:
            opacity_values = np.asarray(opacity.resize((w, h), Image.Resampling.BILINEAR).convert("L"), dtype=np.float32)
            base[..., 3] = opacity_values

        normal = assigned.get("Normal")
        if normal is not None:
            nm = np.asarray(normal.resize((w, h), Image.Resampling.BILINEAR).convert("RGB"), dtype=np.float32) / 127.5 - 1.0
            # Iluminación aproximada en espacio tangente; no sustituye TBN real del modelo.
            length = np.linalg.norm(nm, axis=2, keepdims=True)
            nm /= np.maximum(length, 1e-5)
            lambert = np.clip((nm[..., 0] * -0.35 + nm[..., 1] * 0.25 + nm[..., 2] * 0.90), 0.15, 1.0)
            base[..., :3] *= lambert[..., None]

        metallic = assigned.get("Metallic")
        if metallic is not None:
            metal = np.asarray(metallic.resize((w, h), Image.Resampling.BILINEAR).convert("RGB"), dtype=np.float32)
            factor = np.mean(metal, axis=2, keepdims=True) / 255.0
            gray = np.mean(base[..., :3], axis=2, keepdims=True)
            base[..., :3] = base[..., :3] * (1.0 - 0.22 * factor) + (metal * 0.55 + gray * 0.45) * (0.22 * factor)

        roughness = assigned.get("Roughness")
        if roughness is not None:
            rough = np.asarray(roughness.resize((w, h), Image.Resampling.BILINEAR).convert("L"), dtype=np.float32) / 255.0
            contrast = 1.0 + (0.35 * (0.5 - rough))
            mean = np.mean(base[..., :3], axis=2, keepdims=True)
            base[..., :3] = mean + (base[..., :3] - mean) * contrast[..., None]

        emission = assigned.get("Emission")
        if emission is not None:
            emit = np.asarray(emission.resize((w, h), Image.Resampling.BILINEAR).convert("RGB"), dtype=np.float32)
            base[..., :3] = np.clip(base[..., :3] + emit * 0.35, 0, 255)

        result = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGBA")
        self._material_cache_key = cache_key
        self._material_cache_image = result.copy()
        return result

    def redraw(self, *_args, force=False):
        if self.mesh is None:
            return
        mode = MODES.get(self.mode.currentText(), "alambre")
        width = max(320, self.viewport.width() - 8)
        height = max(240, self.viewport.height() - 8)
        texture = self._material_image() if mode == "material" else None
        if mode in ("solido", "material") and len(self.mesh.caras) and create_backend:
            try:
                api_id = str(self.config.value("general/api", "opengl"))
                if self.render_backend is None:
                    gpu_preference = str(self.config.value("general/gpu", "default"))
                    self.render_backend = create_backend(api_id, gpu_preference)
                    self.render_backend.initialize()
                    self.gl_context = getattr(self.render_backend, "context", None)
                    self.gl_renderer = getattr(self.render_backend, "renderer", None)
                image = self.render_backend.render_image(self.mesh.pos, self.mesh.uv, self.mesh.caras,
                    texture if mode == "material" else None, width, height, self.rot_x, self.rot_y,
                    self.zoom, self.pan_x, self.pan_y)
                self._present_image(image)
                info = self.render_backend.info
                self.statusBar().showMessage(self.viewer_text("backend_active", "{label} activo · {vendor} · {renderer}").format(label=info['label'], vendor=info.get('vendor', ''), renderer=info.get('renderer', '')))
                return
            except Exception:
                if self.render_backend is not None:
                    try:
                        self.render_backend.close()
                    except Exception:
                        pass
                    self.render_backend = None
                    self.gl_context = self.gl_renderer = None
                if not self.gl_error_reported:
                    self.gl_error_reported = True
                    log_message("Fallo del backend gráfico; se cambia a software:\\n" + traceback.format_exc())
                    self.statusBar().showMessage(self.viewer_text("backend_software", "Backend gráfico no disponible; se usa el renderizador por software."))
        image = X.renderizar_malla(self.mesh, width, height, self.rot_x, self.rot_y, self.zoom,
                                   mode, max_elementos=max(120000, len(self.mesh.caras)),
                                   textura_material=texture, pan_x=self.pan_x, pan_y=self.pan_y)
        self._present_image(image)

    def _present_image(self, image):
        image = image.convert("RGB")
        if getattr(self, "floor_grid_checkbox", None) is not None and self.floor_grid_checkbox.isChecked():
            from PIL import ImageDraw
            width, height = image.size
            grid = Image.new("RGB", (width, height), (17, 17, 17))
            draw = ImageDraw.Draw(grid, "RGBA")
            # Plano XZ real en el espacio normalizado de la malla. Se proyecta
            # con la misma rotación, escala y desplazamiento que el modelo.
            if self.mesh is not None and len(self.mesh.pos):
                valid = np.isfinite(self.mesh.pos).all(axis=1)
                points = self.mesh.pos[valid]
                if len(points):
                    cy, sy = np.cos(self.rot_y), np.sin(self.rot_y)
                    cx, sx = np.cos(self.rot_x), np.sin(self.rot_x)
                    scale = 0.85 * min(width, height) * self.zoom
                    floor_y = -0.53
                    grid_values = np.arange(-1.5, 1.501, 0.125)
                    line_color = (112, 139, 137, 58)
                    for fixed in grid_values:
                        for along_x in (True, False):
                            coords = []
                            for varying in np.linspace(-1.5, 1.5, 49):
                                px, pz = (varying, fixed) if along_x else (fixed, varying)
                                world = np.array([px, floor_y, pz], dtype=np.float64)
                                x1 = world[0] * cy - world[2] * sy
                                z1 = world[0] * sy + world[2] * cy
                                y2 = world[1] * cx - z1 * sx
                                sxp = width / 2 + x1 * scale + self.pan_x
                                syp = height / 2 - y2 * scale + self.pan_y
                                coords.append((int(sxp), int(syp)))
                            draw.line(coords, fill=line_color, width=1)
                    # Ejes X/Z del plano, resaltados discretamente.
                    for along_x, color in ((True, (39, 181, 154, 135)),
                                           (False, (102, 139, 210, 120))):
                        coords = []
                        for varying in np.linspace(-1.5, 1.5, 65):
                            px, pz = (varying, 0.0) if along_x else (0.0, varying)
                            world = np.array([px, floor_y, pz], dtype=np.float64)
                            x1 = world[0] * cy - world[2] * sy
                            z1 = world[0] * sy + world[2] * cy
                            y2 = world[1] * cx - z1 * sx
                            coords.append((int(width / 2 + x1 * scale + self.pan_x),
                                           int(height / 2 - y2 * scale + self.pan_y)))
                        draw.line(coords, fill=color, width=2)
            pixels = np.asarray(image, dtype=np.int16)
            foreground = (pixels.max(axis=2) > 25).astype(np.uint8) * 255
            mask = Image.fromarray(foreground, "L")
            image = Image.composite(image, grid, mask)
        image = image.convert("RGBA")
        qimage = QImage(image.tobytes(), image.width, image.height, image.width * 4, QImage.Format_RGBA8888).copy()
        self.viewport.setPixmap(QPixmap.fromImage(qimage).scaled(self.viewport.size(), Qt.KeepAspectRatio,
                                                                  Qt.SmoothTransformation))
        self.last_image = image
        if hasattr(self, "orientation_gizmo"):
            self.orientation_gizmo.update()

    def show_empty(self):
        self.mesh = X.Malla()
        self.redraw(force=True)

    def _sync_camera_controls(self):
        controls = ((self.rot_x_control, np.degrees(self.rot_x)),
                    (self.rot_y_control, np.degrees(self.rot_y)),
                    (self.zoom_control, self.zoom),
                    (self.pan_x_control, self.pan_x),
                    (self.pan_y_control, self.pan_y))
        for widget, value in controls:
            widget.blockSignals(True)
            widget.setValue(float(value))
            widget.blockSignals(False)

    def _camera_changed(self, *_):
        self.rot_x = np.radians(self.rot_x_control.value())
        self.rot_y = np.radians(self.rot_y_control.value())
        self.zoom = self.zoom_control.value()
        self.pan_x = self.pan_x_control.value()
        self.pan_y = self.pan_y_control.value()
        self.redraw(force=True)

    def reset_view(self):
        self.rot_x, self.rot_y, self.zoom = .5, .6, 1.0
        self.pan_x = self.pan_y = 0.0
        self._sync_camera_controls()
        self.redraw(force=True)

    def _mouse_press(self, event):
        self.viewport.setFocus(Qt.MouseFocusReason)
        if event.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            self.drag_pos = event.position().toPoint()
            self.pan_drag = event.button() in (Qt.RightButton, Qt.MiddleButton)
            # QWidget obtiene captura implícita durante el arrastre; no usar
            # grabMouse(), que puede interferir con el movimiento de ventanas.

    def _mouse_move(self, event):
        if self.drag_pos is not None:
            pos = event.position().toPoint()
            delta = pos - self.drag_pos
            if self.pan_drag:
                self.pan_x += delta.x()
                self.pan_y += delta.y()
            else:
                self.rot_y += delta.x() * .01
                self.rot_x += delta.y() * .01
            self.drag_pos = pos
            self._sync_camera_controls()
            self.redraw()

    def _mouse_release(self, event):
        self.drag_pos = None
        self.pan_drag = False
        self.redraw(force=True)

    def _mouse_wheel(self, event):
        self.zoom = max(.1, min(20.0, self.zoom * (1.1 if event.angleDelta().y() > 0 else 1 / 1.1)))
        self._sync_camera_controls()
        self.redraw(force=True)
        event.accept()

    def set_axis_view(self, axis, sign=1):
        if axis == "X":
            self.rot_x, self.rot_y = 0.0, (np.pi / 2) * sign
        elif axis == "Y":
            self.rot_x, self.rot_y = (np.pi / 2) * sign, 0.0
        else:
            self.rot_x, self.rot_y = 0.0, (0.0 if sign > 0 else np.pi)
        self._sync_camera_controls()
        self.redraw(force=True)

    def keyPressEvent(self, event):
        key = event.key()
        step = 0.08
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        if key in (Qt.Key_Left, Qt.Key_A):
            if shift: self.pan_x -= 20
            else: self.rot_y -= step
        elif key in (Qt.Key_Right, Qt.Key_D):
            if shift: self.pan_x += 20
            else: self.rot_y += step
        elif key in (Qt.Key_Up, Qt.Key_W):
            if shift: self.pan_y -= 20
            else: self.rot_x -= step
        elif key in (Qt.Key_Down, Qt.Key_S):
            if shift: self.pan_y += 20
            else: self.rot_x += step
        elif key == Qt.Key_Q:
            self.rot_y -= step
        elif key == Qt.Key_E:
            self.rot_y += step
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom = min(20.0, self.zoom * 1.1)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom = max(.1, self.zoom / 1.1)
        elif key == Qt.Key_0:
            self.reset_view()
            event.accept()
            return
        elif key == Qt.Key_X:
            self.set_axis_view("X", 1)
            event.accept()
            return
        elif key == Qt.Key_Y:
            self.set_axis_view("Y", 1)
            event.accept()
            return
        elif key == Qt.Key_Z:
            self.set_axis_view("Z", 1)
            event.accept()
            return
        else:
            super().keyPressEvent(event)
            return
        self._sync_camera_controls()
        self.redraw(force=True)
        event.accept()

    def export_obj(self):
        if self.mesh is None or self.mesh.vacia:
            QMessageBox.information(self, self.viewer_text("export_obj_title", "Exportar OBJ"), self.viewer_text("no_geometry", "No hay geometría reconstruida para exportar."))
            return
        path, _ = QFileDialog.getSaveFileName(self, self.viewer_text("export_model", "Exportar modelo"), str((self.current_buffer or Path.cwd()).with_suffix(".obj")),
                                              self.viewer_text("obj_filter", "Wavefront OBJ (*.obj)"))
        if path:
            try:
                count = X.exportar_obj(self.mesh, path, Path(path).stem)
                self.statusBar().showMessage(self.viewer_text("exported_triangles", "Exportado {path} · {count} triángulos").format(path=path, count=count), 6000)
            except Exception as exc:
                QMessageBox.critical(self, self.viewer_text("export_obj_title", "Exportar OBJ"), str(exc))

    def closeEvent(self, event):
        try:
            if self.render_backend:
                self.render_backend.close()
                self.render_backend = None
            self.gl_renderer = None
            self.gl_context = None
        except Exception:
            pass
        super().closeEvent(event)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--xxami-wgpu-probe":
        from xxami_render_backend import probe_wgpu_adapters_in_process
        try:
            result = probe_wgpu_adapters_in_process(sys.argv[2])
        except Exception as exc:
            result = {"error": str(exc)}
        print("XXAMI_WGPU_PROBE=" + json.dumps(result))
        return
    parser = argparse.ArgumentParser(description="Visor independiente de modelos y frame_trace XXAMI")
    parser.add_argument("file", nargs="?", help="frame_trace.json o .buf")
    parser.add_argument("--root", help="Carpeta raíz del entorno de recursos")
    parser.add_argument("--log-path", help="Ruta opcional al registro de diagnóstico compartido")
    args = parser.parse_args()
    log_path = configure_crash_logging(args.log_path, "3D Viewer")
    app = QApplication(sys.argv)
    app.setWindowIcon(application_icon("viewer_icon"))
    window = ModelViewer(args.root, args.file, log_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
