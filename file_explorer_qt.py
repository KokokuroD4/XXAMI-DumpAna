# -*- coding: utf-8 -*-
"""XXAMI Explorer — explorador Qt independiente.

Dependencia: PySide6 (pip install PySide6). No utiliza Tkinter.
"""
from __future__ import annotations
import argparse, os, re, sys, zipfile, tempfile, subprocess, json, traceback
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QDir, QObject, Signal, QRunnable, QThreadPool, QPoint, QTimer, QSettings, QProcess, QUrl
from PySide6.QtWidgets import QFileSystemModel, QCompleter, QToolButton
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPixmap, QSyntaxHighlighter, QTextCharFormat, QPainter, QPen, QPolygon, QTextFormat, QKeySequence, QTextDocument, QTextCursor, QMovie, QDesktopServices
from xxami_logging import configure_crash_logging, log_message
from PySide6.QtWidgets import (QStyle, QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTabWidget, QSplitter, QListWidget, QListWidgetItem, QLabel,
    QFileDialog, QMessageBox, QFrame, QScrollArea, QPlainTextEdit, QToolBar, QStatusBar,
    QAbstractItemView, QGridLayout, QDialog, QSlider, QComboBox, QMenu, QTextEdit, QInputDialog, QProgressBar, QStackedWidget, QGroupBox)

BG="#202124"; PANEL="#292b2f"; PANEL2="#202226"; TEXT="#e8eaed"; MUTED="#aeb4bd"
GREEN="#00e878"; SELECT="#173d30"; MOD="#59452b"


