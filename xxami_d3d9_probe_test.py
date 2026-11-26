# -*- coding: utf-8 -*-
"""Prueba de enumeración y creación de dispositivos Direct3D 9.

Ejecutar en Windows:
    python xxami_d3d9_probe_test.py

Guarda xxami_d3d9_probe_test.log junto al script.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

LOG = Path(__file__).resolve().with_name("xxami_d3d9_probe_test.log")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("XXAMI")
    log.info("XXAMI - prueba de detección Direct3D 9")
    if sys.platform != "win32":
        log.error("Direct3D 9 solo está disponible en Windows")
        return 1
    try:
        from xxami_d3d9_probe import probe_d3d9_adapters
        adapters = probe_d3d9_adapters()
        log.info("Adaptadores Direct3D 9 enumerados: %d", len(adapters))
        passed = 0
        failed = 0
        for adapter in adapters:
            log.info("Adaptador: %s | Vendor %s | Device %s | Driver %s",
                     adapter.get("name"), adapter.get("vendor_id"),
                     adapter.get("device_id"), adapter.get("driver"))
            if adapter.get("d3d9_supported"):
                passed += 1
                log.info("PASS CreateDevice HAL | vertex processing: %s",
                         adapter.get("vertex_processing"))
            else:
                failed += 1
                log.error("FAIL CreateDevice HAL | %s", adapter.get("error"))
        log.info("RESULTADO JSON: %s", json.dumps(adapters, ensure_ascii=False))
        log.info("RESUMEN: %d correctos, %d fallidos", passed, failed)
        return 0 if passed else 1
    except Exception:
        log.error("ERROR inesperado:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
