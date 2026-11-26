# -*- coding: utf-8 -*-
"""Decodificador de texturas compartido por XXAMI Explorer y AMI 3D Viewer.
Extraído de la lógica de decodificación existente; no inicializa Tkinter.
"""
import os, re, sys, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
try:
    import ktx2_util
except Exception:
    ktx2_util = None
try:
    import texture2ddecoder
except ImportError:
    texture2ddecoder = None
try:
    import numpy as np
except ImportError:
    np = None

def obtener_ruta_recurso(nombre):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, nombre)
    return os.path.join(Path(__file__).resolve().parent, nombre)

def parsear_dimensiones(ruta):
    if ktx2_util and ktx2_util.es_ktx2(ruta):
        info = ktx2_util.info_textura(ruta)
        if info:
            return (info.w, info.h)
    m = re.search(r"(\d+)x(\d+)", Path(ruta).name.lower())
    return (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)

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
    """Devuelve bytes de KTX2 (nivel 0/capa 0) o de ASTC independiente."""
    ext = Path(ruta).suffix.lower()
    if ext == ".ktx2":
        if not ktx2_util: raise RuntimeError("El módulo ktx2_util no está disponible.")
        return ktx2_util.bytes_mip0(ruta)
    if ext == ".astc": return Path(ruta).read_bytes()
    raise ValueError(f"Formato de textura no admitido: {ext or '(sin extensión)'}")

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

def _registrar_diagnostico(self, ruta_textura, motivo):
    # motivo=None significa "todo bien"; se guarda igual para no dejar un diagnóstico
    # viejo colgado si la textura se vuelve a decodificar más tarde (ej. tras un reemplazo).
    try:
        self._diagnostico_textura[ruta_textura] = motivo
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

