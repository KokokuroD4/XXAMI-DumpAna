# -*- coding: utf-8 -*-
"""Prueba temporal de renderizado offscreen Direct3D 11 para XXAMI.

Ejecutar en Windows:
    python xxami_d3d11_render_test.py

Crea xxami_d3d11_render_test.log y, si el renderizado termina, una PNG por
adaptador físico probado. No forma parte del visor ni registra DX11 como API.
"""
from __future__ import annotations

import ctypes
import logging
import struct
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

LOG_PATH = Path(__file__).resolve().with_name("xxami_d3d11_render_test.log")
OUTPUT_DIR = LOG_PATH.parent
WIDTH, HEIGHT = 256, 256

# DXGI / D3D11 constants
IID_FACTORY = bytes.fromhex("ec66717bc721ae44b21ac9ae321ae369")
SDK_VERSION = 7
DRIVER_TYPE_UNKNOWN = 0
FEATURE_LEVELS = (0xB100, 0xB000, 0xA100, 0xA000, 0x9300, 0x9200, 0x9100)
DXGI_ERROR_NOT_FOUND = 0x887A0002
E_INVALIDARG = 0x80070057
DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_FORMAT_R32G32B32_FLOAT = 6
D3D11_USAGE_DEFAULT = 0
D3D11_USAGE_STAGING = 3
D3D11_BIND_VERTEX_BUFFER = 0x1
D3D11_BIND_RENDER_TARGET = 0x20
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST = 4
FEATURE_NAMES = {0xB100: "11.1", 0xB000: "11.0", 0xA100: "10.1",
                 0xA000: "10.0", 0x9300: "9.3", 0x9200: "9.2", 0x9100: "9.1"}


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class AdapterDesc(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID),
    ]


class Texture2DDesc(ctypes.Structure):
    _fields_ = [
        ("Width", wintypes.UINT), ("Height", wintypes.UINT),
        ("MipLevels", wintypes.UINT), ("ArraySize", wintypes.UINT),
        ("Format", wintypes.UINT),
        ("SampleCount", wintypes.UINT), ("SampleQuality", wintypes.UINT),
        ("Usage", wintypes.UINT), ("BindFlags", wintypes.UINT),
        ("CPUAccessFlags", wintypes.UINT), ("MiscFlags", wintypes.UINT),
    ]


class BufferDesc(ctypes.Structure):
    _fields_ = [
        ("ByteWidth", wintypes.UINT), ("Usage", wintypes.UINT),
        ("BindFlags", wintypes.UINT), ("CPUAccessFlags", wintypes.UINT),
        ("MiscFlags", wintypes.UINT), ("StructureByteStride", wintypes.UINT),
    ]


class SubresourceData(ctypes.Structure):
    _fields_ = [("pSysMem", ctypes.c_void_p), ("SysMemPitch", wintypes.UINT),
                ("SysMemSlicePitch", wintypes.UINT)]


class InputElementDesc(ctypes.Structure):
    _fields_ = [
        ("SemanticName", ctypes.c_char_p), ("SemanticIndex", wintypes.UINT),
        ("Format", wintypes.UINT), ("InputSlot", wintypes.UINT),
        ("AlignedByteOffset", wintypes.UINT), ("InputSlotClass", wintypes.UINT),
        ("InstanceDataStepRate", wintypes.UINT),
    ]


class Viewport(ctypes.Structure):
    _fields_ = [("TopLeftX", ctypes.c_float), ("TopLeftY", ctypes.c_float),
                ("Width", ctypes.c_float), ("Height", ctypes.c_float),
                ("MinDepth", ctypes.c_float), ("MaxDepth", ctypes.c_float)]


class MappedSubresource(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", wintypes.UINT),
                ("DepthPitch", wintypes.UINT)]


def hresult(hr):
    return "0x%08X" % (hr & 0xFFFFFFFF)


def com_method(obj, index, restype, *argtypes):
    if not obj:
        raise RuntimeError("Puntero COM nulo para método vtable %d" % index)
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def release(obj):
    if obj:
        try:
            com_method(obj, 2, wintypes.ULONG)(obj)
        except Exception:
            logging.exception("Error liberando objeto COM")


def check_hr(hr, stage):
    if hr < 0:
        raise RuntimeError("%s falló: HRESULT %s" % (stage, hresult(hr)))


