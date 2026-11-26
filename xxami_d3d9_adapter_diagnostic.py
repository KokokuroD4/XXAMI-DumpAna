# -*- coding: utf-8 -*-
"""Diagnóstico DXGI, monitores, D3D9 clásico/Ex y D3D9On12.

Ejecutar en Windows:
    python xxami_d3d9_adapter_diagnostic.py

No modifica la configuración del sistema. La prueba D3D9On12 crea un
ID3D12Device para cada adaptador DXGI hardware y lo pasa como override
explícito a Direct3DCreate9On12.
"""
from __future__ import annotations

import ctypes
import json
import logging
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

LOG = Path(__file__).resolve().with_name("xxami_d3d9_adapter_diagnostic.log")
D3D_SDK_VERSION = 32
D3DDEVTYPE_HAL = 1
CREATE_FLAGS = ((0x40, "hardware"), (0x20, "software"))
SWAPEFFECT_DISCARD = 1
PRESENT_INTERVAL_IMMEDIATE = 0x80000000
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_FACTORY_IID = bytes.fromhex("ec66717bc721ae44b21ac9ae321ae369")
D3D12_DEVICE_IID = bytes.fromhex("189819f11db64b57be541821339b85f7")


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MonitorInfoExW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", Rect),
                ("rcWork", Rect), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


class AdapterDesc(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
    ]


class OutputDesc(ctypes.Structure):
    _fields_ = [("DeviceName", wintypes.WCHAR * 32), ("DesktopCoordinates", Rect),
                ("AttachedToDesktop", wintypes.BOOL), ("Rotation", wintypes.UINT),
                ("Monitor", wintypes.HANDLE)]


class AdapterIdentifier9(ctypes.Structure):
    _fields_ = [
        ("Driver", ctypes.c_char * 512), ("Description", ctypes.c_char * 512),
        ("DeviceName", ctypes.c_char * 32), ("DriverVersion", ctypes.c_int64),
        ("VendorId", wintypes.DWORD), ("DeviceId", wintypes.DWORD),
        ("SubSysId", wintypes.DWORD), ("Revision", wintypes.DWORD),
        ("DeviceIdentifier", ctypes.c_byte * 16), ("WHQLLevel", wintypes.DWORD),
    ]


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


class D3D9On12Args(ctypes.Structure):
    _fields_ = [("Enable9On12", wintypes.BOOL),
                ("pD3D12Device", ctypes.c_void_p),
                ("ppD3D12Queues", ctypes.c_void_p * 2),
                ("NumQueues", wintypes.UINT), ("NodeMask", wintypes.UINT)]


def method(obj, index, restype, *argtypes):
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def release(obj):
    if obj and obj.value:
        try:
            method(obj, 2, wintypes.ULONG)(obj)
        except Exception:
            pass
        obj.value = None


def decode(value):
    return bytes(value).split(bytes((0,)), 1)[0].decode("mbcs", errors="replace").strip()


def hr(value):
    return "0x%08X" % (value & 0xFFFFFFFF)


def luid_text(value):
    return "%08X:%08X" % (value.HighPart & 0xFFFFFFFF, value.LowPart)


def present_parameters(hwnd):
    pp = PresentParameters()
    pp.BackBufferWidth = pp.BackBufferHeight = 1
    pp.BackBufferFormat = 0
    pp.BackBufferCount = 1
    pp.SwapEffect = SWAPEFFECT_DISCARD
    pp.hDeviceWindow = hwnd
    pp.Windowed = 1
    pp.EnableAutoDepthStencil = 0
    pp.PresentationInterval = PRESENT_INTERVAL_IMMEDIATE
    return pp


def monitor_details(handle):
    if not handle:
        return None
    user32 = ctypes.WinDLL("user32.dll")
    info = MonitorInfoExW()
    info.cbSize = ctypes.sizeof(info)
    get_info = user32.GetMonitorInfoW
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfoExW)]
    get_info.restype = wintypes.BOOL
    if not get_info(handle, ctypes.byref(info)):
        return {"handle": "0x%X" % (handle or 0), "error": "GetMonitorInfoW falló"}
    return {
        "handle": "0x%X" % (handle or 0),
        "device": info.szDevice,
        "primary": bool(info.dwFlags & 1),
        "rect": [info.rcMonitor.left, info.rcMonitor.top,
                 info.rcMonitor.right, info.rcMonitor.bottom],
    }


