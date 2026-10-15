# -*- coding: utf-8 -*-
"""
xxami_trace.py -- núcleo (SIN Tkinter) para trabajar con volcados XXAMI y sus
frame traces ("xxami-frame-trace", version 1).

Tres piezas, todas probables por separado de la interfaz:
  1) IndiceRecursos : escanea la carpeta raíz del volcado (y sus Frame_Trace_*)
                      y resuelve archivos por nombre/hash.
  2) Trace          : lee frame_trace.json y lo convierte en una lista de draws,
                      con el estado de Vulkan vigente en cada uno (pipeline,
                      descriptor sets, buffers de vértices/índices).
  3) construir_malla: reconstruye la geometría de un draw a partir de los .buf
                      (vb_/ib_) siguiendo las reglas del generador, y
                      renderizar_malla / exportar_obj para verla o sacarla.

Reglas de geometría (verificadas contra main.cpp del generador):
  * Si el draw trae "geometry" con source "mapped", el .buf contiene SOLO el rango
    del draw: el índice 0 del archivo es el índice 'first_index'; el vértice k
    del archivo es el k-ésimo desde el offset del binding.
  * Si no hay "geometry" para esa parte pero el bind_* trae "model" (subida por
    copia), el .buf es la región subida completa: el dato del binding está en
    (offset - region_offset), y el índice i del draw en
    (offset - region_offset) + (first_index + i) * tamaño_índice.
  * Vértice usado por el índice i  =  i + vertex_offset  (draw_indexed)
                                       first_vertex + i   (draw)
"""
import json
import os
import re
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Nombres legibles de enums de Vulkan que aparecen en el trace
# ---------------------------------------------------------------------------
NOMBRES_TOPOLOGIA = {0: "POINT_LIST", 1: "LINE_LIST", 2: "LINE_STRIP", 3: "TRIANGLE_LIST",
                     4: "TRIANGLE_STRIP", 5: "TRIANGLE_FAN", 6: "LINE_LIST_ADJ", 7: "LINE_STRIP_ADJ",
                     8: "TRIANGLE_LIST_ADJ", 9: "TRIANGLE_STRIP_ADJ", 10: "PATCH_LIST"}
NOMBRES_DESCRIPTOR = {0: "SAMPLER", 1: "COMBINED_IMAGE_SAMPLER", 2: "SAMPLED_IMAGE", 3: "STORAGE_IMAGE",
                      4: "UNIFORM_TEXEL_BUFFER", 5: "STORAGE_TEXEL_BUFFER", 6: "UNIFORM_BUFFER",
                      7: "STORAGE_BUFFER", 8: "UNIFORM_BUFFER_DYNAMIC", 9: "STORAGE_BUFFER_DYNAMIC",
                      10: "INPUT_ATTACHMENT"}
TIPOS_DESCRIPTOR_IMAGEN = (0, 1, 2, 3, 10)
TIPOS_DESCRIPTOR_DINAMICO = (8, 9)
_BITS_ETAPA = ((1, "vertex"), (2, "tess_control"), (4, "tess_eval"), (8, "geometry"), (16, "fragment"), (32, "compute"))


def nombre_etapa(valor):
    partes = [n for bit, n in _BITS_ETAPA if valor & bit]
    return "+".join(partes) if partes else f"stage{valor}"


# ---------------------------------------------------------------------------
# 1) ÍNDICE DE RECURSOS
# ---------------------------------------------------------------------------
_RE_SHADER = re.compile(r'^shader_([0-9a-fA-F]+)\.spv$')
_RE_TEX = re.compile(r'^tex_([0-9a-fA-F]+)(?:_\d+x\d+_fmt\d+)?\.(?:raw|ktx2)$')
_RE_BUF = re.compile(r'^(?:vb|ib|vbib|sb|bones)_([0-9a-fA-F]+)_\d+\.buf$')


class IndiceRecursos:
    """Mapa nombre/hash -> rutas, sobre la raíz del volcado y todas sus subcarpetas.

    El trace marca "status":"missing" cuando un archivo NO está en SU carpeta; eso no
    significa que no exista: puede estar en la raíz u otra captura. Por eso se
    resuelve contra todo el árbol, prefiriendo la carpeta del propio trace.
    """

    def __init__(self):
        self.raiz = None
        self.por_nombre = {}   # nombre de archivo -> [Path, ...]
        self.por_hash = {}     # (tipo, hash)      -> [Path, ...]   tipo: shader | tex | buf
        self.trazas = []       # [Path(frame_trace.json), ...] ordenadas por carpeta
        self._cache = OrderedDict()
        self._cache_bytes = 0

    def escanear(self, raiz):
        self.raiz = Path(raiz)
        self.por_nombre.clear()
        self.por_hash.clear()
        self.trazas = []
        self._cache.clear()
        self._cache_bytes = 0
        for carpeta, _subs, archivos in os.walk(str(self.raiz)):
            for nombre in archivos:
                ruta = Path(carpeta) / nombre
                if nombre == "frame_trace.json":
                    self.trazas.append(ruta)
                    continue
                self.por_nombre.setdefault(nombre, []).append(ruta)
                for patron, tipo in ((_RE_SHADER, "shader"), (_RE_TEX, "tex"), (_RE_BUF, "buf")):
                    m = patron.match(nombre)
                    if m:
                        self.por_hash.setdefault((tipo, m.group(1).lower()), []).append(ruta)
                        break
        self.trazas.sort(key=lambda p: p.parent.name)
        return self

    def _elegir(self, rutas, carpeta):
        if not rutas:
            return None
        if carpeta is not None:
            carpeta = Path(carpeta)
            for r in rutas:
                if r.parent == carpeta:
                    return r
        if self.raiz is not None:
            for r in rutas:
                if r.parent == self.raiz:
                    return r
        return rutas[0]

    def buscar(self, nombre, carpeta=None):
        """Ruta de un archivo por su nombre exacto (o None)."""
        return self._elegir(self.por_nombre.get(nombre), carpeta)

    def buscar_por_hash(self, tipo, hash_hex, carpeta=None):
        return self._elegir(self.por_hash.get((tipo, str(hash_hex).lower())), carpeta)

    def leer(self, ruta, limite_bytes=256 * 1024 * 1024):
        """Bytes de un archivo, con una caché LRU pequeña (los .buf se reutilizan entre draws)."""
        clave = str(ruta)
        if clave in self._cache:
            self._cache.move_to_end(clave)
            return self._cache[clave]
        datos = Path(ruta).read_bytes()
        self._cache[clave] = datos
        self._cache_bytes += len(datos)
        while (len(self._cache) > 64 or self._cache_bytes > limite_bytes) and len(self._cache) > 1:
            _k, v = self._cache.popitem(last=False)
            self._cache_bytes -= len(v)
        return datos