def enumerate_adapters():
    dxgi = ctypes.WinDLL("dxgi.dll")
    create_factory = dxgi.CreateDXGIFactory
    create_factory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create_factory.restype = ctypes.c_long
    iid = ctypes.create_string_buffer(IID_FACTORY)
    factory = ctypes.c_void_p()
    check_hr(create_factory(ctypes.byref(iid), ctypes.byref(factory)), "CreateDXGIFactory")
    found = []
    try:
        enum = com_method(factory, 7, ctypes.c_long, wintypes.UINT,
                          ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            hr = enum(factory, index, ctypes.byref(adapter))
            if (hr & 0xFFFFFFFF) == DXGI_ERROR_NOT_FOUND:
                break
            check_hr(hr, "IDXGIFactory::EnumAdapters(%d)" % index)
            try:
                desc = AdapterDesc()
                check_hr(com_method(adapter, 8, ctypes.c_long,
                                    ctypes.POINTER(AdapterDesc))(adapter, ctypes.byref(desc)),
                         "IDXGIAdapter::GetDesc")
                # El driver Microsoft Basic Render Driver es software: se registra,
                # pero no se mezcla con las pruebas de GPU física.
                if desc.VendorId == 0x1414 and desc.DeviceId == 0x008C:
                    logging.info("Se omite adaptador software: %s", desc.Description)
                else:
                    found.append((adapter.value, {
                        "name": str(desc.Description),
                        "vendor_id": "0x%04X" % desc.VendorId,
                        "device_id": "0x%04X" % desc.DeviceId,
                        "luid": "%08X:%08X" % (desc.AdapterLuid.HighPart & 0xFFFFFFFF,
                                               desc.AdapterLuid.LowPart),
                        "dedicated_video_memory": int(desc.DedicatedVideoMemory),
                    }))
                    # La referencia COM se transfiere al llamador.
                    adapter = ctypes.c_void_p()
            finally:
                release(adapter)
            index += 1
    finally:
        release(factory)
    return found


def compile_shader(compiler, source, entry, target):
    compile_fn = compiler.D3DCompile
    compile_fn.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, wintypes.UINT,
        wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)
    ]
    compile_fn.restype = ctypes.c_long
    source_bytes = source.encode("utf-8")
    source_buffer = ctypes.create_string_buffer(source_bytes)
    code, errors = ctypes.c_void_p(), ctypes.c_void_p()
    hr = compile_fn(source_buffer, len(source_bytes), b"xxami_d3d11_test.hlsl",
                    None, None, entry.encode("ascii"), target.encode("ascii"),
                    0, 0, ctypes.byref(code), ctypes.byref(errors))
    try:
        if hr < 0:
            message = "D3DCompile %s/%s falló: HRESULT %s" % (entry, target, hresult(hr))
            if errors.value:
                ptr = com_method(errors, 3, ctypes.c_void_p)(errors)
                size = com_method(errors, 4, ctypes.c_size_t)(errors)
                message += "\n" + ctypes.string_at(ptr, size).decode("utf-8", "replace")
            raise RuntimeError(message)
        ptr = com_method(code, 3, ctypes.c_void_p)(code)
        size = com_method(code, 4, ctypes.c_size_t)(code)
        return ctypes.string_at(ptr, size)
    finally:
        release(errors)
        release(code)


def create_device(d3d11, adapter):
    create = d3d11.D3D11CreateDevice
    create.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(wintypes.UINT), wintypes.UINT, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(ctypes.c_void_p)
    ]
    create.restype = ctypes.c_long
    level_type = wintypes.UINT * len(FEATURE_LEVELS)
    levels = level_type(*FEATURE_LEVELS)
    device, context, selected = ctypes.c_void_p(), ctypes.c_void_p(), wintypes.UINT()
    hr = create(adapter, DRIVER_TYPE_UNKNOWN, None, 0, levels, len(levels),
                SDK_VERSION, ctypes.byref(device), ctypes.byref(selected),
                ctypes.byref(context))
    if hr < 0 and (hr & 0xFFFFFFFF) == E_INVALIDARG:
        legacy = level_type(*FEATURE_LEVELS[1:])
        hr = create(adapter, DRIVER_TYPE_UNKNOWN, None, 0, legacy, len(legacy),
                    SDK_VERSION, ctypes.byref(device), ctypes.byref(selected),
                    ctypes.byref(context))
    check_hr(hr, "D3D11CreateDevice")
    if not device.value or not context.value:
        raise RuntimeError("D3D11CreateDevice no devolvió device/context")
    return device, context, FEATURE_NAMES.get(selected.value, hex(selected.value))


