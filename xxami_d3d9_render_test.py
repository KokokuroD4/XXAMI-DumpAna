# -*- coding: utf-8 -*-
"""Prueba real de renderizado Direct3D 9 (geometría, textura, profundidad y readback).

Ejecutar en Windows:
    python xxami_d3d9_render_test.py

Genera una PNG y xxami_d3d9_render_test.log junto al script.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

LOG = Path(__file__).resolve().with_name("xxami_d3d9_render_test.log")
OUT = LOG.parent

D3D_SDK_VERSION = 32
D3DDEVTYPE_HAL = 1
D3DSWAPEFFECT_DISCARD = 1
D3DFMT_A8R8G8B8 = 21
D3DFMT_D24S8 = 75
D3DPOOL_DEFAULT = 0
D3DPOOL_MANAGED = 1
D3DUSAGE_RENDERTARGET = 1
D3DUSAGE_DEPTHSTENCIL = 2
D3DCREATE_HARDWARE_VERTEXPROCESSING = 0x40
D3DCREATE_SOFTWARE_VERTEXPROCESSING = 0x20
D3DPRESENT_INTERVAL_IMMEDIATE = 0x80000000
D3DCLEAR_TARGET = 1
D3DCLEAR_ZBUFFER = 2
D3DLOCK_READONLY = 0x10
D3DLOCK_DISCARD = 0x2000
D3DPT_TRIANGLELIST = 4
D3DFVF_XYZRHW = 0x004
D3DFVF_DIFFUSE = 0x040
D3DFVF_TEX1 = 0x100
D3DTSS_COLOROP = 1
D3DTSS_COLORARG1 = 2
D3DTSS_ALPHAOP = 4
D3DTSS_ALPHAARG1 = 5
D3DTOP_SELECTARG1 = 2
D3DTA_TEXTURE = 2
D3DSAMP_MINFILTER = 6
D3DSAMP_MAGFILTER = 5
D3DTEXF_POINT = 1
D3DRS_ZENABLE = 7
D3DRS_ZWRITEENABLE = 14
D3DRS_LIGHTING = 137
D3DRS_CULLMODE = 22
D3DCULL_NONE = 1


class PresentParameters(ctypes.Structure):
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


class LockedRect(ctypes.Structure):
    _fields_ = [("Pitch", ctypes.c_int), ("pBits", ctypes.c_void_p)]


class Vertex(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float), ("y", ctypes.c_float),
        ("z", ctypes.c_float), ("rhw", ctypes.c_float),
        ("diffuse", wintypes.DWORD),
        ("u", ctypes.c_float), ("v", ctypes.c_float),
    ]


def method(obj, index, restype, *argtypes):
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def release(obj):
    if obj and obj.value:
        method(obj, 2, wintypes.ULONG)(obj)
        obj.value = None


def check(hr, label):
    if hr < 0:
        raise RuntimeError("%s: HRESULT 0x%08X" % (label, hr & 0xFFFFFFFF))


def make_quad(width, height, z, u):
    left, right = width * 0.15, width * 0.85
    top, bottom = height * 0.15, height * 0.85
    # D3D9 XYZRHW usa coordenadas de pantalla y profundidad [0,1].
    points = [
        (left, top, u, 0.5), (right, top, u, 0.5), (right, bottom, u, 0.5),
        (left, top, u, 0.5), (right, bottom, u, 0.5), (left, bottom, u, 0.5),
    ]
    return [Vertex(x, y, z, 1.0, 0xFFFFFFFF, tu, tv) for x, y, tu, tv in points]


def run_adapter(adapter):
    d3d_lib = ctypes.WinDLL("d3d9.dll")
    create9 = d3d_lib.Direct3DCreate9
    create9.argtypes = [wintypes.UINT]
    create9.restype = ctypes.c_void_p
    raw = create9(D3D_SDK_VERSION)
    if not raw:
        raise RuntimeError("Direct3DCreate9 devolvió NULL")
    d3d = ctypes.c_void_p(raw)
    device = ctypes.c_void_p()
    texture = ctypes.c_void_p()
    readback = ctypes.c_void_p()
    try:
        get_desktop = ctypes.WinDLL("user32.dll").GetDesktopWindow
        get_desktop.argtypes = []
        get_desktop.restype = wintypes.HWND
        hwnd = get_desktop()
        width, height = 320, 240
        pp = PresentParameters()
        pp.BackBufferWidth = width
        pp.BackBufferHeight = height
        pp.BackBufferFormat = D3DFMT_A8R8G8B8
        pp.BackBufferCount = 1
        pp.SwapEffect = D3DSWAPEFFECT_DISCARD
        pp.hDeviceWindow = hwnd
        pp.Windowed = 1
        pp.EnableAutoDepthStencil = 1
        pp.AutoDepthStencilFormat = D3DFMT_D24S8
        pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE

        create_device = method(
            d3d, 16, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.HWND, wintypes.DWORD, ctypes.POINTER(PresentParameters),
            ctypes.POINTER(ctypes.c_void_p))
        last_hr = None
        for flags in (D3DCREATE_HARDWARE_VERTEXPROCESSING,
                      D3DCREATE_SOFTWARE_VERTEXPROCESSING):
            hr = create_device(d3d, int(adapter["adapter_ordinal"]), D3DDEVTYPE_HAL,
                               hwnd, flags, ctypes.byref(pp), ctypes.byref(device))
            if hr >= 0 and device.value:
                break
            last_hr = hr
        else:
            raise RuntimeError("CreateDevice falló: HRESULT 0x%08X" % (last_hr & 0xFFFFFFFF))

        create_texture = method(
            device, 23, ctypes.c_long, wintypes.UINT, wintypes.UINT, wintypes.UINT,
            wintypes.DWORD, wintypes.UINT, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
        check(create_texture(device, 2, 1, 1, 0, D3DFMT_A8R8G8B8,
                             D3DPOOL_MANAGED, ctypes.byref(texture), None),
              "CreateTexture")

        lock_texture = method(texture, 19, ctypes.c_long, wintypes.UINT,
                              ctypes.POINTER(LockedRect), ctypes.c_void_p, wintypes.DWORD)
        unlock_texture = method(texture, 20, ctypes.c_long, wintypes.UINT)
        locked = LockedRect()
        check(lock_texture(texture, 0, ctypes.byref(locked), None, 0), "Texture LockRect")
        # Memoria A8R8G8B8 en little-endian: bytes BGRA.
        ctypes.memmove(locked.pBits, bytes((0, 0, 255, 255, 0, 255, 0, 255)), 8)
        check(unlock_texture(texture, 0), "Texture UnlockRect")

        set_render_state = method(device, 57, ctypes.c_long, wintypes.UINT, wintypes.DWORD)
        set_texture = method(device, 65, ctypes.c_long, wintypes.UINT, ctypes.c_void_p)
        set_texture_stage = method(device, 67, ctypes.c_long, wintypes.UINT,
                                   wintypes.UINT, wintypes.DWORD)
        set_sampler = method(device, 69, ctypes.c_long, wintypes.UINT,
                             wintypes.UINT, wintypes.DWORD)
        set_fvf = method(device, 89, ctypes.c_long, wintypes.DWORD)
        clear = method(device, 43, ctypes.c_long, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, ctypes.c_float, wintypes.DWORD)
        begin_scene = method(device, 41, ctypes.c_long)
        end_scene = method(device, 42, ctypes.c_long)
        draw_up = method(device, 83, ctypes.c_long, wintypes.UINT, wintypes.UINT,
                         ctypes.c_void_p, wintypes.UINT, wintypes.DWORD)

        for state, value in ((D3DRS_ZENABLE, 1), (D3DRS_ZWRITEENABLE, 1),
                             (D3DRS_LIGHTING, 0), (D3DRS_CULLMODE, D3DCULL_NONE)):
            check(set_render_state(device, state, value), "SetRenderState(%d)" % state)
        check(set_texture(device, 0, texture), "SetTexture")
        for state, value in ((D3DTSS_COLOROP, D3DTOP_SELECTARG1),
                             (D3DTSS_COLORARG1, D3DTA_TEXTURE),
                             (D3DTSS_ALPHAOP, D3DTOP_SELECTARG1),
                             (D3DTSS_ALPHAARG1, D3DTA_TEXTURE)):
            check(set_texture_stage(device, 0, state, value), "SetTextureStageState")
        for state in (D3DSAMP_MINFILTER, D3DSAMP_MAGFILTER):
            check(set_sampler(device, 0, state, D3DTEXF_POINT), "SetSamplerState")
        check(set_fvf(device, D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1), "SetFVF")

        check(clear(device, 0, None, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER,
                    0xFF202020, 1.0, 0), "Clear")
        check(begin_scene(device), "BeginScene")
        # Primero el quad cercano (texel rojo), después el lejano (verde).
        # El depth test debe impedir que el segundo sobrescriba el primero.
        for z, u in ((0.2, 0.25), (0.8, 0.75)):
            vertices = (Vertex * 6)(*make_quad(width, height, z, u))
            check(draw_up(device, D3DPT_TRIANGLELIST, 2,
                          ctypes.cast(vertices, ctypes.c_void_p),
                          ctypes.sizeof(Vertex), 0), "DrawPrimitiveUP")
        check(end_scene(device), "EndScene")

        create_surface = method(
            device, 36, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p)
        check(create_surface(device, width, height, D3DFMT_A8R8G8B8,
                             2, ctypes.byref(readback), None),
              "CreateOffscreenPlainSurface")
        get_target = method(device, 38, ctypes.c_long, wintypes.UINT,
                            ctypes.POINTER(ctypes.c_void_p))
        backbuffer = ctypes.c_void_p()
        check(get_target(device, 0, ctypes.byref(backbuffer)), "GetRenderTarget")
        try:
            get_data = method(device, 32, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
            check(get_data(device, backbuffer, readback), "GetRenderTargetData")
        finally:
            release(backbuffer)

        lock_surface = method(readback, 13, ctypes.c_long, ctypes.POINTER(LockedRect),
                              ctypes.c_void_p, wintypes.DWORD)
        unlock_surface = method(readback, 14, ctypes.c_long)
        mapped = LockedRect()
        check(lock_surface(readback, ctypes.byref(mapped), None, D3DLOCK_READONLY),
              "Readback LockRect")
        try:
            from PIL import Image
            import numpy as np
            raw_bytes = ctypes.string_at(mapped.pBits, mapped.Pitch * height)
            bgra = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(height, mapped.Pitch)[:, :width * 4]
            rgba = bgra.reshape(height, width, 4)[:, :, [2, 1, 0, 3]].copy()
            image = Image.fromarray(rgba, "RGBA").convert("RGB")
        finally:
            check(unlock_surface(readback), "Readback UnlockRect")

        center = image.getpixel((width // 2, height // 2))
        colors = len(set(image.getdata()))
        if colors < 2:
            raise RuntimeError("Readback sin variación visible: %d colores" % colors)
        if not (center[0] > center[1] * 1.5 and center[0] > center[2] * 1.5):
            raise RuntimeError("Textura/profundidad incorrecta en centro: RGB=%r" % (center,))
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in adapter["name"])
        output = OUT / ("xxami_d3d9_render_%s.png" % safe[:48])
        image.save(output)
        return {"image": str(output), "size": image.size, "center": center, "colors": colors}
    finally:
        release(readback)
        release(texture)
        release(device)
        release(d3d)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG, mode="w", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("XXAMI")
    log.info("XXAMI - prueba de renderizado Direct3D 9")
    if sys.platform != "win32":
        log.error("Esta prueba requiere Windows")
        return 2
    try:
        from xxami_d3d9_probe import probe_d3d9_adapters
        adapters = [a for a in probe_d3d9_adapters() if a.get("d3d9_supported")]
        log.info("Adaptadores HAL DX9 disponibles: %d", len(adapters))
        passed = failed = 0
        for adapter in adapters:
            log.info("GPU: %s | ordinal=%s | VP=%s", adapter["name"],
                     adapter["adapter_ordinal"], adapter["vertex_processing"])
            try:
                result = run_adapter(adapter)
                passed += 1
                log.info("PASS geometría + textura + profundidad: centro RGB=%s | colores=%d",
                         result["center"], result["colors"])
                log.info("PASS readback: %s | tamaño=%s", result["image"], result["size"])
            except Exception as exc:
                failed += 1
                log.error("FAIL %s: %s", adapter["name"], exc)
                log.error("%s", traceback.format_exc())
        log.info("RESUMEN: %d correctos, %d fallidos", passed, failed)
        log.info("Registro: %s", LOG)
        return 0 if passed and not failed else 1
    except Exception:
        log.error("ERROR inesperado:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
