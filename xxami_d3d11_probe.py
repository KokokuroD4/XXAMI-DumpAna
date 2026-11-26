# -*- coding: utf-8 -*-
"""Detección nativa de adaptadores Direct3D 11 en Windows.

Este módulo solo comprueba enumeración DXGI y creación real de un dispositivo
D3D11 por adaptador. No constituye todavía un renderizador y, por tanto, sus
resultados no deben registrarse como una API de renderizado disponible.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


_DXGI_FACTORY_IID = bytes.fromhex("ec66717b c721 ae44 b21a c9ae321ae369".replace(" ", ""))
_D3D11_SDK_VERSION = 7
_D3D_DRIVER_TYPE_UNKNOWN = 0
_D3D_FEATURE_LEVELS = (0xB100, 0xB000, 0xA100, 0xA000, 0x9300, 0x9200, 0x9100)
_FEATURE_LEVEL_NAMES = {
    0xB100: "11.1", 0xB000: "11.0", 0xA100: "10.1",
    0xA000: "10.0", 0x9300: "9.3", 0x9200: "9.2", 0x9100: "9.1",
}
_DXGI_ERROR_NOT_FOUND = 0x887A0002


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DXGI_ADAPTER_DESC(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
    ]


def _com_method(instance, index, restype, *argtypes):
    """Obtiene una función de la vtable COM con la convención WINAPI."""
    if not instance:
        raise ValueError("Puntero COM nulo")
    vtable = ctypes.cast(
        instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    address = vtable[index]
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(address)


def _release(instance):
    if instance:
        try:
            _com_method(instance, 2, wintypes.ULONG)(instance)
        except Exception:
            pass


def _hresult_text(value):
    return "HRESULT 0x%08X" % (value & 0xFFFFFFFF)


def _create_factory():
    dxgi = ctypes.WinDLL("dxgi.dll")
    create = dxgi.CreateDXGIFactory
    create.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_long
    iid_buffer = ctypes.create_string_buffer(_DXGI_FACTORY_IID)
    factory = ctypes.c_void_p()
    hr = create(ctypes.byref(iid_buffer), ctypes.byref(factory))
    if hr < 0 or not factory.value:
        raise OSError("CreateDXGIFactory falló: " + _hresult_text(hr))
    return dxgi, factory


def _try_create_device(d3d11, adapter):
    create = d3d11.D3D11CreateDevice
    create.restype = ctypes.c_long
    create.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(wintypes.UINT), wintypes.UINT, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    levels_type = wintypes.UINT * len(_D3D_FEATURE_LEVELS)
    levels = levels_type(*_D3D_FEATURE_LEVELS)
    device, context = ctypes.c_void_p(), ctypes.c_void_p()
    selected_level = wintypes.UINT()

    hr = create(
        adapter, _D3D_DRIVER_TYPE_UNKNOWN, None, 0,
        levels, len(levels), _D3D11_SDK_VERSION,
        ctypes.byref(device), ctypes.byref(selected_level),
        ctypes.byref(context),
    )
    if hr < 0 and (hr & 0xFFFFFFFF) == 0x80070057:
        # Algunos runtimes antiguos no aceptan 11.1 en la lista de niveles.
        levels_legacy = levels_type(*_D3D_FEATURE_LEVELS[1:])
        hr = create(
            adapter, _D3D_DRIVER_TYPE_UNKNOWN, None, 0,
            levels_legacy, len(levels_legacy), _D3D11_SDK_VERSION,
            ctypes.byref(device), ctypes.byref(selected_level),
            ctypes.byref(context),
        )
    try:
        if hr < 0 or not device.value:
            return False, None, _hresult_text(hr)
        return True, _FEATURE_LEVEL_NAMES.get(selected_level.value,
                                               "0x%04X" % selected_level.value), ""
    finally:
        _release(context)
        _release(device)


def probe_d3d11_adapters():
    """Devuelve el resultado de probar D3D11 en cada adaptador DXGI.

    Cada entrada contiene identidad DXGI y el resultado de crear un dispositivo
    hardware D3D11 sobre ese adaptador concreto. En sistemas no Windows devuelve
    una lista vacía.
    """
    if sys.platform != "win32":
        return []

    d3d11 = ctypes.WinDLL("d3d11.dll")
    _dxgi, factory = _create_factory()
    results = []
    try:
        enum_adapters = _com_method(
            factory, 7, ctypes.c_long, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p)
        )
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            hr = enum_adapters(factory, index, ctypes.byref(adapter))
            if hr < 0:
                if (hr & 0xFFFFFFFF) == _DXGI_ERROR_NOT_FOUND:
                    break
                raise OSError("IDXGIFactory::EnumAdapters falló: " + _hresult_text(hr))
            try:
                desc = _DXGI_ADAPTER_DESC()
                get_desc = _com_method(
                    adapter, 8, ctypes.c_long,
                    ctypes.POINTER(_DXGI_ADAPTER_DESC)
                )
                hr_desc = get_desc(adapter, ctypes.byref(desc))
                if hr_desc < 0:
                    raise OSError("IDXGIAdapter::GetDesc falló: " + _hresult_text(hr_desc))

                supported, feature_level, error = _try_create_device(d3d11, adapter)
                luid = "%08X:%08X" % (
                    desc.AdapterLuid.HighPart & 0xFFFFFFFF,
                    desc.AdapterLuid.LowPart,
                )
                results.append({
                    "name": str(desc.Description),
                    "vendor_id": "0x%04X" % desc.VendorId,
                    "device_id": "0x%04X" % desc.DeviceId,
                    "luid": luid,
                    "dedicated_video_memory": int(desc.DedicatedVideoMemory),
                    "d3d11_supported": bool(supported),
                    "feature_level": feature_level,
                    "error": error,
                })
            finally:
                _release(adapter)
            index += 1
    finally:
        _release(factory)
    return results
