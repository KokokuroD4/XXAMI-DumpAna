# -*- coding: utf-8 -*-
"""
ktx2_util.py -- lectura de texturas KTX2 (el formato en que el generador vuelca ahora las
texturas) y creación de reemplazos con ktx.exe de KTX-Software. Sin Tkinter.

Lectura:  cabecera (80 bytes) + índice de niveles. El generador escribe SIN supercompresión,
          pero se aceptan también zlib (nativo) y zstd (si está instalado el paquete
          'zstandard'). BasisLZ no se puede leer.
Creación: `ktx create --format <VkFormat> ... entrada.png salida.ktx2` y después se VALIDA que el
          resultado sea inyectable (mismo VkFormat, mismas dimensiones, mismos niveles y el mismo
          tamaño por nivel), que es lo que exige InjectFromKtx2 del generador.
"""
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

IDENT = bytes([0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A])  # «KTX 20»

SUPERCOMPRESION = {0: "ninguna", 1: "BasisLZ", 2: "zstd", 3: "zlib"}


class Ktx2Error(Exception):
    pass


class Ktx2Info:
    __slots__ = ("ruta", "fmt", "w", "h", "d", "capas", "caras", "niveles", "super", "indice")

    @property
    def n_niveles(self):
        return max(1, self.niveles)

    @property
    def es_simple(self):
        """2D, sin capas, sin cubemap, sin profundidad: lo único que se puede reemplazar con un PNG."""
        return self.capas <= 1 and self.caras == 1 and self.d <= 1

    def resumen(self):
        partes = [f"{self.w}x{self.h}", f"{self.n_niveles} nivel(es)"]
        if self.capas > 1: partes.append(f"{self.capas} capas")
        if self.caras > 1: partes.append(f"{self.caras} caras (cubemap)")
        if self.d > 1: partes.append(f"profundidad {self.d}")
        if self.super: partes.append("supercompresión " + SUPERCOMPRESION.get(self.super, str(self.super)))
        return ", ".join(partes)


def es_ktx2(ruta):
    return str(ruta).lower().endswith(".ktx2")


def leer_cabecera(ruta):
    """Ktx2Info de un archivo, o lanza Ktx2Error si no es un KTX2 válido."""
    try:
        with open(str(ruta), "rb") as f:
            cab = f.read(80)
            if len(cab) < 80 or cab[:12] != IDENT:
                raise Ktx2Error("no es un archivo KTX2")
            (fmt, _tsize, w, h, d, capas, caras, niveles, sup) = struct.unpack_from("<9I", cab, 12)
            n = max(1, niveles)
            if n > 32:
                raise Ktx2Error(f"cantidad de niveles absurda ({niveles})")
            idx = f.read(24 * n)
            if len(idx) < 24 * n:
                raise Ktx2Error("el índice de niveles está incompleto")
    except OSError as e:
        raise Ktx2Error(str(e))
    info = Ktx2Info()
    info.ruta = str(ruta)
    info.fmt, info.w, info.h, info.d = fmt, w, max(1, h), d
    info.capas, info.caras, info.niveles, info.super = capas, max(1, caras), niveles, sup
    info.indice = [struct.unpack_from("<3Q", idx, 24 * i) for i in range(n)]   # (offset, largo, largo sin comprimir)
    return info


_cache = {}


def info_textura(ruta):
    """Cabecera con caché (por ruta + fecha + tamaño). None si no se puede leer."""
    try:
        st = os.stat(str(ruta))
    except OSError:
        return None
    clave = (str(ruta), st.st_mtime_ns, st.st_size)
    if clave not in _cache:
        if len(_cache) > 4096:
            _cache.clear()
        try:
            _cache[clave] = leer_cabecera(ruta)
        except Ktx2Error:
            _cache[clave] = None
    return _cache[clave]


def _datos_nivel(f, info, nivel):
    off, largo, ulargo = info.indice[nivel]
    f.seek(off)
    crudo = f.read(largo)
    if len(crudo) != largo:
        raise Ktx2Error("el archivo está truncado")
    if info.super == 0:
        return crudo
    if info.super == 3:
        return zlib.decompress(crudo)
    if info.super == 2:
        try:
            import zstandard
        except ImportError:
            raise Ktx2Error("el archivo usa supercompresión zstd: instala el paquete 'zstandard' (pip install zstandard)")
        return zstandard.ZstdDecompressor().decompress(crudo, max_output_size=max(ulargo, 1))
    raise Ktx2Error(f"supercompresión {SUPERCOMPRESION.get(info.super, info.super)} no soportada")


