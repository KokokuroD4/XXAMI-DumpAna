# -*- coding: utf-8 -*-
"""Detección nativa de dispositivos Direct3D 9 por adaptador en Windows.

La sonda enumera los adaptadores Direct3D 9 y prueba CreateDevice en cada uno.
No implementa un renderizador y sus resultados no deben anunciarse como backend
hasta que exista y se valide un pipeline DX9 completo.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


_D3D_SDK_VERSION = 32
_D3DDEVTYPE_HAL = 1
_D3DCREATE_HARDWARE_VERTEXPROCESSING = 0x00000040
_D3DCREATE_SOFTWARE_VERTEXPROCESSING = 0x00000020
_D3DSWAPEFFECT_DISCARD = 1
_D3DPRESENT_INTERVAL_IMMEDIATE = 0x80000000


class _D3DAdapterIdentifier9(ctypes.Structure):
    _fields_ = [
        ("Driver", ctypes.c_char * 512),
        ("Description", ctypes.c_char * 512),
        ("DeviceName", ctypes.c_char * 32),
        ("DriverVersion", ctypes.c_int64),
        ("VendorId", wintypes.DWORD),
        ("DeviceId", wintypes.DWORD),
        ("SubSysId", wintypes.DWORD),
        ("Revision", wintypes.DWORD),
        ("DeviceIdentifier", ctypes.c_byte * 16),
        ("WHQLLevel", wintypes.DWORD),
    ]


class _D3DPresentParameters(ctypes.Structure):
    _fields_ = [
        ("BackBufferWidth", wintypes.UINT),
        ("BackBufferHeight", wintypes.UINT),
        ("BackBufferFormat", wintypes.UINT),
        ("BackBufferCount", wintypes.UINT),
        ("MultiSampleType", wintypes.UINT),
        ("MultiSampleQuality", wintypes.DWORD),
        ("SwapEffect", wintypes.UINT),
        ("hDeviceWindow", wintypes.HWND),
        ("Windowed", wintypes.BOOL),
        ("EnableAutoDepthStencil", wintypes.BOOL),
        ("AutoDepthStencilFormat", wintypes.UINT),
        ("Flags", wintypes.DWORD),
        ("FullScreen_RefreshRateInHz", wintypes.UINT),
        ("PresentationInterval", wintypes.UINT),
    ]


def _method(instance, index, restype, *argtypes):
    table = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    address = table[index]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(address)


def _release(instance):
    if instance and instance.value:
        try:
            _method(instance, 2, wintypes.ULONG)(instance)
        except Exception:
            pass
        instance.value = None


def _decode(value):
    return bytes(value).split(bytes((0,)), 1)[0].decode("mbcs", errors="replace").strip()


def probe_d3d9_adapters():
    """Devuelve información de adaptadores con un dispositivo HAL D3D9 creado."""
    if sys.platform != "win32":
        return []

    d3d9 = ctypes.WinDLL("d3d9.dll")
    create9 = d3d9.Direct3DCreate9
    create9.argtypes = [wintypes.UINT]
    create9.restype = ctypes.c_void_p
    raw = create9(_D3D_SDK_VERSION)
    if not raw:
        return []
    d3d = ctypes.c_void_p(raw)
    results = []
    try:
        count = _method(d3d, 4, wintypes.UINT)(d3d)
        get_identifier = _method(
            d3d, 5, ctypes.c_long, wintypes.UINT, wintypes.DWORD,
            ctypes.POINTER(_D3DAdapterIdentifier9)
        )
        create_device = _method(
            d3d, 16, ctypes.c_long, wintypes.UINT, wintypes.UINT,
            wintypes.HWND, wintypes.DWORD,
            ctypes.POINTER(_D3DPresentParameters), ctypes.POINTER(ctypes.c_void_p)
        )
        get_desktop = ctypes.WinDLL("user32.dll").GetDesktopWindow
        get_desktop.argtypes = []
        get_desktop.restype = wintypes.HWND
        hwnd = get_desktop()

        for ordinal in range(int(count)):
            identifier = _D3DAdapterIdentifier9()
            result = {
                "adapter_ordinal": ordinal,
                "name": "",
                "driver": "",
                "vendor_id": "",
                "device_id": "",
                "d3d9_supported": False,
                "vertex_processing": "",
                "error": "",
            }
            try:
                hr = get_identifier(d3d, ordinal, 0, ctypes.byref(identifier))
                if hr < 0:
                    raise OSError("GetAdapterIdentifier HRESULT 0x%08X" % (hr & 0xFFFFFFFF))
                result.update({
                    "name": _decode(identifier.Description),
                    "driver": _decode(identifier.Driver),
                    "vendor_id": "0x%04X" % identifier.VendorId,
                    "device_id": "0x%04X" % identifier.DeviceId,
                })

                last_error = None
                for flags, label in (
                    (_D3DCREATE_HARDWARE_VERTEXPROCESSING, "hardware"),
                    (_D3DCREATE_SOFTWARE_VERTEXPROCESSING, "software"),
                ):
                    params = _D3DPresentParameters()
                    params.BackBufferWidth = 1
                    params.BackBufferHeight = 1
                    params.BackBufferFormat = 0  # D3DFMT_UNKNOWN en modo ventana
                    params.BackBufferCount = 1
                    params.MultiSampleType = 0
                    params.SwapEffect = _D3DSWAPEFFECT_DISCARD
                    params.hDeviceWindow = hwnd
                    params.Windowed = 1
                    params.EnableAutoDepthStencil = 0
                    params.PresentationInterval = _D3DPRESENT_INTERVAL_IMMEDIATE
                    device = ctypes.c_void_p()
                    hr = create_device(
                        d3d, ordinal, _D3DDEVTYPE_HAL, hwnd, flags,
                        ctypes.byref(params), ctypes.byref(device)
                    )
                    if hr >= 0 and device.value:
                        result["d3d9_supported"] = True
                        result["vertex_processing"] = label
                        _release(device)
                        break
                    last_error = "CreateDevice(%s) HRESULT 0x%08X" % (
                        label, hr & 0xFFFFFFFF
                    )
                if not result["d3d9_supported"]:
                    result["error"] = last_error or "CreateDevice no devolvió dispositivo"
            except Exception as exc:
                result["error"] = str(exc)
            results.append(result)
        return results
    finally:
        _release(d3d)