# ---------------------------------------------------------------------------
# 2) TRACE
# ---------------------------------------------------------------------------
class Draw:
    """Un draw con el estado de Vulkan que tenía en ese momento."""
    __slots__ = ("idx", "cb", "pase", "op", "ev", "pipeline", "vbs", "ib", "sets")

    def __init__(self, idx, cb, pase, op, ev, pipeline, vbs, ib, sets):
        self.idx, self.cb, self.pase, self.op, self.ev = idx, cb, pase, op, ev
        self.pipeline, self.vbs, self.ib, self.sets = pipeline, vbs, ib, sets

    @property
    def indexado(self):
        return self.op == "draw_indexed"

    @property
    def cantidad(self):
        return self.ev.get("index_count" if self.indexado else "vertex_count", 0)

    @property
    def geometria(self):
        return self.ev.get("geometry") or {}

    def etiqueta(self):
        if self.indexado:
            return f"#{self.idx}  indexado  {self.cantidad} índices"
        return f"#{self.idx}  no indexado  {self.cantidad} vértices"


class Trace:
    VERSION_SOPORTADA = 1

    def __init__(self, ruta_json):
        self.ruta = Path(ruta_json)
        self.carpeta = self.ruta.parent
        with open(str(self.ruta), "r", encoding="utf-8") as f:
            self.datos = json.load(f)
        d = self.datos
        self.avisos = []
        if d.get("format") != "xxami-frame-trace":
            self.avisos.append(f"formato inesperado: {d.get('format')!r}")
        if int(d.get("version", 0) or 0) > self.VERSION_SOPORTADA:
            self.avisos.append(f"el trace es versión {d.get('version')} y este visor conoce la {self.VERSION_SOPORTADA}: puede faltar información")
        if d.get("truncated"):
            self.avisos.append("el trace está TRUNCADO por el tope de eventos: el frame no está completo")
        self.paquete = d.get("package", "")
        self.capturado = d.get("captured", "")
        self.pipelines = {p["id"]: p for p in d.get("pipelines", [])}
        res = d.get("resources", {})
        self.shaders = {s["hash"]: s for s in res.get("shaders", [])}
        self.texturas = {t["hash"]: t for t in res.get("textures", [])}
        self.modelos = {m["hash"]: m for m in res.get("models", [])}
        self.faltantes = list(d.get("missing", []))
        self.diagnosticos = d.get("diagnostics", {})
        self.model_dump = d.get("model_dump") or {}            # volcado de personajes (carpeta Models/)
        self.skin_validation = d.get("skin_validation") or []
        self.skins = []                                        # eventos skin_dispatch, en orden
        self._skin_salidas = []                                # (buffer, desde, hasta, indice en self.skins)
        self.pases = []     # [{'indice', 'x','y','w','h','clear', 'draws':[Draw,...]}]
        self.draws = []     # todos los draws, en orden de envío
        self._recorrer()

    # -- recorrido ---------------------------------------------------------
    def _recorrer(self):
        cbs = {cb["id"]: cb for cb in self.datos.get("command_buffers", [])}
        orden = [cid for s in self.datos.get("submits", []) for cid in s.get("command_buffers", [])]
        if not orden:
            orden = list(cbs.keys())
            if orden:
                self.avisos.append("el trace no trae 'submits': se usa el orden del archivo")
        for cid in orden:
            if cid in cbs:
                self._ejecutar(cbs[cid], cbs, None, 0)
            else:
                self.avisos.append(f"el submit referencia el command buffer {cid} que no está en el trace")

    def _aviso(self, texto):
        if texto not in self.avisos:
            self.avisos.append(texto)

    def _nuevo_pase(self, ev=None):
        ev = ev or {}
        pase = {"indice": len(self.pases), "x": ev.get("x", 0), "y": ev.get("y", 0),
                "w": ev.get("width", 0), "h": ev.get("height", 0), "clear": ev.get("clear_values", 0), "draws": []}
        self.pases.append(pase)
        return pase

    def _ejecutar(self, cb, cbs, estado_padre, profundidad):
        if profundidad > 8:
            self.avisos.append("execute_commands demasiado anidado: se corta")
            return
        if cb.get("partial"):
            self.avisos.append(f"el command buffer {cb['id']} está marcado 'partial' (empezó a grabarse antes de la captura)")
        est = {"pipeline": None, "vbs": {}, "ib": None, "sets": {}, "pase": None}
        if estado_padre:  # un secundario ejecutado dentro de un render pass hereda el pase actual
            est["pase"] = estado_padre.get("pase")
        for e in cb.get("events", []):
            op = e.get("op")
            if op == "begin_render_pass":
                est["pase"] = self._nuevo_pase(e)
            elif op == "end_render_pass":
                est["pase"] = None
            elif op == "bind_pipeline":
                if e.get("bind_point", 0) == 0:
                    est["pipeline"] = e.get("pipeline")
            elif op == "bind_descriptor_sets":
                self._bind_sets(est, e)
            elif op == "bind_vertex_buffers":
                primero = e.get("first", 0)
                for i, b in enumerate(e.get("buffers", [])):
                    est["vbs"][primero + i] = b
            elif op == "bind_index_buffer":
                est["ib"] = e
            elif op in ("draw", "draw_indexed"):
                pase = est["pase"]
                if pase is None:
                    pase = self._sin_pase()
                d = Draw(len(self.draws), cb.get("id", "?"), pase["indice"], op, e, est["pipeline"],
                         dict(est["vbs"]), est["ib"], {k: dict(v) for k, v in est["sets"].items()})
                pase["draws"].append(d)
                self.draws.append(d)
            elif op == "skin_dispatch":
                self._nota_skin(e)
            elif op == "execute_commands":
                for hijo in e.get("command_buffers", []):
                    if hijo in cbs:
                        self._ejecutar(cbs[hijo], cbs, est, profundidad + 1)

    def _nota_skin(self, e):
        self.skins.append(e)
        salida = e.get("output") or {}
        if salida.get("buffer") is not None and salida.get("bytes"):
            ini = salida.get("offset", 0) or 0
            self._skin_salidas.append((salida["buffer"], ini, ini + salida["bytes"], len(self.skins) - 1))

    def skin_de_salida(self, buffer, offset):
        """El skin_dispatch cuya SALIDA contiene (buffer, offset): es el que produjo los vértices de ese binding.
        Si hubo varios (el ring buffer se reutiliza), el último antes del final del frame."""
        hallado = None
        for b, ini, fin, i in self._skin_salidas:
            if b == buffer and ini <= (offset or 0) < fin:
                hallado = (i, ini)
        if hallado is None:
            return None, 0
        return self.skins[hallado[0]], hallado[1]

    def _sin_pase(self):
        for p in self.pases:
            if p.get("fuera"):
                return p
        p = self._nuevo_pase()
        p["fuera"] = True
        return p

    def _bind_sets(self, est, e):
        """Registra los sets enlazados y reparte los offsets dinámicos a los descriptores dinámicos
        (en orden de set y luego de binding, como define Vulkan)."""
        dyn = e.get("dynamic_offset_values")
        dyn = list(dyn) if dyn is not None else None
        primero = e.get("first_set", 0)
        for k, s in enumerate(e.get("sets", [])):
            entradas = []
            for en in s.get("entries", []):
                en = dict(en)
                if en.get("type") in TIPOS_DESCRIPTOR_DINAMICO:
                    en["dyn"] = dyn.pop(0) if dyn else None
                entradas.append(en)
            est["sets"][primero + k] = {"set": s.get("set"), "entries": entradas}
        if dyn:  # sobraron valores: algún descriptor dinámico no se registró en el trace
            self._aviso("los offsets dinámicos no calzan con los descriptores dinámicos vistos (algún descriptor no se registró)")

    # -- consultas ---------------------------------------------------------
    def nombre_modelo(self, hash_hex):
        m = self.modelos.get(hash_hex)
        return m["file"] if m else None

    def shaders_de(self, draw):
        p = self.pipelines.get(draw.pipeline)
        if not p:
            return []
        return [(nombre_etapa(s.get("stage", 0)), s.get("shader")) for s in p.get("stages", [])]

    def texturas_de(self, draw):
        """[(set, binding, elemento, hash|None, info|None)] para cada imagen enlazada.
        hash None = imagen no identificada (típicamente un render target, no una textura volcada)."""
        salida = []
        for nset in sorted(draw.sets):
            for en in draw.sets[nset]["entries"]:
                if en.get("type") in TIPOS_DESCRIPTOR_IMAGEN:
                    h = en.get("texture")
                    salida.append((nset, en.get("binding"), en.get("element"), h, self.texturas.get(h) if h else None))
        return salida

    def buffers_uniformes_de(self, draw):
        salida = []
        for nset in sorted(draw.sets):
            for en in draw.sets[nset]["entries"]:
                if en.get("type") in (6, 7, 8, 9):
                    base = en.get("offset", 0) or 0
                    dyn = en.get("dyn")
                    salida.append({"set": nset, "binding": en.get("binding"), "tipo": NOMBRES_DESCRIPTOR.get(en.get("type"), str(en.get("type"))),
                                   "buffer": en.get("buffer"), "offset": base, "dinamico": dyn, "offset_efectivo": base + (dyn or 0),
                                   "rango": en.get("range")})
        return salida

    def resumen_draw(self, draw):
        p = self.pipelines.get(draw.pipeline, {})
        lineas = [draw.etiqueta()]
        ev = draw.ev
        if draw.indexado:
            lineas.append(f"first_index={ev.get('first_index')}  vertex_offset={ev.get('vertex_offset')}  instancias={ev.get('instance_count')}")
        else:
            lineas.append(f"first_vertex={ev.get('first_vertex')}  instancias={ev.get('instance_count')}")
        if p:
            lineas.append(f"topología: {NOMBRES_TOPOLOGIA.get(p.get('topology'), p.get('topology'))}")
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# 3) RECONSTRUCCIÓN DE MALLAS
# ---------------------------------------------------------------------------
# código VkFormat -> (componentes, dtype little-endian, tipo)
FORMATOS_ATRIBUTO = {
    9: (1, "u1", "unorm"), 10: (1, "i1", "snorm"), 13: (1, "u1", "uint"),
    16: (2, "u1", "unorm"), 17: (2, "i1", "snorm"),
    23: (3, "u1", "unorm"), 24: (3, "i1", "snorm"),
    37: (4, "u1", "unorm"), 38: (4, "i1", "snorm"), 41: (4, "u1", "uint"), 44: (4, "u1", "unorm"),
    70: (1, "<u2", "unorm"), 71: (1, "<i2", "snorm"), 76: (1, "<f2", "float"),
    77: (2, "<u2", "unorm"), 78: (2, "<i2", "snorm"), 81: (2, "<u2", "uint"), 83: (2, "<f2", "float"),
    84: (3, "<u2", "unorm"), 85: (3, "<i2", "snorm"), 90: (3, "<f2", "float"),
    91: (4, "<u2", "unorm"), 92: (4, "<i2", "snorm"), 95: (4, "<u2", "uint"), 97: (4, "<f2", "float"),
    98: (1, "<u4", "uint"), 100: (1, "<f4", "float"), 101: (2, "<u4", "uint"), 103: (2, "<f4", "float"),
    104: (3, "<u4", "uint"), 106: (3, "<f4", "float"), 107: (4, "<u4", "uint"), 109: (4, "<f4", "float"),
}


