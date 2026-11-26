# -*- coding: utf-8 -*-
"""Prueba del backend D3D11 de XXAMI sobre cada adaptador físico.

Ejecutar en Windows:
    python xxami_d3d11_backend_test.py

Genera PNG y xxami_d3d11_backend_test.log junto al script.
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

LOG = Path(__file__).resolve().with_name("xxami_d3d11_backend_test.log")
OUT = LOG.parent


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG, mode="w", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    logging.info("XXAMI - prueba del backend D3D11")
    if sys.platform != "win32":
        logging.error("Esta prueba requiere Windows")
        return 2

    import numpy as np
    from PIL import Image
    from xxami_d3d11_probe import probe_d3d11_adapters
    from xxami_render_backend import create_backend

    adapters = [a for a in probe_d3d11_adapters()
                if a.get("d3d11_supported") and
                not (a.get("vendor_id") == "0x1414" and a.get("device_id") == "0x008C")]
    logging.info("Adaptadores físicos D3D11: %d", len(adapters))

    # Dos cuadriláteros coplanares en pantalla, pero a distinta profundidad.
    # El frontal se dibuja primero; el posterior después. El depth test debe
    # conservar el frontal. Sus UV constantes seleccionan texeles distintos.
    quad = [[-0.8, -0.7], [0.8, -0.7], [0.8, 0.7], [-0.8, 0.7]]
    positions = np.asarray(
        [[x, y, -0.25] for x, y in quad] +
        [[x, y, 0.25] for x, y in quad], dtype=np.float32)
    uvs = np.asarray([[0.25, 0.25]] * 4 + [[0.75, 0.75]] * 4, dtype=np.float32)
    triangles = np.asarray([
        [0, 1, 2], [0, 2, 3],
        [4, 5, 6], [4, 6, 7],
    ], dtype=np.uint32)
    texture = Image.new("RGBA", (2, 2))
    texture.putdata([
        (255, 0, 0, 255), (0, 255, 0, 255),
        (0, 0, 255, 255), (255, 255, 0, 255),
    ])

    results = []
    for adapter in adapters:
        name = adapter["name"]
        # Usa la misma fábrica que empleará el visor; así se prueba también
        # el registro interno y el contrato común RenderBackend.
        backend = create_backend("d3d11", name)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        output = OUT / ("xxami_d3d11_backend_%s.png" % safe[:48])
        try:
            info = backend.initialize()
            logging.info("PASS device: %s | Feature Level %s | LUID %s",
                         info.get("renderer"), info.get("feature_level"), info.get("luid"))
            image = backend.render_image(
                positions, uvs, triangles, texture, 320, 240,
                rot_x=0.0, rot_y=0.0, zoom=1.0, pan_x=0.0, pan_y=0.0)
            image.save(output)
            colors = len(set(image.convert("RGB").getdata()))
            center = image.convert("RGB").getpixel((160, 120))
            if colors < 2:
                raise RuntimeError("El readback no contiene variación visible")
            # El cuadrilátero frontal usa el texel rojo. Si el posterior,
            # dibujado después, lo tapa, el test de profundidad debe fallar.
            if not (center[0] > center[1] * 1.5 and center[0] > center[2] * 1.5):
                raise RuntimeError("Falló textura/profundidad: píxel central inesperado %r" % (center,))
            logging.info("PASS textura+profundidad: centro RGB=%s | colores=%d",
                         center, colors)
            resized = backend.render_image(
                positions, uvs, triangles, texture, 400, 300,
                rot_x=0.0, rot_y=0.0, zoom=1.0, pan_x=0.0, pan_y=0.0)
            resize_output = OUT / ("xxami_d3d11_backend_%s_resize.png" % safe[:40])
            resized.save(resize_output)
            if resized.size != (400, 300):
                raise RuntimeError("El redimensionado no produjo 400x300")
            logging.info("PASS resize: %s | tamaño=%s", resize_output, resized.size)
            logging.info("PASS render: %s | tamaño=%s | colores=%d",
                         output, image.size, colors)
            results.append((name, True))
        except Exception as exc:
            logging.error("FAIL %s: %s", name, exc)
            logging.error("%s", traceback.format_exc())
            results.append((name, False))
        finally:
            backend.close()

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    logging.info("RESUMEN: %d correctos, %d fallidos", passed, failed)
    logging.info("Registro: %s", LOG)
    return 0 if results and failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