def textura_a_png(self, ruta_textura, ruta_png_temp, rapido=False):
    # rapido=True: se usa desde el hilo de miniaturas (corre automáticamente para
    # TODA la carpeta, sin que el usuario lo pida archivo por archivo). En ese modo
    # se evita la fuerza bruta multi-códec y el reintento de desentrelazado -cada
    # intento extra es una llamada más a una librería en C que no puedo verificar
    # aquí-, para minimizar cuántas llamadas nativas se disparan sin supervisión.
    # rapido=False (vista de una sola textura, bajo pedido explícito): se hace el
    # análisis completo.
    ancho, alto = parsear_dimensiones(ruta_textura)
    codigo_formato = obtener_codigo_formato(ruta_textura)
    info_formato = FORMATOS_VULKAN.get(codigo_formato) if codigo_formato is not None else None

    if Path(ruta_png_temp).exists():
        try: Path(ruta_png_temp).unlink()
        except: pass

    # Formatos que ya se probaron y no son imágenes legibles (ver FORMATOS_NO_VISUALIZABLES):
    # se usa directamente el aviso "no se pudo leer" en vez de intentar decodificar ruido.
    if codigo_formato in FORMATOS_NO_VISUALIZABLES:
        obtener_imagen_notload().save(ruta_png_temp)
        _registrar_diagnostico(self, ruta_textura, None)  # ese caso ya se explica solo en el panel; no hace falta duplicar el aviso
        return True

    try:
        datos = leer_datos_textura(ruta_textura)
        tamano_bytes = len(datos)

        # --- FORMATOS PLANOS (SIN COMPRESIÓN DE BLOQUES) ---
        if info_formato is not None and info_formato["tipo"] == "plano":
            _decodificar_formato_plano(datos, ancho, alto, info_formato).save(ruta_png_temp)
            _registrar_diagnostico(self, ruta_textura, None)  # copia directa de píxeles: no hay "decodificación" que pueda salir mal
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
                _registrar_diagnostico(self, ruta_textura, f"archivo vacío o incompleto ({tamano_bytes} bytes; se esperaban {bytes_necesarios})")
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
            _registrar_diagnostico(self, ruta_textura, motivo)
            img_decodificada.save(ruta_png_temp)
            return Path(ruta_png_temp).exists()

        # --- fmt NO CATALOGADO: fuerza bruta entre ASTC/ETC2/BC en vez de asumir ASTC ---
        if info_formato is None:
            if tamano_bytes < 8:
                obtener_imagen_notload().save(ruta_png_temp)
                _registrar_diagnostico(self, ruta_textura, f"archivo vacío o incompleto ({tamano_bytes} bytes)")
                return Path(ruta_png_temp).exists()
            # En miniaturas automáticas no se debe enviar un formato desconocido
            # al decodificador ASTC nativo "a ojo": algunos volcados contienen datos
            # auxiliares o bloques truncados que pueden provocar una access violation
            # dentro de texture2ddecoder (un fallo nativo que Python no puede capturar).
            # La decodificación heurística completa queda reservada a la vista explícita.
            if rapido:
                obtener_imagen_notload().save(ruta_png_temp)
                _registrar_diagnostico(
                    self, ruta_textura,
                    "formato Vulkan no catalogado; se omitió la decodificación automática por seguridad"
                )
                return Path(ruta_png_temp).exists()

            resultado = _probar_todos_los_codecs(datos, ancho, alto)
            if resultado is None:
                # Ningún candidato calza con el tamaño real: caemos al viejo criterio
                # (ASTC "a ojo") únicamente en una decodificación solicitada explícitamente.
                bloque_estimado = detectar_bloque_astc(ancho, alto, tamano_bytes)
                bx, by = map(int, bloque_estimado.split('x'))
                ax, ay = ((ancho + bx - 1) // bx) * bx, ((alto + by - 1) // by) * by
                bytes_necesarios = (ax // bx) * (ay // by) * 16
                d = datos[:bytes_necesarios] + b'\x00' * max(0, bytes_necesarios - len(datos))
                bgra = texture2ddecoder.decode_astc(d, ax, ay, bx, by) if texture2ddecoder else None
                if bgra is None:
                    obtener_imagen_notload().save(ruta_png_temp)
                    _registrar_diagnostico(self, ruta_textura, "fmt no catalogado y el tamaño no coincide con ningún formato conocido (ASTC/ETC2/BC)")
                    return Path(ruta_png_temp).exists()
                img_decodificada = Image.frombytes("RGBA", (ax, ay), bgra, "raw", "BGRA")
                if (ax, ay) != (ancho, alto): img_decodificada = img_decodificada.crop((0, 0, ancho, alto))
                motivo_vacio = "" if rapido else "; se probaron ASTC/ETC2/BC y ninguno calzó en tamaño"
                _registrar_diagnostico(self, ruta_textura, f"fmt no catalogado{motivo_vacio}, se usó ASTC {bloque_estimado} a ojo (sin certeza)")
            else:
                img_decodificada, descripcion, puntaje = resultado
                if puntaje > UMBRAL_SOSPECHA_DECODIFICACION:
                    _registrar_diagnostico(self, ruta_textura, f"fmt no catalogado; el mejor intento fue {descripcion} pero con ~{puntaje*100:.0f}% de bloques de error (dato incierto)")
                else:
                    _registrar_diagnostico(self, ruta_textura, f"fmt no catalogado; identificado automáticamente por tamaño como {descripcion}")
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
            _registrar_diagnostico(self, ruta_textura, f"archivo vacío o incompleto ({tamano_bytes} bytes; se esperaban {bytes_necesarios})")
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

        _registrar_diagnostico(self, ruta_textura, motivo_diagnostico)
        img_decodificada.save(ruta_png_temp)
        return Path(ruta_png_temp).exists()
    except Exception as e:
        try:
            _registrar_diagnostico(self, ruta_textura, f"error de decodificación: {type(e).__name__}: {e}")
        except Exception:
            pass
        return False


__all__ = ["textura_a_png", "parsear_dimensiones", "obtener_codigo_formato", "FORMATOS_VULKAN"]