def decodificar_atributo(datos_u8, posiciones, formato):
    """Lee un atributo para cada posición (byte de inicio) dada. Devuelve (float32 [n, comps], n_fuera_de_rango).
    Las filas cuyos bytes caen fuera del archivo quedan en 0."""
    if formato not in FORMATOS_ATRIBUTO:
        raise ValueError(f"formato de atributo {formato} no soportado")
    ncomp, dt, tipo = FORMATOS_ATRIBUTO[formato]
    dtype = np.dtype(dt)
    tam = ncomp * dtype.itemsize
    pos = np.asarray(posiciones, dtype=np.int64)
    ok = (pos >= 0) & (pos + tam <= len(datos_u8))
    seguro = np.where(ok, pos, 0)
    if len(datos_u8) < tam:
        return np.zeros((len(pos), ncomp), dtype=np.float32), int(len(pos))
    crudo = np.ascontiguousarray(datos_u8[seguro[:, None] + np.arange(tam)[None, :]])
    vals = crudo.view(dtype).reshape(len(pos), ncomp)
    if tipo == "unorm":
        v = vals.astype(np.float32) / np.float32(np.iinfo(dtype).max)
    elif tipo == "snorm":
        v = np.maximum(vals.astype(np.float32) / np.float32(np.iinfo(dtype).max), -1.0)
    else:
        v = vals.astype(np.float32)
    v[~ok] = 0.0
    return v, int((~ok).sum())


