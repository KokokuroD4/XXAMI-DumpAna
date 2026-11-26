# -*- coding: utf-8 -*-
"""Backend nativo Direct3D 9 para XXAMI (renderizado offscreen)."""
from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes


_D3D_SDK_VERSION = 32
_D3DDEVTYPE_HAL = 1
_D3DSWAPEFFECT_DISCARD = 1
_D3DFMT_UNKNOWN = 0
_D3DFMT_A8R8G8B8 = 21
_D3DFMT_D24S8 = 75
_D3DPOOL_DEFAULT = 0
_D3DPOOL_MANAGED = 1
_D3DPOOL_SYSTEMMEM = 2
_D3DUSAGE_RENDERTARGET = 1
_D3DCREATE_HARDWARE_VERTEXPROCESSING = 0x40
_D3DCREATE_SOFTWARE_VERTEXPROCESSING = 0x20
_D3DPRESENT_INTERVAL_IMMEDIATE = 0x80000000
_D3DCLEAR_TARGET = 1
_D3DCLEAR_ZBUFFER = 2
_D3DPT_TRIANGLELIST = 4
_D3DFMT_INDEX32 = 102
_D3DFVF_XYZRHW = 0x004
_D3DFVF_TEX1 = 0x100
_D3DRS_ZENABLE = 7
_D3DRS_ZWRITEENABLE = 14
_D3DRS_ZFUNC = 23
_D3DRS_LIGHTING = 137
_D3DRS_CULLMODE = 22
_D3DCULL_NONE = 1
_D3DCMP_LESSEQUAL = 4
_D3DTSS_COLOROP = 1
_D3DTSS_COLORARG1 = 2
_D3DTSS_ALPHAOP = 4
_D3DTSS_ALPHAARG1 = 5
_D3DTOP_SELECTARG1 = 2
_D3DTA_TEXTURE = 2
_D3DSAMP_MINFILTER = 6
_D3DSAMP_MAGFILTER = 5
_D3DSAMP_ADDRESSU = 1
_D3DSAMP_ADDRESSV = 2
_D3DTEXF_LINEAR = 2
_D3DTADDRESS_CLAMP = 3
_D3DLOCK_READONLY = 0x10


class _PresentParameters(ctypes.Structure):
    _fields_ = [
        ("BackBufferWidth", wintypes.UINT), ("BackBufferHeight", wintypes.UINT),
        ("BackBufferFormat", wintypes.UINT), ("BackBufferCount", wintypes.UINT),
        ("MultiSampleType", wintypes.UINT), ("MultiSampleQuality", wintypes.DWORD),
        ("SwapEffect", wintypes.UINT), ("hDeviceWindow", wintypes.HWND),
        ("Windowed", wintypes.BOOL), ("EnableAutoDepthStencil", wintypes.BOOL),
        ("AutoDepthStencilFormat", wintypes.UINT), ("Flags", wintypes.DWORD),
        ("FullScreen_RefreshRateInHz", wintypes.UINT),
        ("PresentationInterval", wintypes.UINT),
    ]


class _Viewport(ctypes.Structure):
    _fields_ = [("X", wintypes.DWORD), ("Y", wintypes.DWORD),
                ("Width", wintypes.DWORD), ("Height", wintypes.DWORD),
                ("MinZ", ctypes.c_float), ("MaxZ", ctypes.c_float)]


class _LockedRect(ctypes.Structure):
    _fields_ = [("Pitch", ctypes.c_int), ("pBits", ctypes.c_void_p)]


class _Vertex(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float),
                ("z", ctypes.c_float), ("rhw", ctypes.c_float),
                ("u", ctypes.c_float), ("v", ctypes.c_float)]


def _method(obj, index, restype, *argtypes):
    if not obj:
        raise RuntimeError("Puntero COM nulo (vtable %d)" % index)
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def _release(obj):
    if obj:
        try:
            _method(obj, 2, wintypes.ULONG)(obj)
        except Exception:
            pass