def bytes_mip0(ruta):
    """Bytes del mip 0 / capa 0 / cara 0 / corte 0 del contenedor KTX2."""
    info = leer_cabecera(ruta)
    with open(str(ruta), "rb") as f:
        datos = _datos_nivel(f, info, 0)
    n_imagenes = max(1, info.capas) * info.caras * max(1, info.d)
    una = len(datos) // n_imagenes
    return datos[:una]


# ---------------------------------------------------------------------------
# Creación con ktx.exe
# ---------------------------------------------------------------------------
def buscar_ktx_exe(candidatos):
    """Primera ruta existente de 'candidatos' (cadenas). None si no hay ninguna."""
    for c in candidatos:
        if c and os.path.isfile(str(c)):
            return str(c)
    return None


def _flags_subproceso():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0


def comando_ktx_create(ktx_exe, nombre_formato, ruta_png, ruta_salida, niveles, calidad="medium"):
    """Línea de comandos de `ktx create` para recrear la textura con el mismo VkFormat.

    --assign-tf es obligatorio para NO alterar los valores del PNG: sin él, ktx create convierte
    implícitamente (p.ej. sRGB->lineal en un formato UNORM), y la textura cambiaría de aspecto.
    Un formato *_SRGB_* se trata como sRGB y el resto como lineal; así los bytes que ve el juego
    son los mismos valores que tiene el PNG."""
    es_srgb = "SRGB" in nombre_formato.upper()
    cmd = [str(ktx_exe), "create", "--format", nombre_formato, "--assign-tf", "srgb" if es_srgb else "linear"]
    if niveles > 1:
        cmd += ["--generate-mipmap", "--levels", str(niveles)]
    if nombre_formato.upper().startswith("ASTC_"):
        cmd += ["--astc-quality", calidad]
    cmd += [str(ruta_png), str(ruta_salida)]
    return cmd


def validar_compatibilidad(ruta_original, ruta_nueva):
    """Lanza Ktx2Error si el archivo nuevo no se podría inyectar en lugar del original."""
    o, n = leer_cabecera(ruta_original), leer_cabecera(ruta_nueva)
    if n.super != 0:
        raise Ktx2Error("el archivo generado tiene supercompresión")
    if n.fmt != o.fmt:
        raise Ktx2Error(f"el formato generado (fmt {n.fmt}) no coincide con el original (fmt {o.fmt})")
    if (n.w, n.h) != (o.w, o.h):
        raise Ktx2Error(f"el tamaño generado ({n.w}x{n.h}) no coincide con el original ({o.w}x{o.h})")
    if n.n_niveles != o.n_niveles:
        raise Ktx2Error(f"el archivo generado tiene {n.n_niveles} nivel(es) y el original {o.n_niveles}")
    for i, (a, b) in enumerate(zip(o.indice, n.indice)):
        if a[2] != b[2]:
            raise Ktx2Error(f"el nivel {i} mide {b[2]} bytes y el original {a[2]}")


def crear_reemplazo(ktx_exe, nombre_formato, ruta_png, ruta_original, ruta_salida, calidad="medium"):
    """Crea 'ruta_salida' (.ktx2) a partir de un PNG con el formato/tamaño/niveles del original.
    Devuelve (True, "") o (False, "motivo"). Nunca deja un archivo a medias en 'ruta_salida'."""
    try:
        o = leer_cabecera(ruta_original)
    except Ktx2Error as e:
        return False, f"no se pudo leer el original: {e}"
    if not o.es_simple:
        return False, ("solo se pueden reemplazar texturas 2D simples; esta tiene " + o.resumen())
    tmp = str(ruta_salida) + ".tmp"
    try:
        if os.path.exists(tmp):
            os.unlink(tmp)
        cmd = comando_ktx_create(ktx_exe, nombre_formato, ruta_png, tmp, o.n_niveles, calidad)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_flags_subproceso())
        except OSError as e:
            return False, f"no se pudo ejecutar ktx.exe: {e}"
        if r.returncode != 0:
            salida = (r.stderr or r.stdout or "").strip()
            return False, f"ktx create falló (código {r.returncode}): {salida[-400:]}"
        try:
            validar_compatibilidad(ruta_original, tmp)
        except Ktx2Error as e:
            return False, f"el resultado no es compatible con el original: {e}"
        os.replace(tmp, str(ruta_salida))
        return True, ""
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
