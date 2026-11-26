# -*- coding: utf-8 -*-
"""Registro compartido de errores para los procesos independientes de XXAMI."""
from __future__ import annotations

import atexit
import faulthandler
import sys
import tempfile
import threading
import time
import traceback
import warnings
from pathlib import Path

_stream = None
_log_path = None
_lock = threading.Lock()
_component = "XXAMI"


def get_log_path():
    return _log_path


def log_message(message):
    """Añade una entrada al registro compartido, sin propagar errores de logging."""
    try:
        if _stream is not None:
            stamp = time.strftime("%H:%M:%S")
            text = str(message)
            with _lock:
                _stream.write(f"[{stamp}] [{_component}] {text}")
                if not text.endswith("\n"):
                    _stream.write("\n")
                _stream.flush()
    except Exception:
        pass


def _exception_hook(exc_type, exc_value, exc_tb):
    if exc_type is KeyboardInterrupt:
        return
    log_message("EXCEPCIÓN NO CONTROLADA:\n" + "".join(
        traceback.format_exception(exc_type, exc_value, exc_tb)
    ))
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass


def _thread_exception_hook(args):
    _exception_hook(args.exc_type, args.exc_value, args.exc_traceback)


def _unraisable_hook(args):
    log_message(
        f"ERROR NO CAPTURABLE ({args.err_msg or ''}):\n" +
        "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    )


def _warning_hook(message, category, filename, lineno, file=None, line=None):
    log_message(f"AVISO ({category.__name__}) en {filename}:{lineno}: {message}")


def configure_crash_logging(log_path=None, component="XXAMI"):
    """Conecta este proceso al mismo archivo de log que DumpAna."""
    global _stream, _log_path, _component
    if _stream is not None:
        return _log_path

    _component = str(component)
    candidates = []
    if log_path:
        candidates.append(Path(log_path).expanduser())
    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    candidates.extend((app_dir / "xxami_crash_log.txt", Path(tempfile.gettempdir()) / "xxami_crash_log.txt"))

    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            _stream = open(candidate, "a", buffering=1, encoding="utf-8")
            _log_path = candidate.resolve()
            break
        except OSError:
            continue

    if _stream is None:
        return None

    log_message(f"===== Proceso iniciado | registro compartido: {_log_path} =====")
    try:
        faulthandler.enable(file=_stream, all_threads=True)
    except Exception as exc:
        log_message(f"No se pudo activar faulthandler: {exc}")

    sys.excepthook = _exception_hook
    threading.excepthook = _thread_exception_hook
    try:
        sys.unraisablehook = _unraisable_hook
    except Exception:
        pass
    warnings.showwarning = _warning_hook
    warnings.simplefilter("always")

    def _shutdown():
        try:
            log_message("===== Proceso finalizado normalmente =====")
            try:
                faulthandler.disable()
            except Exception:
                pass
            with _lock:
                _stream.flush()
                _stream.close()
        except Exception:
            pass

    atexit.register(_shutdown)
    return _log_path