def render_triangle(device, context, output_path):
    # Un triángulo rojo/verde/azul sobre fondo azul oscuro.
    source = r"""
struct VSIn { float3 pos : POSITION; };
struct VSOut { float4 pos : SV_POSITION; };
VSOut VSMain(VSIn input) {
    VSOut output;
    output.pos = float4(input.pos, 1.0);
    return output;
}
float4 PSMain() : SV_TARGET { return float4(0.15, 0.85, 0.35, 1.0); }
"""
    compiler = ctypes.WinDLL("d3dcompiler_47.dll")
    vs_code = compile_shader(compiler, source, "VSMain", "vs_4_0")
    ps_code = compile_shader(compiler, source, "PSMain", "ps_4_0")
    logging.info("Shaders HLSL compilados (VS=%d bytes, PS=%d bytes)",
                 len(vs_code), len(ps_code))

    vs, ps, layout = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    vb, target, rtv, staging = (ctypes.c_void_p() for _ in range(4))
    vs_buffer = ctypes.create_string_buffer(vs_code)
    ps_buffer = ctypes.create_string_buffer(ps_code)
    try:
        create_vs = com_method(device, 12, ctypes.c_long, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_void_p))
        check_hr(create_vs(device, ctypes.cast(vs_buffer, ctypes.c_void_p),
                           len(vs_code), None, ctypes.byref(vs)),
                 "ID3D11Device::CreateVertexShader")
        create_ps = com_method(device, 15, ctypes.c_long, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_void_p))
        check_hr(create_ps(device, ctypes.cast(ps_buffer, ctypes.c_void_p),
                           len(ps_code), None, ctypes.byref(ps)),
                 "ID3D11Device::CreatePixelShader")

        element = InputElementDesc(b"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT,
                                   0, 0, 0, 0)
        create_layout = com_method(device, 11, ctypes.c_long,
                                   ctypes.POINTER(InputElementDesc), wintypes.UINT,
                                   ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_void_p))
        check_hr(create_layout(device, ctypes.byref(element), 1,
                               ctypes.cast(vs_buffer, ctypes.c_void_p), len(vs_code),
                               ctypes.byref(layout)), "CreateInputLayout")

        vertices = (ctypes.c_float * 9)(0.0, 0.75, 0.0, 0.75, -0.65, 0.0,
                                        -0.75, -0.65, 0.0)
        buffer_desc = BufferDesc(ctypes.sizeof(vertices), D3D11_USAGE_DEFAULT,
                                 D3D11_BIND_VERTEX_BUFFER, 0, 0, 0)
        initial = SubresourceData(ctypes.cast(vertices, ctypes.c_void_p), 0, 0)
        create_buffer = com_method(device, 3, ctypes.c_long,
                                   ctypes.POINTER(BufferDesc),
                                   ctypes.POINTER(SubresourceData),
                                   ctypes.POINTER(ctypes.c_void_p))
        check_hr(create_buffer(device, ctypes.byref(buffer_desc), ctypes.byref(initial),
                               ctypes.byref(vb)), "CreateBuffer(vertex)")

        tex_desc = Texture2DDesc(WIDTH, HEIGHT, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM,
                                 1, 0, D3D11_USAGE_DEFAULT,
                                 D3D11_BIND_RENDER_TARGET, 0, 0)
        create_texture = com_method(device, 5, ctypes.c_long,
                                    ctypes.POINTER(Texture2DDesc), ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p))
        check_hr(create_texture(device, ctypes.byref(tex_desc), None, ctypes.byref(target)),
                 "CreateTexture2D(render target)")
        create_rtv = com_method(device, 9, ctypes.c_long, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        check_hr(create_rtv(device, target, None, ctypes.byref(rtv)),
                 "CreateRenderTargetView")

        staging_desc = Texture2DDesc(WIDTH, HEIGHT, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM,
                                     1, 0, D3D11_USAGE_STAGING, 0,
                                     D3D11_CPU_ACCESS_READ, 0)
        check_hr(create_texture(device, ctypes.byref(staging_desc), None,
                                ctypes.byref(staging)), "CreateTexture2D(staging)")

        clear = (ctypes.c_float * 4)(0.025, 0.04, 0.09, 1.0)
        com_method(context, 50, None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float))(
            context, rtv, clear)
        # OMSetRenderTargets recibe tres argumentos: número de RTV,
        # array de RTV y DSV opcional. Omitir el tercer argumento dejaba
        # basura en el registro correspondiente y provocaba access violation.
        com_method(context, 33, None, wintypes.UINT,
                   ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)(
            context, 1, ctypes.byref(rtv), None)
        viewport = Viewport(0.0, 0.0, float(WIDTH), float(HEIGHT), 0.0, 1.0)
        com_method(context, 44, None, wintypes.UINT, ctypes.POINTER(Viewport))(
            context, 1, ctypes.byref(viewport))
        com_method(context, 17, None, ctypes.c_void_p)(context, layout)
        stride, offset = wintypes.UINT(12), wintypes.UINT(0)
        vb_arg = ctypes.c_void_p(vb.value)
        # IASetVertexBuffers(this, StartSlot, NumBuffers, ppBuffers, pStrides, pOffsets)
        com_method(context, 18, None, wintypes.UINT, wintypes.UINT,
                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
                   ctypes.POINTER(wintypes.UINT))(
            context, 0, 1, ctypes.byref(vb_arg), ctypes.byref(stride), ctypes.byref(offset))
        com_method(context, 24, None, wintypes.UINT)(
            context, D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST)
        com_method(context, 11, None, ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.UINT)(context, vs, None, 0)
        com_method(context, 9, None, ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.UINT)(context, ps, None, 0)
        com_method(context, 13, None, wintypes.UINT, wintypes.UINT)(context, 3, 0)
        logging.info("Draw(3, 0) ejecutado")

        com_method(context, 47, None, ctypes.c_void_p, ctypes.c_void_p)(
            context, staging, target)
        mapped = MappedSubresource()
        hr = com_method(context, 14, ctypes.c_long, ctypes.c_void_p, wintypes.UINT,
                        wintypes.UINT, wintypes.UINT,
                        ctypes.POINTER(MappedSubresource))(
            context, staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped))
        check_hr(hr, "ID3D11DeviceContext::Map")
        try:
            if not mapped.pData or mapped.RowPitch < WIDTH * 4:
                raise RuntimeError("Map devolvió datos/pitch inválidos")
            rows = []
            for y in range(HEIGHT):
                rows.append(ctypes.string_at(mapped.pData + y * mapped.RowPitch, WIDTH * 4))
            pixels = b"".join(rows)
        finally:
            com_method(context, 15, None, ctypes.c_void_p, wintypes.UINT)(
                context, staging, 0)

        # Verifica que el resultado contiene píxeles dibujados distintos del clear.
        colors = {pixels[i:i + 4] for i in range(0, len(pixels), 4)}
        if len(colors) < 2:
            raise RuntimeError("La imagen leída no contiene variación; el triángulo no se detectó")
        from PIL import Image
        image = Image.frombytes("RGBA", (WIDTH, HEIGHT), pixels)
        image.save(output_path)
        logging.info("Readback correcto: pitch=%d, colores=%d, PNG=%s",
                     mapped.RowPitch, len(colors), output_path)
        return len(colors)
    finally:
        for obj in (staging, rtv, target, vb, layout, ps, vs):
            release(obj)


