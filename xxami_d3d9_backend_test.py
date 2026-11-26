# -*- coding: utf-8 -*-
"""Prueba del backend Direct3D 9 de XXAMI: geometría indexada, textura, Z y readback.

Ejecutar en Windows desde la raíz del repositorio:
    python xxami_d3d9_backend_test.py
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

LOG = Path(__file__).resolve().with_name("xxami_d3d9_backend_test.log")
OUT = LOG.parent


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG, mode="w", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("XXAMI")
    log.info("XXAMI - prueba del backend Direct3D 9")
    if sys.platform != "win32":
        log.error("Esta prueba requiere Windows")
        return 2

    backend = None
    try:
        import numpy as np
        from PIL import Image
        from xxami_render_backend import create_backend

        backend = create_backend("d3d9", "default")
        info = backend.initialize()
        log.info("PASS inicialización: %s | ordinal=%s | VP=%s",
                 info.get("renderer"), info.get("adapter_ordinal"),
                 info.get("vertex_processing"))

        # Dos quads coplanares en XY, pero separados en Z. El rojo está delante;
        # el verde se dibuja después y debe quedar oculto por la prueba de profundidad.
        positions = np.asarray([
            [-1, -1, -0.2], [1, -1, -0.2], [1, 1, -0.2], [-1, 1, -0.2],
            [-1, -1,  0.2], [1, -1,  0.2], [1, 1,  0.2], [-1, 1,  0.2],
        ], dtype=np.float32)
        uvs = np.asarray([
            [0.25, 0.5], [0.25, 0.5], [0.25, 0.5], [0.25, 0.5],
            [0.75, 0.5], [0.75, 0.5], [0.75, 0.5], [0.75, 0.5],
        ], dtype=np.float32)
        triangles = np.asarray([
            [0, 1, 2], [0, 2, 3],
            [4, 5, 6], [4, 6, 7],
        ], dtype=np.uint32)
        texture = Image.new("RGBA", (2, 1))
        texture.putdata([(255, 0, 0, 255), (0, 255, 0, 255)])

        image = backend.render_image(
            positions, uvs, triangles, texture, 320, 240,
            rot_x=0.0, rot_y=0.0, zoom=1.0, pan_x=0.0, pan_y=0.0
        ).convert("RGB")
        center = image.getpixel((160, 120))
        colors = len(set(image.getdata()))
        if colors < 2:
            raise RuntimeError("La imagen recuperada no contiene variación visible")
        if not (center[0] > center[1] * 1.5 and center[0] > center[2] * 1.5):
            raise RuntimeError("Textura/profundidad incorrecta en centro: RGB=%r" % (center,))

        output = OUT / "xxami_d3d9_backend_test.png"
        image.save(output)
        log.info("PASS geometría indexada + textura + profundidad: centro RGB=%s | colores=%d",
                 center, colors)
        log.info("PASS readback: %s | tamaño=%s", output, image.size)
        log.info("RESUMEN: 1 correcto, 0 fallidos")
        return 0
    except Exception as exc:
        log.error("FAIL backend DX9: %s", exc)
        log.error("%s", traceback.format_exc())
        log.info("RESUMEN: 0 correctos, 1 fallido")
        return 1
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception:
                log.exception("Error liberando backend DX9")


if __name__ == "__main__":
    raise SystemExit(main())
