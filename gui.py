# Parte 1
import sys
import os
import subprocess
import re
import tempfile
import math
import threading
import queue
import faulthandler
import traceback
import warnings
import atexit
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw
try:  # pestaña de frame traces: opcional (xxami_trace.py y trace_tab.py junto a este archivo)
    from trace_tab import PestanaTrace
except Exception:
    PestanaTrace = None
try:  # texturas KTX2 (formato actual del volcado) y creación de reemplazos con ktx.exe
    import ktx2_util
except Exception:
    ktx2_util = None

# --- MANEJO DE RUTAS PARA PYINSTALLER ---
def obtener_ruta_recurso(nombre):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, nombre)
    return os.path.join(os.path.abspath("."), nombre)

# --- PARSEO AUTOMÁTICO DE DIMENSIONES EN EL NOMBRE DE ARCHIVO ---
def parsear_dimensiones(ruta):
    if ktx2_util and ktx2_util.es_ktx2(ruta):
        info = ktx2_util.info_textura(ruta)
        if info: return (info.w, info.h)
    nombre = Path(ruta).name.lower()
    m = re.search(r'(\d+)x(\d+)', nombre)
    return (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)

def extraer_hash_textura(nombre_archivo):
    # "tex_7bd1c1f1a9699159_64x64_fmt157.raw" -> "7bd1c1f1a9699159"
    m = re.match(r'^tex_([0-9a-fA-F]+)(?:_|\.)', Path(nombre_archivo).name)
    return m.group(1) if m else None

# --- TABLA DE FORMATOS VULKAN (VkFormat) CONOCIDOS ---
# La clave es el número que aparece en el nombre de archivo como "fmt<N>":
# es directamente el valor numérico del enum VkFormat de la especificación
# Vulkan (por eso fmt157 = VK_FORMAT_ASTC_4x4_UNORM_BLOCK, fmt9 = R8_UNORM,
# etc.). Para soportar un formato nuevo que aparezca más adelante, alcanza
# con agregar una línea aquí — no hace falta tocar la lógica de decodificación.
FORMATOS_VULKAN = {
    9:   {"nombre": "R8_UNORM",             "tipo": "plano", "canales": ("R",),             "dtype": "u1"},
    16:  {"nombre": "R8G8_UNORM",           "tipo": "plano", "canales": ("R", "G"),          "dtype": "u1"},
    23:  {"nombre": "R8G8B8_UNORM",         "tipo": "plano", "canales": ("R", "G", "B"),     "dtype": "u1"},
    30:  {"nombre": "B8G8R8_UNORM",         "tipo": "plano", "canales": ("B", "G", "R"),     "dtype": "u1"},
    37:  {"nombre": "R8G8B8A8_UNORM",       "tipo": "plano", "canales": ("R", "G", "B", "A"), "dtype": "u1"},
    43:  {"nombre": "R8G8B8A8_SRGB",        "tipo": "plano", "canales": ("R", "G", "B", "A"), "dtype": "u1"},
    44:  {"nombre": "B8G8R8A8_UNORM",       "tipo": "plano", "canales": ("B", "G", "R", "A"), "dtype": "u1"},
    50:  {"nombre": "B8G8R8A8_SRGB",        "tipo": "plano", "canales": ("B", "G", "R", "A"), "dtype": "u1"},
    70:  {"nombre": "R16_UNORM",            "tipo": "plano", "canales": ("R",),              "dtype": "<u2"},
    76:  {"nombre": "R16_SFLOAT",           "tipo": "plano", "canales": ("R",),              "dtype": "<f2"},
    83:  {"nombre": "R16G16_SFLOAT",        "tipo": "plano", "canales": ("R", "G"),          "dtype": "<f2"},
    91:  {"nombre": "R16G16B16A16_UNORM",   "tipo": "plano", "canales": ("R", "G", "B", "A"), "dtype": "<u2"},
    97:  {"nombre": "R16G16B16A16_SFLOAT",  "tipo": "plano", "canales": ("R", "G", "B", "A"), "dtype": "<f2"},
    100: {"nombre": "R32_SFLOAT",           "tipo": "plano", "canales": ("R",),              "dtype": "<f4"},
    109: {"nombre": "R32G32B32A32_SFLOAT",  "tipo": "plano", "canales": ("R", "G", "B", "A"), "dtype": "<f4"},
    # ETC2: otra familia de compresión por bloques de Vulkan/Android (además de ASTC).
    # Bloque siempre 4x4; "rgb"=8 bytes/bloque, "rgba1"/"rgba8"=8/16 bytes/bloque.
    147: {"nombre": "ETC2_R8G8B8_UNORM_BLOCK",   "tipo": "etc2", "variante": "rgb"},
    148: {"nombre": "ETC2_R8G8B8_SRGB_BLOCK",    "tipo": "etc2", "variante": "rgb"},
    149: {"nombre": "ETC2_R8G8B8A1_UNORM_BLOCK", "tipo": "etc2", "variante": "rgba1"},
    150: {"nombre": "ETC2_R8G8B8A1_SRGB_BLOCK",  "tipo": "etc2", "variante": "rgba1"},
    151: {"nombre": "ETC2_R8G8B8A8_UNORM_BLOCK", "tipo": "etc2", "variante": "rgba8"},
    152: {"nombre": "ETC2_R8G8B8A8_SRGB_BLOCK",  "tipo": "etc2", "variante": "rgba8"},
    157: {"nombre": "ASTC_4x4_UNORM_BLOCK",   "tipo": "astc", "bloque": "4x4"},
    158: {"nombre": "ASTC_4x4_SRGB_BLOCK",    "tipo": "astc", "bloque": "4x4"},
    159: {"nombre": "ASTC_5x4_UNORM_BLOCK",   "tipo": "astc", "bloque": "5x4"},
    160: {"nombre": "ASTC_5x4_SRGB_BLOCK",    "tipo": "astc", "bloque": "5x4"},
    161: {"nombre": "ASTC_5x5_UNORM_BLOCK",   "tipo": "astc", "bloque": "5x5"},
    162: {"nombre": "ASTC_5x5_SRGB_BLOCK",    "tipo": "astc", "bloque": "5x5"},
    163: {"nombre": "ASTC_6x5_UNORM_BLOCK",   "tipo": "astc", "bloque": "6x5"},
    164: {"nombre": "ASTC_6x5_SRGB_BLOCK",    "tipo": "astc", "bloque": "6x5"},
    165: {"nombre": "ASTC_6x6_UNORM_BLOCK",   "tipo": "astc", "bloque": "6x6"},
    166: {"nombre": "ASTC_6x6_SRGB_BLOCK",    "tipo": "astc", "bloque": "6x6"},
    167: {"nombre": "ASTC_8x5_UNORM_BLOCK",   "tipo": "astc", "bloque": "8x5"},
    168: {"nombre": "ASTC_8x5_SRGB_BLOCK",    "tipo": "astc", "bloque": "8x5"},
    169: {"nombre": "ASTC_8x6_UNORM_BLOCK",   "tipo": "astc", "bloque": "8x6"},
    170: {"nombre": "ASTC_8x6_SRGB_BLOCK",    "tipo": "astc", "bloque": "8x6"},
    171: {"nombre": "ASTC_8x8_UNORM_BLOCK",   "tipo": "astc", "bloque": "8x8"},
    172: {"nombre": "ASTC_8x8_SRGB_BLOCK",    "tipo": "astc", "bloque": "8x8"},
    173: {"nombre": "ASTC_10x5_UNORM_BLOCK",  "tipo": "astc", "bloque": "10x5"},
    174: {"nombre": "ASTC_10x5_SRGB_BLOCK",   "tipo": "astc", "bloque": "10x5"},
    175: {"nombre": "ASTC_10x6_UNORM_BLOCK",  "tipo": "astc", "bloque": "10x6"},
    176: {"nombre": "ASTC_10x6_SRGB_BLOCK",   "tipo": "astc", "bloque": "10x6"},
    177: {"nombre": "ASTC_10x8_UNORM_BLOCK",  "tipo": "astc", "bloque": "10x8"},
    178: {"nombre": "ASTC_10x8_SRGB_BLOCK",   "tipo": "astc", "bloque": "10x8"},
    179: {"nombre": "ASTC_10x10_UNORM_BLOCK", "tipo": "astc", "bloque": "10x10"},
    180: {"nombre": "ASTC_10x10_SRGB_BLOCK",  "tipo": "astc", "bloque": "10x10"},
    181: {"nombre": "ASTC_12x10_UNORM_BLOCK", "tipo": "astc", "bloque": "12x10"},
    182: {"nombre": "ASTC_12x10_SRGB_BLOCK",  "tipo": "astc", "bloque": "12x10"},
    183: {"nombre": "ASTC_12x12_UNORM_BLOCK", "tipo": "astc", "bloque": "12x12"},
    184: {"nombre": "ASTC_12x12_SRGB_BLOCK",  "tipo": "astc", "bloque": "12x12"},
}

def leer_datos_textura(ruta):
    """Bytes del mip 0 de una textura: el contenido del .raw o, en un .ktx2, el nivel 0 / capa 0."""
    if ktx2_util and ktx2_util.es_ktx2(ruta):
        return ktx2_util.bytes_mip0(ruta)
    return Path(ruta).read_bytes()

def es_modelo_listable(ruta):
    """Qué .buf van a la lista Modelos: geometría de draws (vb_/ib_/vbib_) y los vb0 de Models/PartNN.
    Los buffers de entrada del skinning (sb_, bones_) y los ib/bones de cada Part no se listan."""
    n = Path(ruta).name.lower()
    return n.startswith(('vb_', 'ib_', 'vbib_')) or re.match(r'^part\d+-vb0=', n) is not None

def obtener_codigo_formato(ruta):
    if ktx2_util and ktx2_util.es_ktx2(ruta):
        info = ktx2_util.info_textura(ruta)
        if info: return info.fmt
    m = re.search(r'fmt(\d+)', Path(ruta).name.lower())
    return int(m.group(1)) if m else None

def obtener_info_formato(ruta):
    codigo = obtener_codigo_formato(ruta)
    return FORMATOS_VULKAN.get(codigo) if codigo is not None else None

# --- FORMATOS QUE SE SABE QUE NO SON IMÁGENES VISUALIZABLES ---
# fmt109 (R32G32B32A32_SFLOAT) se probó con normalización min/max y luego por
# percentil, y en ambos casos el resultado sigue siendo ruido sin forma: no es
# una textura de color, sino algún otro tipo de buffer de datos (LUT, datos de
# animación, etc.). En vez de seguir mostrando ruido enredoso, se reemplaza por
# un aviso claro de "no se pudo leer". Si más adelante se identifica otro fmt
# con el mismo problema, alcanza con sumar su número aquí.
FORMATOS_NO_VISUALIZABLES = {109}

_RUTA_NOTLOAD_CANDIDATAS = None
_IMG_NOTLOAD_CACHE = None

def _rutas_candidatas_notload():
    global _RUTA_NOTLOAD_CANDIDATAS
    if _RUTA_NOTLOAD_CANDIDATAS is None:
        candidatas = []
        try:
            candidatas.append(Path(__file__).resolve().with_name("notload.png"))
        except Exception:
            pass
        candidatas.append(Path(obtener_ruta_recurso("notload.png")))
        _RUTA_NOTLOAD_CANDIDATAS = candidatas
    return _RUTA_NOTLOAD_CANDIDATAS

def obtener_imagen_notload():
    # Se cachea en memoria: da igual cuántas miniaturas/vistas la usen, se abre una sola vez.
    global _IMG_NOTLOAD_CACHE
    if _IMG_NOTLOAD_CACHE is not None:
        return _IMG_NOTLOAD_CACHE
    for ruta in _rutas_candidatas_notload():
        try:
            if ruta.exists():
                _IMG_NOTLOAD_CACHE = Image.open(str(ruta)).convert("RGBA")
                return _IMG_NOTLOAD_CACHE
        except Exception:
            continue
    # Red de seguridad: si notload.png no está (o no se pudo abrir), se genera
    # un aviso simple en memoria para que la vista nunca quede rota por esto.
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    dib = ImageDraw.Draw(img)
    margen = 90
    dib.line((margen, margen, 512 - margen, 512 - margen), fill=(255, 60, 60, 255), width=14)
    dib.line((512 - margen, margen, margen, 512 - margen), fill=(255, 60, 60, 255), width=14)
    _IMG_NOTLOAD_CACHE = img
    return img
# Parte 2
# --- LÓGICA DE CONVERSIÓN DE SHADERS (SPIR-V <-> GLSL) ---
def desensamblar_spv(ruta):
    # Se conserva: ya no se usa para mostrar el shader (eso ahora es GLSL vía
    # spirv-cross), pero sigue sirviendo para detectar la etapa del shader
    # (vertex/fragment/...) leyendo la línea "OpEntryPoint" del desensamblado.
    try:
        r = subprocess.run([obtener_ruta_recurso("spirv-dis.exe"), str(ruta)], check=True, capture_output=True, text=True)
        return r.stdout
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo desensamblar:\n{e}")
        return None