class Malla:
    def __init__(self):
        self.pos = np.zeros((0, 3), np.float32)
        self.uv = None
        self.caras = np.zeros((0, 3), np.int64)      # triángulos
        self.lineas = np.zeros((0, 2), np.int64)     # aristas explícitas (topologías de línea)
        self.avisos = []
        self.attr_pos = None
        self.attr_uv = None
        self.n_indices = 0
        self.info = {}          # datos extra (p.ej. de una Part del volcado de modelos)

    @property
    def vacia(self):
        return len(self.pos) == 0


def _es_atributo_uv(a):
    return a.get("format") in (83, 103, 77, 78) and a.get("location") != 0


def atributos_del_pipeline(pipeline):
    return list((pipeline or {}).get("vertex_attributes", []))


def atributo_posicion_por_defecto(attrs):
    for a in attrs:
        if a.get("location") == 0 and FORMATOS_ATRIBUTO.get(a.get("format"), (0,))[0] >= 3:
            return a
    for a in attrs:
        if FORMATOS_ATRIBUTO.get(a.get("format"), (0,))[0] >= 3:
            return a
    return attrs[0] if attrs else None


def atributo_uv_por_defecto(attrs, pos):
    cand = [a for a in attrs if _es_atributo_uv(a) and a is not pos]
    cand.sort(key=lambda a: (a.get("format") != 103, a.get("location", 99)))  # prefiere R32G32_SFLOAT
    return cand[0] if cand else None