def _check(hr, operation):
    if hr < 0:
        raise RuntimeError("%s falló: HRESULT 0x%08X" % (operation, hr & 0xFFFFFFFF))


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _matches_gpu(name, preference):
    preferred = str(preference or "default").strip()
    if preferred.casefold() in ("", "default"):
        return True
    wanted, candidate = _normalize(preferred), _normalize(name)
    if wanted in candidate or candidate in wanted:
        return True
    a = set(re.findall(r"[a-z0-9]+", preferred.casefold()))
    b = set(re.findall(r"[a-z0-9]+", str(name).casefold()))
    stop = {"graphics", "gpu", "adapter", "microsoft", "corporation", "inc", "ltd", "the"}
    a -= stop
    b -= stop
    return bool(a and len(a & b) / len(a | b) >= 0.72)


class D3D9Backend:
    backend_id = "d3d9"
    label = "Direct3D 9"

    def __init__(self):
        self.info = {"id": self.backend_id, "label": self.label}
        self.gpu_preference = "default"
        self.d3d_lib = None
        self.d3d = ctypes.c_void_p()
        self.device = ctypes.c_void_p()
        self.target_texture = ctypes.c_void_p()
        self.target_surface = ctypes.c_void_p()
        self.depth_surface = ctypes.c_void_p()
        self.readback_surface = ctypes.c_void_p()
        self.texture = ctypes.c_void_p()
        self.texture_key = None
        self.mesh_key = None
        self.size = None
        self.index_count = 0
        self.vertex_data = None
        self.index_data = None

    def initialize(self):
        if sys.platform != "win32":
            raise RuntimeError("Direct3D 9 requiere Windows")
        try:
            from xxami_d3d9_probe import probe_d3d9_adapters
            probe_results = probe_d3d9_adapters()
            adapters = [a for a in probe_results if a.get("d3d9_supported")]
            preferred = str(self.gpu_preference or "default")
            selected = next((a for a in adapters if _matches_gpu(a.get("name", ""), preferred)), None)
            if selected is None:
                detected = "; ".join(
                    "%s [ordinal=%s, compatible=%s, error=%s]" % (
                        a.get("name") or "(nombre desconocido)",
                        a.get("adapter_ordinal", "?"),
                        bool(a.get("d3d9_supported")),
                        a.get("error") or "ninguno"
                    ) for a in probe_results
                ) or "Direct3D 9 no enumeró adaptadores"
                raise RuntimeError(
                    "No se encontró un adaptador DX9 inicializable para '%s'. "
                    "Adaptadores enumerados: %s" % (preferred, detected)
                )

            self.d3d_lib = ctypes.WinDLL("d3d9.dll")
            create9 = self.d3d_lib.Direct3DCreate9
            create9.argtypes = [wintypes.UINT]
            create9.restype = ctypes.c_void_p
            raw = create9(_D3D_SDK_VERSION)
            if not raw:
                raise RuntimeError("Direct3DCreate9 devolvió NULL")
            self.d3d = ctypes.c_void_p(raw)
            self._create_device(int(selected["adapter_ordinal"]))
            self._ensure_texture(None)
            self.info.update(
                renderer=selected["name"], adapter=selected["name"],
                vendor=selected.get("vendor_id", ""),
                driver=selected.get("driver", ""),
                vertex_processing=selected.get("vertex_processing", ""),
                adapter_ordinal=int(selected["adapter_ordinal"]),
            )
            return self.info
        except Exception:
            self.close()
            raise

    def _create_device(self, ordinal):
        get_desktop = ctypes.WinDLL("user32.dll").GetDesktopWindow
        get_desktop.argtypes = []
        get_desktop.restype = wintypes.HWND
        hwnd = get_desktop()
        pp = _PresentParameters()
        pp.BackBufferWidth = 1
        pp.BackBufferHeight = 1
        pp.BackBufferFormat = _D3DFMT_UNKNOWN
        pp.BackBufferCount = 1
        pp.SwapEffect = _D3DSWAPEFFECT_DISCARD
        pp.hDeviceWindow = hwnd
        pp.Windowed = 1
        pp.EnableAutoDepthStencil = 0
        pp.PresentationInterval = _D3DPRESENT_INTERVAL_IMMEDIATE
        create = _method(
            self.d3d, 16, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.HWND, wintypes.DWORD, ctypes.POINTER(_PresentParameters),
            ctypes.POINTER(ctypes.c_void_p))
        last_hr = 0
        for flags, label in ((_D3DCREATE_HARDWARE_VERTEXPROCESSING, "hardware"),
                             (_D3DCREATE_SOFTWARE_VERTEXPROCESSING, "software")):
            device = ctypes.c_void_p()
            hr = create(self.d3d, ordinal, _D3DDEVTYPE_HAL, hwnd, flags,
                        ctypes.byref(pp), ctypes.byref(device))
            if hr >= 0 and device.value:
                self.device = device
                self.info["vertex_processing"] = label
                return
            last_hr = hr
            _release(device)
        raise RuntimeError("IDirect3D9::CreateDevice falló: HRESULT 0x%08X" %
                           (last_hr & 0xFFFFFFFF))

    def _ensure_targets(self, width, height):
        if self.size == (width, height):
            return
        for name in ("readback_surface", "depth_surface", "target_surface",
                     "target_texture"):
            _release(getattr(self, name))
            setattr(self, name, ctypes.c_void_p())

        create_texture = _method(
            self.device, 23, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.UINT, wintypes.DWORD, wintypes.UINT, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
        _check(create_texture(self.device, width, height, 1, _D3DUSAGE_RENDERTARGET,
                              _D3DFMT_A8R8G8B8, _D3DPOOL_DEFAULT,
                              ctypes.byref(self.target_texture), None),
               "CreateTexture(render target)")
        _check(_method(self.target_texture, 18, ctypes.c_long, wintypes.UINT,
                       ctypes.POINTER(ctypes.c_void_p))(
            self.target_texture, 0, ctypes.byref(self.target_surface)),
            "GetSurfaceLevel(render target)")

        create_depth = _method(
            self.device, 29, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.UINT, wintypes.UINT, wintypes.DWORD, wintypes.BOOL,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
        _check(create_depth(self.device, width, height, _D3DFMT_D24S8, 0, 0, True,
                            ctypes.byref(self.depth_surface), None),
               "CreateDepthStencilSurface")

        create_readback = _method(
            self.device, 36, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p)
        _check(create_readback(self.device, width, height, _D3DFMT_A8R8G8B8,
                               _D3DPOOL_SYSTEMMEM, ctypes.byref(self.readback_surface),
                               None), "CreateOffscreenPlainSurface")
        self.size = (width, height)

    def _ensure_texture(self, texture):
        from PIL import Image
        import numpy as np
        if texture is None:
            image = Image.new("RGBA", (1, 1), (255, 255, 255, 255))
        elif isinstance(texture, Image.Image):
            image = texture.convert("RGBA")
        else:
            image = Image.fromarray(texture).convert("RGBA")
        width, height = image.size
        if width < 1 or height < 1:
            raise ValueError("La textura debe tener dimensiones positivas")
        raw = image.tobytes()
        key = (width, height, hash(raw))
        if key == self.texture_key:
            return
        _release(self.texture)
        self.texture = ctypes.c_void_p()
        create = _method(
            self.device, 23, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.UINT, wintypes.DWORD, wintypes.UINT, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
        _check(create(self.device, width, height, 1, 0, _D3DFMT_A8R8G8B8,
                      _D3DPOOL_MANAGED, ctypes.byref(self.texture), None),
               "CreateTexture(material)")
        lock = _method(self.texture, 19, ctypes.c_long, wintypes.UINT,
                       ctypes.POINTER(_LockedRect), ctypes.c_void_p, wintypes.DWORD)
        unlock = _method(self.texture, 20, ctypes.c_long, wintypes.UINT)
        mapped = _LockedRect()
        _check(lock(self.texture, 0, ctypes.byref(mapped), None, 0),
               "LockRect(material)")
        try:
            rgba = np.asarray(image, dtype=np.uint8)
            bgra = np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]])
            pitch = int(mapped.Pitch)
            if not mapped.pBits or pitch < width * 4:
                raise RuntimeError("LockRect(material) devolvió pitch/puntero inválido")
            for row in range(height):
                ctypes.memmove(mapped.pBits + row * pitch,
                               bgra[row].ctypes.data, width * 4)
        finally:
            _check(unlock(self.texture, 0), "UnlockRect(material)")
        self.texture_key = key

    def _upload_mesh(self, positions, uvs, triangles):
        import numpy as np
        pos = np.asarray(positions, dtype=np.float32)
        faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        if not len(pos) or not len(faces):
            raise ValueError("La malla no contiene triángulos")
        valid = np.isfinite(pos).all(axis=1)
        pos = np.where(valid[:, None], pos, 0.0)
        low, high = pos.min(axis=0), pos.max(axis=0)
        center = (low + high) * 0.5
        extent = float((high - low).max())
        normalized = (pos - center) / (extent if extent > 1e-12 else 1.0)
        uv = np.zeros((len(pos), 2), dtype=np.float32) if uvs is None else np.asarray(uvs, dtype=np.float32)
        if uv.shape != (len(pos), 2):
            raise ValueError("Las coordenadas UV deben tener forma (número de vértices, 2)")
        if faces.min() < 0 or faces.max() >= len(pos):
            raise ValueError("Índice de triángulo fuera del rango de vértices")
        self.vertex_data = np.ascontiguousarray(np.column_stack((normalized, uv)), dtype=np.float32)
        self.index_data = np.ascontiguousarray(faces.reshape(-1), dtype=np.uint32)
        self.index_count = int(self.index_data.size)
        self.mesh_key = (id(positions), id(uvs), id(triangles), pos.shape, faces.shape)

    def render_image(self, positions, uvs, triangles, texture, width, height,
                     rot_x=0.5, rot_y=0.6, zoom=1.0, pan_x=0.0, pan_y=0.0):
        import numpy as np
        from PIL import Image
        if not self.device:
            raise RuntimeError("Backend D3D9 no inicializado")
        width, height = max(1, int(width)), max(1, int(height))
        pos = np.asarray(positions)
        faces = np.asarray(triangles)
        if not len(pos) or not len(faces):
            return Image.new("RGB", (width, height), (17, 17, 17))
        key = (id(positions), id(uvs), id(triangles), pos.shape, faces.shape)
        if key != self.mesh_key:
            self._upload_mesh(positions, uvs, triangles)
        self._ensure_targets(width, height)
        self._ensure_texture(texture)

        vertices = self.vertex_data
        cy, sy = np.cos(rot_y), np.sin(rot_y)
        cx, sx = np.cos(rot_x), np.sin(rot_x)
        x = vertices[:, 0] * cy - vertices[:, 2] * sy
        z = vertices[:, 0] * sy + vertices[:, 2] * cy
        y = vertices[:, 1] * cx - z * sx
        z = vertices[:, 1] * sx + z * cx
        scale = 0.85 * min(width, height) * float(zoom)
        screen = np.empty((len(vertices), 6), dtype=np.float32)
        screen[:, 0] = width * 0.5 + x * scale + float(pan_x)
        screen[:, 1] = height * 0.5 - y * scale + float(pan_y)
        screen[:, 2] = np.clip(0.5 + z * 0.4, 0.0, 1.0)
        screen[:, 3] = 1.0
        screen[:, 4:6] = vertices[:, 3:5]
        vertex_array = (_Vertex * len(screen))()
        for i, values in enumerate(screen):
            vertex_array[i] = _Vertex(*map(float, values))
        index_array = (ctypes.c_uint32 * len(self.index_data))(
            *map(int, self.index_data))

        set_target = _method(self.device, 37, ctypes.c_long, wintypes.UINT,
                             ctypes.c_void_p)
        _check(set_target(self.device, 0, self.target_surface), "SetRenderTarget")
        set_depth = _method(self.device, 39, ctypes.c_long, ctypes.c_void_p)
        _check(set_depth(self.device, self.depth_surface), "SetDepthStencilSurface")
        viewport = _Viewport(0, 0, width, height, 0.0, 1.0)
        _check(_method(self.device, 47, ctypes.c_long, ctypes.POINTER(_Viewport))(
            self.device, ctypes.byref(viewport)), "SetViewport")
        clear = _method(self.device, 43, ctypes.c_long, wintypes.DWORD,
                        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                        ctypes.c_float, wintypes.DWORD)
        _check(clear(self.device, 0, None, _D3DCLEAR_TARGET | _D3DCLEAR_ZBUFFER,
                     0xFF111111, 1.0, 0), "Clear")
        for state, value in ((_D3DRS_ZENABLE, 1), (_D3DRS_ZWRITEENABLE, 1),
                             (_D3DRS_ZFUNC, _D3DCMP_LESSEQUAL),
                             (_D3DRS_LIGHTING, 0), (_D3DRS_CULLMODE, _D3DCULL_NONE)):
            _check(_method(self.device, 57, ctypes.c_long, wintypes.UINT, wintypes.DWORD)(
                self.device, state, value), "SetRenderState(%d)" % state)
        _check(_method(self.device, 89, ctypes.c_long, wintypes.DWORD)(
            self.device, _D3DFVF_XYZRHW | _D3DFVF_TEX1), "SetFVF")
        _check(_method(self.device, 65, ctypes.c_long, wintypes.UINT, ctypes.c_void_p)(
            self.device, 0, self.texture), "SetTexture")
        set_stage = _method(self.device, 67, ctypes.c_long, wintypes.UINT,
                            wintypes.UINT, wintypes.DWORD)
        for state, value in ((_D3DTSS_COLOROP, _D3DTOP_SELECTARG1),
                             (_D3DTSS_COLORARG1, _D3DTA_TEXTURE),
                             (_D3DTSS_ALPHAOP, _D3DTOP_SELECTARG1),
                             (_D3DTSS_ALPHAARG1, _D3DTA_TEXTURE)):
            _check(set_stage(self.device, 0, state, value), "SetTextureStageState")
        set_sampler = _method(self.device, 69, ctypes.c_long, wintypes.UINT,
                              wintypes.UINT, wintypes.DWORD)
        for state, value in ((_D3DSAMP_MINFILTER, _D3DTEXF_LINEAR),
                             (_D3DSAMP_MAGFILTER, _D3DTEXF_LINEAR),
                             (_D3DSAMP_ADDRESSU, _D3DTADDRESS_CLAMP),
                             (_D3DSAMP_ADDRESSV, _D3DTADDRESS_CLAMP)):
            _check(set_sampler(self.device, 0, state, value), "SetSamplerState")

        _check(_method(self.device, 41, ctypes.c_long)(self.device), "BeginScene")
        try:
            draw = _method(
                self.device, 84, ctypes.c_long, wintypes.UINT, wintypes.UINT,
                wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT,
                ctypes.c_void_p, wintypes.UINT)
            _check(draw(self.device, _D3DPT_TRIANGLELIST, 0, len(vertices),
                        len(self.index_data) // 3, index_array, _D3DFMT_INDEX32,
                        vertex_array, ctypes.sizeof(_Vertex)),
                   "DrawIndexedPrimitiveUP")
        finally:
            _check(_method(self.device, 42, ctypes.c_long)(self.device), "EndScene")

        get_data = _method(self.device, 32, ctypes.c_long, ctypes.c_void_p,
                           ctypes.c_void_p)
        _check(get_data(self.device, self.target_surface, self.readback_surface),
               "GetRenderTargetData")
        mapped = _LockedRect()
        lock = _method(self.readback_surface, 13, ctypes.c_long,
                       ctypes.POINTER(_LockedRect), ctypes.c_void_p, wintypes.DWORD)
        unlock = _method(self.readback_surface, 14, ctypes.c_long)
        _check(lock(self.readback_surface, ctypes.byref(mapped), None,
                    _D3DLOCK_READONLY), "Readback LockRect")
        try:
            if not mapped.pBits or mapped.Pitch < width * 4:
                raise RuntimeError("Readback LockRect devolvió pitch/puntero inválido")
            raw = b"".join(ctypes.string_at(mapped.pBits + y * mapped.Pitch,
                                            width * 4) for y in range(height))
        finally:
            _check(unlock(self.readback_surface), "Readback UnlockRect")
        bgra = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        rgba = bgra[:, :, [2, 1, 0, 3]].copy()
        return Image.fromarray(rgba, "RGBA").convert("RGB")

    def close(self):
        for name in ("readback_surface", "depth_surface", "target_surface",
                     "target_texture", "texture", "device", "d3d"):
            obj = getattr(self, name, None)
            _release(obj)
            setattr(self, name, ctypes.c_void_p())
        self.d3d_lib = None
        self.texture_key = self.mesh_key = self.size = None
        self.vertex_data = self.index_data = None
        self.index_count = 0
