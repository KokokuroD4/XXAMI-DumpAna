# -*- coding: utf-8 -*-
"""Backend nativo Direct3D 11 para el visor XXAMI (renderizado offscreen).

Primera implementación: geometría indexada, cámara, color sólido y readback.
No se registra en el selector hasta completar y validar texturas/profundidad.
"""
from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes


_FEATURE_LEVELS = (0xB100, 0xB000, 0xA100, 0xA000, 0x9300, 0x9200, 0x9100)
_FEATURE_NAMES = {0xB100: "11.1", 0xB000: "11.0", 0xA100: "10.1",
                  0xA000: "10.0", 0x9300: "9.3", 0x9200: "9.2", 0x9100: "9.1"}
_E_INVALIDARG = 0x80070057
_DXGI_ERROR_NOT_FOUND = 0x887A0002
_DXGI_FORMAT_R8G8B8A8_UNORM = 28
_DXGI_FORMAT_R32G32B32_FLOAT = 6
_DXGI_FORMAT_R32G32_FLOAT = 16
_D3D11_USAGE_DEFAULT = 0
_D3D11_USAGE_STAGING = 3
_D3D11_BIND_VERTEX_BUFFER = 0x1
_D3D11_BIND_INDEX_BUFFER = 0x2
_D3D11_BIND_CONSTANT_BUFFER = 0x4
_D3D11_BIND_RENDER_TARGET = 0x20
_D3D11_CPU_ACCESS_READ = 0x20000
_D3D11_MAP_READ = 1
_D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST = 4
_SDK_VERSION = 7


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _AdapterDesc(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", _LUID),
    ]


class _BufferDesc(ctypes.Structure):
    _fields_ = [("ByteWidth", wintypes.UINT), ("Usage", wintypes.UINT),
                ("BindFlags", wintypes.UINT), ("CPUAccessFlags", wintypes.UINT),
                ("MiscFlags", wintypes.UINT), ("StructureByteStride", wintypes.UINT)]


class _SubresourceData(ctypes.Structure):
    _fields_ = [("pSysMem", ctypes.c_void_p), ("SysMemPitch", wintypes.UINT),
                ("SysMemSlicePitch", wintypes.UINT)]


class _Texture2DDesc(ctypes.Structure):
    _fields_ = [("Width", wintypes.UINT), ("Height", wintypes.UINT),
                ("MipLevels", wintypes.UINT), ("ArraySize", wintypes.UINT),
                ("Format", wintypes.UINT), ("SampleCount", wintypes.UINT),
                ("SampleQuality", wintypes.UINT), ("Usage", wintypes.UINT),
                ("BindFlags", wintypes.UINT), ("CPUAccessFlags", wintypes.UINT),
                ("MiscFlags", wintypes.UINT)]


class _InputElementDesc(ctypes.Structure):
    _fields_ = [("SemanticName", ctypes.c_char_p), ("SemanticIndex", wintypes.UINT),
                ("Format", wintypes.UINT), ("InputSlot", wintypes.UINT),
                ("AlignedByteOffset", wintypes.UINT), ("InputSlotClass", wintypes.UINT),
                ("InstanceDataStepRate", wintypes.UINT)]


class _Viewport(ctypes.Structure):
    _fields_ = [("TopLeftX", ctypes.c_float), ("TopLeftY", ctypes.c_float),
                ("Width", ctypes.c_float), ("Height", ctypes.c_float),
                ("MinDepth", ctypes.c_float), ("MaxDepth", ctypes.c_float)]


class _RasterizerDesc(ctypes.Structure):
    _fields_ = [("FillMode", wintypes.UINT), ("CullMode", wintypes.UINT),
                ("FrontCounterClockwise", wintypes.BOOL), ("DepthBias", ctypes.c_int),
                ("DepthBiasClamp", ctypes.c_float), ("SlopeScaledDepthBias", ctypes.c_float),
                ("DepthClipEnable", wintypes.BOOL), ("ScissorEnable", wintypes.BOOL),
                ("MultisampleEnable", wintypes.BOOL), ("AntialiasedLineEnable", wintypes.BOOL)]