def _triangulos(topologia, ref, avisos):
    """Convierte la lista de referencias (índices a vértices únicos) en triángulos/líneas según la topología."""
    n = len(ref)
    vacio_t, vacio_l = np.zeros((0, 3), np.int64), np.zeros((0, 2), np.int64)
    if topologia == 3:
        n3 = (n // 3) * 3
        return ref[:n3].reshape(-1, 3), vacio_l
    if topologia == 4:
        if n < 3:
            return vacio_t, vacio_l
        a, b, c = ref[:-2].copy(), ref[1:-1].copy(), ref[2:].copy()
        impar = (np.arange(n - 2) % 2) == 1
        b[impar], c[impar] = ref[2:][impar], ref[1:-1][impar]
        t = np.stack([a, b, c], axis=1)
        return t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])], vacio_l
    if topologia == 5:
        if n < 3:
            return vacio_t, vacio_l
        return np.stack([np.full(n - 2, ref[0]), ref[1:-1], ref[2:]], axis=1), vacio_l
    if topologia == 1:
        return vacio_t, ref[:(n // 2) * 2].reshape(-1, 2)
    if topologia == 2:
        return vacio_t, (np.stack([ref[:-1], ref[1:]], axis=1) if n >= 2 else vacio_l)
    if topologia == 0:
        return vacio_t, vacio_l
    avisos.append(f"topología {NOMBRES_TOPOLOGIA.get(topologia, topologia)} no soportada: se muestran solo los puntos")
    return vacio_t, vacio_l


def construir_malla(trace, draw, indice, attr_pos=None, attr_uv=None):
    """Reconstruye la geometría de un draw. attr_pos / attr_uv: dicts de 'vertex_attributes' del pipeline
    (si no se dan, se elige location 0 para la posición y el primer par float para UV).
    Nunca lanza por datos faltantes: devuelve una Malla vacía con la explicación en .avisos."""
    m = Malla()
    pipe = trace.pipelines.get(draw.pipeline)
    if not pipe:
        m.avisos.append("el draw no tiene pipeline conocido")
        return m
    attrs = atributos_del_pipeline(pipe)
    attr_pos = attr_pos or atributo_posicion_por_defecto(attrs)
    if not attr_pos:
        m.avisos.append("el pipeline no declara atributos de vértice")
        return m
    if attr_uv is None:
        attr_uv = atributo_uv_por_defecto(attrs, attr_pos)
    elif attr_uv == "ninguno":
        attr_uv = None
    m.attr_pos, m.attr_uv = attr_pos, attr_uv
    ev, geo = draw.ev, draw.geometria
    if ev.get("instance_count", 1) > 1:
        m.avisos.append(f"el draw usa {ev['instance_count']} instancias: se muestra solo la primera forma")

    def cargar(nombre):
        ruta = indice.buscar(nombre, trace.carpeta) if nombre else None
        if ruta is None:
            return None, nombre
        try:
            return np.frombuffer(indice.leer(ruta), dtype=np.uint8), nombre
        except OSError as e:
            m.avisos.append(f"no se pudo leer {nombre}: {e}")
            return None, nombre

    # --- índices -> vértices usados ---
    if draw.indexado:
        ib = draw.ib or {}
        isz = 4 if ib.get("index_type") == 1 else 2
        geo_i = geo.get("index")
        if geo_i:
            datos_i, nom = cargar(trace.nombre_modelo(geo_i.get("model")))
            base_i = 0
        elif ib.get("model"):
            datos_i, nom = cargar(trace.nombre_modelo(ib.get("model")))
            base_i = (ib.get("offset", 0) - (ib.get("region_offset") or 0)) + ev.get("first_index", 0) * isz
        else:
            m.avisos.append("el draw indexado no tiene buffer de índices identificado (el generador no pudo leerlo)")
            return m
        if datos_i is None:
            m.avisos.append(f"falta el archivo de índices {nom or '(sin nombre)'}")
            return m
        disponibles = max(0, (len(datos_i) - base_i) // isz)
        n = min(ev.get("index_count", 0), disponibles)
        if n < ev.get("index_count", 0):
            m.avisos.append(f"el archivo de índices solo tiene {disponibles} de {ev['index_count']} índices")
        idx = np.frombuffer(datos_i, dtype=np.uint32 if isz == 4 else np.uint16, count=n, offset=base_i).astype(np.int64) \
            if n > 0 else np.zeros(0, np.int64)
        vidx = idx + int(ev.get("vertex_offset", 0))
    else:
        vidx = int(ev.get("first_vertex", 0)) + np.arange(ev.get("vertex_count", 0), dtype=np.int64)
    m.n_indices = len(vidx)
    if len(vidx) == 0:
        m.avisos.append("el draw no tiene índices/vértices para mostrar")
        return m
    if vidx.min() < 0:
        m.avisos.append("hay índices negativos tras aplicar vertex_offset: se descartan")
        vidx = np.where(vidx < 0, -1, vidx)
    uniq, inv = np.unique(vidx, return_inverse=True)
    validos = uniq >= 0
    if not validos.all():  # el -1 queda en uniq[0]; se evita y se reasigna al primer vértice válido
        uniq = np.where(validos, uniq, 0)

    strides = {b["binding"]: b.get("stride", 0) for b in pipe.get("vertex_bindings", [])}

    def datos_binding(binding):
        gv = next((v for v in geo.get("vertex", []) if v.get("binding") == binding), None)
        if gv:
            d, nom = cargar(trace.nombre_modelo(gv.get("model")))
            return d, 0, nom
        vb = draw.vbs.get(binding)
        if vb and vb.get("model"):
            d, nom = cargar(trace.nombre_modelo(vb.get("model")))
            return d, vb.get("offset", 0) - (vb.get("region_offset") or 0), nom
        if vb and vb.get("buffer") is not None:
            # ¿es la salida de un compute de skinning? Esos vértices solo existen en la GPU: se usa la
            # ENTRADA del compute (posición/normal/tangente en reposo), alineada con el offset del binding.
            sk, ini = trace.skin_de_salida(vb.get("buffer"), vb.get("offset", 0))
            if sk:
                src = sk.get("source") or {}
                if src.get("status") != "ok" or not src.get("file"):
                    m.avisos.append(f"binding {binding}: vértices skinneados y la entrada del skinning no se pudo leer ({src.get('status', 'sin datos')})")
                    return None, 0, None
                d, nom = cargar(src["file"])
                if d is not None:
                    stride_src = src.get("stride")
                    if stride_src and strides.get(binding) and stride_src != strides[binding]:
                        m.avisos.append(f"binding {binding}: el stride del pipeline ({strides[binding]}) no coincide con el de la entrada del skinning ({stride_src}); la forma puede salir mal")
                    m.avisos.append(f"binding {binding}: vértices skinneados en la GPU; se muestra la pose base (entrada del compute, sin aplicar huesos)")
                    return d, (src.get("slice_offset", 0) or 0) + (vb.get("offset", 0) - ini), nom
                return None, 0, nom
        return None, 0, None

    def leer_attr(attr):
        d, base, nom = datos_binding(attr.get("binding"))
        if d is None:
            m.avisos.append(f"binding {attr.get('binding')}: " + (f"falta el archivo {nom}" if nom else "el generador no pudo leer ese buffer de vértices"))
            return None
        stride = strides.get(attr.get("binding"), 0)
        try:
            v, fuera = decodificar_atributo(d, base + uniq * stride + attr.get("offset", 0), attr.get("format"))
        except ValueError as e:
            m.avisos.append(str(e))
            return None
        if fuera:
            m.avisos.append(f"{fuera} vértice(s) caen fuera del archivo (location {attr.get('location')}): quedan en 0")
        return v

    p = leer_attr(attr_pos)
    if p is None:
        return m
    if p.shape[1] < 3:
        p = np.concatenate([p, np.zeros((len(p), 3 - p.shape[1]), np.float32)], axis=1)
    m.pos = np.ascontiguousarray(p[:, :3], dtype=np.float32)
    if attr_uv:
        uv = leer_attr(attr_uv)
        if uv is not None and uv.shape[1] >= 2:
            m.uv = np.ascontiguousarray(uv[:, :2], dtype=np.float32)
    m.caras, m.lineas = _triangulos(pipe.get("topology", 3), inv.astype(np.int64), m.avisos)
    return m


# ---------------------------------------------------------------------------
# Volcado de modelos del generador (carpeta Models/ dentro de cada Frame_Trace_*)
#   PartNN-vb0=<hash>.buf/.txt  vértices ya unidos: posición, normal, tangente, pesos, índices de hueso, texcoords
#   PartNN-ib=<hash>.buf/.txt   índices          PartNN-bones.buf   matrices de huesos      PartNN<Slot>.ktx2/.raw texturas
# ---------------------------------------------------------------------------
_RE_PART_VB = re.compile(r"^(Part\d+)-vb0=([0-9a-fA-F]+)\.buf$")
DXGI_A_VK = {"R8_UNORM": 9, "R8G8_UNORM": 16, "R8G8B8A8_UNORM": 37, "R8G8B8A8_SNORM": 38, "R8G8B8A8_UINT": 41,
             "R16_UNORM": 70, "R16_SNORM": 71, "R16_FLOAT": 76, "R16G16_UNORM": 77, "R16G16_SNORM": 78, "R16G16_UINT": 81,
             "R16G16_FLOAT": 83, "R16G16B16A16_UNORM": 91, "R16G16B16A16_SNORM": 92, "R16G16B16A16_UINT": 95,
             "R16G16B16A16_FLOAT": 97, "R32_UINT": 98, "R32_FLOAT": 100, "R32G32_UINT": 101, "R32G32_FLOAT": 103,
             "R32G32B32_UINT": 104, "R32G32B32_FLOAT": 106, "R32G32B32A32_UINT": 107, "R32G32B32A32_FLOAT": 109}
_TOPOLOGIA_TXT = {"pointlist": 0, "linelist": 1, "linestrip": 2, "trianglelist": 3, "trianglestrip": 4}
# layout fijo que escribe el generador cuando no hay .txt: pos/normal/tangent | pesos/índices | texcoords
_ELEMENTOS_PART = [("POSITION", 0, "R32G32B32_FLOAT", 0), ("NORMAL", 0, "R32G32B32_FLOAT", 12), ("TANGENT", 0, "R32G32B32A32_FLOAT", 24),
                   ("BLENDWEIGHTS", 0, "R32G32B32A32_FLOAT", 40), ("BLENDINDICES", 0, "R32G32B32A32_UINT", 56)]


def es_part_vb(ruta):
    return _RE_PART_VB.match(Path(ruta).name) is not None


def _cabecera_txt(ruta, marca):
    """Líneas de un .txt de 3DMigoto hasta la marca (los datos de vértices pueden pesar decenas de MB)."""
    lineas = []
    try:
        with open(str(ruta), "r", encoding="utf-8", errors="replace") as f:
            for linea in f:
                if linea.strip().startswith(marca) or len(lineas) > 400:
                    break
                lineas.append(linea.rstrip("\r\n"))
    except OSError:
        pass
    return lineas


def _layout_part(txt):
    stride, topologia, elementos, actual = None, 3, [], None
    for l in _cabecera_txt(txt, "vertex-data"):
        t = l.strip()
        if t.startswith("stride:"):
            stride = int(t.split(":", 1)[1])
        elif t.startswith("topology:"):
            topologia = _TOPOLOGIA_TXT.get(t.split(":", 1)[1].strip(), 3)
        elif t.startswith("element["):
            actual = {}
            elementos.append(actual)
        elif actual is not None and ":" in t:
            k, v = [x.strip() for x in t.split(":", 1)]
            actual[k] = v
    els = []
    for e in elementos:
        try:
            els.append((e["SemanticName"], int(e.get("SemanticIndex", 0)), e["Format"], int(e["AlignedByteOffset"])))
        except (KeyError, ValueError):
            pass
    return stride, topologia, els


def construir_malla_part(ruta_vb):
    """Malla en pose base de una Part del volcado de modelos (vb0 + ib + layout del .txt)."""
    m = Malla()
    ruta_vb = Path(ruta_vb)
    mt = _RE_PART_VB.match(ruta_vb.name)
    if not mt:
        m.avisos.append("el nombre no es PartNN-vb0=<hash>.buf")
        return m
    parte = mt.group(1)
    stride, topologia, elementos = _layout_part(ruta_vb.with_suffix(".txt"))
    if not elementos:
        elementos = list(_ELEMENTOS_PART)
        stride = stride or 72
        m.avisos.append("no hay .txt de layout: se usa el layout fijo del generador (posición, normal, tangente, pesos, índices; sin texcoords)")
    try:
        vb = np.frombuffer(ruta_vb.read_bytes(), dtype=np.uint8)
    except OSError as e:
        m.avisos.append(f"no se pudo leer {ruta_vb.name}: {e}")
        return m
    if not stride:
        m.avisos.append("el layout no indica el stride")
        return m
    n = len(vb) // stride
    ibs = sorted(ruta_vb.parent.glob(f"{parte}-ib=*.buf"))
    if not ibs:
        m.avisos.append(f"falta {parte}-ib=*.buf (los índices de esta parte)")
        return m
    ib_ruta = ibs[0]
    ib_txt = _cabecera_txt(ib_ruta.with_suffix(".txt"), "\x00")
    es32 = any("R32_UINT" in l for l in ib_txt) or (not ib_txt and n > 65535)
    try:
        idx = np.frombuffer(ib_ruta.read_bytes(), dtype="<u4" if es32 else "<u2").astype(np.int64)
    except (OSError, ValueError) as e:
        m.avisos.append(f"no se pudo leer {ib_ruta.name}: {e}")
        return m
    fuera = idx >= n
    if fuera.any():
        m.avisos.append(f"{int(fuera.sum())} índice(s) apuntan fuera de los {n} vértices: se descartan")
        idx = np.where(fuera, 0, idx)
    m.n_indices = len(idx)
    uniq, inv = np.unique(idx, return_inverse=True)
    base = uniq * stride

    def leer(sem, num=0):
        for nombre, i, fmt, off in elementos:
            if nombre.upper() == sem and i == num and fmt in DXGI_A_VK:
                v, _f = decodificar_atributo(vb, base + off, DXGI_A_VK[fmt])
                return v, {"location": 0, "binding": 0, "format": DXGI_A_VK[fmt], "format_name": fmt, "offset": off}
        return None, None

    p, m.attr_pos = leer("POSITION")
    if p is None:
        m.avisos.append("el layout no tiene POSITION en un formato conocido")
        return m
    m.pos = np.ascontiguousarray(p[:, :3], dtype=np.float32)
    uv, m.attr_uv = leer("TEXCOORD")
    if uv is not None and uv.shape[1] >= 2:
        m.uv = np.ascontiguousarray(uv[:, :2], dtype=np.float32)
    m.caras, m.lineas = _triangulos(topologia, inv.astype(np.int64), m.avisos)
    bones = ruta_vb.parent / f"{parte}-bones.buf"
    texturas = sorted(p for p in ruta_vb.parent.iterdir()
                      if p.name.startswith(parte) and "-" not in p.name and p.suffix.lower() in (".ktx2", ".raw"))
    m.info = {"parte": parte, "vertices": n, "stride": stride, "ib": ib_ruta, "bones": bones if bones.exists() else None, "texturas": texturas}
    m.avisos.append("pose base: no se aplican los huesos")
    return m


# ---------------------------------------------------------------------------
# Render rápido (sin Tk): PIL dibuja y la interfaz solo muestra la imagen
# ---------------------------------------------------------------------------
def _aristas_unicas(caras, lineas):
    partes = []
    if len(caras):
        partes += [caras[:, [0, 1]], caras[:, [1, 2]], caras[:, [2, 0]]]
    if len(lineas):
        partes.append(lineas)
    if not partes:
        return np.zeros((0, 2), np.int64)
    e = np.concatenate(partes)
    e = np.sort(e, axis=1)
    return np.unique(e, axis=0)


def renderizar_malla(malla, ancho=700, alto=480, rot_x=0.5, rot_y=0.5, zoom=1.0, modo="alambre", max_elementos=120000, textura_material=None):
    """Imagen RGB de la malla. Material aplica una textura al modo sólido cuando hay UV."""

    img = Image.new("RGB", (ancho, alto), (17, 17, 17))
    if malla.vacia:
        return img
    ok = np.isfinite(malla.pos).all(axis=1)
    P = np.where(ok[:, None], malla.pos, 0.0).astype(np.float64)
    centro = (P[ok].min(axis=0) + P[ok].max(axis=0)) / 2 if ok.any() else np.zeros(3)
    extension = float((P[ok].max(axis=0) - P[ok].min(axis=0)).max()) if ok.any() else 1.0
    P = (P - centro) / (extension if extension > 1e-12 else 1.0)
    cy, sy, cx, sx = np.cos(rot_y), np.sin(rot_y), np.cos(rot_x), np.sin(rot_x)
    x1 = P[:, 0] * cy - P[:, 2] * sy
    z1 = P[:, 0] * sy + P[:, 2] * cy
    y2 = P[:, 1] * cx - z1 * sx
    z2 = P[:, 1] * sx + z1 * cx
    escala = 0.85 * min(ancho, alto) * zoom
    X = ancho / 2 + x1 * escala
    Y = alto / 2 - y2 * escala
    dib = ImageDraw.Draw(img)
    caras = malla.caras[ok[malla.caras].all(axis=1)] if len(malla.caras) else malla.caras
    if modo == "puntos" or (malla.vacia is False and len(caras) == 0 and len(malla.lineas) == 0):
        for i in np.flatnonzero(ok)[:max_elementos]:
            dib.point((float(X[i]), float(Y[i])), fill=(0, 255, 102))
        return img
    if modo in ("solido", "material") and len(caras):
        if len(caras) > max_elementos:
            caras = caras[:: int(np.ceil(len(caras) / max_elementos))]
        A, B, C = P[caras[:, 0]], P[caras[:, 1]], P[caras[:, 2]]
        n = np.cross(B - A, C - A)
        ln = np.linalg.norm(n, axis=1)
        ln[ln == 0] = 1.0
        n = n / ln[:, None]
        # normal en el espacio de cámara para un sombreado simple
        nx = n[:, 0] * cy - n[:, 2] * sy
        nz0 = n[:, 0] * sy + n[:, 2] * cy
        ny = n[:, 1] * cx - nz0 * sx
        nz = n[:, 1] * sx + nz0 * cx
        luz = np.abs(nz) * 0.75 + 0.25
        prof = z2[caras].mean(axis=1)
        if modo == "material" and textura_material is not None and malla.uv is not None and len(malla.uv) == len(malla.pos):
            # Rasterización UV por triángulo con interpolación baricéntrica y alpha real.
            tex = textura_material.convert("RGBA")
            tw, th = tex.size
            pix = np.asarray(tex, dtype=np.uint8)
            canvas = np.asarray(img.convert("RGBA"), dtype=np.uint8).copy()
            for k in np.argsort(-prof):
                t = caras[k]
                pts = np.array([[X[t[0]], Y[t[0]]], [X[t[1]], Y[t[1]]], [X[t[2]], Y[t[2]]]], dtype=np.float64)
                uv = malla.uv[t].astype(np.float64).copy()
                if not np.isfinite(pts).all() or not np.isfinite(uv).all():
                    continue
                xlo = max(0, int(np.floor(pts[:, 0].min())))
                xhi = min(ancho - 1, int(np.ceil(pts[:, 0].max())))
                ylo = max(0, int(np.floor(pts[:, 1].min())))
                yhi = min(alto - 1, int(np.ceil(pts[:, 1].max())))
                if xhi < xlo or yhi < ylo:
                    continue
                den = ((pts[1,1]-pts[2,1])*(pts[0,0]-pts[2,0]) +
                       (pts[2,0]-pts[1,0])*(pts[0,1]-pts[2,1]))
                if abs(den) < 1e-8:
                    continue
                gx, gy = np.meshgrid(np.arange(xlo, xhi+1), np.arange(ylo, yhi+1))
                w0 = ((pts[1,1]-pts[2,1])*(gx-pts[2,0]) +
                      (pts[2,0]-pts[1,0])*(gy-pts[2,1])) / den
                w1 = ((pts[2,1]-pts[0,1])*(gx-pts[2,0]) +
                      (pts[0,0]-pts[2,0])*(gy-pts[2,1])) / den
                w2 = 1.0 - w0 - w1
                mask = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
                if not mask.any():
                    continue
                u = (w0*uv[0,0] + w1*uv[1,0] + w2*uv[2,0]) % 1.0
                v = (w0*uv[0,1] + w1*uv[1,1] + w2*uv[2,1]) % 1.0
                tx = np.minimum((u*tw).astype(np.int64), tw-1)
                ty = np.minimum((v*th).astype(np.int64), th-1)
                rgba = pix[ty, tx].astype(np.float64)
                shade = float(luz[k])
                rgba[..., :3] *= shade
                alpha = rgba[..., 3] / 255.0
                region = canvas[ylo:yhi+1, xlo:xhi+1]
                for ch in range(3):
                    region[..., ch][mask] = (rgba[..., ch][mask] * alpha[mask] +
                                               region[..., ch][mask] * (1.0-alpha[mask])).astype(np.uint8)
                region[..., 3][mask] = 255
            return Image.fromarray(canvas, "RGBA").convert("RGB")
        for k in np.argsort(-prof):  # del más lejano al más cercano (algoritmo del pintor)
            t = caras[k]
            g = int(40 + 200 * float(luz[k]))
            pts = [(float(X[t[0]]), float(Y[t[0]])), (float(X[t[1]]), float(Y[t[1]])), (float(X[t[2]]), float(Y[t[2]]))]
            if textura_material is not None and malla.uv is not None and len(malla.uv) == len(malla.pos):
                # Render aproximado por triángulo: muestrea diffuse en el centro UV.
                uv = np.nanmean(malla.uv[t], axis=0)
                if np.isfinite(uv).all():
                    tx = int(np.clip(uv[0] % 1.0, 0.0, 0.999999) * textura_material.width)
                    ty = int(np.clip(uv[1] % 1.0, 0.0, 0.999999) * textura_material.height)
                    rgb = textura_material.getpixel((tx, ty))
                    shade = float(luz[k])
                    color = tuple(int(np.clip(ch * shade, 0, 255)) for ch in rgb[:3])
                else:
                    color = (g // 2, g, g // 2)
            else:
                color = (g // 2, g, g // 2)
            dib.polygon(pts, fill=color)
        return img
    e = _aristas_unicas(caras, malla.lineas)
    if len(e) > max_elementos:
        e = e[:: int(np.ceil(len(e) / max_elementos))]
    for a, b in e:
        dib.line((float(X[a]), float(Y[a]), float(X[b]), float(Y[b])), fill=(0, 255, 102), width=1)
    return img


def exportar_obj(malla, ruta, nombre="xxami_draw"):
    """Escribe un .obj (triángulos; UV si hay). La V se invierte (Vulkan: origen arriba; OBJ: abajo)."""
    con_uv = malla.uv is not None and len(malla.uv) == len(malla.pos)
    with open(str(ruta), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# XXAMI - exportado desde frame trace\no {nombre}\n")
        for v in malla.pos:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        if con_uv:
            for t in malla.uv:
                f.write(f"vt {t[0]:.6f} {1.0 - t[1]:.6f}\n")
        for c in malla.caras:
            a, b, d = (int(c[0]) + 1, int(c[1]) + 1, int(c[2]) + 1)
            f.write(f"f {a}/{a} {b}/{b} {d}/{d}\n" if con_uv else f"f {a} {b} {d}\n")
    return len(malla.caras)
