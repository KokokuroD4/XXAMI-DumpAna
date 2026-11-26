# -*- coding: utf-8 -*-
"""Diagnóstico de adaptadores gráficos de Windows y HALs WGPU para XXAMI.

Ejecutar desde el entorno Python usado por XXAMI:
    python xxami_gpu_diagnostic.py

Genera xxami_gpu_diagnostic.json en el directorio actual. No modifica
preferencias ni archivos de configuración del visor.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

MARKER = "XXAMI_GPU_DIAGNOSTIC="
HALS = {
    "vulkan": ("Vulkan", "Vulkan"),
    "dx12": ("D3D12", "DX12"),
    "wgpu-opengl": ("OpenGL", "GL"),
}


def _text(value):
    return str(value or "").strip()


def _probe_hal(backend_id):
    env_backend, hal_name = HALS[backend_id]
    os.environ["WGPU_BACKEND_TYPE"] = env_backend
    try:
        import wgpu
        from wgpu.backends.wgpu_native.extras import set_instance_extras

        set_instance_extras(backends=[hal_name])
        adapters = wgpu.gpu.enumerate_adapters_sync()
        results = []
        for index, adapter in enumerate(adapters):
            info = dict(adapter.info)
            record = {
                "index": index,
                "device": _text(info.get("device")),
                "description": _text(info.get("description")),
                "summary": _text(adapter.summary),
                "vendor": _text(info.get("vendor")),
                "vendor_id": _text(info.get("vendor_id")),
                "device_id": _text(info.get("device_id")),
                "backend_type": _text(info.get("backend_type")),
                "adapter_type": _text(info.get("adapter_type")),
                "is_fallback_adapter": bool(info.get("is_fallback_adapter", False)),
                "device_creation": "not_tested",
            }
            try:
                device = adapter.request_device_sync()
                record["device_creation"] = "success"
                destroy = getattr(device, "destroy", None)
                if callable(destroy):
                    destroy()
            except Exception as exc:
                record["device_creation"] = "failed"
                record["device_error"] = _text(exc)[:1200]
            results.append(record)
        return {"hal": backend_id, "adapters": results}
    except Exception as exc:
        return {"hal": backend_id, "error": _text(exc)[:1600], "adapters": []}


def _windows_gpus():
    if sys.platform != "win32":
        return {"available": False, "reason": "Este inventario detallado requiere Windows."}
    ps = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,VideoProcessor,DriverVersion,PNPDeviceID | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if proc.returncode != 0:
            return {"available": False, "error": _text(proc.stderr)[:1200]}
        raw = json.loads(proc.stdout or "[]")
        if isinstance(raw, dict):
            raw = [raw]
        result = []
        for item in raw:
            pnp = _text(item.get("PNPDeviceID"))
            ids = {}
            for key in ("VEN", "DEV", "SUBSYS", "REV"):
                match = re.search(r"(?:^|[\\\\&])" + key + r"_([0-9A-Fa-f]+)", pnp, re.I)
                if match:
                    ids[key.lower()] = match.group(1).upper()
            result.append({
                "name": _text(item.get("Name")),
                "manufacturer": _text(item.get("AdapterCompatibility")),
                "video_processor": _text(item.get("VideoProcessor")),
                "driver_version": _text(item.get("DriverVersion")),
                "pci_ids": ids,
            })
        return {"available": True, "adapters": result}
    except Exception as exc:
        return {"available": False, "error": _text(exc)[:1200]}


def _worker(backend_id):
    print(MARKER + json.dumps(_probe_hal(backend_id), ensure_ascii=False))


def _run_hal_worker(script, backend_id):
    env_backend, _ = HALS[backend_id]
    env = os.environ.copy()
    env["WGPU_BACKEND_TYPE"] = env_backend
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--probe", backend_id],
            capture_output=True, text=True, timeout=50, check=False, env=env,
        )
        for line in reversed((proc.stdout or "").splitlines()):
            if line.startswith(MARKER):
                return json.loads(line[len(MARKER):])
        return {
            "hal": backend_id,
            "error": (_text(proc.stderr) or _text(proc.stdout) or
                      "El proceso de sondeo no devolvió resultados.")[:1600],
            "return_code": proc.returncode,
            "adapters": [],
        }
    except Exception as exc:
        return {"hal": backend_id, "error": _text(exc)[:1200], "adapters": []}


def _main():
    script = Path(__file__).resolve()
    try:
        wgpu_version = metadata.version("wgpu")
    except metadata.PackageNotFoundError:
        wgpu_version = None
    report = {
        "schema_version": 1,
        "environment": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "python_executable": Path(sys.executable).name,
            "wgpu_version": wgpu_version,
        },
        "windows_video_controllers": _windows_gpus(),
        "wgpu_hal_probes": [
            _run_hal_worker(script, backend_id) for backend_id in HALS
        ],
    }
    output = Path.cwd() / "xxami_gpu_diagnostic.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Diagnóstico guardado en:", output)
    print("Adaptadores Windows:", len(report["windows_video_controllers"].get("adapters", [])))
    for result in report["wgpu_hal_probes"]:
        adapters = result.get("adapters", [])
        print(f"{result['hal']}: {len(adapters)} adaptador(es) enumerado(s)")
        for adapter in adapters:
            print(
                "  -", adapter.get("device") or adapter.get("description") or adapter.get("summary"),
                "| vendor_id:", adapter.get("vendor_id"),
                "| device_id:", adapter.get("device_id"),
                "| device:", adapter.get("device_creation"),
            )
        if result.get("error"):
            print("  Error:", result["error"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe" and sys.argv[2] in HALS:
        _worker(sys.argv[2])
    else:
        _main()