def dxgi_report():
    dxgi = ctypes.WinDLL("dxgi.dll")
    create_factory = dxgi.CreateDXGIFactory
    create_factory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create_factory.restype = ctypes.c_long
    iid = ctypes.create_string_buffer(DXGI_FACTORY_IID)
    factory = ctypes.c_void_p()
    result = create_factory(ctypes.byref(iid), ctypes.byref(factory))
    if result < 0 or not factory.value:
        return {"error": "CreateDXGIFactory " + hr(result)}
    adapters = []
    try:
        enum_adapter = method(factory, 7, ctypes.c_long, wintypes.UINT,
                              ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            result = enum_adapter(factory, index, ctypes.byref(adapter))
            if result < 0:
                if (result & 0xFFFFFFFF) == DXGI_ERROR_NOT_FOUND:
                    break
                raise OSError("EnumAdapters " + hr(result))
            try:
                desc = AdapterDesc()
                result = method(adapter, 8, ctypes.c_long,
                                ctypes.POINTER(AdapterDesc))(adapter, ctypes.byref(desc))
                if result < 0:
                    raise OSError("GetDesc " + hr(result))
                item = {
                    "name": desc.Description,
                    "vendor_id": "0x%04X" % desc.VendorId,
                    "device_id": "0x%04X" % desc.DeviceId,
                    "luid": luid_text(desc.AdapterLuid),
                    "dedicated_video_memory": int(desc.DedicatedVideoMemory),
                    "outputs": [],
                }
                enum_output = method(adapter, 7, ctypes.c_long, wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_void_p))
                out_index = 0
                while True:
                    output = ctypes.c_void_p()
                    out_hr = enum_output(adapter, out_index, ctypes.byref(output))
                    if out_hr < 0:
                        if (out_hr & 0xFFFFFFFF) == DXGI_ERROR_NOT_FOUND:
                            break
                        item["output_error"] = hr(out_hr)
                        break
                    try:
                        out_desc = OutputDesc()
                        out_hr = method(output, 7, ctypes.c_long,
                                        ctypes.POINTER(OutputDesc))(output, ctypes.byref(out_desc))
                        if out_hr >= 0:
                            item["outputs"].append({
                                "device": out_desc.DeviceName,
                                "attached_to_desktop": bool(out_desc.AttachedToDesktop),
                                "monitor": monitor_details(out_desc.Monitor),
                                "desktop_rect": [out_desc.DesktopCoordinates.left,
                                                 out_desc.DesktopCoordinates.top,
                                                 out_desc.DesktopCoordinates.right,
                                                 out_desc.DesktopCoordinates.bottom],
                            })
                    finally:
                        release(output)
                    out_index += 1
                adapters.append(item)
            finally:
                release(adapter)
            index += 1
    finally:
        release(factory)
    return {"adapter_count": len(adapters), "adapters": adapters}


