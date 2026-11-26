# -*- coding: utf-8 -*-
"""Contrato común y registro de backends gráficos del visor XXAMI.

Los backends comparten ciclo de vida y entrada de geometría/cámara. Solo se
registran APIs realmente implementadas; no se anuncian backends ficticios.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import importlib.util
import json
import os
import subprocess
import sys
from functools import lru_cache


class RenderBackend(ABC):
    backend_id = ""
    label = ""

    def __init__(self):
        self.info = {"id": self.backend_id, "label": self.label}

    @abstractmethod
    def initialize(self):
        """Inicializa el dispositivo y los recursos gráficos."""

    @abstractmethod
    def render_image(self, positions, uvs, triangles, texture, width, height,
                     rot_x=0.5, rot_y=0.6, zoom=1.0, pan_x=0.0, pan_y=0.0):
        """Renderiza una malla y devuelve una imagen PIL."""

    @abstractmethod
    def close(self):
        """Libera recursos en el hilo propietario."""


class OpenGLBackend(RenderBackend):
    backend_id = "opengl"
    label = "OpenGL 3.3 Core"

    def __init__(self):
        super().__init__()
        self.context = None
        self.renderer = None

    def initialize(self):
        from xxami_gl import SDL3GLContext, GLMeshRenderer

        context = SDL3GLContext()
        status = context.create(title="XXAMI Model Viewer GPU", width=1200,
                                height=900, hidden=True)
        if not status.available:
            raise RuntimeError(status.message)
        try:
            renderer = GLMeshRenderer(context)
        except Exception:
            context.close()
            raise
        self.context, self.renderer = context, renderer
        self.info.update(vendor=status.vendor, renderer=status.renderer,
                         version=status.version)
        return self.info

    def render_image(self, positions, uvs, triangles, texture, width, height,
                     rot_x=0.5, rot_y=0.6, zoom=1.0, pan_x=0.0, pan_y=0.0):
        if self.renderer is None:
            raise RuntimeError("El backend OpenGL no está inicializado")
        return self.renderer.render_image(
            positions, uvs, triangles, texture, width, height,
            rot_x, rot_y, zoom, pan_x, pan_y
        )

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        if self.context is not None:
            self.context.close()
            self.context = None


# Los backends D3D se cargan en Windows y se anuncian solo si la sonda
# confirma que el adaptador gráfico seleccionado puede crear el dispositivo.
D3D11Backend = None
D3D9Backend = None
if sys.platform == "win32":
    try:
        from xxami_d3d11_backend import D3D11Backend
    except Exception:
        D3D11Backend = None
    try:
        from xxami_d3d9_backend import D3D9Backend
    except Exception:
        D3D9Backend = None


WgpuBackend = None
try:
    if importlib.util.find_spec("wgpu") is not None:
        from xxami_wgpu_backend import WgpuBackend

        class VulkanBackend(WgpuBackend):
            backend_id = "vulkan"
            label = "Vulkan (wgpu)"

            def __init__(self):
                super().__init__(self.backend_id)

        class Direct3D12Backend(WgpuBackend):
            backend_id = "dx12"
            label = "Direct3D 12 (wgpu)"

            def __init__(self):
                super().__init__(self.backend_id)

        class WgpuOpenGLBackend(WgpuBackend):
            backend_id = "wgpu-opengl"
            label = "OpenGL (wgpu)"

            def __init__(self):
                super().__init__(self.backend_id)
    else:
        VulkanBackend = Direct3D12Backend = WgpuOpenGLBackend = None
except Exception:
    VulkanBackend = Direct3D12Backend = WgpuOpenGLBackend = None


_BACKENDS = {OpenGLBackend.backend_id: OpenGLBackend}
# Registro interno para que create_backend y las pruebas usen el mismo contrato.
# available_backends no lo anuncia hasta validar escenas reales en el visor.
if D3D11Backend is not None:
    _BACKENDS[D3D11Backend.backend_id] = D3D11Backend
if D3D9Backend is not None:
    _BACKENDS[D3D9Backend.backend_id] = D3D9Backend
for _backend in (VulkanBackend, Direct3D12Backend, WgpuOpenGLBackend):
    if _backend is None:
        continue
    if sys.platform == "darwin":
        continue  # wgpu-native usa Metal en macOS; no anunciar HALs no compatibles.
    if _backend.backend_id == "dx12" and sys.platform != "win32":
        continue
    _BACKENDS[_backend.backend_id] = _backend


def probe_wgpu_adapters_in_process(backend_id):
    """Enumera y prueba adaptadores de un HAL; se ejecuta en un proceso aislado."""
    settings = {
        "vulkan": ("Vulkan", "Vulkan", {"vulkan"}),
        "dx12": ("D3D12", "DX12", {"dx12", "d3d12"}),
        "wgpu-opengl": ("OpenGL", "GL", {"gl", "opengl"}),
    }
    env_backend, hal_name, aliases = settings[backend_id]
    os.environ["WGPU_BACKEND_TYPE"] = env_backend
    import wgpu
    from wgpu.backends.wgpu_native.extras import set_instance_extras
    set_instance_extras(backends=[hal_name])
    result = []
    for adapter in wgpu.gpu.enumerate_adapters_sync():
        info = dict(adapter.info)
        try:
            adapter.request_device_sync()
        except Exception:
            continue
        backend_type = str(info.get("backend_type", "")).casefold()
        if backend_type and backend_type not in aliases:
            continue
        if info.get("is_fallback_adapter", False):
            continue
        result.append({
            "device": str(info.get("device", "")),
            "description": str(info.get("description", "")),
            "summary": str(adapter.summary),
            "vendor": str(info.get("vendor", "")),
            "vendor_id": str(info.get("vendor_id", "")),
            "device_id": str(info.get("device_id", "")),
            "backend_type": backend_type,
        })
    return result


@lru_cache(maxsize=16)
def _probe_wgpu_adapters(backend_id):
    """Prueba cada HAL en un proceso aislado para evitar la instancia global de wgpu."""
    settings = {
        "vulkan": ("Vulkan", "Vulkan"),
        "dx12": ("D3D12", "DX12"),
        "wgpu-opengl": ("OpenGL", "GL"),
    }
    env_backend, hal_name = settings[backend_id]
    script = r"""