def ensamblar_spv(texto, ruta_salida):
    # Se conserva sin usar por ahora (era el camino viejo, SPIR-V ensamblado a
    # mano). El guardado actual pasa por glsl_a_spv.
    tmp = Path(ruta_salida).with_suffix('.tmp.txt')
    try:
        tmp.write_text(texto, encoding='utf-8')
        subprocess.run([obtener_ruta_recurso("spirv-as.exe"), str(tmp), "-o", str(ruta_salida)], check=True)
        if tmp.exists(): tmp.unlink()
        return True
    except Exception as e:
        if tmp.exists(): tmp.unlink()
        messagebox.showerror("Error de sintaxis SPIR-V", f"Error en el código:\n{e}")
        return False

# El modelo de ejecución de SPIR-V (OpEntryPoint) indica la etapa del shader;
# GLSL por sí solo no la lleva, así que glslc necesita que se la digamos
# explícitamente con -fshader-stage=<...> al recompilar.
_MAPA_ETAPA_SPIRV_A_GLSLC = {
    "Vertex": "vertex", "Fragment": "fragment", "GLCompute": "compute",
    "Geometry": "geometry", "TessellationControl": "tesscontrol",
    "TessellationEvaluation": "tesseval",
}

def detectar_etapa_shader(ruta_spv):
    """Devuelve 'vertex'/'fragment'/etc. (el valor que espera -fshader-stage de
    glslc) a partir del SPIR-V original, o None si no se pudo determinar."""
    texto_asm = desensamblar_spv(ruta_spv)
    if not texto_asm:
        return None
    m = re.search(r'OpEntryPoint\s+(\w+)', texto_asm)
    return _MAPA_ETAPA_SPIRV_A_GLSLC.get(m.group(1)) if m else None

def spv_a_glsl(ruta_spv):
    """SPIR-V -> GLSL legible, vía spirv-cross.exe (equivalente a:
    spirv-cross.exe shader.spv --output shader.glsl --version 450 --vulkan-semantics)."""
    tmp_glsl = Path(ruta_spv).with_name(Path(ruta_spv).stem + "_xxami_tmp.glsl")
    try:
        r = subprocess.run(
            [obtener_ruta_recurso("spirv-cross.exe"), str(ruta_spv), "--output", str(tmp_glsl),
             "--version", "450", "--vulkan-semantics"],
            check=True, capture_output=True, text=True)
        return tmp_glsl.read_text(encoding="utf-8")
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error", f"No se pudo convertir a GLSL:\n{e.stderr or e}")
        return None
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo convertir a GLSL:\n{e}")
        return None
    finally:
        try:
            if tmp_glsl.exists(): tmp_glsl.unlink()
        except Exception:
            pass