def d3d9_report(use_ex=False):
    lib = ctypes.WinDLL("d3d9.dll")
    if use_ex:
        create = getattr(lib, "Direct3DCreate9Ex", None)
        if create is None:
            return {"available": False, "error": "Direct3DCreate9Ex no exportada"}
        create.argtypes = [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        d3d = ctypes.c_void_p()
        result = create(D3D_SDK_VERSION, ctypes.byref(d3d))
        if result < 0 or not d3d.value:
            return {"available": False, "create_hresult": hr(result)}
    else:
        create = lib.Direct3DCreate9
        create.argtypes = [wintypes.UINT]
        create.restype = ctypes.c_void_p
        raw = create(D3D_SDK_VERSION)
        if not raw:
            return {"error": "Direct3DCreate9 devolvió NULL"}
        d3d = ctypes.c_void_p(raw)

    output = []
    try:
        count = int(method(d3d, 4, wintypes.UINT)(d3d))
        get_id = method(d3d, 5, ctypes.c_long, wintypes.UINT, wintypes.DWORD,
                        ctypes.POINTER(AdapterIdentifier9))
        get_monitor = method(d3d, 15, wintypes.HANDLE, wintypes.UINT)
        create_index = 20 if use_ex else 16
        if use_ex:
            create_device = method(
                d3d, create_index, ctypes.c_long, wintypes.UINT, wintypes.UINT,
                wintypes.HWND, wintypes.DWORD, ctypes.POINTER(PresentParameters),
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        else:
            create_device = method(
                d3d, create_index, ctypes.c_long, wintypes.UINT, wintypes.UINT,
                wintypes.HWND, wintypes.DWORD, ctypes.POINTER(PresentParameters),
                ctypes.POINTER(ctypes.c_void_p))
        user32 = ctypes.WinDLL("user32.dll")
        user32.GetDesktopWindow.restype = wintypes.HWND
        hwnd = user32.GetDesktopWindow()
        for ordinal in range(count):
            item = {"ordinal": ordinal}
            ident = AdapterIdentifier9()
            result = get_id(d3d, ordinal, 0, ctypes.byref(ident))
            if result >= 0:
                item.update(name=decode(ident.Description), driver=decode(ident.Driver),
                            vendor_id="0x%04X" % ident.VendorId,
                            device_id="0x%04X" % ident.DeviceId,
                            subsystem_id="0x%08X" % ident.SubSysId)
            else:
                item["get_identifier_error"] = hr(result)
            monitor = get_monitor(d3d, ordinal)
            item["monitor"] = monitor_details(monitor)
            for flags, label in CREATE_FLAGS:
                pp, device = present_parameters(hwnd), ctypes.c_void_p()
                if use_ex:
                    result = create_device(d3d, ordinal, D3DDEVTYPE_HAL, hwnd, flags,
                                           ctypes.byref(pp), None, ctypes.byref(device))
                else:
                    result = create_device(d3d, ordinal, D3DDEVTYPE_HAL, hwnd, flags,
                                           ctypes.byref(pp), ctypes.byref(device))
                item["create_device_" + label] = hr(result)
                if result >= 0 and device.value:
                    item["create_device_pass"] = label
                    release(device)
                    break
            if use_ex:
                luid = LUID()
                result = method(d3d, 21, ctypes.c_long, wintypes.UINT,
                                ctypes.POINTER(LUID))(d3d, ordinal, ctypes.byref(luid))
                item["luid_hresult"] = hr(result)
                if result >= 0:
                    item["luid"] = luid_text(luid)
            output.append(item)
        return {"available": True, "adapter_count": count, "adapters": output}
    finally:
        release(d3d)


def d3d9on12_report(dxgi_adapters):
    """Intenta crear D3D9On12 con un D3D12 device explícito por GPU DXGI."""
    d3d9 = ctypes.WinDLL("d3d9.dll")
    create9on12 = getattr(d3d9, "Direct3DCreate9On12", None)
    if create9on12 is None:
        return {"available": False,
                "error": "Direct3DCreate9On12 no está exportada por d3d9.dll"}
    d3d12 = ctypes.WinDLL("d3d12.dll")
    create12 = d3d12.D3D12CreateDevice
    create12.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_void_p)]
    create12.restype = ctypes.c_long
    create9on12.argtypes = [wintypes.UINT, ctypes.POINTER(D3D9On12Args), wintypes.UINT]
    create9on12.restype = ctypes.c_void_p
    get_desktop = ctypes.WinDLL("user32.dll").GetDesktopWindow
    get_desktop.restype = wintypes.HWND
    hwnd = get_desktop()
    results = []

    for target in dxgi_adapters:
        vendor = target.get("vendor_id", "")
        if vendor == "0x1414":
            continue
        target_luid = target.get("luid")
        item = {"target_name": target.get("name"), "target_luid": target_luid}
        # Re-enumerate DXGI and retain the exact adapter whose LUID matches.
        factory_lib = ctypes.WinDLL("dxgi.dll")
        create_factory = factory_lib.CreateDXGIFactory
        create_factory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        create_factory.restype = ctypes.c_long
        iid = ctypes.create_string_buffer(DXGI_FACTORY_IID)
        factory = ctypes.c_void_p()
        result = create_factory(ctypes.byref(iid), ctypes.byref(factory))
        if result < 0 or not factory.value:
            item["status"] = "CreateDXGIFactory " + hr(result)
            results.append(item)
            continue
        d3d12_device = ctypes.c_void_p()
        d3d9_object = ctypes.c_void_p()
        try:
            enum_adapter = method(factory, 7, ctypes.c_long, wintypes.UINT,
                                  ctypes.POINTER(ctypes.c_void_p))
            index = 0
            matched = None
            while True:
                adapter = ctypes.c_void_p()
                result = enum_adapter(factory, index, ctypes.byref(adapter))
                if result < 0:
                    break
                desc = AdapterDesc()
                get_desc = method(adapter, 8, ctypes.c_long,
                                  ctypes.POINTER(AdapterDesc))
                result = get_desc(adapter, ctypes.byref(desc))
                if result >= 0 and luid_text(desc.AdapterLuid) == target_luid:
                    matched = adapter
                    break
                release(adapter)
                index += 1
            if matched is None:
                item["status"] = "No se pudo recuperar el adaptador DXGI por LUID"
                results.append(item)
                continue
            try:
                iid12 = ctypes.create_string_buffer(D3D12_DEVICE_IID)
                result = create12(matched, 0xB000, ctypes.byref(iid12),
                                  ctypes.byref(d3d12_device))
                item["d3d12_create_hresult"] = hr(result)
                if result < 0 or not d3d12_device.value:
                    item["status"] = "No se pudo crear ID3D12Device para el adaptador"
                    results.append(item)
                    continue
            finally:
                release(matched)

            args = D3D9On12Args()
            args.Enable9On12 = 1
            args.pD3D12Device = d3d12_device.value
            args.NumQueues = 0
            args.NodeMask = 0
            d3d9_object = ctypes.c_void_p(
                create9on12(D3D_SDK_VERSION, ctypes.byref(args), 1))
            if not d3d9_object.value:
                item["status"] = "Direct3DCreate9On12 devolvió NULL"
                results.append(item)
                continue

            count = int(method(d3d9_object, 4, wintypes.UINT)(d3d9_object))
            item["d3d9on12_adapter_count"] = count
            item["adapters"] = []
            item["target_adapter_found"] = False
            get_id = method(d3d9_object, 5, ctypes.c_long, wintypes.UINT,
                            wintypes.DWORD, ctypes.POINTER(AdapterIdentifier9))
            create_device = method(
                d3d9_object, 16, ctypes.c_long, wintypes.UINT, wintypes.UINT,
                wintypes.HWND, wintypes.DWORD, ctypes.POINTER(PresentParameters),
                ctypes.POINTER(ctypes.c_void_p))
            for ordinal in range(count):
                ident = AdapterIdentifier9()
                entry = {"ordinal": ordinal}
                result = get_id(d3d9_object, ordinal, 0, ctypes.byref(ident))
                if result >= 0:
                    entry.update(name=decode(ident.Description),
                                 vendor_id="0x%04X" % ident.VendorId,
                                 device_id="0x%04X" % ident.DeviceId)
                    is_target = (
                        entry["vendor_id"] == target.get("vendor_id") and
                        entry["device_id"] == target.get("device_id")
                    )
                else:
                    is_target = False
                    entry["get_identifier_error"] = hr(result)
                if is_target:
                    item["target_adapter_found"] = True
                    pp, device = present_parameters(hwnd), ctypes.c_void_p()
                    result = create_device(d3d9_object, ordinal, D3DDEVTYPE_HAL,
                                           hwnd, 0x40, ctypes.byref(pp),
                                           ctypes.byref(device))
                    entry["create_device_hardware"] = hr(result)
                    if result >= 0 and device.value:
                        entry["create_device_pass"] = "hardware"
                        release(device)
                item["adapters"].append(entry)
            if item["target_adapter_found"]:
                item["status"] = "Adaptador objetivo enumerado; CreateDevice probado"
            else:
                item["status"] = ("El adaptador objetivo no aparece en la enumeración "
                                  "D3D9On12; no se atribuye el dispositivo a esa GPU")
            results.append(item)
        except Exception as exc:
            item["status"] = "EXCEPTION: " + repr(exc)
            results.append(item)
        finally:
            release(d3d9_object)
            release(d3d12_device)
            release(factory)
    return {"available": True, "targets": results}


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("XXAMI")
    log.info("XXAMI - diagnóstico DXGI / monitores / D3D9 / D3D9Ex / D3D9On12")
    if sys.platform != "win32":
        log.error("Esta prueba requiere Windows")
        return 1
    try:
        dxgi = dxgi_report()
        classic = d3d9_report(False)
        ex = d3d9_report(True)
        dxgi_adapters = dxgi.get("adapters", []) if isinstance(dxgi, dict) else []
        on12 = d3d9on12_report(dxgi_adapters)
        report = {"dxgi": dxgi, "d3d9_classic": classic,
                  "d3d9_ex": ex, "d3d9_on12": on12}
        log.info("DXGI + salidas: %s", json.dumps(dxgi, ensure_ascii=False))
        log.info("D3D9 + monitores: %s", json.dumps(classic, ensure_ascii=False))
        log.info("D3D9Ex + LUID + monitores: %s", json.dumps(ex, ensure_ascii=False))
        log.info("D3D9On12 por GPU DXGI: %s", json.dumps(on12, ensure_ascii=False))
        log.info("INFORME JSON COMPLETO: %s", json.dumps(report, ensure_ascii=False))
        log.info("Adjunta este log completo para evaluar el mapeo de GPU.")
        return 0
    except Exception:
        log.error("ERROR inesperado:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