import json, sys
backend = sys.argv[1]
hal = sys.argv[2]
try:
    import wgpu
    from wgpu.backends.wgpu_native.extras import set_instance_extras
    set_instance_extras(backends=[hal])
    result = []
    for adapter in wgpu.gpu.enumerate_adapters_sync():
        info = dict(adapter.info)
        try:
            device = adapter.request_device_sync()
        except Exception:
            continue
        backend_type = str(info.get("backend_type", "")).casefold()
        aliases = {"vulkan": ("vulkan",), "dx12": ("dx12", "d3d12"),
                   "gl": ("gl", "opengl")}[hal.casefold()]
        if backend_type and backend_type not in aliases:
            continue
        if info.get("is_fallback_adapter", False):
            continue
        result.append({
            "device": str(info.get("device", "")),
            "description": str(info.get("description", "")),
            "summary": str(adapter.summary),
            "vendor": str(info.get("vendor", "")),
            "vendor_id": str(info.get("vendor_id", "")),
            "device_id": str(info.get("device_id", "")),
            "backend_type": backend_type,
        })
    print("XXAMI_WGPU_PROBE=" + json.dumps(result))
except Exception as exc:
    print("XXAMI_WGPU_PROBE=" + json.dumps({"error": str(exc)}))
"""
    env = os.environ.copy()
    env["WGPU_BACKEND_TYPE"] = env_backend
    try:
        command = ([sys.executable, "--xxami-wgpu-probe", backend_id]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, "-c", script, backend_id, hal_name])
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=25,
            check=False, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        for line in reversed((proc.stdout or "").splitlines()):
            if line.startswith("XXAMI_WGPU_PROBE="):
                data = json.loads(line.split("=", 1)[1])
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _matches_gpu(adapter, gpu_preference):
    """Relaciona nombres de Windows/Linux con la identidad publicada por WGPU."""
    import re
    preferred = str(gpu_preference or "default").strip().casefold()
    if preferred in ("", "default"):
        return True

    def normalize(value):
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

    wanted = normalize(preferred)
    fields = (
        adapter.get("device", ""),
        adapter.get("description", ""),
        adapter.get("summary", ""),
    )
    normalized_fields = [normalize(value) for value in fields if normalize(value)]
    if any(wanted in value or value in wanted for value in normalized_fields):
        return True

    # Win32_VideoController y wgpu pueden describir el mismo adaptador con
    # nombres comerciales distintos. Usa el identificador PCI del fabricante
    # como segunda evidencia, sin confundir dos GPUs del mismo fabricante.
    vendor_ids = {
        "intel": {"0x8086", "8086", "32902"},
        "nvidia": {"0x10de", "10de", "4318"},
        "amd": {"0x1002", "1002", "4098"},
        "ati": {"0x1002", "1002", "4098"},
    }
    selected_vendor = next((name for name in vendor_ids if name in wanted), None)
    if selected_vendor:
        reported = normalize(adapter.get("vendor_id", ""))
        vendor_name = normalize(adapter.get("vendor", ""))
        if reported in {normalize(v) for v in vendor_ids[selected_vendor]}:
            return True
        if selected_vendor in vendor_name:
            return True

    # Comparación por tokens para variaciones como "AMD Radeon(TM) RX..."
    # frente a "Radeon RX..."; se exige una coincidencia fuerte para no
    # habilitar una API en otra GPU por compartir solo "Graphics".
    stop = {"graphics", "gpu", "adapter", "microsoft", "corporation",
            "inc", "ltd", "the", "tm", "r"}
    wanted_tokens = {t for t in re.findall(r"[a-z0-9]+", preferred)
                     if len(t) > 1 and t not in stop}
    if not wanted_tokens:
        return False
    for value in fields:
        tokens = {t for t in re.findall(r"[a-z0-9]+", str(value).casefold())
                  if len(t) > 1 and t not in stop}
        if tokens:
            overlap = len(wanted_tokens & tokens) / len(wanted_tokens | tokens)
            if overlap >= 0.72 or (len(wanted_tokens & tokens) >= 3
                                   and len(wanted_tokens & tokens) / len(wanted_tokens) >= 0.8):
                return True
    return False


@lru_cache(maxsize=1)
def _probe_d3d11_adapters():
    """Comprueba la creación real de un dispositivo D3D11 por adaptador."""
    if sys.platform != "win32" or D3D11Backend is None:
        return []
    try:
        from xxami_d3d11_probe import probe_d3d11_adapters
        return probe_d3d11_adapters()
    except Exception:
        return []



@lru_cache(maxsize=1)
def _probe_d3d9_adapters():
    """Comprueba qué adaptadores pueden crear un dispositivo HAL D3D9."""
    if sys.platform != "win32" or D3D9Backend is None:
        return []
    try:
        from xxami_d3d9_probe import probe_d3d9_adapters
        return probe_d3d9_adapters()
    except Exception:
        return []


def available_backends(gpu_preference="default"):
    """Devuelve APIs inicializables en la GPU seleccionada.

    D3D11 y D3D9 se anuncian únicamente si sus sondas pueden crear un
    dispositivo en el adaptador elegido. Cada HAL wgpu se consulta en un subproceso independiente
    porque wgpu-native fija sus backends al crear su instancia global.
    """
    result = [{"id": OpenGLBackend.backend_id, "label": OpenGLBackend.label}]
    if D3D11Backend is not None:
        try:
            from xxami_d3d11_backend import _matches_gpu as _matches_d3d11_gpu
            supported = any(
                adapter.get("d3d11_supported") and
                not (adapter.get("vendor_id") == "0x1414" and
                     adapter.get("device_id") == "0x008C") and
                _matches_d3d11_gpu(adapter.get("name", ""), gpu_preference)
                for adapter in _probe_d3d11_adapters()
            )
            if supported:
                result.append({"id": D3D11Backend.backend_id,
                               "label": D3D11Backend.label})
        except Exception:
            pass
    if D3D9Backend is not None:
        try:
            supported = any(
                adapter.get("d3d9_supported") and
                _matches_gpu({
                    "device": adapter.get("name", ""),
                    "description": adapter.get("name", ""),
                    "summary": adapter.get("name", ""),
                    "vendor_id": adapter.get("vendor_id", ""),
                }, gpu_preference)
                for adapter in _probe_d3d9_adapters()
            )
            if supported:
                result.append({"id": D3D9Backend.backend_id,
                               "label": D3D9Backend.label})
        except Exception:
            pass
    if WgpuBackend is None:
        return result
    for backend_id in ("vulkan", "dx12", "wgpu-opengl"):
        if backend_id not in _BACKENDS:
            continue
        adapters = _probe_wgpu_adapters(backend_id)
        if any(_matches_gpu(adapter, gpu_preference) for adapter in adapters):
            backend_type = _BACKENDS[backend_id]
            result.append({"id": backend_type.backend_id, "label": backend_type.label})
    return result


def create_backend(backend_id, gpu_preference="default"):
    """Construye un backend registrado, sin simular APIs pendientes."""
    backend_type = _BACKENDS.get(str(backend_id or "opengl").lower())
    if backend_type is None:
        raise ValueError(f"Backend gráfico no disponible: {backend_id}")
    backend = backend_type()
    if WgpuBackend is not None and isinstance(backend, WgpuBackend):
        backend.gpu_preference = str(gpu_preference or "default")
    if D3D11Backend is not None and isinstance(backend, D3D11Backend):
        backend.gpu_preference = str(gpu_preference or "default")
    if D3D9Backend is not None and isinstance(backend, D3D9Backend):
        backend.gpu_preference = str(gpu_preference or "default")
    return backend