def glsl_a_spv(texto, ruta_salida, etapa):
    """GLSL -> SPIR-V, vía glslc.exe (equivalente a:
    glslc.exe -fshader-stage=<etapa> shader.glsl -o shader_modificado.spv)."""
    if not etapa:
        messagebox.showerror("Error", "No se pudo determinar la etapa de este shader (vertex/fragment/...), así que glslc no puede recompilarlo con certeza. No se tocó el archivo.")
        return False
    tmp_glsl = Path(ruta_salida).with_name(Path(ruta_salida).stem + "_xxami_tmp.glsl")
    try:
        tmp_glsl.write_text(texto, encoding="utf-8")
        subprocess.run(
            [obtener_ruta_recurso("glslc.exe"), f"-fshader-stage={etapa}", str(tmp_glsl), "-o", str(ruta_salida)],
            check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error de sintaxis GLSL", f"Error en el código:\n{e.stderr or e}")
        return False
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo compilar:\n{e}")
        return False
    finally:
        try:
            if tmp_glsl.exists(): tmp_glsl.unlink()
        except Exception:
            pass
# --- RESALTADO DE SINTAXIS GLSL (coloreado simple por regex, no un parser real) ---
_GLSL_PALABRAS_CLAVE = {
    "if", "else", "for", "while", "do", "return", "discard", "break", "continue", "switch", "case", "default",
    "struct", "void", "true", "false", "const", "in", "out", "inout", "uniform", "buffer", "shared",
    "flat", "smooth", "noperspective", "invariant", "precise", "layout", "attribute", "varying",
    "highp", "mediump", "lowp", "precision", "coherent", "volatile", "restrict", "readonly", "writeonly",
}
_GLSL_TIPOS = {
    "float", "int", "uint", "bool", "double",
    "vec2", "vec3", "vec4", "ivec2", "ivec3", "ivec4", "uvec2", "uvec3", "uvec4", "bvec2", "bvec3", "bvec4",
    "dvec2", "dvec3", "dvec4",
    "mat2", "mat3", "mat4", "mat2x2", "mat2x3", "mat2x4", "mat3x2", "mat3x3", "mat3x4", "mat4x2", "mat4x3", "mat4x4",
    "sampler1D", "sampler2D", "sampler3D", "samplerCube", "sampler2DArray", "samplerCubeArray",
    "sampler2DShadow", "samplerCubeShadow", "sampler2DArrayShadow",
    "isampler2D", "usampler2D", "image1D", "image2D", "image3D", "imageCube", "image2DArray",
}
_GLSL_FUNCIONES_BUILTIN = {
    "texture", "textureLod", "textureProj", "texelFetch", "normalize", "dot", "cross", "mix", "clamp",
    "pow", "sqrt", "inversesqrt", "length", "distance", "reflect", "refract", "min", "max", "abs",
    "floor", "ceil", "fract", "mod", "step", "smoothstep", "sin", "cos", "tan", "asin", "acos", "atan",
    "exp", "log", "exp2", "log2", "transpose", "inverse", "determinant", "dFdx", "dFdy", "fwidth",
}
_GLSL_ESTILOS_TAGS = {
    "glsl_num": {"foreground": "#b5cea8"},
    "glsl_tipo": {"foreground": "#4ec9b0"},
    "glsl_kw": {"foreground": "#569cd6"},
    "glsl_fn": {"foreground": "#dcdcaa"},
    "glsl_pre": {"foreground": "#c586c0"},
    "glsl_str": {"foreground": "#ce9178"},
    "glsl_com": {"foreground": "#6a9955", "font": ("Consolas", 11, "italic")},
}

def configurar_tags_glsl(text_widget):
    for tag, opciones in _GLSL_ESTILOS_TAGS.items():
        text_widget.tag_configure(tag, **opciones)

def _resaltar_glsl(text_widget):
    # Coloreado por regex sobre texto completo: no es un parser GLSL real, así que
    # puede equivocarse en casos raros (ej. la palabra "void" dentro de un string),
    # pero para leer/editar el shader decompilado alcanza de sobra.
    for tag in _GLSL_ESTILOS_TAGS:
        text_widget.tag_remove(tag, "1.0", "end")
    texto = text_widget.get("1.0", "end-1c")
    if not texto:
        return

    def marcar(patron, tag, flags=0):
        for m in re.finditer(patron, texto, flags):
            text_widget.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    marcar(r'\b\d+\.\d+([eE][+-]?\d+)?[fF]?\b|\b\d+[fFuUlL]?\b', "glsl_num")
    marcar(r'\b(' + '|'.join(_GLSL_TIPOS) + r')\b', "glsl_tipo")
    marcar(r'\b(' + '|'.join(_GLSL_PALABRAS_CLAVE) + r')\b', "glsl_kw")
    marcar(r'\b(' + '|'.join(_GLSL_FUNCIONES_BUILTIN) + r')\b(?=\s*\()', "glsl_fn")
    # Estos tres van al final y se elevan por encima: una palabra clave DENTRO de un
    # comentario/string/directiva debe verse con el color del comentario, no el suyo.
    marcar(r'^[ \t]*#\w+.*$', "glsl_pre", re.MULTILINE)
    marcar(r'"[^"\n]*"', "glsl_str")
    marcar(r'//[^\n]*', "glsl_com")
    marcar(r'/\*.*?\*/', "glsl_com", re.DOTALL)
    for tag in ("glsl_pre", "glsl_str", "glsl_com"):
        text_widget.tag_raise(tag)

try:
    import texture2ddecoder  # pip install texture2ddecoder
except ImportError:
    texture2ddecoder = None
try:
    import numpy as np  # pip install numpy (para formatos planos: R8G8B8A8, R32G32B32A32_SFLOAT, etc.)
except ImportError:
    np = None

# --- DETECCIÓN DE DECODIFICACIÓN FALLIDA (bloques de error ASTC/ETC2) ---
# El magenta puro (255,0,255) es, por convención, el color que usan casi todos
# los decodificadores de bloques (incluido el que usa esta herramienta) para
# señalar un bloque inválido/corrupto -es una convención de la industria, no
# algo específico de esta app-. Un porcentaje alto de esos píxeles es una señal
# fuerte de que el bloque/orientación de origen no era el correcto, pero no es
# 100% infalible: una textura real, legítimamente magenta, daría un falso
# positivo. Ajustable si hiciera falta.
_COLOR_ERROR_BLOQUE = (255, 0, 255)
UMBRAL_SOSPECHA_DECODIFICACION = 0.5  # fracción de píxeles "de error" para considerarlo sospechoso

# Techo de miniaturas que se generan/retienen a la vez en la grilla. Cada una
# consume un recurso GDI de Windows (PhotoImage) que se mantiene vivo mientras
# esté en pantalla, con un cupo propio (~10.000 por proceso) independiente del
# límite de handles de ventana que ya se resolvió antes al pasar a dibujar sobre
# un Canvas. Dejar márgen generoso por el resto de la UI (vista grande, etc.).
MAX_MINIATURAS_POR_VISTA = 2000

def _puntaje_sospecha_decodificacion(img_rgba):
    arr = np.asarray(img_rgba.convert("RGB")) if np is not None else None
    if arr is None or arr.size == 0:
        return 0.0
    r, g, b = arr[:, :, 0].astype(np.int16), arr[:, :, 1].astype(np.int16), arr[:, :, 2].astype(np.int16)
    coincide = (np.abs(r - _COLOR_ERROR_BLOQUE[0]) < 12) & (np.abs(g - _COLOR_ERROR_BLOQUE[1]) < 12) & (np.abs(b - _COLOR_ERROR_BLOQUE[2]) < 12)
    return float(coincide.mean())

def _desentrelazar_bloques_astc(datos, bloques_ancho, bloques_alto):
    """Reordena los bloques desde el mosaico de memoria de la GPU (Android/Vulkan)
    a orden normal por filas. Se aplica sobre los bytes originales del archivo,
    nunca de forma encadenada, así que no necesita ser su propia inversa."""
    ancho_mosaico = 16 if bloques_ancho % 16 == 0 else 8
    salida = bytearray(len(datos))
    for idx_bloque in range(bloques_ancho * bloques_alto):
        bloques_por_columna = bloques_alto * ancho_mosaico
        columna_macro = idx_bloque // bloques_por_columna
        resto = idx_bloque % bloques_por_columna
        y_blq = resto // ancho_mosaico
        x_blq = (columna_macro * ancho_mosaico) + (resto % ancho_mosaico)
        if x_blq < bloques_ancho and y_blq < bloques_alto:
            idx_orig = idx_bloque * 16
            idx_dest = (y_blq * bloques_ancho + x_blq) * 16
            salida[idx_dest:idx_dest + 16] = datos[idx_orig:idx_orig + 16]
    return bytes(salida)

def _registrar_diagnostico(self, ruta_raw, motivo):
    # motivo=None significa "todo bien"; se guarda igual para no dejar un diagnóstico
    # viejo colgado si la textura se vuelve a decodificar más tarde (ej. tras un reemplazo).
    try:
        self._diagnostico_textura[ruta_raw] = motivo
    except Exception:
        pass  # self puede ser un objeto de prueba sin este diccionario; no es crítico

# --- CANDIDATOS PARA "ADIVINAR" UN fmt QUE NO ESTÁ EN LA TABLA ---
# BC1-BC7 son la familia de compresión por bloques de DirectX/PC (equivalente a
# ASTC/ETC2 mobile). Todas usan bloques 4x4; BC1/BC4 pesan 8 bytes/bloque,
# BC2/BC3/BC5/BC6/BC7 pesan 16. NOTA: no pude probar estas funciones contra el
# paquete real (no está instalado en este entorno) -si el nombre de alguna
# función no coincide con la librería instalada, esa opción se salta sola
# (hasattr) en vez de romper todo; avísame y lo corrijo.
_CODECS_BC = {
    "BC1": (8, "decode_bc1"), "BC2": (16, "decode_bc2"), "BC3": (16, "decode_bc3"),
    "BC4": (8, "decode_bc4"), "BC5": (16, "decode_bc5"),
    "BC6": (16, "decode_bc6"), "BC7": (16, "decode_bc7"),
}
_BLOQUES_ASTC_POSIBLES = ["4x4", "5x4", "5x5", "6x5", "6x6", "8x5", "8x6", "8x8",
                          "10x5", "10x6", "10x8", "10x10", "12x10", "12x12"]
_VARIANTES_ETC2_POSIBLES = {"ETC2 rgb": ("rgb", 8), "ETC2 rgba1": ("rgba1", 8), "ETC2 rgba8": ("rgba8", 16)}

def _probar_todos_los_codecs(datos, ancho, alto):
    """Para un fmt sin catalogar: prueba ASTC (los 14 tamaños de bloque), ETC2 y
    BC1-7, y devuelve (imagen, descripción, puntaje_de_error) del candidato con
    menos señales de bloques inválidos -solo entre los que calzan EXACTO con el
    tamaño real del archivo, para no adivinar sobre datos rellenados con ceros-.
    Devuelve None si ni el tamaño coincide con ninguno."""
    if texture2ddecoder is None:
        return None
    candidatos = []  # (descripcion, ax, ay, bx, by, funcion_decode)
    for b in _BLOQUES_ASTC_POSIBLES:
        bx, by = map(int, b.split('x'))
        ax, ay = ((ancho + bx - 1) // bx) * bx, ((alto + by - 1) // by) * by
        if (ax // bx) * (ay // by) * 16 == len(datos):
            candidatos.append((f"ASTC {b}", ax, ay, bx, by, lambda d, a, h, bx=bx, by=by: texture2ddecoder.decode_astc(d, a, h, bx, by)))
    ax4, ay4 = ((ancho + 3) // 4) * 4, ((alto + 3) // 4) * 4
    n_bloques_4x4 = (ax4 // 4) * (ay4 // 4)
    for desc, (variante, bpb) in _VARIANTES_ETC2_POSIBLES.items():
        fn_nombre = {"rgb": "decode_etc2", "rgba1": "decode_etc2a1", "rgba8": "decode_etc2a8"}[variante]
        if n_bloques_4x4 * bpb == len(datos) and hasattr(texture2ddecoder, fn_nombre):
            candidatos.append((desc, ax4, ay4, 4, 4, getattr(texture2ddecoder, fn_nombre)))
    for nombre_bc, (bpb, fn_nombre) in _CODECS_BC.items():
        if n_bloques_4x4 * bpb == len(datos) and hasattr(texture2ddecoder, fn_nombre):
            candidatos.append((nombre_bc, ax4, ay4, 4, 4, getattr(texture2ddecoder, fn_nombre)))

    mejor = None
    for desc, ax, ay, bx, by, decodificar in candidatos:
        try:
            bgra = decodificar(datos, ax, ay)
            img = Image.frombytes("RGBA", (ax, ay), bgra, "raw", "BGRA")
            if (ax, ay) != (ancho, alto):
                img = img.crop((0, 0, ancho, alto))
            puntaje = _puntaje_sospecha_decodificacion(img)
        except Exception:
            continue
        if mejor is None or puntaje < mejor[2]:
            mejor = (img, desc, puntaje)
    return mejor

# --- DETECCIÓN DEL BLOQUE ASTC POR TAMAÑO DE ARCHIVO ---
# Se usa solo como último recurso, cuando el número de "fmtN" del archivo no
# está en FORMATOS_VULKAN: cada bloque ASTC pesa siempre 16 bytes sin importar
# sus dimensiones, así que probamos cuál combinación calza con el tamaño real.
def detectar_bloque_astc(ancho, alto, tamano_bytes, bloque_sugerido="4x4"):
    for b in ["4x4", "5x5", "6x6", "8x8", "10x10", "12x12"]:
        bx, by = map(int, b.split('x'))
        bloques_x = (ancho + bx - 1) // bx
        bloques_y = (alto + by - 1) // by
        if tamano_bytes == bloques_x * bloques_y * 16:
            return b
    return bloque_sugerido

# --- DECODIFICACIÓN DE FORMATOS PLANOS (SIN COMPRESIÓN DE BLOQUES) ---
# Heurística: un canal único (R8, R16...) suele ser una MÁSCARA DE COBERTURA
# (atlas de fuentes, siluetas, etc.) que el shader usa como alfa. Se considera
# máscara si la mayoría de los píxeles son negro puro (fondo vacío) y hay algo
# de contenido casi blanco. Un gris "de verdad" (rugosidad, AO, ruido) no
# cumple esto y se sigue mostrando opaco. Ajustable aquí si hiciera falta.
UMBRAL_MASCARA_NEGROS = 0.50   # fracción mínima de píxeles <= 8
UMBRAL_MASCARA_BLANCOS = 0.005 # fracción mínima de píxeles >= 200

def _parece_mascara_alfa(canal_u8):
    total = canal_u8.size
    if total == 0: return False
    negros = np.count_nonzero(canal_u8 <= 8) / total
    blancos = np.count_nonzero(canal_u8 >= 200) / total
    return negros >= UMBRAL_MASCARA_NEGROS and blancos >= UMBRAL_MASCARA_BLANCOS

def _decodificar_formato_plano(datos, ancho, alto, info_formato):
    if np is None:
        raise RuntimeError("Falta el paquete 'numpy' (pip install numpy)")
    canales = info_formato["canales"]
    n_canales = len(canales)
    dtype_np = np.dtype(info_formato["dtype"])
    bytes_por_canal = dtype_np.itemsize
    bytes_necesarios = ancho * alto * n_canales * bytes_por_canal
    buffer = datos[:bytes_necesarios]
    if len(buffer) < bytes_necesarios:
        buffer = buffer + b'\x00' * (bytes_necesarios - len(buffer))
    arr = np.frombuffer(buffer, dtype=dtype_np).reshape((alto, ancho, n_canales))

    es_float = np.issubdtype(arr.dtype, np.floating)
    if es_float:
        # Datos HDR/flotantes: casi nunca están en [0,1] (pueden ser mucho
        # más grandes o negativos), así que normalizamos cada canal por su
        # propio mínimo/máximo en vez de recortar, para no saturar todo a
        # blanco o negro y poder ver el patrón real de la textura.
        # float64 (no float32): si los bytes crudos no son un HDR "sano", el
        # rango real puede acercarse a los límites de float32, y máximo-mínimo
        # desbordaría a inf/NaN en esa precisión. float64 tiene margen de sobra.
        with np.errstate(all="ignore"):  # NaN/inf en los bytes crudos son esperables aquí; se sanean justo debajo
            arr_f = np.nan_to_num(arr.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        # Percentil 2-98 en vez de mínimo/máximo absoluto: unos pocos píxeles
        # con valores extremos no deberían aplastar a todos los demás en una
        # franja angosta del rango (eso es lo que se veía como "casi todo
        # un solo color sólido" en texturas HDR con outliers).
        p_bajo = np.percentile(arr_f, 2, axis=(0, 1), keepdims=True)
        p_alto = np.percentile(arr_f, 98, axis=(0, 1), keepdims=True)
        rango = np.where(p_alto > p_bajo, p_alto - p_bajo, 1.0)
        arr_u8 = ((arr_f - p_bajo) / rango * 255.0).clip(0, 255).astype(np.uint8)
    elif arr.dtype == np.uint16:
        arr_u8 = (arr.astype(np.uint32) * 255 // 65535).astype(np.uint8)
    else:
        arr_u8 = arr.astype(np.uint8)

    salida = np.zeros((alto, ancho, 4), dtype=np.uint8)
    salida[:, :, 3] = 255  # opaco por defecto
    if n_canales == 1 and canales[0] == "R":
        canal = arr_u8[:, :, 0]
        if not es_float and _parece_mascara_alfa(canal):
            # Máscara de cobertura: color blanco y el valor del canal como alfa
            salida[:, :, 0:3] = 255
            salida[:, :, 3] = canal
        else:
            # Un solo canal (ej. R8_UNORM): se muestra en escala de grises opaca
            salida[:, :, 0] = salida[:, :, 1] = salida[:, :, 2] = canal
    else:
        indice_canal = {c: i for i, c in enumerate(canales)}
        for destino, letra in enumerate(("R", "G", "B")):
            if letra in indice_canal:
                salida[:, :, destino] = arr_u8[:, :, indice_canal[letra]]
        # El canal alfa solo se respeta en formatos enteros (UNORM real de
        # opacidad). En datos de punto flotante casi nunca es una opacidad
        # válida, así que se deja opaco para no volver invisible el preview.
        if "A" in indice_canal and not es_float:
            salida[:, :, 3] = arr_u8[:, :, indice_canal["A"]]
    return Image.fromarray(salida, mode="RGBA")

# --- LÓGICA DE PREVISUALIZACIÓN: DECODIFICACIÓN REAL POR FORMATO ---
# --- COMPOSICIÓN SOBRE TABLERO DE AJEDREZ (SOLO PARA VISUALIZAR, NUNCA PARA GUARDAR) ---
# El PNG cacheado en disco (el que usa "Exportar a PNG") siempre debe conservar
# su canal alfa real intacto. Este tablero es puramente cosmético, para que la
# transparencia real se distinga del negro sólido en pantalla (contra el fondo
# oscuro del visor, ambos se verían idénticos si no se hace esta composición).
def componer_sobre_tablero(img_rgba, tam_cuadro=8):
    if img_rgba.mode != "RGBA":
        return img_rgba.convert("RGB")
    if np is None:
        return img_rgba.convert("RGB")
    ancho, alto = img_rgba.size
    ys, xs = np.indices((alto, ancho))
    patron = ((xs // tam_cuadro) + (ys // tam_cuadro)) % 2
    color_claro = np.array([90, 90, 90], dtype=np.uint8)
    color_oscuro = np.array([60, 60, 60], dtype=np.uint8)
    tablero_arr = np.where(patron[:, :, None] == 0, color_claro, color_oscuro).astype(np.uint8)
    tablero = Image.fromarray(tablero_arr, mode="RGB")
    tablero.paste(img_rgba, (0, 0), img_rgba)
    return tablero

def astc_raw_a_png(self, ruta_raw, ruta_png_temp, rapido=False):
    # rapido=True: se usa desde el hilo de miniaturas (corre automáticamente para
    # TODA la carpeta, sin que el usuario lo pida archivo por archivo). En ese modo
    # se evita la fuerza bruta multi-códec y el reintento de desentrelazado -cada
    # intento extra es una llamada más a una librería en C que no puedo verificar
    # aquí-, para minimizar cuántas llamadas nativas se disparan sin supervisión.
    # rapido=False (vista de una sola textura, bajo pedido explícito): se hace el
    # análisis completo.
    ancho, alto = parsear_dimensiones(ruta_raw)
    codigo_formato = obtener_codigo_formato(ruta_raw)
    info_formato = FORMATOS_VULKAN.get(codigo_formato) if codigo_formato is not None else None

    if Path(ruta_png_temp).exists():
        try: Path(ruta_png_temp).unlink()
        except: pass

    # Formatos que ya se probaron y no son imágenes legibles (ver FORMATOS_NO_VISUALIZABLES):
    # se usa directamente el aviso "no se pudo leer" en vez de intentar decodificar ruido.
    if codigo_formato in FORMATOS_NO_VISUALIZABLES:
        obtener_imagen_notload().save(ruta_png_temp)
        _registrar_diagnostico(self, ruta_raw, None)  # ese caso ya se explica solo en el panel; no hace falta duplicar el aviso
        return True

    try:
        datos = leer_datos_textura(ruta_raw)
        tamano_bytes = len(datos)

        # --- FORMATOS PLANOS (SIN COMPRESIÓN DE BLOQUES) ---
        if info_formato is not None and info_formato["tipo"] == "plano":
            _decodificar_formato_plano(datos, ancho, alto, info_formato).save(ruta_png_temp)
            _registrar_diagnostico(self, ruta_raw, None)  # copia directa de píxeles: no hay "decodificación" que pueda salir mal
            return Path(ruta_png_temp).exists()

        # --- FORMATOS ETC2 (otra familia de compresión por bloques, bloque fijo 4x4) ---
        if info_formato is not None and info_formato["tipo"] == "etc2":
            if texture2ddecoder is None:
                raise RuntimeError("Falta el paquete 'texture2ddecoder' (pip install texture2ddecoder)")
            variante = info_formato["variante"]
            ax = ((ancho + 3) // 4) * 4
            ay = ((alto + 3) // 4) * 4
            n_bloques = (ax // 4) * (ay // 4)
            bytes_por_bloque = 16 if variante == "rgba8" else 8
            bytes_necesarios = n_bloques * bytes_por_bloque

            if tamano_bytes < bytes_por_bloque:
                obtener_imagen_notload().save(ruta_png_temp)
                _registrar_diagnostico(self, ruta_raw, f"archivo vacío o incompleto ({tamano_bytes} bytes; se esperaban {bytes_necesarios})")
                return Path(ruta_png_temp).exists()

            datos_bloque = datos[:bytes_necesarios]
            if len(datos_bloque) < bytes_necesarios:
                datos_bloque += b'\x00' * (bytes_necesarios - len(datos_bloque))
            if variante == "rgb":
                bgra = texture2ddecoder.decode_etc2(datos_bloque, ax, ay)
            elif variante == "rgba1":
                bgra = texture2ddecoder.decode_etc2a1(datos_bloque, ax, ay)
            else:
                bgra = texture2ddecoder.decode_etc2a8(datos_bloque, ax, ay)
            img_decodificada = Image.frombytes("RGBA", (ax, ay), bgra, "raw", "BGRA")
            if (ax, ay) != (ancho, alto):
                img_decodificada = img_decodificada.crop((0, 0, ancho, alto))
            puntaje = _puntaje_sospecha_decodificacion(img_decodificada)
            # ETC2 no tiene (por ahora) una lógica de desentrelazado propia que probar;
            # solo se informa la sospecha, sin reintento automático.
            motivo = f"posible decodificación inválida (~{puntaje*100:.0f}% de bloques de error) — revisar si el archivo está completo" if puntaje > UMBRAL_SOSPECHA_DECODIFICACION else None
            _registrar_diagnostico(self, ruta_raw, motivo)
            img_decodificada.save(ruta_png_temp)
            return Path(ruta_png_temp).exists()

        # --- fmt NO CATALOGADO: fuerza bruta entre ASTC/ETC2/BC en vez de asumir ASTC ---
        if info_formato is None:
            if tamano_bytes < 8:
                obtener_imagen_notload().save(ruta_png_temp)
                _registrar_diagnostico(self, ruta_raw, f"archivo vacío o incompleto ({tamano_bytes} bytes)")
                return Path(ruta_png_temp).exists()
            resultado = None if rapido else _probar_todos_los_codecs(datos, ancho, alto)
            if resultado is None:
                # Ningún candidato calza con el tamaño real: caemos al viejo criterio
                # (ASTC "a ojo" por tamaño) solo para no dejar la vista completamente en blanco.
                bloque_estimado = detectar_bloque_astc(ancho, alto, tamano_bytes)
                bx, by = map(int, bloque_estimado.split('x'))
                ax, ay = ((ancho + bx - 1) // bx) * bx, ((alto + by - 1) // by) * by
                bytes_necesarios = (ax // bx) * (ay // by) * 16
                d = datos[:bytes_necesarios] + b'\x00' * max(0, bytes_necesarios - len(datos))
                bgra = texture2ddecoder.decode_astc(d, ax, ay, bx, by) if texture2ddecoder else None
                if bgra is None:
                    obtener_imagen_notload().save(ruta_png_temp)
                    _registrar_diagnostico(self, ruta_raw, "fmt no catalogado y el tamaño no coincide con ningún formato conocido (ASTC/ETC2/BC)")
                    return Path(ruta_png_temp).exists()
                img_decodificada = Image.frombytes("RGBA", (ax, ay), bgra, "raw", "BGRA")
                if (ax, ay) != (ancho, alto): img_decodificada = img_decodificada.crop((0, 0, ancho, alto))
                motivo_vacio = "" if rapido else "; se probaron ASTC/ETC2/BC y ninguno calzó en tamaño"
                _registrar_diagnostico(self, ruta_raw, f"fmt no catalogado{motivo_vacio}, se usó ASTC {bloque_estimado} a ojo (sin certeza)")
            else:
                img_decodificada, descripcion, puntaje = resultado
                if puntaje > UMBRAL_SOSPECHA_DECODIFICACION:
                    _registrar_diagnostico(self, ruta_raw, f"fmt no catalogado; el mejor intento fue {descripcion} pero con ~{puntaje*100:.0f}% de bloques de error (dato incierto)")
                else:
                    _registrar_diagnostico(self, ruta_raw, f"fmt no catalogado; identificado automáticamente por tamaño como {descripcion}")
            img_decodificada.save(ruta_png_temp)
            return Path(ruta_png_temp).exists()

        # --- FORMATOS ASTC CATALOGADOS ---
        bloque_real = info_formato["bloque"]
        bx, by = map(int, bloque_real.split('x'))
        ax = ((ancho + bx - 1) // bx) * bx
        ay = ((alto + by - 1) // by) * by
        bloques_ancho = ax // bx
        bloques_alto = ay // by
        bytes_necesarios = bloques_ancho * bloques_alto * 16

        # Archivo vacío o demasiado chico para contener ni un solo bloque: no es
        # un problema de decodificación, es que no hay datos que decodificar.
        if tamano_bytes < 16:
            obtener_imagen_notload().save(ruta_png_temp)
            _registrar_diagnostico(self, ruta_raw, f"archivo vacío o incompleto ({tamano_bytes} bytes; se esperaban {bytes_necesarios})")
            return Path(ruta_png_temp).exists()

        if texture2ddecoder is None:
            raise RuntimeError("Falta el paquete 'texture2ddecoder' (pip install texture2ddecoder)")

        aplica_desentrelazado = (getattr(self, 'unswizzle_activo', False)
                                  and tamano_bytes == bytes_necesarios and bloques_ancho > 16)

        def _decodificar(datos_entrada, con_swizzle):
            d = _desentrelazar_bloques_astc(datos_entrada, bloques_ancho, bloques_alto) if con_swizzle else datos_entrada
            d = d[:bytes_necesarios]
            if len(d) < bytes_necesarios:
                d = d + b'\x00' * (bytes_necesarios - len(d))
            bgra = texture2ddecoder.decode_astc(d, ax, ay, bx, by)
            img = Image.frombytes("RGBA", (ax, ay), bgra, "raw", "BGRA")
            return img.crop((0, 0, ancho, alto)) if (ax, ay) != (ancho, alto) else img

        img_decodificada = _decodificar(datos, aplica_desentrelazado)
        puntaje = _puntaje_sospecha_decodificacion(img_decodificada)

        # Reintento automático: si el resultado tiene pinta de bloques inválidos,
        # se prueba UNA vez la otra variante (con/sin desentrelazado) y se usa la
        # que dé menos bloques de error. Solo aplica si el tamaño calza exacto con
        # bloques completos -si no, "la otra variante" no tiene sentido-, y solo
        # en modo no-rápido (ver nota en la firma de la función).
        motivo_diagnostico = None
        if not rapido and puntaje > UMBRAL_SOSPECHA_DECODIFICACION and tamano_bytes == bytes_necesarios and bloques_ancho > 16:
            img_alt = _decodificar(datos, not aplica_desentrelazado)
            puntaje_alt = _puntaje_sospecha_decodificacion(img_alt)
            if puntaje_alt < puntaje:
                img_decodificada, puntaje = img_alt, puntaje_alt
                motivo_diagnostico = f"se corrigió automáticamente probando {'con' if not aplica_desentrelazado else 'sin'} desentrelazado Android"
        if puntaje > UMBRAL_SOSPECHA_DECODIFICACION and motivo_diagnostico is None:
            motivo_diagnostico = f"posible decodificación inválida (~{puntaje*100:.0f}% de bloques de error) — probar otro bloque/formato o revisar si el archivo está completo"

        _registrar_diagnostico(self, ruta_raw, motivo_diagnostico)
        img_decodificada.save(ruta_png_temp)
        return Path(ruta_png_temp).exists()
    except Exception:
        return False

def png_a_astc_raw(ruta_png, ruta_raw_salida, bloque):
    tmp_out = Path(ruta_raw_salida).with_suffix('.tmp_out.astc')
    try:
        r = subprocess.run([obtener_ruta_recurso("astcenc.exe"), "-cl", str(ruta_png), str(tmp_out), bloque, "-medium"], capture_output=True, text=True)
        if r.returncode != 0: raise Exception(r.stderr)
        Path(ruta_raw_salida).write_bytes(tmp_out.read_bytes()[16:])
        if tmp_out.exists(): tmp_out.unlink()
        return True
    except Exception as e:
        if tmp_out.exists(): tmp_out.unlink()
        messagebox.showerror("Error ASTC", f"Fallo en compresión:\n{e}")
        return False

# --- REEMPLAZO DE TEXTURAS: CODIFICAR EN EL MISMO FORMATO QUE EL ORIGINAL ---
# Un .raw debe conservar formato y tamaño exactos, porque el juego lo lee tal cual.
# Antes se comprimía SIEMPRE a ASTC, y eso rompía las texturas de otros formatos
# (ej. RGBA8 plano: se escribían bytes ASTC que luego se leían como píxeles).
def _a_u8(arr, dtype):
    return (arr.astype(np.uint32) * 255 // 65535).astype(np.uint8) if np.dtype(dtype).itemsize == 2 else arr.astype(np.uint8)

def png_a_raw_segun_formato(ruta_png, ruta_raw_salida, info_formato, ancho, alto, datos_originales):
    tipo = info_formato["tipo"] if info_formato else None

    # --- ASTC: el bloque sale del código fmt del archivo, no de una suposición ---
    if tipo == "astc":
        return png_a_astc_raw(ruta_png, ruta_raw_salida, info_formato["bloque"])

    # --- Formato desconocido: solo si el tamaño calza con algún bloque ASTC ---
    if info_formato is None:
        bloque = detectar_bloque_astc(ancho, alto, len(datos_originales), None)
        if bloque is None:
            messagebox.showerror("Formato no soportado", "No reconozco el formato de esta textura (fmt no catalogado) y su tamaño no coincide con ASTC. No se aplicó el reemplazo.")
            return False
        return png_a_astc_raw(ruta_png, ruta_raw_salida, bloque)

    # --- Formatos planos enteros (UNORM/SRGB): se reescriben píxel a píxel ---
    if tipo == "plano":
        dt = np.dtype(info_formato["dtype"]) if np is not None else None
        if np is None or dt.kind != "u":
            messagebox.showerror("Formato no soportado", f"El reemplazo de {info_formato['nombre']} no está soportado (los formatos de punto flotante no son imágenes que se puedan reconstruir desde un PNG). No se aplicó el reemplazo.")
            return False
        img = Image.open(ruta_png).convert("RGBA")
        if img.size != (ancho, alto): img = img.resize((ancho, alto), Image.Resampling.LANCZOS)
        rgba = np.array(img)
        canales = info_formato["canales"]
        pos = {"R": 0, "G": 1, "B": 2, "A": 3}
        if len(canales) == 1:
            # Un solo canal: si el original era una máscara (atlas de fuente) y el PNG trae
            # alfa real, se usa el alfa; en cualquier otro caso, la luminancia.
            orig = np.frombuffer(datos_originales[:ancho * alto * dt.itemsize], dtype=dt)
            orig_u8 = _a_u8(orig, dt) if orig.size == ancho * alto else np.zeros(1, dtype=np.uint8)
            if _parece_mascara_alfa(orig_u8) and rgba[:, :, 3].min() < 255:
                plano = rgba[:, :, 3][:, :, None]
            else:
                plano = np.array(img.convert("L"))[:, :, None]
        else:
            plano = np.stack([rgba[:, :, pos[c]] for c in canales], axis=2)
        if dt.itemsize == 2: plano = plano.astype(np.uint16) * 257
        Path(ruta_raw_salida).write_bytes(np.ascontiguousarray(plano.astype(dt)).tobytes())
        return True

    # --- ETC2 y otros: no hay codificador incluido ---
    messagebox.showerror("Formato no soportado", f"El reemplazo de {info_formato['nombre']} no está soportado todavía (no hay un codificador para ese formato incluido en la herramienta). No se aplicó el reemplazo, para no dejar un archivo corrupto.")
    return False

# --- TEMA OSCURO GLOBAL ---
# El tema nativo de Windows ("vista"/"xpnative") no se puede recolorear porque
# dibuja los widgets con el motor nativo de Windows; "clam" es el tema de ttk
# que sí se puede personalizar por completo. Los widgets tk "crudos" (Listbox,
# Text, Canvas) no seguían ningún tema de todos modos, así que llevan su color
# puesto directamente donde se crean.
PALETA_OSCURA = {
    "fondo": "#1e1e1e", "panel": "#2d2d2d", "borde": "#3c3c3c",
    "texto": "#d4d4d4", "acento": "#0e639c", "entrada": "#2b2b2b",
}

def aplicar_tema_oscuro(root):
    p = PALETA_OSCURA
    root.configure(background=p["fondo"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass  # si "clam" no está disponible en este Tcl/Tk, se sigue con el tema por defecto
    style.configure(".", background=p["fondo"], foreground=p["texto"], fieldbackground=p["entrada"])
    style.configure("TFrame", background=p["fondo"])
    style.configure("TLabel", background=p["fondo"], foreground=p["texto"])
    style.configure("TButton", background=p["panel"], foreground=p["texto"], bordercolor=p["borde"], focusthickness=1, focuscolor=p["acento"])
    style.map("TButton", background=[("active", p["acento"])], foreground=[("active", "#ffffff")])
    style.configure("TEntry", fieldbackground=p["entrada"], foreground=p["texto"], insertcolor=p["texto"], bordercolor=p["borde"])
    style.configure("TCombobox", fieldbackground=p["entrada"], foreground=p["texto"], background=p["panel"], arrowcolor=p["texto"], bordercolor=p["borde"])
    style.map("TCombobox", fieldbackground=[("readonly", p["entrada"])], foreground=[("readonly", p["texto"])])
    root.option_add("*TCombobox*Listbox.background", p["entrada"])
    root.option_add("*TCombobox*Listbox.foreground", p["texto"])
    style.configure("TCheckbutton", background=p["fondo"], foreground=p["texto"])
    style.map("TCheckbutton", background=[("active", p["fondo"])])
    style.configure("TNotebook", background=p["fondo"], bordercolor=p["borde"])
    style.configure("TNotebook.Tab", background=p["panel"], foreground=p["texto"], padding=(10, 4))
    style.map("TNotebook.Tab", background=[("selected", p["acento"])], foreground=[("selected", "#ffffff")])
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=p["panel"], troughcolor=p["fondo"], bordercolor=p["borde"], arrowcolor=p["texto"])

# Parte 5
class AppMultiherramienta:
    def __init__(self, root):
        self.root = root
        # El exportador de modelos reutiliza el mismo decodificador que el visor.
        self.decode_texture_to_png = lambda ruta, salida: astc_raw_a_png(self, ruta, salida)
        self.root.title("XXAMI: DUMP Manager")
        self.root.geometry("1250x780")
        self.ruta_spv_actual, self.ruta_raw_actual, self.ruta_obj_actual, self.archivos_mapeados = None, None, None, {}
        self.etapa_shader_actual = None
        
        self.img_cache = Path(tempfile.gettempdir()).joinpath("temp_preview_cache.png")
        self.dir_cache_thumbs = Path(tempfile.gettempdir()).joinpath("multiherramienta_thumbs")
        self.dir_cache_thumbs.mkdir(exist_ok=True)
        
        self.texturas_reemplazadas = {}  
        self.directorio_temp_raws = Path(tempfile.gettempdir()).joinpath("multiherramienta_raws_cache")
        self.directorio_temp_raws.mkdir(exist_ok=True)
        
        # Control de concurrencia para la generación de miniaturas: evita que
        # hilos viejos (de una búsqueda o carpeta anterior) sigan insertando
        # widgets en una grilla que ya no corresponde, lo que agotaba los
        # handles GDI de Windows y terminaba cerrando la app.
        # Diagnóstico de la última decodificación de cada .raw: None = sin problemas,
        # o un texto explicando qué se sospecha que salió mal. Lo llena astc_raw_a_png.
        self._diagnostico_textura = {}
        self.generacion_miniaturas = 0
        # Cola hilo->UI: el hilo de fondo solo entrega imágenes PIL; TODO lo de Tk
        # (PhotoImage, canvas, labels) se hace en el hilo principal.
        self.cola_miniaturas = queue.Queue(maxsize=200)
        self.root.after(50, self._procesar_cola_miniaturas)
        self._id_debounce_busqueda = None
        
        pe = ttk.Frame(root, padding=10, width=340)
        pe.pack(side="left", fill="y")
        pe.pack_propagate(False)
        ttk.Label(pe, text="Explorador de Volcados", font=("Arial", 11, "bold")).pack(anchor="w", pady=5)
        ttk.Button(pe, text="Seleccionar Carpeta Raíz", command=self.cargar_carpeta).pack(fill="x", pady=5)
        ttk.Button(pe, text="💾 Guardar Texturas Reemplazadas", command=self.exportar_bloque_reemplazos).pack(fill="x", pady=5)
        
        frame_busqueda = ttk.Frame(pe)
        frame_busqueda.pack(fill="x", pady=(10, 2))
        ttk.Label(frame_busqueda, text="🔍 Buscar:", font=("Arial", 9)).pack(side="left", padx=(0, 5))
# Parte 6
        self.sv_busqueda = tk.StringVar()
        self.sv_busqueda.trace_add("write", self.on_escribir_busqueda)
        self.entry_busqueda = ttk.Entry(frame_busqueda, textvariable=self.sv_busqueda)
        self.entry_busqueda.pack(side="right", expand=True, fill="x")
        
        self.sub_tabs = ttk.Notebook(pe)
        self.tab_sub_shaders = ttk.Frame(self.sub_tabs)
        self.tab_sub_texturas = ttk.Frame(self.sub_tabs)
        self.tab_sub_modelos = ttk.Frame(self.sub_tabs)
        
        self.sub_tabs.add(self.tab_sub_shaders, text="Shaders")
        self.sub_tabs.add(self.tab_sub_texturas, text="Texturas")
        self.sub_tabs.add(self.tab_sub_modelos, text="Modelos")
        self.sub_tabs.pack(expand=True, fill="both", pady=5)
        
        fl_s = ttk.Frame(self.tab_sub_shaders)
        fl_s.pack(expand=True, fill="both")
        sl_s = ttk.Scrollbar(fl_s, orient="vertical")
        self.lista_shaders = tk.Listbox(fl_s, yscrollcommand=sl_s.set, font=("Consolas", 9), background="#2b2b2b", foreground="#ffffff")
        sl_s.config(command=self.lista_shaders.yview)
        sl_s.pack(side="right", fill="y")
        self.lista_shaders.pack(side="left", expand=True, fill="both")
        self.lista_shaders.bind("<<ListboxSelect>>", lambda e: self.on_seleccionar_lista(self.lista_shaders))
        
        self.nb_modelos = ttk.Notebook(self.tab_sub_modelos)
        self.nb_modelos.pack(expand=True, fill="both")
        self.tab_archivos_sueltos = ttk.Frame(self.nb_modelos)
        self.tab_modelo_empaquetado = ttk.Frame(self.nb_modelos)
        self.nb_modelos.add(self.tab_archivos_sueltos, text="Archivos sueltos")
        self.nb_modelos.add(self.tab_modelo_empaquetado, text="Modelo empaquetado")

        fl_m = ttk.Frame(self.tab_archivos_sueltos)
        fl_m.pack(expand=True, fill="both")
        sl_m = ttk.Scrollbar(fl_m, orient="vertical")
        self.lista_modelos = tk.Listbox(fl_m, yscrollcommand=sl_m.set, font=("Consolas", 9), background="#2b2b2b", foreground="#ffffff")
        sl_m.config(command=self.lista_modelos.yview)
        sl_m.pack(side="right", fill="y")
        self.lista_modelos.pack(side="left", expand=True, fill="both")
        self.lista_modelos.bind("<<ListboxSelect>>", lambda e: self.on_seleccionar_lista(self.lista_modelos))

        barra_paquete = ttk.Frame(self.tab_modelo_empaquetado, padding=4)
        barra_paquete.pack(fill="x")
        ttk.Label(barra_paquete, text="Modelo:").pack(side="left")
        self.cb_modelo_empaquetado = ttk.Combobox(barra_paquete, state="readonly")
        self.cb_modelo_empaquetado.pack(side="left", fill="x", expand=True, padx=5)
        self.cb_modelo_empaquetado.bind("<<ComboboxSelected>>", lambda e: self._mostrar_archivos_modelo())
        ttk.Button(barra_paquete, text="Parsear volcado de modelo", command=self.parsear_volcado_modelo).pack(side="right")
        marco_archivos_paquete = ttk.Frame(self.tab_modelo_empaquetado)
        marco_archivos_paquete.pack(expand=True, fill="both")
        sb_paquete = ttk.Scrollbar(marco_archivos_paquete, orient="vertical")
        self.lista_archivos_modelo = tk.Listbox(marco_archivos_paquete, yscrollcommand=sb_paquete.set,
                                                font=("Consolas", 9), background="#2b2b2b", foreground="#ffffff")
        sb_paquete.config(command=self.lista_archivos_modelo.yview)
        sb_paquete.pack(side="right", fill="y")
        self.lista_archivos_modelo.pack(side="left", expand=True, fill="both")
        self.lista_archivos_modelo.bind("<<Double-Button-1>>", lambda e: self._abrir_archivo_modelo_seleccionado())
# Parte 7
        fl_t = ttk.Frame(self.tab_sub_texturas)
        fl_t.pack(expand=True, fill="both")
        self.lbl_loading_thumbs = ttk.Label(fl_t, text="", font=("Arial", 9, "italic"), foreground="#00ff66")
        self.lbl_loading_thumbs.pack(side="top", fill="x", pady=2)
        
        # NOTA DE ESCALABILIDAD: las miniaturas se dibujan como ítems del
        # propio Canvas (create_image/create_rectangle/create_text), NO como
        # widgets Frame/Button/Label independientes. Un dump real puede traer
        # miles de texturas, y cada widget nativo consume un handle GDI/USER
        # de Windows (límite ~10.000 por proceso); con miles de texturas eso
        # agotaba el límite y corrompía/cerraba la ventana. Los ítems de
        # Canvas no consumen handles propios, así que esto escala sin límite.
        self.canvas_thumbs = tk.Canvas(fl_t, background="#1e1e1e", highlightthickness=0)
        sl_t = ttk.Scrollbar(fl_t, orient="vertical", command=self.canvas_thumbs.yview)
        self.canvas_thumbs.config(yscrollcommand=sl_t.set)
        sl_t.pack(side="right", fill="y")
        self.canvas_thumbs.pack(side="left", expand=True, fill="both")
        self.canvas_thumbs.bind("<MouseWheel>", lambda e: self.canvas_thumbs.yview_scroll(int(-e.delta / 60), "units"))
        self.id_rect_seleccionado = None
        
        self.tabs = ttk.Notebook(root)
        self.tab_s, self.tab_a, self.tab_3d = ttk.Frame(self.tabs), ttk.Frame(self.tabs), ttk.Frame(self.tabs)
        self.tabs.add(self.tab_s, text=" Editor Shader SPIR-V ")
        self.tabs.add(self.tab_a, text=" Visor / Conversor Texturas RAW ASTC ")
        self.tabs.add(self.tab_3d, text=" Visor Geometría 3D (.OBJ) ")
        self.tabs.pack(side="right", expand=True, fill="both", padx=5, pady=5)
        self.thumb_refs = []
# Parte 8
    def construir_pestana_shader(self):
        fb = ttk.Frame(self.tab_s, padding=5)
        fb.pack(side="top", fill="x")
        ttk.Button(fb, text="Guardar y Recompilar (.spv)", command=self.guardar_shader).pack(side="left", padx=5)
        self.lbl_s = ttk.Label(fb, text="Selecciona un archivo .spv de la lista", font=("Arial", 9, "italic"))
        self.lbl_s.pack(side="right", padx=10)
        self.editor = tk.Text(self.tab_s, font=("Consolas", 11), wrap="none", undo=True,
                               background="#1e1e1e", foreground="#d4d4d4", insertbackground="#ffffff",
                               selectbackground="#264f78", selectforeground="#ffffff")
        configurar_tags_glsl(self.editor)
        self._id_debounce_resaltado = None
        self.editor.bind("<KeyRelease>", self._on_editar_glsl)
        s_y = ttk.Scrollbar(self.tab_s, orient="vertical", command=self.editor.yview)
        s_x = ttk.Scrollbar(self.tab_s, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=s_y.set, xscrollcommand=s_x.set)
        s_y.pack(side="right", fill="y")
        s_x.pack(side="bottom", fill="x")
        self.editor.pack(expand=True, fill="both", padx=5, pady=5)

    def _on_editar_glsl(self, evento=None):
        # Antirrebote: resaltar en cada tecla sería innecesariamente costoso en
        # archivos largos; se espera una pausa corta antes de recolorear.
        if self._id_debounce_resaltado is not None:
            self.root.after_cancel(self._id_debounce_resaltado)
        self._id_debounce_resaltado = self.root.after(250, lambda: _resaltar_glsl(self.editor))
        
    def construir_pestana_astc(self):
        fbc = ttk.Frame(self.tab_a, padding=5)
        fbc.pack(side="top", fill="x")
        ttk.Button(fbc, text="Exportar a PNG", command=self.exportar_png).pack(side="left", padx=5)
        ttk.Button(fbc, text="🔄 Reemplazar por PNG externo", command=self.reemplazar_textura_por_png).pack(side="left", padx=15)
        
        self.var_unswizzle = tk.BooleanVar(value=False)
        # Copia en un bool normal de Python: los hilos de fondo NO pueden leer variables de Tk.
        self.unswizzle_activo = False
        self.var_unswizzle.trace_add("write", lambda *a: setattr(self, "unswizzle_activo", bool(self.var_unswizzle.get())))
        self.check_unswizzle = ttk.Checkbutton(fbc, text="Desentrelazar (Android)", variable=self.var_unswizzle, command=self.forzar_refresco_por_checkbox)
        self.check_unswizzle.pack(side="left", padx=10)
        
        ttk.Label(fbc, text="Bloque Destino:").pack(side="left", padx=(10, 5))
        self.cb = ttk.Combobox(fbc, values=["4x4", "5x5", "6x6", "8x8"], state="readonly", width=8)
        self.cb.set("4x4")
        self.cb.pack(side="left", padx=5)
        ttk.Button(fbc, text="Convertir PNG a .raw", command=self.importar_png).pack(side="left", padx=5)
        
        pd = tk.Frame(self.tab_a, background="#212121")
        pd.pack(expand=True, fill="both", padx=5, pady=5)
        self.p_img = ttk.Label(pd, text="Selecciona una textura .raw", anchor="center", background="#212121", foreground="white")
        self.p_img.pack(side="top", expand=True, fill="both", padx=5, pady=5)
        self.p_txt = tk.Label(pd, text="[ NINGUNA TEXTURA CARGADA ]", anchor="w", justify="left", background="#1a1a1a", foreground="#00ff66", font=("Consolas", 10), padx=15, pady=12, bd=1, relief="solid")
        self.p_txt.pack(side="bottom", fill="x", padx=5, pady=5)
        self.p_txt.bind("<Configure>", lambda e: self.p_txt.config(wraplength=e.width - 30) if e.width > 100 else None)

    def construir_pestana_3d(self):
        fb3 = ttk.Frame(self.tab_3d, padding=5)
        fb3.pack(side="top", fill="x")
        self.lbl_3d = ttk.Label(fb3, text="Selecciona un modelo .obj de la lista lateral", font=("Arial", 9, "italic"))
        self.lbl_3d.pack(side="left", padx=10)
        self.canvas_3d = tk.Canvas(self.tab_3d, background="#111111", highlightthickness=0)
        self.canvas_3d.pack(expand=True, fill="both", padx=5, pady=5)
        self.canvas_3d.create_text(20, 20, text="Controles:\nArrastrar Clic Izquierdo -> Rotar Modelo\nScroll Mouse -> Zoom", fill="#888888", anchor="nw", font=("Arial", 9))
        self.vertices_3d, self.caras_3d, self.zoom_3d = [], [], 50.0
        self.rot_x, self.rot_y, self.last_mouse_x, self.last_mouse_y = 0.0, 0.0, 0, 0
        self.canvas_3d.bind("<Button-1>", self.start_pan_3d)
        self.canvas_3d.bind("<B1-Motion>", self.rotate_mesh_3d)
        self.canvas_3d.bind("<MouseWheel>", self.zoom_mesh_3d)

    def filtrar_lista(self, *args): self.actualizar_interfaz_explorador()

    def on_escribir_busqueda(self, *args):
        # Antirrebote: si el usuario sigue escribiendo, cancela la
        # regeneración pendiente en vez de apilar un hilo por cada tecla.
        if self._id_debounce_busqueda is not None:
            self.root.after_cancel(self._id_debounce_busqueda)
        self._id_debounce_busqueda = self.root.after(250, self._ejecutar_filtro_diferido)

    def _ejecutar_filtro_diferido(self):
        self._id_debounce_busqueda = None
        self.actualizar_interfaz_explorador()
# Parte 9
    def cargar_carpeta(self):
        dir_raiz = filedialog.askdirectory()
        if dir_raiz:
            self.dir_raiz_volcado = Path(dir_raiz)
            self.entry_busqueda.delete(0, tk.END)
            self.archivos_mapeados.clear()
            self.texturas_reemplazadas.clear()
            self.id_rect_seleccionado = None
            for archivo_viejo in self.dir_cache_thumbs.glob("*.png"):
                try: archivo_viejo.unlink()
                except: pass
            items = []
            for ext in ('*.spv', '*.raw', '*.ktx2', '*.buf'): items.extend(Path(dir_raiz).rglob(ext))
            if not items:
                messagebox.showinfo("Búsqueda", "No se encontraron archivos.")
                return

            # Si TODOS los .raw de la carpeta siguen el patrón corto "tex_hash.raw" (el
            # que genera "Guardar Texturas Reemplazadas") y hay un indexes.txt, se usan
            # para recuperar el nombre completo (dimensiones/formato) de cada uno. Si un
            # solo .raw no sigue ese patrón, se descarta esto por completo y se procede
            # como siempre -para no aplicar esta reinterpretación sobre un dump normal
            # por error, p.ej. si justo tuviera un indexes.txt perdido de otra sesión-.
            raws = [p for p in items if p.suffix.lower() == ".raw"]
            patron_corto = re.compile(r'^tex_[0-9a-fA-F]+\.raw$', re.IGNORECASE)
            dir_resueltos = self.directorio_temp_raws / "resueltos_por_indice"
            for viejo in dir_resueltos.glob("*") if dir_resueltos.exists() else []:
                try: viejo.unlink()
                except Exception: pass
            if raws and all(patron_corto.match(p.name) for p in raws):
                rutas_indice = list(Path(dir_raiz).rglob("indexes.txt"))
                mapa_corto_a_completo = {}
                if rutas_indice:
                    try:
                        for linea in rutas_indice[0].read_text(encoding="utf-8").splitlines():
                            if " = " in linea:
                                completo, corto = linea.split(" = ", 1)
                                mapa_corto_a_completo[corto.strip().lower()] = completo.strip()
                    except Exception:
                        mapa_corto_a_completo = {}
                if mapa_corto_a_completo:
                    dir_resueltos.mkdir(parents=True, exist_ok=True)
                    items_resueltos = []
                    for p in items:
                        nombre_real = mapa_corto_a_completo.get(p.name.lower()) if p in raws else None
                        if nombre_real:
                            destino = dir_resueltos / nombre_real
                            try:
                                destino.write_bytes(p.read_bytes())
                                items_resueltos.append(destino)
                            except Exception:
                                items_resueltos.append(p)  # si falla la copia, se ve con su nombre corto (sin resolver), no se pierde
                        else:
                            items_resueltos.append(p)
                    items = items_resueltos

            for p in sorted(items, key=lambda x: x.name.lower()):
                # El hash va en el nombre (mismo nombre = mismo contenido): una sola entrada. No aplica a
                # las texturas de Models/ (Part00Tex0.ktx2...): el mismo nombre en otra captura es OTRA textura.
                es_repetible = p.suffix.lower() == '.buf' or (p.suffix.lower() == '.ktx2' and p.name.lower().startswith('tex_'))
                if es_repetible and p.name in self.archivos_mapeados: continue
                lbl = f"{p.parent.name}/{p.name}" if p.name in self.archivos_mapeados else p.name
                if lbl in self.archivos_mapeados: lbl = f"{p.parent.parent.name}/{p.parent.name}/{p.name}"
                self.archivos_mapeados[lbl] = str(p)
            self.actualizar_interfaz_explorador()
            self._cargar_modelos_empaquetados()
            if getattr(self, "pestana_trace", None):
                try: self.pestana_trace.cargar_raiz(dir_raiz)
                except Exception: _log(traceback.format_exc())

    def _cargar_modelos_empaquetados(self):
        """Indexa Models/Model_NN de todas las capturas sin duplicar entradas por cada Part."""
        self._modelos_empaquetados = {}
        if not hasattr(self, "cb_modelo_empaquetado"):
            return
        self.cb_modelo_empaquetado.set("")
        self.cb_modelo_empaquetado["values"] = ()
        self.lista_archivos_modelo.delete(0, tk.END)
        raiz = getattr(self, "dir_raiz_volcado", None)
        if not raiz or not raiz.exists():
            return
        for carpeta_models in sorted(raiz.rglob("Models"), key=lambda p: str(p).lower()):
            if not carpeta_models.is_dir():
                continue
            submodelos = sorted((p for p in carpeta_models.iterdir() if p.is_dir() and re.match(r"^Model_\d+$", p.name, re.I)),
                                key=lambda p: p.name.lower())
            if submodelos:
                for sub in submodelos:
                    etiqueta = str(sub.relative_to(raiz))
                    self._modelos_empaquetados[etiqueta] = sub
            elif any(p.is_file() and p.name.lower().startswith("part") and p.suffix.lower() == ".buf" for p in carpeta_models.iterdir()):
                etiqueta = str(carpeta_models.relative_to(raiz))
                self._modelos_empaquetados[etiqueta] = carpeta_models
        valores = list(self._modelos_empaquetados)
        self.cb_modelo_empaquetado["values"] = valores
        if valores:
            self.cb_modelo_empaquetado.current(0)
            self._mostrar_archivos_modelo()
        else:
            self.lista_archivos_modelo.insert(tk.END, "(No se encontraron Models/Model_NN en esta carpeta)")

    def _ruta_modelo_empaquetado(self):
        etiqueta = self.cb_modelo_empaquetado.get()
        return getattr(self, "_modelos_empaquetados", {}).get(etiqueta)

    def _mostrar_archivos_modelo(self):
        self.lista_archivos_modelo.delete(0, tk.END)
        carpeta = self._ruta_modelo_empaquetado()
        if not carpeta:
            return
        for ruta in sorted((p for p in carpeta.rglob("*") if p.is_file()), key=lambda p: str(p).lower()):
            self.lista_archivos_modelo.insert(tk.END, str(ruta.relative_to(carpeta)))

    def _abrir_archivo_modelo_seleccionado(self):
        sel = self.lista_archivos_modelo.curselection()
        carpeta = self._ruta_modelo_empaquetado()
        if not sel or not carpeta:
            return
        ruta = carpeta / self.lista_archivos_modelo.get(sel[0])
        if ruta.is_file():
            self.abrir_archivo_por_ruta(str(ruta))

    def parsear_volcado_modelo(self):
        """Convierte texturas KTX2/RAW del modelo a PNG, conservando originales y nombres/slots."""
        carpeta = self._ruta_modelo_empaquetado()
        if not carpeta or not carpeta.is_dir():
            messagebox.showinfo("Parsear volcado de modelo", "Selecciona un modelo empaquetado válido.")
            return
        decodificador = getattr(self, "decode_texture_to_png", None)
        if decodificador is None:
            messagebox.showerror("Parsear volcado de modelo", "El decodificador de texturas no está disponible.")
            return
        texturas = sorted((p for p in carpeta.rglob("*") if p.is_file() and p.suffix.lower() in (".ktx2", ".raw")),
                          key=lambda p: str(p).lower())
        if not texturas:
            messagebox.showinfo("Parsear volcado de modelo", "Este modelo no contiene texturas .ktx2 ni .raw.")
            return
        convertidas, omitidas, errores = 0, 0, []
        for textura in texturas:
            # Un PNG por archivo fuente conserva el nombre del slot (Part00Diffuse,
            # Part00BumpMap, etc.); los originales y sus hashes no se alteran.
            destino = textura.with_suffix(".png")
            try:
                if destino.exists():
                    omitidas += 1
                    continue
                if decodificador(str(textura), str(destino)):
                    convertidas += 1
                else:
                    errores.append(f"{textura.name}: el decodificador no pudo convertirla")
            except Exception as e:
                errores.append(f"{textura.name}: {e}")
        self._mostrar_archivos_modelo()
        resumen = f"PNG creados: {convertidas}. Ya existentes/duplicados omitidos: {omitidas}."
        if errores:
            resumen += "\n\nAvisos:\n" + "\n".join(errores[:12])
        messagebox.showinfo("Parsear volcado de modelo", resumen)

    def actualizar_interfaz_explorador(self):
        self.lista_shaders.delete(0, tk.END)
        self.lista_modelos.delete(0, tk.END)
        self.canvas_thumbs.delete("all")
        self.id_rect_seleccionado = None
        self.thumb_refs.clear()
        texto_filtro = self.sv_busqueda.get().lower().strip()
        claves_texturas = []
        
        # FIJADO DEFINITIVO Y PROBADO: Usamos x[0] para extraer el string del nombre visual de la tupla
        for lbl, ruta in sorted(self.archivos_mapeados.items(), key=lambda x: x[0].lower()):
            if texto_filtro and texto_filtro not in lbl.lower(): continue
            if ruta.endswith('.spv'): self.lista_shaders.insert(tk.END, f" 📄 {lbl}")
            elif ruta.endswith(('.buf', '.txt', '.json')):
                if ruta.endswith('.buf') and es_modelo_listable(ruta):
                    self.lista_modelos.insert(tk.END, f" 📄 {lbl}")
                elif ruta.endswith(('.txt', '.json')):
                    self.lista_modelos.insert(tk.END, f" 📄 {lbl}")
            elif ruta.endswith(('.raw', '.ktx2')): claves_texturas.append(lbl)

        # Límite de seguridad por GDI: cada miniatura necesita un PhotoImage, y eso
        # consume un recurso de Windows (GDI) con su propio cupo (~10.000 por
        # proceso), aparte del límite de handles de ventana que ya se resolvió al
        # pasar a dibujar sobre un Canvas. Si no se pone un techo, un dump sin
        # filtrar con más texturas que ese cupo agota GDI y Windows corrompe/cierra
        # la ventana (el "fail allocate bitmap" del error reportado). Con una
        # búsqueda que acote el resultado, este límite no debería tocarse nunca.
        total_coincidencias = len(claves_texturas)
        if total_coincidencias > MAX_MINIATURAS_POR_VISTA:
            claves_texturas = claves_texturas[:MAX_MINIATURAS_POR_VISTA]

        # Cada regeneración de la grilla invalida cualquier hilo anterior:
        # los hilos viejos verán que su número de generación ya no coincide
        # y dejarán de tocar la UI, aunque sigan corriendo hasta el final.
        self.generacion_miniaturas += 1
        generacion_actual = self.generacion_miniaturas
        if claves_texturas:
            if total_coincidencias > MAX_MINIATURAS_POR_VISTA:
                self.lbl_loading_thumbs.config(text=f"🔄 Generando miniaturas... (mostrando {MAX_MINIATURAS_POR_VISTA} de {total_coincidencias} — afiná la búsqueda para ver el resto)")
            else:
                self.lbl_loading_thumbs.config(text="🔄 Generando miniaturas...")
            truncado = total_coincidencias > MAX_MINIATURAS_POR_VISTA
            threading.Thread(target=self.hilo_generar_miniaturas, args=(claves_texturas, generacion_actual, truncado, total_coincidencias), daemon=True).start()
        else:
            self.lbl_loading_thumbs.config(text="")

    def _encolar_miniatura(self, item, generacion):
        # put() con timeout: si la cola está llena esperamos, pero abandonamos apenas
        # esta generación quede obsoleta (búsqueda/carpeta nueva).
        while generacion == self.generacion_miniaturas:
            try:
                self.cola_miniaturas.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def hilo_generar_miniaturas(self, lista_claves, generacion, truncado=False, total_coincidencias=None):
        # REGLA: este hilo NO puede tocar nada de Tk (ni PhotoImage, ni after(), ni
        # variables Tk). Tkinter no es seguro entre hilos y hacerlo provoca cierres
        # aleatorios. Solo produce imágenes PIL y las entrega por la cola.
        columnas_maximas = 2
        for idx, lbl in enumerate(lista_claves):
            if generacion != self.generacion_miniaturas: return  # una búsqueda/carpeta nueva canceló este hilo
            try:
                ruta_raw = self.archivos_mapeados.get(lbl)
                if not ruta_raw or not os.path.exists(ruta_raw): continue
                ruta_thumb_png = self.dir_cache_thumbs.joinpath(f"thumb_{Path(ruta_raw).stem}.png")
                if not ruta_thumb_png.exists():
                    ruta_lectura = self.texturas_reemplazadas.get(ruta_raw, ruta_raw)
                    astc_raw_a_png(self, ruta_lectura, str(ruta_thumb_png), rapido=True)
                if ruta_thumb_png.exists():
                    with Image.open(str(ruta_thumb_png)) as im:
                        img_p = im.copy()
                    img_p.thumbnail((80, 80))
                    img_final = componer_sobre_tablero(img_p, 6)
                    if not self._encolar_miniatura(("thumb", lbl, img_final, idx, columnas_maximas, generacion), generacion): return
            except Exception:
                continue
        self._encolar_miniatura(("fin", generacion, truncado, total_coincidencias), generacion)

    def _procesar_cola_miniaturas(self):
        # Corre SIEMPRE en el hilo principal (vía after). Procesa un lote pequeño por
        # ciclo para que la interfaz siga fluida aunque lleguen miles de miniaturas.
        try:
            for _ in range(12):
                try:
                    item = self.cola_miniaturas.get_nowait()
                except queue.Empty:
                    break
                try:
                    if item[0] == "thumb":
                        self.dibujar_miniatura_en_canvas(*item[1:])
                    elif item[0] == "fin" and item[1] == self.generacion_miniaturas:
                        _, _, truncado, total = item
                        if truncado:
                            self.lbl_loading_thumbs.config(text=f"✨ Mostrando {MAX_MINIATURAS_POR_VISTA} de {total} coincidencias — afiná la búsqueda para ver el resto")
                        else:
                            self.lbl_loading_thumbs.config(text="✨ Lista lateral sincronizada")
                except Exception:
                    registrar_excepcion(*sys.exc_info())
        finally:
            self.root.after(30, self._procesar_cola_miniaturas)

    def dibujar_miniatura_en_canvas(self, lbl, img_pil, idx, columnas_maximas, generacion):
        if generacion != self.generacion_miniaturas: return  # llegó tarde: ya no corresponde a la grilla actual
        tk_thumb = ImageTk.PhotoImage(img_pil)  # se crea aquí, en el hilo principal
        self.thumb_refs.append(tk_thumb)  # hay que retener la referencia o Tk la recolecta y la imagen desaparece
        ancho_celda, alto_celda, pad = 142, 122, 6
        fila, col = divmod(idx, columnas_maximas)
        x0, y0 = pad + col * ancho_celda, pad + fila * alto_celda
        x1, y1 = x0 + (ancho_celda - pad), y0 + (alto_celda - pad)
        color_texto = "#ff3333" if self.archivos_mapeados.get(lbl) in self.texturas_reemplazadas else "#ffffff"

        id_rect = self.canvas_thumbs.create_rectangle(x0, y0, x1, y1, fill="#2b2b2b", outline="", width=2, tags=("miniatura",))
        id_img = self.canvas_thumbs.create_image((x0 + x1) // 2, y0 + (y1 - y0 - 16) // 2, image=tk_thumb, anchor="center", tags=("miniatura",))
        lbl_truncado = lbl if len(lbl) <= 16 else lbl[:13] + "..."
        id_txt = self.canvas_thumbs.create_text((x0 + x1) // 2, y1 - 10, text=lbl_truncado, fill=color_texto, font=("Arial", 8), tags=("miniatura",))

        for id_item in (id_rect, id_img, id_txt):
            self.canvas_thumbs.tag_bind(id_item, "<Button-1>", lambda e, l=lbl, r=id_rect: self.marcar_y_cargar_textura(l, r))
        self.canvas_thumbs.config(scrollregion=self.canvas_thumbs.bbox("all"))
# Parte 10
    def marcar_y_cargar_textura(self, lbl, id_rect_seleccion):
        if self.id_rect_seleccionado is not None:
            try: self.canvas_thumbs.itemconfig(self.id_rect_seleccionado, outline="", width=1)
            except tk.TclError: pass  # el ítem ya no existe (la grilla se regeneró)
        self.id_rect_seleccionado = id_rect_seleccion
        self.canvas_thumbs.itemconfig(id_rect_seleccion, outline="#00ff66", width=2)
        self.cargar_textura_desde_explorador(lbl)

    def forzar_refresco_por_checkbox(self):
        if hasattr(self, 'ruta_raw_actual') and self.ruta_raw_actual:
            for lbl, ruta in self.archivos_mapeados.items():
                if ruta == self.ruta_raw_actual:
                    self.cargar_textura_desde_explorador(lbl)
                    break

    def on_seleccionar_lista(self, widget_listbox):
        sel = widget_listbox.curselection()
        if not sel: return
        lbl = widget_listbox.get(sel).replace(" 📄 ", "")
        ruta = self.archivos_mapeados.get(lbl)
        if not (ruta and os.path.exists(ruta)): return
        self.abrir_archivo_por_ruta(ruta)

    def abrir_archivo_por_ruta(self, ruta):
        if ruta.endswith('.spv'):
            self.tabs.select(self.tab_s)
            if txt := spv_a_glsl(ruta):
                self.ruta_spv_actual = ruta
                self.etapa_shader_actual = detectar_etapa_shader(ruta)
                self.editor.delete("1.0", tk.END)
                self.editor.insert("1.0", txt)
                _resaltar_glsl(self.editor)
                etiqueta_etapa = f" ({self.etapa_shader_actual})" if self.etapa_shader_actual else " (etapa no identificada — no se podrá recompilar)"
                self.lbl_s.config(text=f"Activo: {Path(ruta).name}{etiqueta_etapa}")
        elif ruta.endswith('.buf'):
            if getattr(self, "pestana_trace", None):
                self.pestana_trace.abrir_buffer(ruta)
            else:
                messagebox.showinfo("Modelos", "Falta trace_tab.py / xxami_trace.py junto a gui.py: sin ellos no se pueden reconstruir modelos desde los .buf.")
        elif ruta.endswith('.obj'):
            self.tabs.select(self.tab_3d)
            self.ruta_obj_actual = ruta
            self.lbl_3d.config(text=f"Modelo Activo: {Path(ruta).name}")
            self.cargar_modelo_obj(ruta)

    def cargar_textura_desde_explorador(self, lbl):
        ruta = self.archivos_mapeados.get(lbl)
        if not ruta: return
        self.tabs.select(self.tab_a)
        ruta_lectura = self.texturas_reemplazadas.get(ruta, ruta)
        if astc_raw_a_png(self, ruta_lectura, str(self.img_cache)):
            self.ruta_raw_actual = ruta
            with Image.open(str(self.img_cache)) as img_abierta:
                img = img_abierta.copy()  # copia desvinculada del archivo: se puede cerrar ya el handle
            orig_w, orig_h = img.size
            try: datos_fieles = leer_datos_textura(ruta_lectura)
            except Exception: datos_fieles = b""
            info_formato = obtener_info_formato(ruta_lectura)
            codigo_formato = obtener_codigo_formato(ruta_lectura)
            motivo_diagnostico = self._diagnostico_textura.get(ruta_lectura)
            color_estado = "#00ff66"
            if codigo_formato in FORMATOS_NO_VISUALIZABLES or (motivo_diagnostico and motivo_diagnostico.startswith("archivo vacío")):
                # El PNG cargado es el aviso "notload", no la textura real: las dimensiones
                # que se muestran son las declaradas en el nombre de archivo, no las del aviso.
                orig_w, orig_h = parsear_dimensiones(ruta_lectura)
                nombre_fmt = info_formato["nombre"] if info_formato else f"fmt{codigo_formato}"
                detalle = motivo_diagnostico or "no es una imagen; datos sin forma reconocible"
                fmt_real = f"{nombre_fmt} — ⚠ NO SE HA PODIDO LEER CORRECTAMENTE LA TEXTURA ({detalle})"
                color_estado = "#ff3333"
                motivo_diagnostico = None  # ya quedó explicado arriba; no lo dupliques abajo
            elif info_formato is not None and info_formato["tipo"] == "astc":
                bloque_real = info_formato["bloque"]
                fmt_real = f"ASTC {bloque_real} (VK_FORMAT_{info_formato['nombre']})"
                self.cb.set(bloque_real)
            elif info_formato is not None and info_formato["tipo"] == "etc2":
                fmt_real = f"ETC2 4x4 (VK_FORMAT_{info_formato['nombre']})"
                self.cb.set("4x4")
            elif info_formato is not None:
                fmt_real = f"{info_formato['nombre']} (sin comprimir)"
                if len(info_formato["canales"]) == 1 and img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 255:
                    fmt_real += " → interpretada como máscara alfa"
            else:
                # fmt no catalogado: astc_raw_a_png ya probó ASTC/ETC2/BC y dejó el resultado
                # en motivo_diagnostico; no asumimos "ASTC" a ciegas como antes.
                fmt_real = f"fmt{codigo_formato} no catalogado" if codigo_formato is not None else "formato no identificable"
                bloque_estimado = detectar_bloque_astc(orig_w, orig_h, len(datos_fieles))
                self.cb.set(bloque_estimado)
            if motivo_diagnostico is not None and color_estado != "#ff3333":
                fmt_real += f"\n• ⚠ {motivo_diagnostico}"
                color_estado = "#ffaa00"
            if ruta in self.texturas_reemplazadas: fmt_real += " [ MODIFICADA ]"
            disp_img = img.copy()
            disp_img.thumbnail((500, 500))
            tk_i = ImageTk.PhotoImage(componer_sobre_tablero(disp_img))
            self.p_img.config(image=tk_i, text="")
            self.p_img.image = tk_i
            extra_ktx = ""
            if ktx2_util and ktx2_util.es_ktx2(ruta_lectura):
                _ki = ktx2_util.info_textura(ruta_lectura)
                if _ki: extra_ktx = f"\n• Contenedor: KTX2 ({_ki.resumen()}); se muestra el nivel 0"
            self.p_txt.config(foreground=color_estado, text=f"[ INFORMACIÓN DE TEXTURA ]\n• Dimensiones: {orig_w}x{orig_h} px\n• Formato GPU: {fmt_real}\n• Codificación: UNORM\n• Peso: {os.path.getsize(ruta_lectura)/1024:.2f} KB{extra_ktx}\n• Ruta: {Path(ruta).name}")

    def reemplazar_textura_por_png(self):
        if not self.ruta_raw_actual: return
        ruta_png_externo = filedialog.askopenfilename(filetypes=[("Imágenes PNG", "*.png")])
        if not ruta_png_externo: return
        img_externa = Image.open(ruta_png_externo)
        w_orig, h_orig = Image.open(str(self.img_cache)).size
        if img_externa.size != (w_orig, h_orig): img_externa = img_externa.resize((w_orig, h_orig), Image.Resampling.LANCZOS)
        ruta_png_adaptado = Path(tempfile.gettempdir()).joinpath("nodo_png_reemplazo_temporal.png")
        img_externa.save(str(ruta_png_adaptado))
        datos_fieles = leer_datos_textura(self.texturas_reemplazadas.get(self.ruta_raw_actual, self.ruta_raw_actual))
        info_formato = obtener_info_formato(self.ruta_raw_actual)
        ruta_final_raw = self.directorio_temp_raws.joinpath(Path(self.ruta_raw_actual).stem + "_mod.raw")
        # Se genera primero en un archivo temporal: si algo falla, un reemplazo anterior válido queda intacto.
        ruta_temp_raw_salida = self.directorio_temp_raws.joinpath(Path(self.ruta_raw_actual).stem + "_mod.nuevo.tmp")
        try:
            if ktx2_util and ktx2_util.es_ktx2(self.ruta_raw_actual):
                self._reemplazar_ktx2(str(ruta_png_adaptado))
                return
            if not png_a_raw_segun_formato(str(ruta_png_adaptado), str(ruta_temp_raw_salida), info_formato, w_orig, h_orig, datos_fieles):
                return
            # Red de seguridad: el .raw nuevo debe pesar EXACTAMENTE lo mismo que el original.
            tam_nuevo = os.path.getsize(ruta_temp_raw_salida)
            if tam_nuevo != len(datos_fieles):
                messagebox.showerror("Reemplazo cancelado", f"El archivo generado pesa {tam_nuevo} bytes y el original {len(datos_fieles)}. No se aplicó el reemplazo para no corromper la textura.")
                return
            os.replace(ruta_temp_raw_salida, ruta_final_raw)
            self.texturas_reemplazadas[self.ruta_raw_actual] = str(ruta_final_raw)
            ruta_thumb_png = self.dir_cache_thumbs.joinpath(f"thumb_{Path(self.ruta_raw_actual).stem}.png")
            if ruta_thumb_png.exists(): ruta_thumb_png.unlink()
            self.actualizar_interfaz_explorador()
            messagebox.showinfo("Éxito", "La textura ha sido reemplazada.")
        finally:
            for tmp in (ruta_png_adaptado, ruta_temp_raw_salida):
                try:
                    if Path(tmp).exists(): Path(tmp).unlink()
                except OSError: pass

    def buscar_ktx(self):
        """ktx.exe (con ktx.dll al lado): junto al programa, en el directorio de trabajo o en el PATH."""
        import shutil
        return ktx2_util.buscar_ktx_exe([obtener_ruta_recurso("ktx.exe"),
                                         os.path.join(os.path.dirname(os.path.abspath(__file__)), "ktx.exe"),
                                         shutil.which("ktx")])

    def _reemplazar_ktx2(self, ruta_png_adaptado):
        """Recrea la textura como KTX2 con el mismo VkFormat, tamaño y niveles que el original."""
        original = self.ruta_raw_actual
        info_formato = obtener_info_formato(original)
        if info_formato is None:
            messagebox.showerror("Reemplazo no disponible", f"El formato fmt{obtener_codigo_formato(original)} no está catalogado: no se sabe con qué formato recrear la textura.")
            return
        ktx_exe = self.buscar_ktx()
        if not ktx_exe:
            messagebox.showerror("Falta ktx.exe", "Para reemplazar texturas .ktx2 hace falta ktx.exe (de KTX-Software) junto a este programa, con ktx.dll en la misma carpeta.")
            return
        destino = self.directorio_temp_raws.joinpath(Path(original).stem + "_mod.ktx2")
        ok, motivo = ktx2_util.crear_reemplazo(ktx_exe, info_formato["nombre"], ruta_png_adaptado, original, str(destino))
        if not ok:
            messagebox.showerror("Reemplazo cancelado", motivo + "\n\nNo se aplicó el reemplazo.")
            return
        self.texturas_reemplazadas[original] = str(destino)
        ruta_thumb_png = self.dir_cache_thumbs.joinpath(f"thumb_{Path(original).stem}.png")
        if ruta_thumb_png.exists(): ruta_thumb_png.unlink()
        self.actualizar_interfaz_explorador()
        messagebox.showinfo("Éxito", "La textura ha sido reemplazada.")

    def exportar_bloque_reemplazos(self):
        if not self.texturas_reemplazadas: return
        directorio_destino = filedialog.askdirectory(title="Selecciona la carpeta")
        if not directorio_destino: return
        contador = 0
        indice_nuevo = {}
        for ruta_original, ruta_temporal in self.texturas_reemplazadas.items():
            nombre_original = Path(ruta_original).name
            hash_tex = extraer_hash_textura(nombre_original)
            # Se guarda con nombre corto "tex_hash.raw" cuando se puede extraer el hash;
            # si el archivo no sigue ese patrón, se conserva el nombre completo tal cual.
            ext_guardado = ".ktx2" if str(ruta_temporal).lower().endswith(".ktx2") else ".raw"
            nombre_guardado = f"tex_{hash_tex}{ext_guardado}" if hash_tex else nombre_original
            try:
                Path(directorio_destino).joinpath(nombre_guardado).write_bytes(Path(ruta_temporal).read_bytes())
                indice_nuevo[nombre_original] = nombre_guardado
                contador += 1
            except Exception:
                pass

        # indexes.txt: "nombre original completo = nombre corto guardado", para poder
        # recuperar dimensiones/formato más adelante al recargar esta misma carpeta.
        # Se fusiona con lo que ya hubiera (no se pisa), así se puede ir exportando en
        # varias tandas sin perder el índice de reemplazos anteriores.
        if indice_nuevo:
            ruta_indice = Path(directorio_destino) / "indexes.txt"
            indice_existente = {}
            if ruta_indice.exists():
                try:
                    for linea in ruta_indice.read_text(encoding="utf-8").splitlines():
                        if " = " in linea:
                            k, v = linea.split(" = ", 1)
                            indice_existente[k.strip()] = v.strip()
                except Exception:
                    pass
            indice_existente.update(indice_nuevo)
            try:
                with open(ruta_indice, "w", encoding="utf-8") as f:
                    for k, v in sorted(indice_existente.items()):
                        f.write(f"{k} = {v}\n")
            except Exception:
                pass

        messagebox.showinfo("Guardado Exitoso", f"Se han exportado {contador} texturas.")

    def cargar_modelo_obj(self, ruta_obj):
        self.vertices_3d, self.caras_3d = [], []
        try:
            with open(ruta_obj, 'r') as f:
                for line in f:
                    if line.startswith('v '):
                        parts = line.split()
                        self.vertices_3d.append([float(parts[1]), float(parts[2]), float(parts[3])])
                    elif line.startswith('f '):
                        parts = line.split()
                        face_indices = []
                        for p in parts[1:]:
                            idx = int(p.split('/')[0])
                            face_indices.append(idx - 1 if idx > 0 else len(self.vertices_3d) + idx)
                        self.caras_3d.append(face_indices)
            if self.vertices_3d:
                self.zoom_3d, self.rot_x, self.rot_y = 150.0, 0.5, 0.5
                self.redibujar_malla_3d()
        except: pass

    def redibujar_malla_3d(self):
        self.canvas_3d.delete("mesh_edge")
        if not self.vertices_3d: return
        cx, cy = self.canvas_3d.winfo_width() / 2, self.canvas_3d.winfo_height() / 2
        if cx <= 0: cx, cy = 300, 250
        cx_rot, sx_rot = math.cos(self.rot_x), math.sin(self.rot_x)
        cy_rot, sy_rot = math.cos(self.rot_y), math.sin(self.rot_y)
        puntos_proyectados = []
        for v in self.vertices_3d:
            x1 = v[0] * cy_rot - v[2] * sy_rot
            z1 = v[0] * sy_rot + v[2] * cy_rot
            y2 = v[1] * cx_rot - z1 * sx_rot
            puntos_proyectados.append((cx + x1 * self.zoom_3d, cy - y2 * self.zoom_3d))
        for cara in self.caras_3d:
            for i in range(len(cara)):
                idx_actual, idx_siguiente = cara[i], cara[(i + 1) % len(cara)]
                if idx_actual < len(puntos_proyectados) and idx_siguiente < len(puntos_proyectados):
                    self.canvas_3d.create_line(puntos_proyectados[idx_actual], puntos_proyectados[idx_siguiente], fill="#00ff66", tags="mesh_edge", width=1)

    def start_pan_3d(self, event): self.last_mouse_x, self.last_mouse_y = event.x, event.y
    def rotate_mesh_3d(self, event):
        dx, dy = event.x - self.last_mouse_x, event.y - self.last_mouse_y
        self.rot_y += dx * 0.01
        self.rot_x += dy * 0.01
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        self.redibujar_malla_3d()
    def zoom_mesh_3d(self, event):
        if event.delta > 0: self.zoom_3d *= 1.1
        else: self.zoom_3d *= 0.9
        self.redibujar_malla_3d()
    def guardar_shader(self):
        if self.ruta_spv_actual and glsl_a_spv(self.editor.get("1.0", tk.END), self.ruta_spv_actual, getattr(self, 'etapa_shader_actual', None)):
            messagebox.showinfo("Éxito", "Shader recompilado correctamente.")
    def exportar_png(self):
        if self.ruta_raw_actual and self.img_cache.exists():
            out = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
            if out: Image.open(str(self.img_cache)).save(out)
    def importar_png(self):
        png = filedialog.askopenfilename(filetypes=[("PNG", "*.png")])
        if png:
            # El código fmt del nombre gobierna cómo se decodifica; debe coincidir con el bloque elegido
            fmt_bloque = next((k for k, v in FORMATOS_VULKAN.items() if v.get("tipo") == "astc" and v["bloque"] == self.cb.get() and "UNORM" in v["nombre"]), 157)
            out = filedialog.asksaveasfilename(initialfile=f"tex_new_{Image.open(png).width}x{Image.open(png).height}_fmt{fmt_bloque}.raw", defaultextension=".raw", filetypes=[("RAW", "*.raw")])
            if out and png_a_astc_raw(png, out, self.cb.get()): messagebox.showinfo("Éxito", "Textura guardada.")
    def inicializar_pestanas_post_registro(self):
        self.construir_pestana_shader()
        self.construir_pestana_astc()
        self.construir_pestana_3d()
        self.pestana_trace = None
        if PestanaTrace is not None:
            try: self.pestana_trace = PestanaTrace(self, log=_log)
            except Exception: _log(traceback.format_exc())
        try: self.tabs.hide(self.tab_3d)  # los modelos ahora salen de los .buf vía frame trace
        except Exception: pass

# --- REGISTRO DE FALLOS (para diagnosticar cierres inesperados) ---
# Escribe SIEMPRE en xxami_crash_log.txt junto al script (o, si ahí no se puede
# escribir -p.ej. carpeta protegida como Program Files-, en la carpeta temporal
# del sistema). Registra: excepciones no controladas de cualquier hilo, errores
# dentro de callbacks de Tk (botones, etc.), errores en el recolector de basura,
# los RuntimeWarning/DeprecationWarning que normalmente solo se ven si hay una
# consola abierta, y -gracias a faulthandler- el traceback de Python si el
# proceso muere de forma nativa (segfault), que de otro modo no deja rastro
# porque la ventana simplemente se cierra sin avisar nada.
_archivo_log_fallos = None
_RUTA_LOG_FALLOS = None

def _log(texto):
    try:
        if _archivo_log_fallos:
            _archivo_log_fallos.write(texto if texto.endswith("\n") else texto + "\n")
    except Exception:
        pass

def registrar_excepcion(tipo, valor, tb):
    if tipo is KeyboardInterrupt:
        return
    _log(f"[{time.strftime('%H:%M:%S')}] EXCEPCIÓN NO CONTROLADA:\n" + "".join(traceback.format_exception(tipo, valor, tb)))
    sys.__excepthook__(tipo, valor, tb)

def _registrar_excepcion_hilo(args):
    registrar_excepcion(args.exc_type, args.exc_value, args.exc_traceback)

def _registrar_no_capturable(args):
    # sys.unraisablehook: errores que ocurren, por ejemplo, dentro de __del__
    # durante el recolector de basura, que normalmente no aparecen en ningún lado.
    try:
        _log(f"[{time.strftime('%H:%M:%S')}] ERROR NO CAPTURABLE ({args.err_msg or ''}):\n" +
             "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    except Exception:
        pass

def _registrar_warning(mensaje, categoria, archivo, linea, f=None, line=None):
    _log(f"[{time.strftime('%H:%M:%S')}] AVISO ({categoria.__name__}) en {archivo}:{linea}: {mensaje}")

def activar_registro_de_fallos():
    global _archivo_log_fallos, _RUTA_LOG_FALLOS
    for candidata in (
        lambda: Path(__file__).resolve().with_name("xxami_crash_log.txt"),
        lambda: Path(tempfile.gettempdir()) / "xxami_crash_log.txt",
    ):
        try:
            ruta_log = candidata()
            _archivo_log_fallos = open(ruta_log, "a", buffering=1, encoding="utf-8")
            _RUTA_LOG_FALLOS = ruta_log
            break
        except Exception:
            continue
    if _archivo_log_fallos is None:
        return  # no hay ninguna carpeta escribible; seguimos sin log en vez de no arrancar

    _log(f"\n===== Sesión iniciada {time.strftime('%Y-%m-%d %H:%M:%S')} | log en: {_RUTA_LOG_FALLOS} =====")
    try:
        faulthandler.enable(file=_archivo_log_fallos, all_threads=True)
    except Exception as e:
        _log(f"(no se pudo activar faulthandler: {e})")

    sys.excepthook = registrar_excepcion
    threading.excepthook = _registrar_excepcion_hilo
    try:
        sys.unraisablehook = _registrar_no_capturable
    except Exception:
        pass
    warnings.showwarning = _registrar_warning
    warnings.simplefilter("always")

    def _al_salir():
        _log(f"===== Sesión finalizada normalmente {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
        try: _archivo_log_fallos.flush(); _archivo_log_fallos.close()
        except Exception: pass
    atexit.register(_al_salir)

# --- ARRANQUE ESTRUCTURAL INDEPENDIENTE DE LA UI ---
if __name__ == "__main__":
    activar_registro_de_fallos()
    try:
        r = tk.Tk()
        aplicar_tema_oscuro(r)
        r.report_callback_exception = registrar_excepcion
        app = AppMultiherramienta(r)
        app.inicializar_pestanas_post_registro()
        r.mainloop()
    except Exception:
        registrar_excepcion(*sys.exc_info())
        raise