def test_adapter(d3d11, adapter_ptr, info):
    logging.info("=" * 72)
    logging.info("Adaptador: %(name)s | LUID %(luid)s | Vendor %(vendor_id)s | Device %(device_id)s", info)
    adapter = ctypes.c_void_p(adapter_ptr)
    device = context = None
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in info["name"])
    output = OUTPUT_DIR / ("xxami_d3d11_%s.png" % safe_name[:48])
    try:
        device, context, feature = create_device(d3d11, adapter)
        logging.info("PASS: dispositivo D3D11 creado; Feature Level %s", feature)
        color_count = render_triangle(device, context, output)
        logging.info("PASS: renderizado offscreen y readback completados (%d colores)", color_count)
        return True
    except Exception as exc:
        logging.error("FAIL: %s", exc)
        logging.error("%s", traceback.format_exc())
        return False
    finally:
        release(context)
        release(device)
        release(adapter)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    logging.info("XXAMI - prueba temporal de renderizado Direct3D 11")
    logging.info("Sistema: %s | Python: %s | Arquitectura: %s",
                 sys.platform, sys.version.replace("\n", " "), struct.calcsize("P") * 8)
    if sys.platform != "win32":
        logging.error("Esta prueba requiere Windows.")
        return 2
    try:
        d3d11 = ctypes.WinDLL("d3d11.dll")
        adapters = enumerate_adapters()
        logging.info("Adaptadores físicos encontrados: %d", len(adapters))
    except Exception as exc:
        logging.exception("No se pudo preparar DXGI/D3D11: %s", exc)
        return 2

    results = []
    try:
        for adapter, info in adapters:
            results.append((info["name"], test_adapter(d3d11, adapter, info)))
    finally:
        for adapter, _ in adapters:
            # test_adapter consume/libera la referencia. Esta pasada no libera.
            pass

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    logging.info("=" * 72)
    logging.info("RESUMEN: %d correctos, %d fallidos, %d adaptadores",
                 passed, failed, len(results))
    logging.info("Registro: %s", LOG_PATH)
    return 0 if results and failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