class _MappedSubresource(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", wintypes.UINT),
                ("DepthPitch", wintypes.UINT)]


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


def _enumerate_adapters():
    if sys.platform != "win32":
        raise RuntimeError("Direct3D 11 solo está disponible en Windows")
    dxgi = ctypes.WinDLL("dxgi.dll")
    create_factory = dxgi.CreateDXGIFactory
    create_factory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create_factory.restype = ctypes.c_long
    iid = ctypes.create_string_buffer(bytes.fromhex("ec66717bc721ae44b21ac9ae321ae369"))
    factory = ctypes.c_void_p()
    _check(create_factory(ctypes.byref(iid), ctypes.byref(factory)), "CreateDXGIFactory")
    adapters = []
    try:
        enum = _method(factory, 7, ctypes.c_long, wintypes.UINT,
                       ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            hr = enum(factory, index, ctypes.byref(adapter))
            if (hr & 0xFFFFFFFF) == _DXGI_ERROR_NOT_FOUND:
                break
            _check(hr, "IDXGIFactory::EnumAdapters")
            try:
                desc = _AdapterDesc()
                _check(_method(adapter, 8, ctypes.c_long,
                               ctypes.POINTER(_AdapterDesc))(adapter, ctypes.byref(desc)),
                       "IDXGIAdapter::GetDesc")
                # El adaptador software se libera en finally, pero el índice
                # debe avanzar igualmente para no enumerarlo en un bucle infinito.
                is_software = desc.VendorId == 0x1414 and desc.DeviceId == 0x008C
                if not is_software:
                    adapters.append((adapter.value, {
                        "name": str(desc.Description),
                        "vendor_id": "0x%04X" % desc.VendorId,
                        "device_id": "0x%04X" % desc.DeviceId,
                        "luid": "%08X:%08X" % (desc.AdapterLuid.HighPart & 0xFFFFFFFF,
                                                desc.AdapterLuid.LowPart),
                    }))
                    adapter = ctypes.c_void_p()
            finally:
                _release(adapter)
            index += 1
    finally:
        _release(factory)
    return adapters


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _matches_gpu(name, preference):
    preferred = str(preference or "default").strip()
    if preferred.casefold() in ("", "default"):
        return True
    wanted = _normalize(preferred)
    candidate = _normalize(name)
    if wanted in candidate or candidate in wanted:
        return True
    wanted_tokens = set(re.findall(r"[a-z0-9]+", preferred.casefold()))
    found_tokens = set(re.findall(r"[a-z0-9]+", name.casefold()))
    stop = {"graphics", "gpu", "adapter", "microsoft", "corporation", "inc", "ltd", "the"}
    wanted_tokens -= stop
    found_tokens -= stop
    return bool(wanted_tokens and len(wanted_tokens & found_tokens) / len(wanted_tokens | found_tokens) >= 0.72)


class D3D11Backend:
    backend_id = "d3d11"
    label = "Direct3D 11"

    def __init__(self):
        self.info = {"id": self.backend_id, "label": self.label}
        self.gpu_preference = "default"
        # Los parámetros de salida COM deben ser instancias ctypes c_void_p,
        # no None: las funciones D3D11 escriben sus interfaces mediante T**.
        self.d3d11 = None
        self.adapter = ctypes.c_void_p()
        self.device = ctypes.c_void_p()
        self.context = ctypes.c_void_p()
        self.vertex_shader = ctypes.c_void_p()
        self.pixel_shader = ctypes.c_void_p()
        self.input_layout = ctypes.c_void_p()
        self.rasterizer_state = ctypes.c_void_p()
        self.vertex_buffer = ctypes.c_void_p()
        self.index_buffer = ctypes.c_void_p()
        self.constant_buffer = ctypes.c_void_p()
        self.color_texture = ctypes.c_void_p()
        self.render_target = ctypes.c_void_p()
        self.staging_texture = ctypes.c_void_p()
        self.mesh_key = None
        self.index_count = 0
        self.size = None

    def initialize(self):
        if sys.platform != "win32":
            raise RuntimeError("Direct3D 11 requiere Windows")
        try:
            self.d3d11 = ctypes.WinDLL("d3d11.dll")
            adapters = _enumerate_adapters()
            if not adapters:
                raise RuntimeError("DXGI no encontró adaptadores físicos")
            preferred = str(self.gpu_preference or "default")
            selected = next((item for item in adapters
                             if _matches_gpu(item[1]["name"], preferred)), None)
            if selected is None:
                raise RuntimeError("No se encontró la GPU solicitada: " + preferred)
            self.adapter = ctypes.c_void_p(selected[0])
            self._create_device()
            self._create_pipeline()
            self.info.update(vendor=selected[1]["vendor_id"],
                             renderer=selected[1]["name"],
                             adapter=selected[1]["name"], luid=selected[1]["luid"],
                             feature_level=self.feature_level)
            return self.info
        except Exception:
            self.close()
            raise

    def _create_device(self):
        create = self.d3d11.D3D11CreateDevice
        create.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                           wintypes.UINT, ctypes.POINTER(wintypes.UINT),
                           wintypes.UINT, wintypes.UINT,
                           ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
                           ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        level_array = wintypes.UINT * len(_FEATURE_LEVELS)
        levels = level_array(*_FEATURE_LEVELS)
        selected = wintypes.UINT()
        self.device, self.context = ctypes.c_void_p(), ctypes.c_void_p()
        hr = create(self.adapter, 0, None, 0, levels, len(levels), _SDK_VERSION,
                    ctypes.byref(self.device), ctypes.byref(selected),
                    ctypes.byref(self.context))
        if hr < 0 and (hr & 0xFFFFFFFF) == _E_INVALIDARG:
            legacy = level_array(*_FEATURE_LEVELS[1:])
            hr = create(self.adapter, 0, None, 0, legacy, len(legacy), _SDK_VERSION,
                        ctypes.byref(self.device), ctypes.byref(selected),
                        ctypes.byref(self.context))
        _check(hr, "D3D11CreateDevice")
        self.feature_level = _FEATURE_NAMES.get(selected.value, hex(selected.value))

    def _compile(self, source, entry, target):
        compiler = ctypes.WinDLL("d3dcompiler_47.dll")
        fn = compiler.D3DCompile
        fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                       ctypes.c_char_p, wintypes.UINT, wintypes.UINT,
                       ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        fn.restype = ctypes.c_long
        raw = source.encode("utf-8")
        source_buffer = ctypes.create_string_buffer(raw)
        code, errors = ctypes.c_void_p(), ctypes.c_void_p()
        hr = fn(source_buffer, len(raw), b"xxami_d3d11_backend.hlsl", None, None,
                entry.encode("ascii"), target.encode("ascii"), 0, 0,
                ctypes.byref(code), ctypes.byref(errors))
        try:
            if hr < 0:
                message = "D3DCompile %s falló: 0x%08X" % (entry, hr & 0xFFFFFFFF)
                if errors.value:
                    ptr = _method(errors, 3, ctypes.c_void_p)(errors)
                    size = _method(errors, 4, ctypes.c_size_t)(errors)
                    message += "\n" + ctypes.string_at(ptr, size).decode("utf-8", "replace")
                raise RuntimeError(message)
            ptr = _method(code, 3, ctypes.c_void_p)(code)
            size = _method(code, 4, ctypes.c_size_t)(code)
            return ctypes.string_at(ptr, size)
        finally:
            _release(errors)
            _release(code)

    def _create_pipeline(self):
        source = r"""
cbuffer Camera : register(b0) { float4x4 mvp; };
struct VSIn { float3 pos : POSITION; };
struct VSOut { float4 pos : SV_POSITION; };
VSOut VSMain(VSIn input) {
    VSOut output;
    output.pos = mul(mvp, float4(input.pos, 1.0));
    return output;
}
float4 PSMain() : SV_TARGET { return float4(0.78, 0.80, 0.83, 1.0); }
"""
        vs = self._compile(source, "VSMain", "vs_4_0")
        ps = self._compile(source, "PSMain", "ps_4_0")
        vs_mem = ctypes.create_string_buffer(vs)
        ps_mem = ctypes.create_string_buffer(ps)
        create_vs = _method(self.device, 12, ctypes.c_long, ctypes.c_void_p,
                            ctypes.c_size_t, ctypes.c_void_p,
                            ctypes.POINTER(ctypes.c_void_p))
        _check(create_vs(self.device, ctypes.cast(vs_mem, ctypes.c_void_p),
                         len(vs), None, ctypes.byref(self.vertex_shader)),
               "CreateVertexShader")
        create_ps = _method(self.device, 15, ctypes.c_long, ctypes.c_void_p,
                            ctypes.c_size_t, ctypes.c_void_p,
                            ctypes.POINTER(ctypes.c_void_p))
        _check(create_ps(self.device, ctypes.cast(ps_mem, ctypes.c_void_p),
                         len(ps), None, ctypes.byref(self.pixel_shader)),
               "CreatePixelShader")
        elements = (_InputElementDesc * 1)(
            _InputElementDesc(b"POSITION", 0, _DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, 0, 0))
        create_layout = _method(self.device, 11, ctypes.c_long,
                                ctypes.POINTER(_InputElementDesc), wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_size_t,
                                ctypes.POINTER(ctypes.c_void_p))
        _check(create_layout(self.device, elements, 1,
                             ctypes.cast(vs_mem, ctypes.c_void_p), len(vs),
                             ctypes.byref(self.input_layout)), "CreateInputLayout")
        desc = _BufferDesc(64, _D3D11_USAGE_DEFAULT, _D3D11_BIND_CONSTANT_BUFFER, 0, 0, 0)
        create_buffer = _method(self.device, 3, ctypes.c_long,
                                ctypes.POINTER(_BufferDesc), ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_void_p))
        _check(create_buffer(self.device, ctypes.byref(desc), None,
                             ctypes.byref(self.constant_buffer)), "CreateBuffer(camera)")

        # No se presupone el winding de las mallas importadas: dibujar ambas caras.
        raster_desc = _RasterizerDesc(3, 1, 0, 0, 0.0, 0.0, 1, 0, 0, 0)
        create_rasterizer = _method(self.device, 22, ctypes.c_long,
                                    ctypes.POINTER(_RasterizerDesc),
                                    ctypes.POINTER(ctypes.c_void_p))
        _check(create_rasterizer(self.device, ctypes.byref(raster_desc),
                                 ctypes.byref(self.rasterizer_state)),
               "CreateRasterizerState")

    def _upload_mesh(self, positions, uvs, triangles):
        import numpy as np
        pos = np.asarray(positions, dtype=np.float32)
        faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        if not len(pos) or not len(faces):
            raise ValueError("La malla no contiene triángulos")
        if not np.isfinite(pos).all():
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
        vertices = np.ascontiguousarray(np.column_stack((normalized, uv)), dtype=np.float32)
        indices = np.ascontiguousarray(faces.reshape(-1), dtype=np.uint32)
        create_buffer = _method(self.device, 3, ctypes.c_long,
                                ctypes.POINTER(_BufferDesc), ctypes.POINTER(_SubresourceData),
                                ctypes.POINTER(ctypes.c_void_p))
        def upload(data, bind, label):
            desc = _BufferDesc(data.nbytes, _D3D11_USAGE_DEFAULT, bind, 0, 0, 0)
            initial = _SubresourceData(data.ctypes.data, 0, 0)
            result = ctypes.c_void_p()
            _check(create_buffer(self.device, ctypes.byref(desc), ctypes.byref(initial),
                                 ctypes.byref(result)), "CreateBuffer(" + label + ")")
            return result
        new_vb = upload(vertices, _D3D11_BIND_VERTEX_BUFFER, "vertex")
        try:
            new_ib = upload(indices, _D3D11_BIND_INDEX_BUFFER, "index")
        except Exception:
            _release(new_vb)
            raise
        _release(self.vertex_buffer)
        _release(self.index_buffer)
        self.vertex_buffer, self.index_buffer = new_vb, new_ib
        self.index_count = int(indices.size)
        self.mesh_key = (id(positions), id(uvs), id(triangles), pos.shape, faces.shape)

    def _ensure_targets(self, width, height):
        if self.size == (width, height):
            return
        _release(self.render_target)
        _release(self.color_texture)
        _release(self.staging_texture)
        desc = _Texture2DDesc(width, height, 1, 1, _DXGI_FORMAT_R8G8B8A8_UNORM,
                              1, 0, _D3D11_USAGE_DEFAULT, _D3D11_BIND_RENDER_TARGET, 0, 0)
        create_texture = _method(self.device, 5, ctypes.c_long,
                                 ctypes.POINTER(_Texture2DDesc), ctypes.c_void_p,
                                 ctypes.POINTER(ctypes.c_void_p))
        _check(create_texture(self.device, ctypes.byref(desc), None,
                              ctypes.byref(self.color_texture)), "CreateTexture2D(target)")
        create_rtv = _method(self.device, 9, ctypes.c_long, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        _check(create_rtv(self.device, self.color_texture, None,
                          ctypes.byref(self.render_target)), "CreateRenderTargetView")
        staging_desc = _Texture2DDesc(width, height, 1, 1, _DXGI_FORMAT_R8G8B8A8_UNORM,
                                      1, 0, _D3D11_USAGE_STAGING, 0,
                                      _D3D11_CPU_ACCESS_READ, 0)
        _check(create_texture(self.device, ctypes.byref(staging_desc), None,
                              ctypes.byref(self.staging_texture)), "CreateTexture2D(staging)")
        self.size = (width, height)

    def render_image(self, positions, uvs, triangles, texture, width, height,
                     rot_x=0.5, rot_y=0.6, zoom=1.0, pan_x=0.0, pan_y=0.0):
        import numpy as np
        from PIL import Image
        if self.device is None:
            raise RuntimeError("Backend D3D11 no inicializado")
        if texture is not None:
            raise NotImplementedError("El backend D3D11 todavía no incorpora carga de texturas")
        width, height = max(1, int(width)), max(1, int(height))
        pos, faces = np.asarray(positions), np.asarray(triangles)
        if not len(pos) or not len(faces):
            return Image.new("RGB", (width, height), (17, 17, 17))
        key = (id(positions), id(uvs), id(triangles), pos.shape, faces.shape)
        if key != self.mesh_key:
            self._upload_mesh(positions, uvs, triangles)

        cy, sy = np.cos(rot_y), np.sin(rot_y)
        cx, sx = np.cos(rot_x), np.sin(rot_x)
        rotate_y = np.array([[cy, 0, -sy, 0], [0, 1, 0, 0],
                             [sy, 0, cy, 0], [0, 0, 0, 1]], dtype=np.float32)
        rotate_x = np.array([[1, 0, 0, 0], [0, cx, -sx, 0],
                             [0, sx, cx, 0], [0, 0, 0, 1]], dtype=np.float32)
        scale = 0.85 * min(width, height) * float(zoom)
        projection = np.diag([2 * scale / width, 2 * scale / height, 0.4, 1.0]).astype(np.float32)
        projection[2, 3] = 0.5
        translate = np.eye(4, dtype=np.float32)
        translate[0, 3] = 2.0 * float(pan_x) / width
        translate[1, 3] = -2.0 * float(pan_y) / height
        mvp = translate @ projection @ rotate_x @ rotate_y
        matrix = np.ascontiguousarray(mvp.T, dtype=np.float32)
        mapped = _MappedSubresource()
        self._ensure_targets(width, height)
        update = _method(self.context, 48, None, ctypes.c_void_p, wintypes.UINT,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT)
        update(self.context, self.constant_buffer, 0, None,
               ctypes.c_void_p(matrix.ctypes.data), 0, 0)

        clear = (ctypes.c_float * 4)(17 / 255, 17 / 255, 17 / 255, 1.0)
        _method(self.context, 50, None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float))(
            self.context, self.render_target, clear)
        _method(self.context, 33, None, wintypes.UINT,
                ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)(
            self.context, 1, ctypes.byref(self.render_target), None)
        viewport = _Viewport(0.0, 0.0, float(width), float(height), 0.0, 1.0)
        _method(self.context, 44, None, wintypes.UINT, ctypes.POINTER(_Viewport))(
            self.context, 1, ctypes.byref(viewport))
        _method(self.context, 43, None, ctypes.c_void_p)(
            self.context, self.rasterizer_state)
        _method(self.context, 17, None, ctypes.c_void_p)(self.context, self.input_layout)
        vb = ctypes.c_void_p(self.vertex_buffer.value)
        stride, offset = wintypes.UINT(20), wintypes.UINT(0)
        _method(self.context, 18, None, wintypes.UINT, wintypes.UINT,
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT))(
            self.context, 0, 1, ctypes.byref(vb), ctypes.byref(stride), ctypes.byref(offset))
        _method(self.context, 19, None, ctypes.c_void_p, wintypes.UINT, wintypes.UINT)(
            self.context, self.index_buffer, 42, 0)
        _method(self.context, 24, None, wintypes.UINT)(
            self.context, _D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST)
        _method(self.context, 7, None, wintypes.UINT, wintypes.UINT,
                ctypes.POINTER(ctypes.c_void_p))(
            self.context, 0, 1, ctypes.byref(self.constant_buffer))
        _method(self.context, 11, None, ctypes.c_void_p, ctypes.c_void_p,
                wintypes.UINT)(self.context, self.vertex_shader, None, 0)
        _method(self.context, 9, None, ctypes.c_void_p, ctypes.c_void_p,
                wintypes.UINT)(self.context, self.pixel_shader, None, 0)
        _method(self.context, 12, None, wintypes.UINT, wintypes.UINT, wintypes.UINT)(
            self.context, self.index_count, 0, 0)
        _method(self.context, 47, None, ctypes.c_void_p, ctypes.c_void_p)(
            self.context, self.staging_texture, self.color_texture)
        hr = _method(self.context, 14, ctypes.c_long, ctypes.c_void_p, wintypes.UINT,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(_MappedSubresource))(
            self.context, self.staging_texture, 0, _D3D11_MAP_READ, 0, ctypes.byref(mapped))
        _check(hr, "ID3D11DeviceContext::Map")
        try:
            if not mapped.pData or mapped.RowPitch < width * 4:
                raise RuntimeError("Map devolvió un puntero o pitch inválido")
            pitch = int(mapped.RowPitch)
            raw = b"".join(ctypes.string_at(mapped.pData + y * pitch, width * 4)
                           for y in range(height))
        finally:
            _method(self.context, 15, None, ctypes.c_void_p, wintypes.UINT)(
                self.context, self.staging_texture, 0)
        rgba = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4).copy()
        return Image.fromarray(rgba, "RGBA").convert("RGB")

    def close(self):
        for name in ("staging_texture", "render_target", "color_texture",
                     "constant_buffer", "index_buffer", "vertex_buffer",
                     "input_layout", "rasterizer_state", "pixel_shader", "vertex_shader",
                     "context", "device", "adapter"):
            obj = getattr(self, name, None)
            _release(obj)
            setattr(self, name, None)
        self.d3d11 = None
        self.mesh_key = self.size = None
        self.index_count = 0