def load_texture_decoder():
    """Carga el decodificador desde el paquete o desde la carpeta del explorador."""
    module_dir = str(Path(__file__).resolve().parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    try:
        import texture_decoder
        return texture_decoder
    except ModuleNotFoundError as exc:
        if exc.name != "texture_decoder":
            raise
        expected = Path(module_dir) / "texture_decoder.py"
        raise ModuleNotFoundError(
            f"No se encontró texture_decoder.py. Se esperaba en: {expected}. "
            "Asegúrate de distribuir ese archivo junto a file_explorer_qt.py "
            "o incluirlo como módulo oculto al compilar con PyInstaller."
        ) from exc


def generated_icon(name, size=256):
    """Iconos vectoriales inspirados en los dibujos del explorador Tk anterior."""
    pix=QPixmap(size,size); pix.fill(Qt.transparent)
    p=QPainter(pix); p.setRenderHint(QPainter.Antialiasing); p.scale(size/256.0,size/256.0)
    colors={"spv":"#d5a7ff","txt":"#8fc7ff","buf":"#e7bd78","xmod":"#e7a84d","mlpk":"#e7a84d",
            "generic":"#aeb6c2","back":"#f2f2f2","forward":"#f2f2f2","refresh":"#f2f2f2",
            "folder":"#e8bd59","search":"#f2f2f2","ktx2":"#77d6c5","up":"#f2f2f2",
            "ini":"#e6c875","json":"#e6c875","glsl":"#73b7ff","decode":"#8fc7ff","decoder":"#8fc7ff","save":"#77d6c5","save_as":"#e7bd78","model_buf":"#b58cff"}
    c=QColor(colors.get(name,"#aeb6c2")); p.setPen(QPen(c,18,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
    if name in ("back","forward","refresh","search","up"):
        p.drawEllipse(24,24,208,208)
        if name=="back":
            p.drawLine(150,65,78,128); p.drawLine(78,128,150,191); p.drawLine(82,128,196,128)
        elif name=="forward":
            p.drawLine(106,65,178,128); p.drawLine(178,128,106,191); p.drawLine(60,128,174,128)
        elif name=="refresh":
            p.drawArc(54,54,148,148,35*16,285*16); p.setPen(Qt.NoPen); p.setBrush(c)
            p.drawPolygon(QPolygon([QPoint(178,45),QPoint(218,58),QPoint(187,91)]))
        elif name=="search":
            p.drawEllipse(52,48,102,102); p.drawLine(136,136,205,205)
        else:
            p.drawLine(128,190,128,72); p.drawLine(72,128,128,72); p.drawLine(128,72,184,128)
    elif name=="folder":
        p.setPen(Qt.NoPen); p.setBrush(c); p.drawRoundedRect(22,60,212,150,18,18); p.drawRoundedRect(35,35,100,55,12,12)
    else:
        p.setPen(Qt.NoPen); p.setBrush(c); p.drawRoundedRect(35,20,185,216,18,18)
        p.setBrush(QColor("#f4f4f4")); p.drawPolygon(QPolygon([QPoint(155,20),QPoint(220,85),QPoint(155,85)]))
        p.setPen(QPen(QColor("#222222"),9)); p.setFont(QFont("Segoe UI",30,QFont.Bold)); p.drawText(48,175,name.upper()[:5])
    p.end(); return QIcon(pix)


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
    return generated_icon(name, 48)


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
    for resource_path in candidates:
        if resource_path.is_file():
            return resource_path
    return None


class ExplorerAboutLogo(QLabel):
    """Muestra el logotipo original de res/explorer_logo.png."""
    def __init__(self, parent=None, missing_text="No se encontró res/explorer_logo.png", logo_tooltip="res/explorer_logo.png"):
        super().__init__(parent)
        self._missing_text = missing_text
        self._logo_tooltip = logo_tooltip
        self._source_pixmap = QPixmap()
        resource = application_resource("explorer_logo.png")
        if resource is not None:
            self._source_pixmap = QPixmap(str(resource))
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(300, 180)
        self.setMaximumWidth(390)
        self._update_pixmap()

    def _update_pixmap(self):
        if not self._source_pixmap.isNull():
            self.setPixmap(self._source_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self.setToolTip(self._logo_tooltip)
        else:
            self.setText(self._missing_text)
            self.setToolTip(
                "Coloca explorer_logo.png en res junto a file_explorer_qt.py "
                "o en res dentro del paquete de la aplicación."
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()


def resource_icon(name, size=48):
    """Carga primero el PNG de res/ y usa el dibujo integrado solo como respaldo."""
    resource = Path(__file__).resolve().parent / "res" / (name + ".png")
    if resource.is_file():
        icon = QIcon(str(resource))
        if not icon.isNull():
            return icon
    return generated_icon(name, size)


class DirectoryLoadSignals(QObject):
    progress = Signal(int)
    finished = Signal(object, str)


class DirectoryLoadWorker(QRunnable):
    """Obtiene entradas de disco o ZIP sin bloquear el hilo gráfico."""
    def __init__(self, path, archive=None, inside=""):
        super().__init__()
        self.path = Path(path)
        self.archive = Path(archive) if archive else None
        self.inside = inside
        self.signals = DirectoryLoadSignals()

    def run(self):
        try:
            if self.archive:
                prefix = self.inside.strip("/")
                base = prefix + "/" if prefix else ""
                dirs, files = set(), []
                with zipfile.ZipFile(self.archive) as archive:
                    infos = archive.infolist()
                    total = len(infos)
                    for index, info in enumerate(infos, 1):
                        name = info.filename.replace("\\\\", "/")
                        if name.startswith(base) and name != base:
                            rest = name[len(base):]
                            first, sep, _ = rest.partition("/")
                            if sep:
                                dirs.add(first)
                            elif first and not info.is_dir():
                                files.append(first)
                        if index % 128 == 0 or index == total:
                            self.signals.progress.emit(index)
                entries = [("dir", n) for n in sorted(dirs, key=str.lower)]
                entries.extend(("file", n) for n in sorted(set(files), key=str.lower))
            else:
                entries = []
                with os.scandir(self.path) as iterator:
                    for index, entry in enumerate(iterator, 1):
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            is_dir = False
                        entries.append((is_dir, entry.name))
                        if index % 128 == 0:
                            self.signals.progress.emit(index)
                entries.sort(key=lambda item: (not item[0], item[1].lower()))
            self.signals.finished.emit(entries, "")
        except Exception as exc:
            log_message(f"Error al enumerar {self.archive or self.path}: {traceback.format_exc()}")
            self.signals.finished.emit(None, f"{type(exc).__name__}: {exc}")


class TextureSignals(QObject):
    finished=Signal(object,int,int,str,str)

class TextureThumbWorker(QRunnable):
    def __init__(self,tab_id,generation,index,source,output):
        super().__init__(); self.tab_id=tab_id; self.generation=generation; self.index=index
        self.source=source; self.output=output; self.signals=TextureSignals()
    def run(self):
        error=""
        try:
            texture_decoder = load_texture_decoder()
            class Context: unswizzle_activo=False
            ctx=Context(); ctx._diagnostico_textura={}
            if not texture_decoder.textura_a_png(ctx,self.source,self.output,rapido=True):
                error=ctx._diagnostico_textura.get(self.source) or "No se pudo decodificar la textura."
                log_message(f"Error al generar miniatura KTX2 {self.source}: {error}")
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"
            log_message(f"Excepción al generar miniatura KTX2 {self.source}: {traceback.format_exc()}")
        self.signals.finished.emit(self.tab_id,self.generation,self.index,self.output,error)


def is_model_buffer_name(name):
    filename=Path(name).name
    return bool(re.match(r"^(?:vb|ib|vbib)_[0-9a-fA-F]+_\d+\.buf$",filename,re.I)
                or re.match(r"^Part\d+-vb0=[0-9a-fA-F]+\.buf$",filename,re.I))


def classify_text(data: bytes) -> str:
    if data[:4] == b"\x03\x02\x23\x07": return "SPIR-V binario detectado en TXT"
    text=data[:65536].decode("utf-8-sig",errors="replace")
    if re.search(r"\bOp(EntryPoint|Capability|MemoryModel|Decorate)\b",text): return "SPIR-V textual (disassembly)"
    if re.search(r"#\s*version\s+\d+|\bvoid\s+main\s*\(|\bgl_Position\b|\bgl_FragColor\b",text): return "Código GLSL"
    return "Archivo de texto"

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor); self.editor=editor
    def sizeHint(self): return QSize(self.editor.line_number_area_width(),0)
    def paintEvent(self,event): self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    findRequested=Signal()
    def __init__(self,parent=None):
        super().__init__(parent); self.line_number_area=LineNumberArea(self); self.base_font_size=11
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0); self.highlight_current_line()
    def set_zoom(self,size):
        self.base_font_size=max(6,min(40,int(size)))
        font=self.font(); font.setFamily("Consolas"); font.setPointSize(self.base_font_size); self.setFont(font)
        # Qt Style Sheets pueden prevalecer sobre QWidget.setFont(); fija también
        # el tamaño en la regla del propio editor para que el cambio sea visible.
        self.setStyleSheet(
            "QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
            "border:1px solid #41444a;font-family:Consolas;"
            f"font-size:{self.base_font_size}pt;}}"
        )
        self.update_line_number_area_width(0)
    def zoom_by(self,delta):
        self.set_zoom(self.base_font_size+delta)
    def wheelEvent(self,event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1 if event.angleDelta().y()>0 else -1)
            event.accept(); return
        super().wheelEvent(event)
    def keyPressEvent(self,event):
        if event.matches(QKeySequence.Find):
            self.findRequested.emit(); event.accept(); return
        if event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Plus,Qt.Key_Equal):
                self.zoom_by(1); event.accept(); return
            if event.key()==Qt.Key_Minus:
                self.zoom_by(-1); event.accept(); return
            if event.key()==Qt.Key_0:
                self.set_zoom(11); event.accept(); return
        super().keyPressEvent(event)
    def line_number_area_width(self):
        digits=max(2,len(str(max(1,self.blockCount()))))
        return 14+self.fontMetrics().horizontalAdvance("9")*digits
    def update_line_number_area_width(self,_): self.setViewportMargins(self.line_number_area_width(),0,0,0)
    def update_line_number_area(self,rect,dy):
        if dy:self.line_number_area.scroll(0,dy)
        else:self.line_number_area.update(0,rect.y(),self.line_number_area.width(),rect.height())
        if rect.contains(self.viewport().rect()):self.update_line_number_area_width(0)
    def resizeEvent(self,event):
        super().resizeEvent(event); cr=self.contentsRect()
        self.line_number_area.setGeometry(cr.left(),cr.top(),self.line_number_area_width(),cr.height())
    def line_number_area_paint_event(self,event):
        painter=QPainter(self.line_number_area); painter.fillRect(event.rect(),QColor("#25272b"))
        block=self.firstVisibleBlock(); number=block.blockNumber()
        top=int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom=top+int(self.blockBoundingRect(block).height())
        while block.isValid() and top<=event.rect().bottom():
            if block.isVisible() and bottom>=event.rect().top():
                painter.setPen(QColor("#858b95"))
                painter.drawText(0,top,self.line_number_area.width()-6,self.fontMetrics().height(),Qt.AlignRight,str(number+1))
            block=block.next(); top=bottom
            bottom=top+int(self.blockBoundingRect(block).height()); number+=1
    def highlight_current_line(self):
        selections=[]
        if not self.isReadOnly():
            selection=QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#292d33"))
            selection.format.setProperty(QTextFormat.FullWidthSelection,True)
            selection.cursor=self.textCursor(); selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)


class ShaderHighlighter(QSyntaxHighlighter):
    def __init__(self,doc,language="text"):
        super().__init__(doc); self.language=language.lower()
        def fmt(color,bold=False):
            f=QTextCharFormat(); f.setForeground(QColor(color))
            if bold:f.setFontWeight(QFont.Bold)
            return f
        self.rules=[]
        if self.language=="glsl":
            rules=[
                (r"\b(if|else|for|while|return|discard|break|continue|struct|void|const|uniform|layout|in|out|inout)\b","#c586c0",True),
                (r"\b(float|double|int|uint|bool|vec[234]|ivec[234]|uvec[234]|mat[234]|sampler\w*)\b","#4ec9b0",False),
                (r"\b(gl_\w+)\b","#9cdcfe",False),(r"\b(\d+(?:\.\d+)?[fFuU]?)\b","#b5cea8",False),
                (r'"[^"\n]*"',"#ce9178",False)]
            self.rules=[(re.compile(p),fmt(c,b)) for p,c,b in rules]
        elif self.language=="json":
            self.rules=[
                (re.compile(r'"(?:\.|[^"\\])*"(?=\s*:)'),fmt("#9cdcfe",True)),
                (re.compile(r'"(?:\.|[^"\\])*"'),fmt("#ce9178")),
                (re.compile(r"\b(true|false|null)\b"),fmt("#c586c0",True)),
                (re.compile(r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),fmt("#b5cea8")),
                (re.compile(r"[{}\[\],:]"),fmt("#d4d4d4"))]
        elif self.language=="ini":
            self.rules=[
                (re.compile(r"^\s*\[[^]]+\]"),fmt("#dcdcaa",True)),
                (re.compile(r"^\s*[^=:#;\s][^=:#]*?(?=\s*=)"),fmt("#9cdcfe")),
                (re.compile(r"(?<==)\s*[^;#]+"),fmt("#ce9178")),
                (re.compile(r"^\s*[;#].*$"),fmt("#6a9955"))]
        else:
            self.rules=[
                (re.compile(r"\b(true|false|null|None)\b"),fmt("#c586c0",True)),
                (re.compile(r"\b(\d+(?:\.\d+)?)\b"),fmt("#b5cea8")),
                (re.compile(r'"[^"\n]*"|\'[^\'\n]*\''),fmt("#ce9178"))]
    def highlightBlock(self,text):
        for pattern,style in self.rules:
            for m in pattern.finditer(text):self.setFormat(m.start(),m.end()-m.start(),style)
        comments={"glsl":((r"//.*$","#6a9955"),(r"/\*.*?\*/","#6a9955")),
                  "ini":((r"[;#].*$","#6a9955"),),
                  "json":((r"//.*$","#6a9955"),),
                  "text":((r"//.*$","#6a9955"),(r"#.*$","#6a9955"))}
        for pattern,color in comments.get(self.language,()):
            for m in re.finditer(pattern,text):self.setFormat(m.start(),m.end()-m.start(),QColor(color))


def rewrite_archive_paths(archive_path, remove_prefixes=(), rename_prefixes=None):
    """Elimina o renombra rutas ZIP (incluidas carpetas) mediante reescritura atómica."""
    archive_path = Path(archive_path)
    remove_prefixes = tuple(x.strip("/") for x in remove_prefixes)
    rename_prefixes = {a.strip("/"): b.strip("/") for a, b in (rename_prefixes or {}).items()}
    temp_path = archive_path.with_name(archive_path.name + ".xxami_tmp")
    try:
        with zipfile.ZipFile(archive_path, "r") as source, zipfile.ZipFile(temp_path, "w") as target:
            for info in source.infolist():
                original_name = info.filename
                original = original_name.rstrip("/")
                if any(original == prefix or original.startswith(prefix + "/") for prefix in remove_prefixes):
                    continue
                payload = source.read(original_name)
                renamed = original_name
                for old, new in rename_prefixes.items():
                    if original == old or original.startswith(old + "/"):
                        renamed = new + original_name[len(old):]
                        break
                info.filename = renamed
                target.writestr(info, payload)
        os.replace(temp_path, archive_path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def write_archive_entries(archive_path, replacements=None, additions=None):
    """Reescribe el ZIP de forma atómica, sustituyendo entradas sin duplicarlas."""
    archive_path = Path(archive_path)
    replacements = replacements or {}
    additions = additions or {}
    temp_path = archive_path.with_name(archive_path.name + ".xxami_tmp")
    try:
        with zipfile.ZipFile(archive_path, "r") as source, zipfile.ZipFile(temp_path, "w") as target:
            written = set()
            for info in source.infolist():
                name = info.filename
                if name in replacements:
                    if name not in written:
                        target.writestr(info, replacements[name])
                        written.add(name)
                else:
                    target.writestr(info, source.read(name))
                    written.add(name)
            for name, data in additions.items():
                if name not in written:
                    target.writestr(name, data, compress_type=zipfile.ZIP_STORED)
                    written.add(name)
        os.replace(temp_path, archive_path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


class ShaderEditor(QMainWindow):
    def _tr(self,key,fallback):
        owner=self.parent()
        return owner.tr(key,fallback) if owner is not None and hasattr(owner,"tr") else fallback

    def __init__(self,path,data,parent=None,save_handler=None):
        super().__init__(parent); self.path=Path(path); self.save_handler=save_handler
        self.original_spv=self.path.suffix.lower()==".spv"; self.active_language=self.path.suffix.lower().lstrip(".")
        self.is_decompiled=False; self.setWindowTitle(f"{self._tr('open_code_editor', 'AMI: Code Editor')} — {self.path.name}"); self.setWindowIcon(application_icon("code_editor_icon"))
        self.resize(1050,760); self.setStyleSheet(STYLE)
        root=QWidget(); lay=QVBoxLayout(root); lay.setContentsMargins(8,8,8,8)
        bar=QHBoxLayout(); bar.setSpacing(8); self.status=QLabel(self._status_for(data))
        self.save_button=QToolButton(); self.save_button.setIcon(resource_icon("save",48))
        self.save_button.setIconSize(QSize(38,38)); self.save_button.setToolTip(self._tr("save_file", "Guardar archivo"))
        self.save_button.setAccessibleName(self._tr("save_file", "Guardar archivo")); self.save_button.setFixedSize(50,48)
        self.save_button.clicked.connect(self.save_text); bar.addWidget(self.save_button)
        self.save_as_button=QToolButton(); self.save_as_button.setIcon(resource_icon("save_as",48))
        self.save_as_button.setIconSize(QSize(38,38)); self.save_as_button.setToolTip(self._tr("save_as", "Guardar como…"))
        self.save_as_button.setAccessibleName(self._tr("save_as", "Guardar como…")); self.save_as_button.setFixedSize(50,48)
        self.save_as_button.clicked.connect(self.save_as); bar.addWidget(self.save_as_button)
        self.decode_button=None
        if self.original_spv:
            self.decode_button=QToolButton(); self.decode_button.setIcon(resource_icon("decoder",48))
            self.decode_button.setIconSize(QSize(38,38)); self.decode_button.setToolTip(self._tr("decode_spirv", "Decodificar SPIR-V para editar"))
            self.decode_button.setAccessibleName(self._tr("decode_spirv_name", "Decodificar SPIR-V")); self.decode_button.setFixedSize(50,48)
            self.decode_button.clicked.connect(self.show_decode_menu); bar.addWidget(self.decode_button)
        bar.addSpacing(12)
        self.find_button=QToolButton(); self.find_button.setText(self._tr("find", "Buscar"))
        self.find_button.setToolTip(self._tr("find_text_tip", "Buscar texto (Ctrl+F)")); self.find_button.clicked.connect(self.show_find); bar.addWidget(self.find_button)
        self.zoom_out_button=QToolButton(); self.zoom_out_button.setText("A−")
        self.zoom_out_button.setToolTip(self._tr("zoom_out", "Reducir texto (Ctrl+rueda abajo)")); self.zoom_out_button.clicked.connect(lambda:self.editor.zoom_by(-1)); bar.addWidget(self.zoom_out_button)
        self.zoom_in_button=QToolButton(); self.zoom_in_button.setText("A+")
        self.zoom_in_button.setToolTip(self._tr("zoom_in", "Ampliar texto (Ctrl+rueda arriba)")); self.zoom_in_button.clicked.connect(lambda:self.editor.zoom_by(1)); bar.addWidget(self.zoom_in_button)
        self.zoom_reset_button=QToolButton(); self.zoom_reset_button.setText("100%")
        self.zoom_reset_button.setToolTip(self._tr("reset_zoom", "Restablecer tamaño del texto")); self.zoom_reset_button.clicked.connect(lambda:self.editor.set_zoom(11)); bar.addWidget(self.zoom_reset_button)
        bar.addSpacing(12); bar.addWidget(self.status); bar.addStretch()
        lay.addLayout(bar)
        find_bar=QHBoxLayout()
        self.find_input=QLineEdit(); self.find_input.setPlaceholderText(self._tr("find_document", "Buscar en el documento…"))
        self.find_input.returnPressed.connect(self.find_next); self.find_input.textChanged.connect(self.update_search_highlights)
        self.find_prev_button=QToolButton(); self.find_prev_button.setText("↑"); self.find_prev_button.clicked.connect(self.find_previous)
        self.find_next_button=QToolButton(); self.find_next_button.setText("↓"); self.find_next_button.clicked.connect(self.find_next)
        self.find_close_button=QToolButton(); self.find_close_button.setText("✕"); self.find_close_button.clicked.connect(self.hide_find)
        find_bar.addWidget(self.find_input,1); find_bar.addWidget(self.find_prev_button); find_bar.addWidget(self.find_next_button); find_bar.addWidget(self.find_close_button)
        self.find_container=QWidget(); self.find_container.setLayout(find_bar); self.find_container.hide(); lay.addWidget(self.find_container)
        self.editor=CodeEditor(); self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setFont(QFont("Consolas",11))
        self.editor.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;border:1px solid #41444a;font-family:Consolas;font-size:11pt;}")
        self.editor.set_zoom(11)
        text=data.decode("utf-8-sig",errors="replace")
        if self.original_spv:text=self._tr("binary_spirv_notice", "// Archivo SPIR-V binario. Pulsa el botón de decodificación para elegir GLSL o SPIR-V Assembly.")
        self.editor.setPlainText(text); self.highlighter=ShaderHighlighter(self.editor.document(),self.active_language)
        self.editor.findRequested.connect(self.show_find)
        self._build_edit_menu()
        lay.addWidget(self.editor); self.setCentralWidget(root)
    def _build_edit_menu(self):
        menu=self.menuBar().addMenu(self._tr("edit_menu", "Editar"))
        actions=((self._tr("undo", "Deshacer"),QKeySequence.Undo,self.editor.undo),
                 (self._tr("redo", "Rehacer"),QKeySequence.Redo,self.editor.redo),
                 (self._tr("cut", "Cortar"),QKeySequence.Cut,self.editor.cut),
                 (self._tr("copy", "Copiar"),QKeySequence.Copy,self.editor.copy),
                 (self._tr("paste", "Pegar"),QKeySequence.Paste,self.editor.paste),
                 (self._tr("select_all", "Seleccionar todo"),QKeySequence.SelectAll,self.editor.selectAll))
        for label,shortcut,callback in actions:
            action=QAction(label,self); action.setShortcut(shortcut); action.triggered.connect(callback); menu.addAction(action)
        menu.addSeparator()
        action=QAction(self._tr("find", "Buscar") + "…",self); action.setShortcut(QKeySequence.Find); action.triggered.connect(self.show_find); menu.addAction(action)

    def show_find(self):
        self.find_container.show(); self.find_input.setFocus(); self.find_input.selectAll(); self.update_search_highlights()

    def hide_find(self):
        self.find_container.hide(); self.editor.setFocus(); self.editor.setExtraSelections([]); self.editor.highlight_current_line()

    def update_search_highlights(self):
        term=self.find_input.text(); selections=[]
        if term:
            cursor=self.editor.document().find(term)
            while not cursor.isNull():
                selection=QTextEdit.ExtraSelection(); selection.cursor=cursor
                selection.format.setBackground(QColor("#66552b")); selection.format.setForeground(QColor("#ffffff"))
                selections.append(selection); cursor=self.editor.document().find(term,cursor)
        self.editor.setExtraSelections(selections)
        if not selections:self.editor.highlight_current_line()

    def find_next(self):
        term=self.find_input.text()
        if not term:return
        if not self.editor.find(term):
            cursor=self.editor.textCursor(); cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor); self.editor.find(term)
        self.update_search_highlights()

    def find_previous(self):
        term=self.find_input.text()
        if not term:return
        if not self.editor.find(term,QTextDocument.FindFlag.FindBackward):
            cursor=self.editor.textCursor(); cursor.movePosition(QTextCursor.End)
            self.editor.setTextCursor(cursor); self.editor.find(term,QTextDocument.FindFlag.FindBackward)
        self.update_search_highlights()

    def _status_for(self,data):
        ext=self.path.suffix.lower()
        key={".spv":"status_spv",".ini":"status_ini",".json":"status_json",".glsl":"status_glsl",".txt":"status_text"}.get(ext,"status_editor")
        fallback={".spv":"SPIR-V binario · pendiente de decodificación",".ini":"Configuración INI",".json":"JSON",".glsl":"Shader GLSL",".txt":classify_text(data)}.get(ext,"Editor de texto")
        if ext==".txt":
            raw=classify_text(data)
            text_keys={"SPIR-V binario detectado en TXT":"type_spirv_text","SPIR-V textual (disassembly)":"type_spirv_disassembly","Código GLSL":"type_glsl","Archivo de texto":"type_text"}
            fallback=raw
            key=text_keys.get(raw,key)
        return self._tr(key,fallback)
    def show_decode_menu(self):
        menu=QMenu(self); glsl=QAction(self._tr("decompile_glsl", "Decompilar a GLSL"),self)
        assembly=QAction(self._tr("disassemble_spirv", "Desensamblar a SPIR-V Assembly"),self)
        glsl.triggered.connect(lambda:self.decompile_spv("glsl"))
        assembly.triggered.connect(lambda:self.decompile_spv("spvasm"))
        menu.addAction(glsl); menu.addAction(assembly)
        menu.exec(self.decode_button.mapToGlobal(self.decode_button.rect().bottomLeft()))
    def _tool_path(self,name):
        base=Path(__file__).resolve().parent
        for candidate in (base/(name+".exe"),base/name):
            if candidate.is_file():return str(candidate)
        return name
    def decompile_spv(self,mode):
        if not self.original_spv:return
        temp=Path(tempfile.gettempdir())/(self.path.stem+"_xxami_decode.spv")
        output=temp.with_suffix(".glsl" if mode=="glsl" else ".s")
        try:
            temp.write_bytes(self.path.read_bytes())
            if mode=="glsl":
                command=[self._tool_path("spirv-cross"),str(temp),"--output",str(output),"--version","450","--vulkan-semantics"]
            else:
                command=[self._tool_path("spirv-dis"),str(temp),"-o",str(output)]
            subprocess.run(command,check=True,capture_output=True,text=True)
            decoded=output.read_text(encoding="utf-8")
            self.editor.setPlainText(decoded); self.is_decompiled=True
            self.active_language="glsl" if mode=="glsl" else "text"
            self.highlighter=ShaderHighlighter(self.editor.document(),self.active_language)
            self.status.setText(self._tr("spirv_glsl_edit", "SPIR-V → GLSL (edición)") if mode=="glsl" else self._tr("spirv_assembly_edit", "SPIR-V Assembly (edición)"))
            self.setWindowTitle(f"{self._tr('code_editor_title', 'Editor')} — {self.path.name} · {self.active_language.upper()}")
        except Exception as exc:
            details=getattr(exc,"stderr","") or str(exc)
            QMessageBox.critical(self,self._tr("spirv_decoder", "Decodificador SPIR-V"),self._tr("decode_error", "No se pudo decodificar el archivo.\n\n{details}").format(details=details))
        finally:
            for file in (temp,output):
                try:file.unlink()
                except OSError:pass
    def save_as(self):
        text=self.editor.toPlainText()
        if self.original_spv:
            if not self.is_decompiled:
                QMessageBox.information(self,self._tr("save_as", "Guardar como…"),self._tr("decode_first", "Primero debes decodificar el SPIR-V para editarlo.")); return
            suffix=".glsl" if self.active_language=="glsl" else ".s"
            filters=self._tr("glsl_filter", "GLSL (*.glsl)") if suffix==".glsl" else self._tr("spvasm_filter", "SPIR-V Assembly (*.s)")
            target,_=QFileDialog.getSaveFileName(self,self._tr("save_decoded_as", "Guardar código decodificado como"),
                str(self.path.with_suffix(suffix)),filters)
            if not target:return
            if self.active_language != "glsl":
                target = str(Path(target).with_suffix(".s"))
            try:
                Path(target).write_text(text,encoding="utf-8"); self.status.setText(self._tr("saved_as", "Guardado como {name}").format(name=Path(target).name))
            except Exception as exc:QMessageBox.critical(self,self._tr("save_as", "Guardar como…"),str(exc))
            return
        target,_=QFileDialog.getSaveFileName(self,self._tr("save_file_as", "Guardar archivo como"),str(self.path),
            self._tr("text_file_filter", "Archivos de texto (*);;Todos los archivos (*)"))
        if not target:return
        try:
            new_path=Path(target)
            new_path.write_text(text,encoding="utf-8")
            self.path=new_path
            self.setWindowTitle(f"{self._tr('code_editor_title', 'Editor')} — {self.path.name}")
            self.status.setText(self._tr("saved_as", "Guardado como {name}").format(name=self.path.name))
        except Exception as exc:QMessageBox.critical(self,self._tr("save_as", "Guardar como…"),str(exc))
    def save_text(self):
        text=self.editor.toPlainText()
        if self.original_spv:
            if not self.is_decompiled:
                QMessageBox.information(self,self._tr("save", "Guardar"),self._tr("decode_first", "Primero debes decodificar el SPIR-V para editarlo.")); return
            suffix=".glsl" if self.active_language=="glsl" else ".s"
            target,_=QFileDialog.getSaveFileName(self,self._tr("save_decoded", "Guardar código decodificado"),
                str(self.path.with_suffix(suffix)),self._tr("glsl_filter", "GLSL (*.glsl)") + ";;" + self._tr("spvasm_filter", "SPIR-V Assembly (*.s)"))
            if not target:return
            if self.active_language != "glsl":
                target = str(Path(target).with_suffix(".s"))
            try:
                Path(target).write_text(text,encoding="utf-8"); self.status.setText(self._tr("saved_as", "Guardado como {name}").format(name=Path(target).name))
            except Exception as exc:QMessageBox.critical(self,self._tr("save", "Guardar"),str(exc))
            return
        try:
            if self.save_handler:
                self.save_handler(text.encode("utf-8"))
            else:
                self.path.write_text(text,encoding="utf-8")
            self.status.setText(self._tr("saved_file", "Guardado · {name}").format(name=self.path.name))
        except Exception as exc:QMessageBox.critical(self,self._tr("save", "Guardar"),str(exc))


class PanImageLabel(QLabel):
    """Etiqueta que permite desplazar la imagen cuando excede el área visible."""
    def __init__(self,scroll_area,parent=None):
        super().__init__(parent); self.scroll_area=scroll_area; self.drag_origin=None
        self.setAlignment(Qt.AlignCenter); self.setStyleSheet("background:#18191b")
    def _can_pan(self):
        area=self.scroll_area.viewport().size()
        return self.width()>area.width() or self.height()>area.height()
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self._can_pan():
            self.drag_origin=event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor); event.accept(); return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.drag_origin is not None and event.buttons() & Qt.LeftButton:
            current=event.position().toPoint()
            delta=current-self.drag_origin
            h=self.scroll_area.horizontalScrollBar(); v=self.scroll_area.verticalScrollBar()
            h.setValue(h.value()-delta.x()); v.setValue(v.value()-delta.y())
            self.drag_origin=current; event.accept(); return
        if self._can_pan(): self.setCursor(Qt.OpenHandCursor)
        else: self.unsetCursor()
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.drag_origin is not None:
            self.drag_origin=None
            self.setCursor(Qt.OpenHandCursor if self._can_pan() else Qt.ArrowCursor)
            event.accept(); return
        super().mouseReleaseEvent(event)
    def wheelEvent(self,event):
        if event.modifiers() & Qt.ControlModifier:
            viewer=self.window()
            if isinstance(viewer,ImageViewer):
                viewer.zoom(1.25 if event.angleDelta().y()>0 else .8)
                event.accept(); return
        super().wheelEvent(event)


class ImageViewer(QMainWindow):
    def _tr(self,key,fallback):
        owner=self.parent()
        return owner.tr(key,fallback) if owner is not None and hasattr(owner,"tr") else fallback

    def __init__(self,path,parent=None):
        super().__init__(parent); self.path=Path(path); self.setWindowTitle(f"{self._tr('open_image_viewer', 'AMI: Image Viewer')} — {self.path.name}"); self.setWindowIcon(application_icon("image_viewer_icon")); self.resize(1000,720)
        self.setStyleSheet(STYLE); self.pix=QPixmap(str(path)); self.scale=1.0
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(False)
        # Centra la imagen en ambos ejes cuando su tamaño es menor que el viewport.
        self.scroll.setAlignment(Qt.AlignCenter)
        self.label=PanImageLabel(self.scroll); self.label.setToolTip(self._tr("image_zoom_tip", "Ctrl + rueda del ratón: zoom · Arrastrar con botón izquierdo: desplazar"))
        self.scroll.setWidget(self.label)
        bar=QToolBar(); self.addToolBar(bar)
        for name,fn in ((self._tr("fit_image", "Ajustar"),self.fit),("100%",self.actual),("−",lambda:self.zoom(.8)),("+",lambda:self.zoom(1.25))):
            a=QAction(name,self); a.triggered.connect(fn); bar.addAction(a)
        self.setCentralWidget(self.scroll)
        if self.pix.isNull():
            self.label.setText(self._tr("no_decoder", "No hay decodificador KTX2 disponible para generar la vista previa."))
        else:
            self.fit()
    def _show_scaled(self):
        if self.pix.isNull():return
        size=self.pix.size()*self.scale
        self.label.setPixmap(self.pix.scaled(size,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.label.adjustSize()
        self.label.setCursor(Qt.OpenHandCursor if self.label._can_pan() else Qt.ArrowCursor)
    def fit(self):
        if self.pix.isNull():return
        viewport=self.scroll.viewport().size()
        sx=viewport.width()/max(1,self.pix.width()); sy=viewport.height()/max(1,self.pix.height())
        self.scale=min(sx,sy)
        self._show_scaled()
        self.scroll.horizontalScrollBar().setValue(0); self.scroll.verticalScrollBar().setValue(0)
    def actual(self):
        if self.pix.isNull():return
        self.scale=1.0; self._show_scaled()
    def zoom(self,f):
        if self.pix.isNull():return
        self.scale=max(.05,min(16,self.scale*f)); self._show_scaled()

class ExplorerTab(QWidget):
    def _ktx_summary(self,info):
        tr=self.window().tr
        parts=[f"{info.w}x{info.h}",tr("mip_levels","{count} nivel(es)").format(count=info.n_niveles)]
        if info.capas>1: parts.append(tr("layers","{count} capas").format(count=info.capas))
        if info.caras>1: parts.append(tr("cube_faces","{count} caras (cubemap)").format(count=info.caras))
        if info.d>1: parts.append(tr("depth","profundidad {count}").format(count=info.d))
        if info.super:
            compression={0:tr("compression_none","ninguna"),1:"BasisLZ",2:"zstd",3:"zlib"}.get(info.super,str(info.super))
            parts.append(tr("supercompression","supercompresión {value}").format(value=compression))
        return ", ".join(parts)

    def _localized_text_kind(self,data):
        raw=classify_text(data)
        keys={"SPIR-V binario detectado en TXT":"type_spirv_text","SPIR-V textual (disassembly)":"type_spirv_disassembly","Código GLSL":"type_glsl","Archivo de texto":"type_text"}
        key=keys.get(raw)
        return self.window().tr(key,raw) if key and isinstance(self.window(),ExplorerWindow) else raw

    def __init__(self,path,archive=None):
        super().__init__(); self.path=Path(path); self.archive=Path(archive) if archive else None; self.inside=""
        self.history=[]; self.future=[]; self.selected=None; self._thumbnail_generation=0
        self._load_generation=0; self._load_entries=[]; self._load_index=0; self._load_worker=None
        self._grid_clearing=False; self._load_ready=False; self._load_error=""
        self.setStyleSheet("background:"+PANEL+";color:"+TEXT)
        outer=QVBoxLayout(self); outer.setContentsMargins(8,8,8,8)
        archive_bar=QHBoxLayout()
        self.banner=QLabel(self.window().tr("package_banner", "PAQUETE DE MOD · ZIP SIN COMPRESIÓN"))
        self.banner.setStyleSheet(f"background:{MOD};color:#ffe0ad;padding:2px 7px;font-size:9pt;font-weight:600;")
        self.banner.setFixedHeight(23)
        self.banner.setVisible(bool(archive)); archive_bar.addWidget(self.banner)
        archive_bar.addStretch()
        self.add_archive_files=QPushButton(self.window().tr("add_replace_files", "Añadir / reemplazar archivos"))
        self.add_archive_files.setToolTip(self.window().tr("add_replace_tip", "Importa archivos en la carpeta actual del paquete; si ya existen, los reemplaza"))
        self.add_archive_files.setVisible(bool(archive))
        self.add_archive_files.clicked.connect(self.import_archive_files)
        archive_bar.addWidget(self.add_archive_files)
        outer.addLayout(archive_bar)
        split=QSplitter(); outer.addWidget(split)
        self.grid=QListWidget(); self.grid.setViewMode(QListWidget.IconMode); self.grid.setResizeMode(QListWidget.Adjust); self.grid.setMovement(QListWidget.Static)
        self.grid.setIconSize(QSize(88,88)); self.grid.setGridSize(QSize(150,142)); self.grid.setSpacing(7)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection); self.grid.setDragEnabled(False)
        self.grid.itemSelectionChanged.connect(self.selection_changed)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.grid.itemDoubleClicked.connect(self.open_item)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.grid)
        self.loading_page = QWidget()
        loading_layout = QVBoxLayout(self.loading_page)
        loading_layout.setContentsMargins(20, 20, 20, 20)
        loading_layout.addStretch(1)
        self.loading_gif = QLabel(alignment=Qt.AlignCenter)
        self.loading_movie = QMovie(str(Path(__file__).resolve().parent / "res" / "loading.gif"))
        if self.loading_movie.isValid():
            self.loading_gif.setMovie(self.loading_movie)
            self.loading_movie.setScaledSize(QSize(112, 112))
        else:
            self.loading_gif.setText("◌")
            self.loading_gif.setStyleSheet("color:#00e878;font-size:54pt;")
        loading_layout.addWidget(self.loading_gif)
        self.loading_text = QLabel(self.window().tr("getting_data", "Obteniendo datos...") if isinstance(self.window(), ExplorerWindow) else "Obteniendo datos...", alignment=Qt.AlignCenter)
        self.loading_text.setStyleSheet("color:#e8eaed;font-size:13pt;font-weight:600;")
        loading_layout.addWidget(self.loading_text)
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setTextVisible(False)
        self.loading_progress.setFixedWidth(280)
        self.loading_progress.setStyleSheet("QProgressBar{background:#151719;border:1px solid #41454b;border-radius:5px;height:9px;} QProgressBar::chunk{background:#00e878;border-radius:4px;}")
        loading_layout.addWidget(self.loading_progress, 0, Qt.AlignHCenter)
        loading_layout.addStretch(1)
        self.content_stack.addWidget(self.loading_page)
        split.addWidget(self.content_stack)
        self.details=QFrame(); self.details.setMinimumWidth(270); self.details.setMaximumWidth(390); self.details.setStyleSheet("background:"+PANEL2+";border-radius:6px;")
        d=QVBoxLayout(self.details); self.preview=QLabel(self.window().tr("selected_file", "Selecciona un archivo") if isinstance(self.window(), ExplorerWindow) else "Selecciona un archivo",alignment=Qt.AlignCenter); self.preview.setMinimumHeight(210)
        self.preview.setStyleSheet("color:"+GREEN+";font-size:15px;"); d.addWidget(self.preview)
        self.name=QLabel(""); self.name.setWordWrap(True); self.name.setStyleSheet("color:"+GREEN+";font-weight:600"); d.addWidget(self.name)
        self.info=QLabel(""); self.info.setWordWrap(True); self.info.setStyleSheet("color:"+MUTED); d.addWidget(self.info); d.addStretch()
        split.addWidget(self.details); split.setSizes([800,320]); self.items=[]; self.refresh()
    def _context_menu(self, position):
        item = self.grid.itemAt(position)
        if item is None:
            self.window().show_directory_context_menu(self, self.grid.mapToGlobal(position))
            return
        if not item.isSelected():
            self.grid.clearSelection()
            item.setSelected(True)
        self.window().show_file_context_menu(self, self.grid.mapToGlobal(position))

    def selected_entries(self):
        return [(item.data(Qt.UserRole)[0], item.data(Qt.UserRole)[1])
                for item in self.grid.selectedItems()]

    def import_archive_files(self):
        if not self.archive:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, self.window().tr("add_files_to_package", "Añadir archivos al paquete"))
        if not paths:
            return
        additions = {}
        try:
            with zipfile.ZipFile(self.archive, "r") as current:
                existing = set(current.namelist())
            for source in paths:
                source_path = Path(source)
                target_name = (self.inside.strip("/") + "/" + source_path.name).strip("/")
                if target_name in existing:
                    answer = QMessageBox.question(
                        self, self.window().tr("replace_file", "Reemplazar archivo"),
                        self.window().tr("package_file_exists", "«{name}» ya existe en esta carpeta. ¿Quieres reemplazarlo?").format(name=source_path.name),
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if answer != QMessageBox.Yes:
                        continue
                additions[target_name] = source_path.read_bytes()
            if additions:
                write_archive_entries(self.archive, replacements=additions, additions=additions)
                self.refresh()
                self.window().statusBar().showMessage(
                    self.window().tr("files_added_package", "{count} archivo(s) incorporado(s) al paquete").format(count=len(additions)), 5000)
        except Exception as exc:
            QMessageBox.critical(self, self.window().tr("modify_package", "Modificar paquete"), self.window().tr("archive_error", "No se pudieron incorporar los archivos:\n{error}").format(error=exc))

    def entries(self):
        if not self.archive:
            try:return sorted(self.path.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
            except OSError:return []
        prefix=self.inside.strip("/"); base=prefix+"/" if prefix else ""; dirs=set(); files=[]
        with zipfile.ZipFile(self.archive) as z:
            for info in z.infolist():
                n=info.filename.replace("\\\\","/")
                if not n.startswith(base) or n==base:continue
                rest=n[len(base):]; first,sep,_=rest.partition("/")
                if sep:dirs.add(first)
                elif first and not info.is_dir():files.append(first)
        return [("dir",n) for n in sorted(dirs,key=str.lower)]+[("file",n) for n in sorted(files,key=str.lower)]

    def _show_loading(self):
        self.content_stack.setCurrentWidget(self.loading_page)
        self._load_entries = []
        self._load_index = 0
        self._load_ready = False
        self._load_error = ""
        self._grid_clearing = True
        self.loading_text.setText(self.window().tr("getting_data", "Obteniendo datos..."))
        self.loading_progress.setRange(0, 0)
        if self.loading_movie.isValid():
            self.loading_movie.start()
        self._clear_grid_batch(self._load_generation)

    def _clear_grid_batch(self, generation):
        if generation != self._load_generation:
            return
        remaining = min(150, self.grid.count())
        for _ in range(remaining):
            item = self.grid.takeItem(self.grid.count() - 1)
            del item
        if self.grid.count():
            QTimer.singleShot(0, lambda g=generation: self._clear_grid_batch(g))
            return
        self.items = []
        self._grid_clearing = False
        if self._load_error:
            if self.loading_movie.isValid():
                self.loading_movie.stop()
            self.content_stack.setCurrentWidget(self.grid)
            QMessageBox.critical(self, self.window().tr("load_directory", "Cargar directorio"), self._load_error)
        elif self._load_ready:
            self._load_next_batch(generation)

    def refresh(self):
        self._thumbnail_generation += 1
        self._load_generation += 1
        generation = self._load_generation
        self._show_loading()
        worker = DirectoryLoadWorker(self.path, self.archive, self.inside)
        worker.signals.progress.connect(lambda count, g=generation: self._load_scan_progress(g, count))
        worker.signals.finished.connect(lambda entries, error, g=generation: self._directory_entries_ready(g, entries, error))
        self._load_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _load_scan_progress(self, generation, count):
        if generation == self._load_generation:
            self.loading_text.setText(self.window().tr("getting_count", "Obteniendo datos... ({count:,} entradas)").format(count=count))

    def _directory_entries_ready(self, generation, entries, error):
        if generation != self._load_generation:
            return
        self._load_worker = None
        if error:
            self._load_error = error
            if not self._grid_clearing:
                if self.loading_movie.isValid():
                    self.loading_movie.stop()
                self.content_stack.setCurrentWidget(self.grid)
                QMessageBox.critical(self, self.window().tr("load_directory", "Cargar directorio"), error)
            return
        self._load_entries = entries or []
        self._load_ready = True
        self.loading_text.setText(self.window().tr("loading_files", "Cargando archivos..."))
        self.loading_progress.setRange(0, max(1, len(self._load_entries)))
        self.loading_progress.setValue(0)
        if not self._grid_clearing:
            self._load_next_batch(generation)

    def _load_next_batch(self, generation):
        if generation != self._load_generation:
            return
        entries = self._load_entries
        end = min(self._load_index + 100, len(entries))
        for entry in entries[self._load_index:end]:
            if isinstance(entry, tuple):
                # Disco: (bool, nombre). ZIP: ("dir"|"file", nombre).
                isdir = entry[0] if isinstance(entry[0], bool) else entry[0] == "dir"
                name = entry[1]
            else:
                isdir, name = entry
            item = QListWidgetItem(self.icon_for(name, isdir), name)
            item.setData(Qt.UserRole, (name, isdir))
            item.setToolTip(name)
            self.grid.addItem(item)
            self.items.append(item)
        self._load_index = end
        self.loading_progress.setValue(end)
        if end < len(entries):
            self.loading_text.setText(self.window().tr("loading_count", "Cargando archivos... ({current:,}/{total:,})").format(current=end, total=len(entries)))
            QTimer.singleShot(0, lambda g=generation: self._load_next_batch(g))
            return
        self.name.setText("")
        self.info.setText("")
        self.preview.setPixmap(QPixmap())
        self.preview.setText(self.window().tr("selected_file", "Selecciona un archivo"))
        if self.loading_movie.isValid():
            self.loading_movie.stop()
        self.content_stack.setCurrentWidget(self.grid)
        for index, entry in enumerate(entries):
            if isinstance(entry, tuple):
                # Disco: (bool, nombre). ZIP: ("dir"|"file", nombre).
                isdir = entry[0] if isinstance(entry[0], bool) else entry[0] == "dir"
                name = entry[1]
            else:
                isdir, name = entry
            if not isdir and Path(name).suffix.lower() == ".ktx2":
                QTimer.singleShot(0, lambda i=index, n=name, g=generation:
                                  self.window().queue_texture_thumbnail(self, i, n, g))

    def icon_for(self,name,isdir):
        ext=Path(name).suffix.lower().lstrip(".")
        model_buf = is_model_buffer_name(name)
        key="folder" if isdir else "model_buf" if ext=="buf" and model_buf else "asm_s" if ext=="s" else ext if ext in ("spv","txt","buf","xmod","mlpk","ktx2","ini","json","glsl","s") else "generic"
        base=Path(__file__).resolve().parent/"res"
        for p in (base/(key+".png"),base/(key+"_256.png")):
            if p.exists():return QIcon(str(p))
        return generated_icon(key,88)
    def get_bytes(self,name):
        if self.archive:
            with zipfile.ZipFile(self.archive) as z:return z.read((self.inside.strip("/")+"/"+name).strip("/"))
        return (self.path/name).read_bytes()
    def selection_changed(self):
        selected=self.grid.selectedItems()
        if not selected:
            self.name.setText("")
            self.info.setText("")
            self.preview.setPixmap(QPixmap())
            self.preview.setText(self.window().tr("selected_file", "Selecciona un archivo"))
            return
        name,isdir=selected[0].data(Qt.UserRole); self.selected=name
        selected_ids={id(item) for item in selected}
        for it in self.items:
            if id(it) in selected_ids:
                it.setBackground(QColor(23,61,48)); it.setForeground(QColor("#ffffff"))
            else:
                it.setBackground(QColor(PANEL2)); it.setForeground(QColor(TEXT))
        self.name.setText(name if len(selected)==1 else self.window().tr("selected_elements", "{count} elementos seleccionados").format(count=len(selected)))
        self.preview.setPixmap(QPixmap())
        if isdir:
            icon=self.icon_for(name,True)
            self.preview.setPixmap(icon.pixmap(QSize(176,176)))
            self.preview.setText("")
            self.info.setText(self.window().tr("folder_preview_info", "Carpeta\\nDoble clic para abrir"))
            return
        try:
            data=self.get_bytes(name); ext=Path(name).suffix.lower()
            kind={".spv":self.window().tr("type_spirv", "Shader SPIR-V binario"),".s":self.window().tr("type_spvasm", "SPIR-V Assembly"), ".txt":self._localized_text_kind(data),".ini":self.window().tr("type_ini", "Archivo INI"),".json":self.window().tr("type_json", "Archivo JSON"),".glsl":self.window().tr("type_glsl", "Shader GLSL"),".buf":self.window().tr("type_buffer", "Buffer binario (.buf)"),".ktx2":self.window().tr("type_ktx2", "Textura Khronos KTX2")}.get(ext,self.window().tr("type_file", "Archivo {extension}").format(extension=ext or self.window().tr("unknown", "desconocido")))
            if ext==".ktx2":
                self.preview.setText(self.window().tr("decoding_ktx", "Decodificando KTX2…"))
                source=self.window().texture_source_path(self,name,data)
                png=self.window().decode_texture(source,rapido=False)
                pix=QPixmap(str(png))
                if pix.isNull():raise RuntimeError(self.window().tr("decoded_image_open_error", "No se pudo abrir la imagen decodificada."))
                self.preview.setPixmap(pix.scaled(230,210,Qt.KeepAspectRatio,Qt.SmoothTransformation))
                try:
                    import ktx2_util
                    kinfo=ktx2_util.leer_cabecera(source)
                    kind+="\n"+self._ktx_summary(kinfo)
                    fmt=self.window().tr("vulkan_format", "\nFormato Vulkan: fmt{format}").format(format=kinfo.fmt)
                except Exception as exc:fmt=self.window().tr("metadata_error", "\nMetadatos: {error}").format(error=exc)
            else:
                # Mostrar el icono correspondiente al tipo de archivo en el panel lateral.
                icon=self.icon_for(name,False)
                self.preview.setPixmap(icon.pixmap(QSize(176,176)))
                self.preview.setText("")
                fmt=""
            self.info.setText(self.window().tr("type_info", "Tipo: {kind}{format}\nTamaño: {size:.2f} KB\nUbicación: {location}").format(kind=kind,format=fmt,size=len(data)/1024,location=self.archive or self.path))
        except Exception as e:
            self.preview.setPixmap(QPixmap()); self.preview.setText(self.window().tr("decode_failed", "No se pudo decodificar"))
            self.info.setText(self.window().tr("read_error", "No se pudo leer:\n{error}").format(error=e))
    def open_item(self,item):
        name,isdir=item.data(Qt.UserRole)
        if isdir:
            target=(self.inside.strip("/")+"/"+name).strip("/") if self.archive else str(self.path/name)
            self.window().navigate_tab(self,target); return
        ext=Path(name).suffix.lower()
        if ext in (".xmod",".mlpk") and not self.archive:
            try:
                with zipfile.ZipFile(self.path/name) as z:z.testzip()
                self.window().add_archive(self.path/name)
            except Exception as e:QMessageBox.critical(self,self.window().tr("container", "Contenedor"),self.window().tr("open_package_error", "No se pudo abrir el paquete:\n{error}").format(error=e))
            return
        if ext==".buf" and not self.archive and is_model_buffer_name(name):
            self.window().open_model_viewer(self.path/name)
            return
        try:
            data=self.get_bytes(name)
            if ext==".ktx2":
                source=self.window().texture_source_path(self,name,data)
                png=self.window().decode_texture(source,rapido=False)
                self.window().show_child(ImageViewer(png,self.window()))
            elif ext in (".spv",".txt",".ini",".json",".glsl",".s"):
                if self.archive:
                    source=Path(tempfile.gettempdir())/("xxami_"+str(abs(hash((str(self.archive),self.inside,name))))+ext); source.write_bytes(data)
                else:source=self.path/name
                save_handler = None
                if self.archive:
                    entry_name = (self.inside.strip("/") + "/" + name).strip("/")
                    archive_path = self.archive
                    def save_handler(payload, archive_path=archive_path, entry_name=entry_name):
                        write_archive_entries(archive_path, replacements={entry_name: payload})
                        self.window().statusBar().showMessage(self.window().tr("save_archive", "Guardado en {archive}: {entry}").format(archive=archive_path.name, entry=entry_name), 5000)
                self.window().show_child(ShaderEditor(source,data,self.window(),save_handler=save_handler))
        except Exception as e:QMessageBox.critical(self,self.window().tr("open", "Abrir"),str(e))

class ExplorerWindow(QMainWindow):
    def __init__(self,initial=None,log_path=None):
        super().__init__()
        self.log_path=Path(log_path).resolve() if log_path else Path(__file__).resolve().with_name("xxami_crash_log.txt")
        # La configuración y los catálogos deben existir antes de crear
        # cualquier control que consulte self.tr().
        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        self.config_path = app_dir / "explorer.ini"
        self.settings = QSettings("AMI", "AMI Explorer")
        self.config = QSettings(str(self.config_path), QSettings.IniFormat)
        self.config.setValue("general/language", self.config.value("general/language", "es"))
        self.config.sync()
        self.file_clipboard = []
        self.file_clipboard_cut = False
        self.external_processes = []
        self._load_language_catalog()
        self.setWindowTitle(self.tr("open_resource_explorer", "AMI: Resource Explorer")); self.setWindowIcon(application_icon("explorer_icon")); self.resize(1360,850); self.setMinimumSize(900,600); self.setStyleSheet(STYLE)
        central=QWidget(); root=QVBoxLayout(central); root.setContentsMargins(10,10,10,10); root.setSpacing(8)
        nav=QHBoxLayout()
        self.btn_back=self._nav_button(QStyle.SP_ArrowBack,self.tr("back", "Atrás"),self.back); nav.addWidget(self.btn_back)
        self.btn_forward=self._nav_button(QStyle.SP_ArrowForward,self.tr("forward", "Adelante"),self.forward); nav.addWidget(self.btn_forward)
        self.btn_up=self._nav_button(QStyle.SP_ArrowUp,self.tr("up", "Subir un nivel"),self.up); nav.addWidget(self.btn_up)
        self.btn_refresh=self._nav_button(QStyle.SP_BrowserReload,self.tr("refresh", "Actualizar"),self.refresh); nav.addWidget(self.btn_refresh)
        self.path=QLineEdit(); self.path.setPlaceholderText(self.tr("enter_path", "Escribe una ruta o selecciona una sugerencia…")); self.path.returnPressed.connect(self.go_path); nav.addWidget(self.path,1)
        self.fs_model=QFileSystemModel(self); self.fs_model.setRootPath("")
        self.path_completer=QCompleter(self.fs_model,self); self.path_completer.setCompletionRole(Qt.DisplayRole); self.path_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.path.setCompleter(self.path_completer); self.path_completer.activated.connect(self.navigate_folder)
        add=self._nav_button(QStyle.SP_DirOpenIcon,self.tr("choose_folder", "Elegir carpeta"),self.choose_folder); nav.addWidget(add)
        self.btn_settings=QToolButton(); self.btn_settings.setIcon(resource_icon("conf",48)); self.btn_settings.setIconSize(QSize(30,30)); self.btn_settings.setToolTip(self.tr("settings", "Configuración")); self.btn_settings.setAccessibleName(self.tr("settings", "Configuración")); self.btn_settings.setAutoRaise(True); self.btn_settings.setFixedSize(40,38); self.btn_settings.clicked.connect(self.open_settings); nav.addWidget(self.btn_settings)
        self.search=QLineEdit(); self.search.setPlaceholderText(self.tr("search_location", "Buscar en esta ubicación")); self.search.setMaximumWidth(280); self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(lambda:self.filter_items(self.search.text())); self.search.textChanged.connect(self.filter_items)
        self.search_action=QAction(self._search_icon(),self.tr("search", "Buscar"),self.search)
        self.search.addAction(self.search_action,QLineEdit.TrailingPosition); self.search_action.triggered.connect(lambda:self.filter_items(self.search.text()))
        nav.addWidget(self.search)
        root.addLayout(nav); self.tabs=QTabWidget(); self.tabs.setTabsClosable(True); self.tabs.tabCloseRequested.connect(self.close_tab); self.tabs.currentChanged.connect(self.sync_path)
        self.add_tab_button=QToolButton(); self.add_tab_button.setText("+"); self.add_tab_button.setToolTip(self.tr("open_new_tab", "Abrir otra carpeta en una nueva pestaña")); self.add_tab_button.setFixedSize(30,28); self.add_tab_button.setAutoRaise(True); self.add_tab_button.setStyleSheet("QToolButton{font-size:20px;font-weight:600;color:#e8eaed;border:1px solid #454950;border-radius:5px;} QToolButton:hover{color:#00e878;border-color:#00e878;}")
        self.add_tab_button.clicked.connect(self.choose_folder); self.tabs.setCornerWidget(self.add_tab_button,Qt.TopRightCorner); root.addWidget(self.tabs)
        self.setCentralWidget(central); self.setStatusBar(QStatusBar()); self.children=[]
        diagnostics=self.menuBar().addMenu(self.tr("diagnostics", "Diagnóstico"))
        self._log_open_action=QAction(self.tr("open_log", "Abrir registro de errores"),self)
        self._log_open_action.triggered.connect(self.open_log_file); diagnostics.addAction(self._log_open_action)
        self._log_export_action=QAction(self.tr("export_log", "Exportar registro…"),self)
        self._log_export_action.triggered.connect(self.export_log_file); diagnostics.addAction(self._log_export_action)
        self._thread_pool=QThreadPool(self); self._thread_pool.setMaxThreadCount(2); self._texture_workers=[]
        restored=False
        if initial:self.open_folder(initial)
        else:
            restored=self.restore_session()
            if not restored:self.open_folder(str(Path.home()))
        geometry=self.settings.value("window/geometry")
        if geometry:self.restoreGeometry(geometry)
        window_state=self.settings.value("window/state")
        if window_state:self.restoreState(window_state)
    def open_log_file(self):
        if not self.log_path.is_file():
            QMessageBox.information(self,self.tr("diagnostics", "Diagnóstico"),self.tr("log_not_found", "Todavía no existe un registro de errores."))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path)))

    def export_log_file(self):
        if not self.log_path.is_file():
            QMessageBox.information(self,self.tr("diagnostics", "Diagnóstico"),self.tr("log_not_found", "Todavía no existe un registro de errores."))
            return
        target,_=QFileDialog.getSaveFileName(self,self.tr("export_log", "Exportar registro…"),str(Path.home()/"xxami_crash_log.txt"),self.tr("log_filter", "Registro de texto (*.txt)"))
        if not target:return
        try:
            Path(target).write_bytes(self.log_path.read_bytes())
            self.statusBar().showMessage(self.tr("log_exported", "Registro exportado correctamente"),4000)
        except Exception as exc:
            QMessageBox.critical(self,self.tr("export_log", "Exportar registro…"),str(exc))

    def _load_language_catalog(self):
        # Primero la ruta solicitada junto al explorador; en PyInstaller one-file
        # también se admite el catálogo empaquetado como recurso de solo lectura.
        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        self.language_dir = app_dir / "lang" / "explorer_lang"
        bundled_dir = Path(getattr(sys, "_MEIPASS", app_dir)) / "lang" / "explorer_lang"
        if not self.language_dir.is_dir() and bundled_dir.is_dir():
            self.language_dir = bundled_dir
        self.languages = {}
        self.language_errors = []
        if self.language_dir.is_dir():
            for path in sorted(self.language_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                    name = data.get("name") if isinstance(data, dict) else None
                    strings = data.get("strings") if isinstance(data, dict) else None
                    if not isinstance(name, str) or not name.strip() or not isinstance(strings, dict):
                        raise ValueError("Se requiere 'name' no vacío y un objeto 'strings'.")
                    if not all(isinstance(k, str) and isinstance(v, str) for k, v in strings.items()):
                        raise ValueError("Todas las entradas de 'strings' deben ser cadenas.")
                    self.languages[path.stem] = data
                except (OSError, ValueError, TypeError) as exc:
                    self.language_errors.append(f"{path.name}: {exc}")
        if not self.languages:
            self.languages = {"es": {"name": "Español", "strings": {}}}

    def tr(self, key, fallback=None):
        code = str(self.config.value("general/language", "es"))
        catalog = self.languages.get(code, {})
        return catalog.get("strings", {}).get(key, fallback or key)

    def _file_category(self, filename):
        ext = Path(filename).suffix.lower()
        if ext in {".ini", ".json", ".txt", ".xml", ".yaml", ".yml", ".toml", ".cfg", ".csv"}:
            return "text"
        if ext in {".spv", ".s", ".glsl", ".vert", ".frag", ".geom", ".tesc", ".tese", ".comp", ".hlsl"}:
            return "shader"
        if ext in {".buf", ".obj", ".fbx", ".gltf", ".glb", ".mesh"}:
            return "model"
        if ext in {".ktx2", ".ktx", ".png", ".jpg", ".jpeg", ".dds", ".tga", ".bmp", ".webp"}:
            return "texture"
        if ext in {".xmod", ".mlpk"}:
            return "package"
        return "other"

    def _configured_program(self, category, operation):
        return str(self.config.value(f"tools/{category}/{operation}", "") or "").strip()

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("settings", "Configuración"))
        dialog.setMinimumSize(760, 650)
        outer = QVBoxLayout(dialog)
        tabs = QTabWidget()
        general = QWidget()
        layout = QVBoxLayout(general)
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel(self.tr("language", "Idioma")))
        language = QComboBox()
        for code, data in self.languages.items():
            language.addItem(str(data.get("name", code)), code)
        current_language = str(self.config.value("general/language", "es"))
        index = language.findData(current_language)
        if index >= 0:
            language.setCurrentIndex(index)
        language_row.addWidget(language, 1)
        layout.addLayout(language_row)
        layout.addWidget(QLabel(self.tr("file_tools", "Herramientas por tipo de archivo")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        rows_host = QWidget()
        rows_layout = QVBoxLayout(rows_host)
        categories = [
            ("text", "category_text"),
            ("shader", "category_shader"),
            ("model", "category_model"),
            ("texture", "category_texture"),
            ("package", "category_package"),
            ("other", "category_other"),
        ]
        controls = {}
        for key, title in categories:
            group = QGroupBox(self.tr(title, title))
            group_layout = QGridLayout(group)
            controls[key] = {}
            for col, operation in enumerate(("manage", "edit")):
                label = QLabel(self.tr("manage", "Gestión") if operation == "manage" else self.tr("editing", "Edición"))
                combo = QComboBox()
                combo.addItem(self.tr("use_internal", "Utilizar herramientas del explorador"), "")
                combo.addItem(self.tr("browse", "Examinar..."), "__browse__")
                selected = self._configured_program(key, operation)
                if selected:
                    combo.addItem(selected, selected)
                    combo.setCurrentIndex(combo.count() - 1)
                combo.currentIndexChanged.connect(
                    lambda idx, c=combo, k=key, op=operation:
                        self._browse_external_tool(c, k, op) if c.currentData() == "__browse__" else None
                )
                group_layout.addWidget(label, 0, col * 2)
                group_layout.addWidget(combo, 0, col * 2 + 1)
                controls[key][operation] = combo
            rows_layout.addWidget(group)
        rows_layout.addStretch(1)
        scroll.setWidget(rows_host)
        layout.addWidget(scroll, 1)
        tabs.addTab(general, self.tr("general", "General"))
        about = QWidget()
        about_layout = QHBoxLayout(about)
        about_layout.setContentsMargins(22, 22, 22, 22)
        about_layout.setSpacing(28)
        about_layout.addWidget(ExplorerAboutLogo(about, self.tr("logo_missing", "No se encontró res/explorer_logo.png"), self.tr("logo_tooltip", "Coloca explorer_logo.png en res junto a file_explorer_qt.py o en res dentro del paquete de la aplicación.")), 1)
        description = QLabel(
            self.tr("about_description", "AMI Resource Explorer es un explorador de archivos que permite navegar por los directorios en busca de recursos volcados. Esta herramienta permite realizar acciones típicas de un explorador de archivos convencional, pero enfocada a tratar con archivos volcados por la herramienta de Android XXAMI (Android Model Importer), y sus mods. AMI Resource Explorer funciona en conjunto con AMI 3D Viewer, y forma parte de la suite del analizador, visualizador y modificador de recursos para API Vulkan Android: XXAMI DumpAna. Creado por Kokokuro*")
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignCenter)
        description.setFont(QFont("Segoe UI", 13, QFont.DemiBold))
        description.setMinimumWidth(300)
        about_layout.addWidget(description, 1)
        tabs.addTab(about, self.tr("about", "Acerca de"))
        outer.addWidget(tabs, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        apply_button = QPushButton(self.tr("apply", "Aplicar"))
        ok_button = QPushButton(self.tr("accept", "Aceptar"))
        cancel_button = QPushButton(self.tr("cancel", "Cancelar"))
        buttons.addWidget(apply_button)
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        outer.addLayout(buttons)

        def apply():
            self.config.setValue("general/language", language.currentData() or "es")
            for category, operations in controls.items():
                for operation, combo in operations.items():
                    value = combo.currentData() or ""
                    self.config.setValue(f"tools/{category}/{operation}", value)
            self.config.sync()
            self.statusBar().showMessage(self.tr("settings_saved", "Configuración guardada"), 3000)

        apply_button.clicked.connect(apply)
        ok_button.clicked.connect(lambda: (apply(), dialog.accept()))
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def _browse_external_tool(self, combo, category, operation):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("select_external_program", "Seleccionar programa externo"), "",
            self.tr("executable_filter", "Programas ejecutables (*.exe *.com *.bat *.cmd);;Todos los archivos (*)")
        )
        if not path:
            previous = self._configured_program(category, operation)
            idx = combo.findData(previous)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            return
        idx = combo.findData(path)
        if idx < 0:
            combo.addItem(path, path)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)

    def show_file_context_menu(self, tab, global_position):
        selected = tab.selected_entries()
        if not selected:
            return
        menu = QMenu(self)
        open_action = menu.addAction(self.tr("open", "Abrir"))
        edit_action = menu.addAction(self.tr("edit", "Editar"))
        menu.addSeparator()
        cut_action = menu.addAction(self.tr("cut", "Cortar"))
        copy_action = menu.addAction(self.tr("copy", "Copiar"))
        rename_action = menu.addAction(self.tr("rename", "Renombrar"))
        delete_action = menu.addAction(self.tr("delete", "Eliminar"))
        multi = len(selected) > 1
        edit_action.setEnabled(not multi and not selected[0][1])
        rename_action.setEnabled(not multi)
        open_action.triggered.connect(lambda: self.open_selected(tab, selected))
        edit_action.triggered.connect(lambda: self.edit_selected(tab, selected[0][0]))
        cut_action.triggered.connect(lambda: self.copy_selected(tab, selected, True))
        copy_action.triggered.connect(lambda: self.copy_selected(tab, selected, False))
        rename_action.triggered.connect(lambda: self.rename_selected(tab, selected[0][0]))
        delete_action.triggered.connect(lambda: self.delete_selected(tab, selected))
        menu.exec(global_position)

    def open_selected(self, tab, selected):
        if len(selected) == 1:
            item = next((it for it in tab.items if it.data(Qt.UserRole) == selected[0]), None)
            if item:
                tab.open_item(item)
            return
        for name, isdir in selected:
            if not isdir:
                self.open_external(tab, name, "manage")

    def edit_selected(self, tab, name):
        self.open_external(tab, name, "edit")

    def open_external(self, tab, name, operation):
        category = self._file_category(name)
        program = self._configured_program(category, operation)
        if not program:
            if operation == "edit":
                item = next((it for it in tab.items if it.data(Qt.UserRole) == (name, False)), None)
                if item:
                    tab.open_item(item)
            else:
                if tab.archive:
                    self._launch_external_for_archive(tab, name, None, program)
                else:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(tab.path / name)))
            return
        self._launch_external_for_archive(tab, name, program, operation)

    def _launch_external_for_archive(self, tab, name, program, operation):
        suffix = Path(name).suffix.lower()
        is_texture = suffix == ".ktx2"
        temp_root = Path(tempfile.mkdtemp(prefix="xxami_external_"))
        archive_entry = (tab.inside.strip("/") + "/" + name).strip("/")
        try:
            if tab.archive:
                payload = tab.get_bytes(name)
                source = temp_root / Path(name).name
                source.write_bytes(payload)
            else:
                source = tab.path / name
                payload = source.read_bytes() if is_texture else None
            target = source
            original_ktx = None
            if is_texture:
                if not tab.archive:
                    payload = source.read_bytes()
                original_ktx = temp_root / "original.ktx2"
                original_ktx.write_bytes(payload)
                decode_source = temp_root / "source.ktx2"
                decode_source.write_bytes(payload)
                png = self.decode_texture(decode_source, rapido=False)
                target = temp_root / (Path(name).stem + ".png")
                target.write_bytes(Path(png).read_bytes())
            if not program:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
                QTimer.singleShot(600000, lambda p=temp_root: __import__("shutil").rmtree(p, ignore_errors=True))
                return
            process = QProcess(self)
            if sys.platform.startswith("win") and Path(program).suffix.lower() in (".bat", ".cmd"):
                process.setProgram(os.environ.get("COMSPEC", "cmd.exe"))
                process.setArguments(["/c", program, str(target)])
            else:
                process.setProgram(program)
                process.setArguments([str(target)])
            state = {"tab": tab, "name": name, "target": target, "temp": temp_root,
                     "archive_entry": archive_entry, "is_archive": bool(tab.archive),
                     "is_texture": is_texture, "original": original_ktx, "process": process,
                     "operation": operation}
            process.finished.connect(lambda code, status, st=state: self._external_edit_finished(st, code))
            process.errorOccurred.connect(lambda err, st=state: self._external_edit_error(st, err))
            self.external_processes.append(state)
            process.start()
        except Exception as exc:
            import shutil
            shutil.rmtree(temp_root, ignore_errors=True)
            QMessageBox.critical(self, self.tr("external_tool", "Herramienta externa"), self.tr("external_tool_prepare", "No se pudo preparar el archivo:\n{error}").format(error=exc))

    def _external_edit_error(self, state, error):
        import shutil
        try:
            QMessageBox.warning(self, self.tr("external_tool", "Herramienta externa"), self.tr("external_tool_start", "No se pudo iniciar el programa externo: {error}").format(error=error))
        finally:
            shutil.rmtree(state["temp"], ignore_errors=True)
            if state in self.external_processes:
                self.external_processes.remove(state)

    def _external_edit_finished(self, state, exit_code):
        import shutil
        try:
            if state.get("operation") == "manage":
                return
            if exit_code != 0:
                QMessageBox.warning(self, self.tr("external_edit", "Edición externa"), self.tr("external_exit", "El editor terminó con código {code}; no se sustituyó el archivo original.").format(code=exit_code))
                return
            target = state["target"]
            if not target.is_file():
                QMessageBox.warning(self, self.tr("external_edit", "Edición externa"), self.tr("missing_output", "El programa terminó, pero no se encontró el archivo de salida."))
                return
            if state["is_texture"]:
                import ktx2_util
                header = ktx2_util.leer_cabecera(state["original"])
                format_names = {
                    9: "R8_UNORM", 10: "R8_SNORM", 13: "R8_UINT", 14: "R8_SINT",
                    16: "R8G8_UNORM", 17: "R8G8_SNORM", 20: "R8G8_UINT", 21: "R8G8_SINT",
                    23: "R8G8B8_UNORM", 29: "R8G8B8_SRGB",
                    30: "B8G8R8_UNORM", 36: "B8G8R8_SRGB",
                    37: "R8G8B8A8_UNORM", 38: "R8G8B8A8_SNORM",
                    41: "R8G8B8A8_UINT", 42: "R8G8B8A8_SINT", 43: "R8G8B8A8_SRGB",
                    44: "B8G8R8A8_UNORM", 50: "B8G8R8A8_SRGB",
                    97: "R16G16B16A16_SFLOAT", 109: "R32G32B32A32_SFLOAT",
                    131: "BC1_RGB_UNORM_BLOCK", 132: "BC1_RGB_SRGB_BLOCK",
                    133: "BC1_RGBA_UNORM_BLOCK", 134: "BC1_RGBA_SRGB_BLOCK",
                    137: "BC3_UNORM_BLOCK", 138: "BC3_SRGB_BLOCK",
                    141: "BC5_UNORM_BLOCK", 142: "BC5_SNORM_BLOCK",
                    145: "BC7_UNORM_BLOCK", 146: "BC7_SRGB_BLOCK",
                    157: "ASTC_4x4_UNORM_BLOCK", 158: "ASTC_4x4_SRGB_BLOCK",
                    159: "ASTC_5x4_UNORM_BLOCK", 160: "ASTC_5x4_SRGB_BLOCK",
                    161: "ASTC_5x5_UNORM_BLOCK", 162: "ASTC_5x5_SRGB_BLOCK",
                    163: "ASTC_6x5_UNORM_BLOCK", 164: "ASTC_6x5_SRGB_BLOCK",
                    165: "ASTC_6x6_UNORM_BLOCK", 166: "ASTC_6x6_SRGB_BLOCK",
                    167: "ASTC_8x5_UNORM_BLOCK", 168: "ASTC_8x5_SRGB_BLOCK",
                    169: "ASTC_8x6_UNORM_BLOCK", 170: "ASTC_8x6_SRGB_BLOCK",
                    171: "ASTC_8x8_UNORM_BLOCK", 172: "ASTC_8x8_SRGB_BLOCK",
                    173: "ASTC_10x5_UNORM_BLOCK", 174: "ASTC_10x5_SRGB_BLOCK",
                    175: "ASTC_10x6_UNORM_BLOCK", 176: "ASTC_10x6_SRGB_BLOCK",
                    177: "ASTC_10x8_UNORM_BLOCK", 178: "ASTC_10x8_SRGB_BLOCK",
                    179: "ASTC_10x10_UNORM_BLOCK", 180: "ASTC_10x10_SRGB_BLOCK",
                    181: "ASTC_12x10_UNORM_BLOCK", 182: "ASTC_12x10_SRGB_BLOCK",
                    183: "ASTC_12x12_UNORM_BLOCK", 184: "ASTC_12x12_SRGB_BLOCK",
                }
                format_name = format_names.get(header.fmt)
                if not format_name:
                    raise RuntimeError(f"No hay conversión PNG→KTX2 configurada para VkFormat {header.fmt}. El original se conserva sin cambios.")
                ktx_exe = Path(__file__).resolve().parent / "ktx.exe"
                if not ktx_exe.is_file():
                    ktx_exe = Path(sys.executable).resolve().parent / "ktx.exe"
                replacement = state["temp"] / "replacement.ktx2"
                ok, error = ktx2_util.crear_reemplazo(
                    str(ktx_exe), format_name, str(target),
                    str(state["original"]), str(replacement)
                )
                if not ok:
                    raise RuntimeError(error)
                payload = replacement.read_bytes()
            else:
                payload = target.read_bytes()
            if state["is_archive"]:
                write_archive_entries(state["tab"].archive, replacements={state["archive_entry"]: payload})
            else:
                destination = state["tab"].path / state["name"]
                temp_out = destination.with_name(destination.name + ".xxami_tmp")
                temp_out.write_bytes(payload)
                os.replace(temp_out, destination)
            state["tab"].refresh()
            self.statusBar().showMessage(self.tr("file_updated", "Archivo actualizado: {name}").format(name=state['name']), 5000)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("external_edit", "Edición externa"), self.tr("apply_result", "No se pudo aplicar el resultado:\n{error}").format(error=exc))
        finally:
            shutil.rmtree(state["temp"], ignore_errors=True)
            if state in self.external_processes:
                self.external_processes.remove(state)

    def copy_selected(self, tab, selected, cut):
        self.file_clipboard = [(tab, name, isdir, tab.inside) for name, isdir in selected]
        self.file_clipboard_cut = cut
        self.statusBar().showMessage(self.tr("cut_count" if cut else "copy_count", "Cortados {count} elemento(s)." if cut else "Copiados {count} elemento(s).").format(count=len(selected)), 4000)

    def paste_selected(self, destination_tab):
        import shutil
        import io
        copied = 0
        additions = {}
        removals = {}
        try:
            for source_tab, name, isdir, source_inside in self.file_clipboard:
                if source_tab.archive:
                    prefix = (source_inside.strip("/") + "/" + name).strip("/")
                    with zipfile.ZipFile(source_tab.archive, "r") as source_zip:
                        matches = [info for info in source_zip.infolist()
                                   if info.filename.rstrip("/") == prefix or info.filename.startswith(prefix + "/")]
                        if not matches:
                            continue
                        for info in matches:
                            if info.is_dir():
                                continue
                            relative = info.filename[len(prefix):].lstrip("/") if isdir else ""
                            dest_name = (name + "/" + relative).strip("/") if isdir else name
                            if destination_tab.archive:
                                target_name = (destination_tab.inside.strip("/") + "/" + dest_name).strip("/")
                                additions[target_name] = source_zip.read(info.filename)
                            else:
                                target = destination_tab.path / dest_name
                                if target.exists():
                                    raise FileExistsError(self.tr("destination_exists", "Ya existe «{name}» en el destino.").format(name=dest_name))
                                target.parent.mkdir(parents=True, exist_ok=True)
                                target.write_bytes(source_zip.read(info.filename))
                    if self.file_clipboard_cut:
                        removals.setdefault(source_tab.archive, []).append(prefix)
                else:
                    source = source_tab.path / name
                    if destination_tab.archive:
                        if isdir:
                            for current, _dirs, files in os.walk(source):
                                for filename in files:
                                    file_path = Path(current) / filename
                                    relative = file_path.relative_to(source).as_posix()
                                    target_name = (destination_tab.inside.strip("/") + "/" + name + "/" + relative).strip("/")
                                    additions[target_name] = file_path.read_bytes()
                        else:
                            target_name = (destination_tab.inside.strip("/") + "/" + name).strip("/")
                            additions[target_name] = source.read_bytes()
                    else:
                        target = destination_tab.path / name
                        if source.resolve() == target.resolve():
                            continue
                        if target.exists():
                            raise FileExistsError(self.tr("destination_exists", "Ya existe «{name}» en el destino.").format(name=name))
                        if self.file_clipboard_cut:
                            source.rename(target)
                        elif isdir:
                            shutil.copytree(source, target)
                        else:
                            shutil.copy2(source, target)
                    if self.file_clipboard_cut and destination_tab.archive:
                        removals.setdefault(None, []).append(source)
                copied += 1
            if destination_tab.archive and additions:
                with zipfile.ZipFile(destination_tab.archive, "r") as current:
                    existing = set(current.namelist())
                collision = existing.intersection(additions)
                if collision:
                    raise FileExistsError(self.tr("destination_exists", "Ya existe «{name}» en el destino.").format(name=sorted(collision)[0]))
                write_archive_entries(destination_tab.archive, additions=additions)
            for archive_path, prefixes in removals.items():
                if archive_path:
                    rewrite_archive_paths(archive_path, remove_prefixes=prefixes)
                else:
                    for source in prefixes:
                        if source.is_dir():
                            shutil.rmtree(source)
                        elif source.exists():
                            source.unlink()
            destination_tab.refresh()
            if self.file_clipboard_cut:
                self.file_clipboard = []
                self.file_clipboard_cut = False
            self.statusBar().showMessage(self.tr("pasted_count", "{count} elemento(s) pegado(s)").format(count=copied), 4000)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("paste", "Pegar"), str(exc))

    def rename_selected(self, tab, name):
        if tab.archive:
            new_name, ok = QInputDialog.getText(self, self.tr("rename", "Renombrar"), self.tr("new_name", "Nuevo nombre:"), text=name)
            if not ok or not new_name.strip() or new_name.strip() == name:
                return
            new_name = new_name.strip()
            if Path(new_name).name != new_name or new_name in (".", ".."):
                QMessageBox.warning(self, self.tr("rename", "Renombrar"), self.tr("invalid_element_name", "El nombre no es válido."))
                return
            old_entry = (tab.inside.strip("/") + "/" + name).strip("/")
            new_entry = (tab.inside.strip("/") + "/" + new_name).strip("/")
            try:
                rewrite_archive_paths(tab.archive, rename_prefixes={old_entry: new_entry})
                tab.refresh()
            except Exception as exc:
                QMessageBox.critical(self, self.tr("rename", "Renombrar"), str(exc))
            return
        new_name, ok = QInputDialog.getText(self, self.tr("rename", "Renombrar"), self.tr("new_name", "Nuevo nombre:"), text=name)
        if not ok or not new_name.strip() or new_name.strip() == name:
            return
        new_name = new_name.strip()
        if Path(new_name).name != new_name or new_name in (".", ".."):
            QMessageBox.warning(self, self.tr("rename", "Renombrar"), self.tr("invalid_element_name", "El nombre no es válido."))
            return
        source, target = tab.path / name, tab.path / new_name
        if target.exists():
            QMessageBox.warning(self, self.tr("rename", "Renombrar"), self.tr("element_exists", "Ya existe un elemento con ese nombre."))
            return
        try:
            source.rename(target)
            tab.refresh()
        except Exception as exc:
            QMessageBox.critical(self, self.tr("rename", "Renombrar"), str(exc))

    def delete_selected(self, tab, selected):
        answer = QMessageBox.question(self, self.tr("delete", "Eliminar"), self.tr("delete_confirm", "¿Eliminar {count} elemento(s) seleccionado(s)?").format(count=len(selected)),
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        import shutil
        try:
            if tab.archive:
                prefixes = [(tab.inside.strip("/") + "/" + name).strip("/") for name, _ in selected]
                rewrite_archive_paths(tab.archive, remove_prefixes=prefixes)
            else:
                for name, isdir in selected:
                    path = tab.path / name
                    if isdir:
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            tab.refresh()
        except Exception as exc:
            QMessageBox.critical(self, self.tr("delete", "Eliminar"), str(exc))

    def _resource_icon(self,name,size=38):
        resource=Path(__file__).resolve().parent/"res"/(name+".png")
        if resource.is_file():
            icon=QIcon(str(resource))
            if not icon.isNull(): return icon
        return generated_icon(name,size)
    def _search_icon(self):
        return self._resource_icon("search",28)
    def _nav_button(self,standard_icon,tooltip,callback):
        icon_name={QStyle.SP_ArrowBack:"back",QStyle.SP_ArrowForward:"forward",QStyle.SP_ArrowUp:"up",QStyle.SP_BrowserReload:"refresh",QStyle.SP_DirOpenIcon:"folder"}.get(standard_icon,"generic")
        b=QToolButton(); b.setIcon(self._resource_icon(icon_name,38)); b.setIconSize(QSize(30,30)); b.setToolTip(tooltip); b.setAccessibleName(tooltip); b.setAutoRaise(True); b.setFixedSize(40,38); b.clicked.connect(callback); return b

    def show_directory_context_menu(self, tab, global_position):
        menu = QMenu(self)
        new_menu = menu.addMenu(self.tr("new", "Nuevo"))
        is_xmod_archive = bool(tab.archive and tab.archive.suffix.lower() == ".xmod")
        creations = [
            (self.tr("new_control", "Archivo de control (INI)"), ".ini"),
            (self.tr("new_shader_asm", "Archivo shader (.s)"), ".s"),
            (self.tr("new_shader_glsl", "Archivo shader (.glsl)"), ".glsl"),
            (self.tr("new_xmod", "Empaquetado XMOD"), ".xmod"),
            (self.tr("new_mlpk", "Empaquetado de mods MLPK"), ".mlpk"),
        ]
        if is_xmod_archive:
            # XXAMI no permite contenedores XMOD/MLPK anidados.
            creations = creations[:3]
            creations.append((self.tr("new_folder", "Carpeta"), "folder"))
        elif tab.archive and tab.archive.suffix.lower() == ".mlpk":
            creations = [(self.tr("new_xmod", "Empaquetado XMOD"), ".xmod")]
        for label, suffix in creations:
            action = new_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, current_tab=tab, ext=suffix:
                    self.create_directory_item(current_tab, ext)
            )
        menu.addSeparator()
        properties = menu.addAction(self.tr("properties", "Propiedades"))
        properties.triggered.connect(lambda: self.show_directory_properties(tab))
        if self.file_clipboard:
            menu.addSeparator()
            paste = menu.addAction(self.tr("paste", "Pegar"))
            paste.triggered.connect(lambda: self.paste_selected(tab))
        menu.exec(global_position)

    def create_directory_item(self, tab, suffix):
        if suffix == "folder":
            raw_name, accepted = QInputDialog.getText(
                self, self.tr("new_folder", "Nueva carpeta"),
                self.tr("new_folder_name", "Nombre de la nueva carpeta:"),
                text=self.tr("new_folder_default", "Nueva carpeta")
            )
        else:
            defaults = {
                ".ini": self.tr("new_control", "Nuevo archivo de control"),
                ".s": self.tr("new_shader", "Nuevo shader"),
                ".glsl": self.tr("new_shader", "Nuevo shader"),
                ".xmod": self.tr("new_package", "Nuevo paquete"),
                ".mlpk": self.tr("new_mod_package", "Nuevo paquete de mods"),
            }
            raw_name, accepted = QInputDialog.getText(
                self, self.tr("create_file", "Crear archivo"), self.tr("new_file_name", "Nombre del nuevo archivo ({suffix}):").format(suffix=suffix),
                text=defaults[suffix]
            )
        if not accepted:
            return
        raw_name = raw_name.strip()
        if not raw_name:
            return
        if tab.archive and tab.archive.suffix.lower() == ".mlpk" and suffix != ".xmod":
            QMessageBox.warning(self, self.tr("new", "Nuevo"), self.tr("mlpk_xmod_only", "Los paquetes MLPK solo admiten archivos XMOD."))
            return
        if suffix == "folder" and not (tab.archive and tab.archive.suffix.lower() == ".xmod"):
            return
        if raw_name in (".", "..") or any(char in raw_name for char in '<>:"/\\|?*'):
            QMessageBox.warning(self, self.tr("invalid_name", "Nombre no válido"), self.tr("enter_valid_filename", "Introduce un nombre de archivo válido."))
            return
        filename = raw_name if suffix == "folder" else (raw_name if raw_name.lower().endswith(suffix) else raw_name + suffix)
        templates = {
            ".ini": "; Archivo de control XXAMI\n\n",
            ".s": "; SPIR-V Assembly\n",
            ".glsl": "#version 450\n\nvoid main() {\n}\n",
        }
        try:
            if tab.archive:
                entry_name = (tab.inside.strip("/") + "/" + filename).strip("/")
                if suffix == "folder":
                    directory_entry = entry_name.rstrip("/") + "/"
                    with zipfile.ZipFile(tab.archive, "r") as current:
                        names = current.namelist()
                    if any(name.rstrip("/") == entry_name or name.startswith(directory_entry) for name in names):
                        QMessageBox.warning(
                            self, self.tr("new_folder", "Nueva carpeta"),
                            self.tr("folder_exists", "Ya existe una carpeta o un elemento con ese nombre.")
                        )
                        return
                    write_archive_entries(tab.archive, additions={directory_entry: b""})
                    tab.refresh()
                    self.sync_path()
                    self.statusBar().showMessage(
                        self.tr("created", "Creado: {name}").format(name=filename), 5000
                    )
                    return
                with zipfile.ZipFile(tab.archive, "r") as current:
                    exists = entry_name in current.namelist()
                if exists:
                    answer = QMessageBox.question(
                        self, self.tr("replace_file", "Reemplazar archivo"),
                        self.tr("already_exists_replace", "Ya existe «{name}». ¿Quieres reemplazarlo?").format(name=filename),
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if answer != QMessageBox.Yes:
                        return
                if suffix in (".xmod", ".mlpk"):
                    import io
                    buffer = io.BytesIO()
                    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED):
                        pass
                    payload = buffer.getvalue()
                else:
                    payload = templates[suffix].encode("utf-8")
                write_archive_entries(tab.archive, replacements={entry_name: payload}, additions={entry_name: payload})
            else:
                target = tab.path / filename
                if target.exists():
                    answer = QMessageBox.question(
                        self, self.tr("replace_file", "Reemplazar archivo"),
                        self.tr("already_exists_replace", "Ya existe «{name}». ¿Quieres reemplazarlo?").format(name=filename),
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if answer != QMessageBox.Yes:
                        return
                if suffix in (".xmod", ".mlpk"):
                    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED):
                        pass
                else:
                    target.write_text(templates[suffix], encoding="utf-8")
            tab.refresh()
            self.sync_path()
            self.statusBar().showMessage(self.tr("created", "Creado: {name}").format(name=filename), 5000)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("create_file", "Crear archivo"), self.tr("create_error", "No se pudo crear «{name}»:\n{error}").format(name=filename, error=exc))

    def show_directory_properties(self, tab):
        if tab.archive:
            prefix = tab.inside.strip("/")
            base = prefix + "/" if prefix else ""
            files = []
            folders = set()
            with zipfile.ZipFile(tab.archive, "r") as package:
                for info in package.infolist():
                    name = info.filename.rstrip("/")
                    if not name.startswith(base) or name == prefix:
                        continue
                    relative = name[len(base):]
                    first, separator, _rest = relative.partition("/")
                    if separator or info.is_dir():
                        folders.add(first)
                    elif first:
                        files.append(first)
            shader_exts = {".spv", ".s", ".glsl", ".vert", ".frag", ".geom", ".tesc", ".tese", ".comp", ".hlsl"}
            texture_exts = {".ktx2", ".ktx", ".png", ".jpg", ".jpeg", ".dds", ".tga", ".bmp", ".webp"}
            shader_formats = {}
            texture_formats = {}
            for name in files:
                ext = Path(name).suffix.lower()
                if ext in shader_exts: shader_formats[ext] = shader_formats.get(ext, 0) + 1
                if ext in texture_exts: texture_formats[ext] = texture_formats.get(ext, 0) + 1
            def formats_text(values):
                return "\n".join(f"  {ext}: {count}" for ext, count in sorted(values.items())) if values else "  " + self.tr("none", "Ninguno")
            report = (
                f"{self.tr('container', 'Contenedor')}: {tab.archive}!/{prefix}\n\n"
                f"{self.tr('files', 'Archivos')}: {len(files)}\n"
                f"{self.tr('folders', 'Carpetas')}: {len(folders)}\n\n"
                f"{self.tr('shaders_by_format', 'Shaders por formato:')}\n{formats_text(shader_formats)}\n\n"
                f"{self.tr('textures_by_format', 'Texturas por formato:')}\n{formats_text(texture_formats)}"
            )
            dialog = QDialog(self)
            dialog.setWindowTitle(self.tr("directory_props_title", "Propiedades del directorio"))
            dialog.setMinimumSize(570, 420)
            layout = QVBoxLayout(dialog)
            details = QPlainTextEdit(); details.setReadOnly(True); details.setPlainText(report)
            details.setStyleSheet("QPlainTextEdit { background:#202226; color:#e8eaed; border:1px solid #41454b; padding:8px; font-family:Consolas; }")
            layout.addWidget(details)
            close_button = QPushButton(self.tr("close", "Cerrar"))
            close_button.clicked.connect(dialog.accept)
            layout.addWidget(close_button, 0, Qt.AlignRight)
            dialog.exec()
            return
        root = tab.path
        file_count = 0
        folder_count = 0
        shader_formats = {}
        texture_formats = {}
        buffer_count = 0
        trace_count = 0
        model_count = 0
        xmod_count = 0
        mlpk_count = 0
        shader_exts = {".spv", ".s", ".glsl", ".vert", ".frag", ".geom",
                       ".tesc", ".tese", ".comp", ".hlsl"}
        texture_exts = {".ktx2", ".ktx", ".png", ".jpg", ".jpeg", ".dds",
                        ".tga", ".bmp", ".webp"}
        for current, dirs, files in os.walk(root):
            # No seguir enlaces simbólicos para evitar ciclos fuera del directorio.
            dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
            if Path(current) != root:
                folder_count += 1
            for directory in dirs:
                if re.fullmatch(r"Model_\d+", directory, re.I):
                    model_count += 1
            for filename in files:
                file_count += 1
                ext = Path(filename).suffix.lower()
                if ext in shader_exts:
                    shader_formats[ext] = shader_formats.get(ext, 0) + 1
                if ext in texture_exts:
                    texture_formats[ext] = texture_formats.get(ext, 0) + 1
                if ext == ".buf":
                    buffer_count += 1
                if filename.lower() == "frame_trace.json":
                    trace_count += 1
                if ext == ".xmod":
                    xmod_count += 1
                elif ext == ".mlpk":
                    mlpk_count += 1

        def format_formats(counts):
            return "\n".join(
                f"  {extension}: {count}" for extension, count in sorted(counts.items())
            ) if counts else "  " + self.tr("none", "Ninguno")
        report = (
            f"{self.tr('directory', 'Directorio')}: {root}\n\n"
            f"{self.tr('files', 'Archivos')}: {file_count}\n"
            f"{self.tr('folders', 'Carpetas')}: {folder_count}\n\n"
            f"{self.tr('shaders_by_format', 'Shaders por formato:')}\n{format_formats(shader_formats)}\n\n"
            f"{self.tr('textures_by_format', 'Texturas por formato:')}\n{format_formats(texture_formats)}\n\n"
            f"{self.tr('buffers', 'Buffers (.buf): {count}').format(count=buffer_count)}\n"
            f"{self.tr('frame_trace', 'Frame trace (frame_trace.json): {count}').format(count=trace_count)}\n"
            f"{self.tr('packed_models', 'Modelos empaquetados (carpetas Model_N): {count}').format(count=model_count)}\n"
            f"{self.tr('xmod_packages', 'Paquetes XMOD (.xmod): {count}').format(count=xmod_count)}\n"
            f"{self.tr('mlpk_packages', 'Paquetes MLPK (.mlpk): {count}').format(count=mlpk_count)}"
        )
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("directory_props_title", "Propiedades del directorio"))
        dialog.setMinimumSize(570, 560)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(report)
        details.setStyleSheet(
            "QPlainTextEdit { background:#202226; color:#e8eaed; "
            "border:1px solid #41454b; padding:8px; font-family:Consolas; }"
        )
        layout.addWidget(details)
        close_button = QPushButton(self.tr("close", "Cerrar"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    def open_model_viewer(self,path):
        """Abre el visor independiente usando como entorno la carpeta del recurso."""
        path=Path(path).resolve()
        base=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
        script=base/"model_viewer_qt.py"
        candidates=(base/"AMI 3D Viewer.exe",base/"model_viewer_qt.exe")
        try:
            executable=next((p for p in candidates if p.is_file()),None)
            if executable:
                cmd=[str(executable),"--root",str(path.parent),"--log-path",str(self.log_path),str(path)]
            elif not getattr(sys,"frozen",False) and script.is_file():
                cmd=[sys.executable,str(script),"--root",str(path.parent),"--log-path",str(self.log_path),str(path)]
            else:
                raise FileNotFoundError("No se encontró el visor independiente. Coloca model_viewer_qt.py junto al explorador Python o compila y coloca XXAMI Model Viewer.exe junto al explorador.")
            flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
            if sys.platform.startswith("win"):
                flags |= getattr(subprocess,"CREATE_NO_WINDOW",0)
            subprocess.Popen(cmd,cwd=str(base),creationflags=flags)
        except Exception as exc:
            QMessageBox.critical(self,self.tr("model_viewer", "Visor de modelos"),self.tr("viewer_start_error", "No se pudo iniciar el visor independiente:\n{error}").format(error=exc))

    def current(self):return self.tabs.currentWidget()
    def show_child(self,w):self.children.append(w); w.show()
    def texture_source_path(self,tab,name,data=None):
        if not tab.archive:return str(tab.path/name)
        if data is None:data=tab.get_bytes(name)
        source=Path(tempfile.gettempdir())/("xxami_texture_"+str(abs(hash((str(tab.archive),tab.inside,name))))+".ktx2")
        if not source.exists() or source.stat().st_size!=len(data):source.write_bytes(data)
        return str(source)
    def decode_texture(self,source,rapido=False):
        texture_decoder = load_texture_decoder()
        st=Path(source).stat()
        output=Path(tempfile.gettempdir())/("xxami_decoded_"+str(abs(hash((str(Path(source).resolve()),st.st_size,st.st_mtime_ns,rapido))))+".png")
        if not output.exists():
            class Context: unswizzle_activo=False
            ctx=Context(); ctx._diagnostico_textura={}
            if not texture_decoder.textura_a_png(ctx,str(source),str(output),rapido=rapido):
                raise RuntimeError(ctx._diagnostico_textura.get(str(source)) or "No se pudo decodificar KTX2.")
        return output
    def queue_texture_thumbnail(self,tab,index,name,generation):
        try:
            data=tab.get_bytes(name); source=self.texture_source_path(tab,name,data); st=Path(source).stat()
            output=Path(tempfile.gettempdir())/("xxami_thumb_"+str(abs(hash((source,st.st_size,st.st_mtime_ns))))+".png")
            if output.exists():
                self._apply_texture_thumbnail(id(tab),generation,index,str(output),""); return
            worker=TextureThumbWorker(id(tab),generation,index,source,str(output))
            worker.signals.finished.connect(self._texture_thumbnail_ready)
            self._texture_workers.append(worker); self._thread_pool.start(worker)
        except Exception as exc:self.statusBar().showMessage(self.tr("ktx_thumbnail_error", "Miniatura KTX2: {error}").format(error=exc),5000)
    def _texture_thumbnail_ready(self,tab_id,generation,index,output,error):
        sender=self.sender()
        self._texture_workers=[worker for worker in self._texture_workers if worker.signals is not sender]
        self._apply_texture_thumbnail(tab_id,generation,index,output,error)
    def _apply_texture_thumbnail(self,tab_id,generation,index,output,error):
        tab=next((self.tabs.widget(i) for i in range(self.tabs.count()) if id(self.tabs.widget(i))==tab_id),None)
        if not tab or tab._thumbnail_generation!=generation or index>=tab.grid.count():return
        if error:
            tab.grid.item(index).setToolTip(self.tr("ktx_error", "KTX2: {error}").format(error=error)); return
        pix=QPixmap(output)
        if not pix.isNull():tab.grid.item(index).setIcon(QIcon(pix.scaled(88,88,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
    def _snapshot(self,t):
        return (str(t.path),t.inside) if t.archive else (str(t.path),"")
    def _restore(self,t,state):
        path,inside=state
        if t.archive:t.inside=inside
        else:t.path=Path(path)
        t.refresh(); self.sync_path()
    def navigate_tab(self,t,target):
        t.history.append(self._snapshot(t)); t.future.clear()
        if t.archive:t.inside=target.strip("/")
        else:t.path=Path(target)
        t.refresh(); self.sync_path()
    def _update_nav(self):
        t=self.current()
        if not t:return
        self.btn_back.setEnabled(bool(t.history)); self.btn_forward.setEnabled(bool(t.future))
        self.btn_up.setEnabled(bool(t.inside) if t.archive else t.path.parent!=t.path)
    def open_folder(self,path):
        p=Path(path).expanduser()
        if not p.is_dir():QMessageBox.warning(self,self.tr("folder_error", "Carpeta"),self.tr("no_folder", "No existe la carpeta:\n{path}").format(path=p));return
        tab=ExplorerTab(p); self.tabs.addTab(tab,p.name or str(p)); self.tabs.setCurrentWidget(tab); self.sync_path()
    def add_archive(self,path):
        tab=ExplorerTab(path,archive=path)
        tab.banner.setText(self.tr("package_banner", "PAQUETE DE MOD · ZIP SIN COMPRESIÓN"))
        self.tabs.addTab(tab,"📦 "+Path(path).name); self.tabs.setCurrentWidget(tab); self.sync_path()
    def close_tab(self,i):
        if self.tabs.count()>1:self.tabs.removeTab(i)
    def sync_path(self):
        t=self.current()
        if t:self.path.setText(str(t.archive)+"!/"+t.inside if t.archive and t.inside else str(t.archive or t.path))
        self._update_nav()
    def choose_folder(self):
        current=self.current()
        if current:
            base=current.archive.parent if current.archive else current.path
            start=base.parent if base.parent!=base else base
        else:start=Path.home()
        p=QFileDialog.getExistingDirectory(self,self.tr("open_folder_new_tab", "Abrir carpeta en nueva pestaña"),str(start))
        if p:self.open_folder(p)
    def go_path(self):
        raw=self.path.text().strip().strip('"')
        if "!/" in raw:
            archive,inside=raw.split("!/",1); a=Path(archive).expanduser()
            if not a.is_file():QMessageBox.warning(self,self.tr("path_error", "Ruta"),self.tr("no_container", "No existe el contenedor:\n{path}").format(path=a));return
            if self.current() and self.current().archive==a:
                t=self.current(); t.history.append(self._snapshot(t)); t.future.clear(); t.inside=inside.strip("/"); t.refresh(); self.sync_path(); return
            self.add_archive(a); t=self.current(); t.inside=inside.strip("/"); t.refresh(); self.sync_path(); return
        self.navigate_folder(raw)
    def navigate_folder(self,path):
        p=Path(path).expanduser()
        if not p.is_dir():
            QMessageBox.warning(self,self.tr("folder_error", "Carpeta"),self.tr("no_folder", "No existe la carpeta:\n{path}").format(path=p)); return
        t=self.current()
        if t and not t.archive:
            self.navigate_tab(t,str(p))
        else:
            self.open_folder(p)
    def refresh(self):
        if self.current():self.current().refresh()
    def filter_items(self,text):
        t=self.current()
        if not t:return
        needle=text.strip().casefold()
        for i in range(t.grid.count()):
            item=t.grid.item(i); item.setHidden(bool(needle and needle not in item.text().casefold()))
        visibles=sum(not t.grid.item(i).isHidden() for i in range(t.grid.count()))
        self.statusBar().showMessage(self.tr("items_count", "{count} elemento(s)").format(count=visibles if needle else t.grid.count()),3000)
    def back(self):
        t=self.current()
        if not t or not t.history:return
        t.future.append(self._snapshot(t)); self._restore(t,t.history.pop())
    def forward(self):
        t=self.current()
        if not t or not t.future:return
        t.history.append(self._snapshot(t)); self._restore(t,t.future.pop())
    def up(self):
        t=self.current()
        if not t:return
        if t.archive:
            if t.inside:self.navigate_tab(t,t.inside.rsplit("/",1)[0] if "/" in t.inside else "")
        elif t.path.parent!=t.path:self.navigate_tab(t,str(t.path.parent))

    def restore_session(self):
        raw=self.settings.value("session/tabs", "")
        try: entries=json.loads(raw) if raw else []
        except (TypeError,ValueError): entries=[]
        if not isinstance(entries,list): entries=[]
        restored_count=0
        for entry in entries:
            try:
                archive=Path(entry.get("archive", "")).expanduser() if entry.get("archive") else None
                path=Path(entry.get("path", "")).expanduser()
                if archive:
                    if not archive.is_file(): continue
                    self.add_archive(archive)
                    tab=self.current(); tab.inside=str(entry.get("inside", "")).strip("/")
                    tab.refresh()
                else:
                    if not path.is_dir(): continue
                    self.open_folder(path)
                restored_count+=1
            except Exception:
                continue
        if restored_count:
            index=int(self.settings.value("session/current_index", restored_count-1))
            self.tabs.setCurrentIndex(max(0,min(index,self.tabs.count()-1)))
            self.sync_path()
            return True
        return False
    def save_session(self):
        entries=[]
        for i in range(self.tabs.count()):
            tab=self.tabs.widget(i)
            if not isinstance(tab,ExplorerTab): continue
            entries.append({"path":str(tab.path),"archive":str(tab.archive) if tab.archive else "","inside":tab.inside})
        self.settings.setValue("session/tabs",json.dumps(entries,ensure_ascii=False))
        self.settings.setValue("session/current_index",self.tabs.currentIndex())
        self.settings.setValue("window/geometry",self.saveGeometry())
        self.settings.setValue("window/state",self.saveState())
        self.settings.sync()
    def closeEvent(self,event):
        self.save_session()
        super().closeEvent(event)

STYLE=f"""
QMainWindow,QWidget {{ background:{BG}; color:{TEXT}; font-family:'Segoe UI'; font-size:10pt; }}
QPushButton {{ background:#34373d; color:{TEXT}; border:1px solid #454950; border-radius:5px; padding:7px 12px; }}
QPushButton:hover {{ background:#41464e; border-color:{GREEN}; }}
QLineEdit {{ background:{PANEL2}; color:{TEXT}; border:1px solid #41454b; border-radius:5px; padding:9px; }}
QTabWidget::pane {{ border:1px solid #41454b; background:{PANEL}; }}
QTabBar::tab {{ background:#303238; color:#cbd0d7; padding:10px 16px; margin-right:3px; }}
QTabBar::tab:selected {{ background:#3d4148; border-bottom:2px solid {GREEN}; color:white; }}
QListWidget {{ background:{PANEL2}; border:1px solid #393d43; border-radius:6px; outline:0; padding:8px; }}
QListWidget::item {{ color:{TEXT}; border:1px solid transparent; border-radius:6px; padding:8px; text-align:center; }}
QListWidget::item:selected {{ background:{SELECT}; border:2px solid {GREEN}; color:white; }}
QStatusBar {{ background:{PANEL}; color:{MUTED}; }}
QToolBar {{ background:{PANEL}; border:0; spacing:6px; }}
"""

def main():
    parser=argparse.ArgumentParser(description="XXAMI Explorer independiente")
    parser.add_argument("path",nargs="?",help="Carpeta inicial")
    parser.add_argument("--log-path",help="Ruta opcional al registro de diagnóstico compartido")
    args=parser.parse_args()
    log_path=configure_crash_logging(args.log_path,"Explorer")
    app=QApplication(sys.argv); app.setStyle("Fusion")
    app.setWindowIcon(application_icon("explorer_icon"))
    win=ExplorerWindow(args.path,log_path); win.show(); sys.exit(app.exec())

if __name__=="__main__":main()
