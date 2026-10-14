# -*- coding: utf-8 -*-
"""
trace_tab.py -- pestaña "Frames" (lista lateral) + "Frame Trace" (visor) para gui.py.

Toda la lógica de datos vive en xxami_trace.py (sin Tk, con pruebas). Aquí solo hay interfaz.
Se engancha con 3 líneas en gui.py (ver parche): crea una subpestaña "Frames" junto a
Shaders/Texturas/Modelos y una pestaña "Frame Trace" a la derecha.
"""
import os
import re
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from PIL import ImageTk

import xxami_trace as X

MODOS = {"Alambre": "alambre", "Sólido": "solido", "Puntos": "puntos"}
_RE_BUF = re.compile(r"^(?:vb|ib|vbib)_([0-9a-fA-F]+)_\d+\.buf$")


class PestanaTrace:
    def __init__(self, app, log=None):
        self.app = app
        self._log = log or (lambda t: None)
        self.indice = X.IndiceRecursos()
        self.trace = None
        self.draw = None
        self.malla = None
        self.rot_x, self.rot_y, self.zoom = 0.5, 0.6, 1.0
        self._img_tk = None
        self._ultimo_dibujo = 0.0
        self._arrastre = None
        self._attrs = []          # atributos del pipeline del draw actual
        self._iid_draw = {}       # iid del árbol -> Draw
        self._ids_enlaces = 0
        self._cache_traces = {}   # ruta del json -> Trace ya leído
        self._ctx_buf = None      # buffer abierto desde la lista Modelos y los draws que lo usan
        self._construir_lateral()
        self._construir_principal()

    # ------------------------------------------------------------------ utilidades
    def _seguro(self, fn):
        """Envuelve un callback de Tk: un error aquí nunca debe tumbar la aplicación."""
        def envoltura(*a, **k):
            try:
                return fn(*a, **k)
            except Exception:
                self._log("[PestanaTrace] " + traceback.format_exc())
                try:
                    self.lbl_estado.config(text="Error interno (ver xxami_crash_log.txt)")
                except Exception:
                    pass
        return envoltura

    # ------------------------------------------------------------------ interfaz lateral
    def _construir_lateral(self):
        app = self.app
        self.frame_lateral = ttk.Frame(app.sub_tabs)
        app.sub_tabs.add(self.frame_lateral, text="Frames")
        ttk.Label(self.frame_lateral, text="Capturas (Frame_Trace_*):", font=("Arial", 8)).pack(anchor="w", padx=2, pady=(4, 0))
        self.lst_trazas = tk.Listbox(self.frame_lateral, height=4, exportselection=False, font=("Consolas", 9),
                                     background="#2b2b2b", foreground="#ffffff")
        self.lst_trazas.pack(fill="x", padx=2, pady=2)
        self.lst_trazas.bind("<<ListboxSelect>>", self._seguro(self._on_elegir_traza))
        marco = ttk.Frame(self.frame_lateral)
        marco.pack(expand=True, fill="both", padx=2, pady=2)
        sb = ttk.Scrollbar(marco, orient="vertical")
        estilo = ttk.Style()
        try:
            estilo.configure("XXAMI.Treeview", background="#2b2b2b", foreground="#ffffff", fieldbackground="#2b2b2b", rowheight=18)
            estilo.map("XXAMI.Treeview", background=[("selected", "#0078d7")], foreground=[("selected", "#ffffff")])
        except Exception:
            pass
        self.arbol = ttk.Treeview(marco, show="tree", style="XXAMI.Treeview", yscrollcommand=sb.set, selectmode="browse")
        sb.config(command=self.arbol.yview)
        sb.pack(side="right", fill="y")
        self.arbol.pack(side="left", expand=True, fill="both")
        self.arbol.bind("<<TreeviewSelect>>", self._seguro(self._on_elegir_nodo))

    # ------------------------------------------------------------------ interfaz principal
    def _construir_principal(self):
        app = self.app
        self.tab = ttk.Frame(app.tabs)
        app.tabs.add(self.tab, text=" Frame Trace ")
        barra = ttk.Frame(self.tab, padding=5)
        barra.pack(side="top", fill="x")
        ttk.Label(barra, text="Posición:").pack(side="left")
        self.cb_pos = ttk.Combobox(barra, state="readonly", width=30)
        self.cb_pos.pack(side="left", padx=(2, 8))
        self.cb_pos.bind("<<ComboboxSelected>>", self._seguro(lambda e=None: self._reconstruir()))
        ttk.Label(barra, text="UV:").pack(side="left")
        self.cb_uv = ttk.Combobox(barra, state="readonly", width=30)
        self.cb_uv.pack(side="left", padx=(2, 8))
        self.cb_uv.bind("<<ComboboxSelected>>", self._seguro(lambda e=None: self._reconstruir()))
        self.cb_modo = ttk.Combobox(barra, state="readonly", width=9, values=list(MODOS))
        self.cb_modo.set("Alambre")
        self.cb_modo.pack(side="left", padx=(2, 8))
        self.cb_modo.bind("<<ComboboxSelected>>", self._seguro(lambda e=None: self._redibujar(forzar=True)))
        ttk.Button(barra, text="Exportar OBJ", command=self._seguro(self.exportar_obj)).pack(side="left", padx=4)
        self.lbl_estado = ttk.Label(barra, text="Elige una captura en la pestaña lateral «Frames»", font=("Arial", 9, "italic"))
        self.lbl_estado.pack(side="right", padx=10)

        panel = ttk.PanedWindow(self.tab, orient="vertical")
        panel.pack(expand=True, fill="both", padx=5, pady=5)
        marco_img = ttk.Frame(panel)
        self.lbl_img = tk.Label(marco_img, background="#111111", cursor="fleur")
        self.lbl_img.pack(expand=True, fill="both")
        panel.add(marco_img, weight=3)
        marco_txt = ttk.Frame(panel)
        sb = ttk.Scrollbar(marco_txt, orient="vertical")
        self.txt = tk.Text(marco_txt, height=12, wrap="word", font=("Consolas", 9), background="#1e1e1e", foreground="#d4d4d4",
                           yscrollcommand=sb.set, state="disabled")
        sb.config(command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", expand=True, fill="both")
        self.txt.tag_config("titulo", foreground="#00ff66", font=("Consolas", 9, "bold"))
        self.txt.tag_config("malo", foreground="#ff6b6b")
        self.txt.tag_config("aviso", foreground="#e5c07b")
        panel.add(marco_txt, weight=2)

        self.lbl_img.bind("<ButtonPress-1>", self._seguro(self._inicio_arrastre))
        self.lbl_img.bind("<B1-Motion>", self._seguro(self._arrastrar))
        self.lbl_img.bind("<MouseWheel>", self._seguro(self._rueda))
        self.lbl_img.bind("<Configure>", self._seguro(lambda e=None: self._redibujar(forzar=True)))

    # ------------------------------------------------------------------ carga
    def cargar_raiz(self, raiz):
        """Llamado por gui.py tras elegir la carpeta raíz del volcado."""
        self.trace = None
        self.draw = None
        self.malla = None
        self._cache_traces = {}
        self._ctx_buf = None
        self.indice.escanear(raiz)
        self.lst_trazas.delete(0, tk.END)
        for ruta in self.indice.trazas:
            self.lst_trazas.insert(tk.END, ruta.parent.name)
        self._limpiar_arbol()
        self._escribir([("No hay capturas de frame en esta carpeta (no se encontró frame_trace.json).\n", "aviso")]
                       if not self.indice.trazas else [(f"{len(self.indice.trazas)} captura(s) de frame encontrada(s). Elige una arriba.\n", None)])
        self._mostrar_imagen_vacia()
        if self.indice.trazas:
            self.lst_trazas.selection_set(tk.END)
            self._on_elegir_traza()

    def _on_elegir_traza(self, _e=None):
        sel = self.lst_trazas.curselection()
        if not sel:
            return
        self._ctx_buf = None
        self._cargar_traza(self.indice.trazas[int(sel[0])])

    def _trace_de(self, ruta_json):
        clave = str(ruta_json)
        if clave not in self._cache_traces:
            self._cache_traces[clave] = X.Trace(ruta_json)
        return self._cache_traces[clave]

    def _cargar_traza(self, ruta):
        """Lee (o reutiliza) un trace y lo muestra en el árbol. Devuelve True si se pudo."""
        self.lbl_estado.config(text="Leyendo " + ruta.parent.name + "...")
        self.app.root.update_idletasks()
        try:
            self.trace = self._trace_de(ruta)
        except Exception as e:
            self.trace = None
            self._limpiar_arbol()
            self._escribir([(f"No se pudo leer {ruta.name}: {e}\n", "malo")])
            self.lbl_estado.config(text="Error leyendo el trace")
            return False
        self._poblar_arbol()
        self._mostrar_resumen_trace()
        self.lbl_estado.config(text=f"{len(self.trace.draws)} draws en {len(self.trace.pases)} render passes")
        return True

    # ------------------------------------------------------------------ árbol
    def _limpiar_arbol(self):
        for iid in self.arbol.get_children():
            self.arbol.delete(iid)
        self._iid_draw = {}

    def _poblar_arbol(self):
        self._limpiar_arbol()
        for pase in self.trace.pases:
            titulo = "(fuera de render pass)" if pase.get("fuera") else f"Pase {pase['indice']}  {pase['w']}x{pase['h']}"
            nodo = self.arbol.insert("", "end", iid=f"p{pase['indice']}", text=f"{titulo}  [{len(pase['draws'])} draws]")
            for d in pase["draws"]:
                iid = f"d{d.idx}"
                self._iid_draw[iid] = d
                self.arbol.insert(nodo, "end", iid=iid, text=d.etiqueta())
        if self.trace.skins:
            nodo = self.arbol.insert("", "end", iid="skins", text=f"Skinning (compute)  [{len(self.trace.skins)} dispatches]")
            for i, e in enumerate(self.trace.skins):
                self.arbol.insert(nodo, "end", iid=f"k{i}", text=f"skin #{i}  {e.get('vertex_count', '?')} vértices")

    def _on_elegir_nodo(self, _e=None):
        sel = self.arbol.selection()
        if not sel or self.trace is None:
            return
        iid = sel[0]
        if iid in self._iid_draw:
            self._mostrar_draw(self._iid_draw[iid])
        elif iid.startswith("k") and iid[1:].isdigit():
            self._mostrar_skin(int(iid[1:]))
        elif iid.startswith("p") and iid[1:].isdigit():
            self._mostrar_pase(int(iid[1:]))

    # ------------------------------------------------------------------ texto con enlaces
    def _escribir(self, trozos):
        """trozos: lista de (texto, tag) o (texto, tag, accion). Una acción convierte el trozo en enlace."""
        self.txt.config(state="normal")
        self.txt.delete("1.0", tk.END)
        for t in trozos:
            texto, tag = t[0], t[1]
            if len(t) > 2 and t[2]:
                self._ids_enlaces += 1
                nombre = f"enlace{self._ids_enlaces}"
                self.txt.tag_config(nombre, foreground="#4da6ff", underline=True)
                self.txt.tag_bind(nombre, "<Button-1>", self._seguro(lambda e, a=t[2]: a()))
                self.txt.insert(tk.END, texto, (nombre,))
            elif tag:
                self.txt.insert(tk.END, texto, (tag,))
            else:
                self.txt.insert(tk.END, texto)
        self.txt.config(state="disabled")

    def _mostrar_resumen_trace(self):
        t = self.trace
        tr = [(f"{t.ruta.parent.name}\n", "titulo"),
              (f"Juego: {t.paquete}   Capturado: {t.capturado}\n", None),
              (f"{len(t.draws)} draws · {len(t.pases)} render passes · {len(t.pipelines)} pipelines\n", None),
              (f"Recursos referenciados: {len(t.shaders)} shaders, {len(t.texturas)} texturas, {len(t.modelos)} buffers\n", None)]
        if t.skins:
            tr.append((f"Skinning: {len(t.skins)} dispatch(es) de compute; sus salidas solo existen en la GPU\n", None))
        md = t.model_dump
        if md:
            tr.append((f"Volcado de modelos ({md.get('folder', 'Models')}): {md.get('components', 0)} parte(s) de {md.get('candidates', 0)} candidata(s)\n", None))
            for r in md.get("report", []):
                if r.get("status") != "ok":
                    tr.append((f"  {r.get('component')}: omitida - {r.get('reason')}\n", "aviso"))
        for a in t.avisos:
            tr.append((f"⚠ {a}\n", "aviso"))
        faltan = []
        for kind, dic in (("shader", t.shaders), ("textura", t.texturas), ("buffer", t.modelos)):
            for h, r in dic.items():
                if not self.indice.buscar(r.get("file", ""), t.carpeta):
                    faltan.append((kind, r.get("file", h)))
        if faltan:
            tr.append((f"\nNo están en ningún lugar del volcado ({len(faltan)}): se volcarán cuando el juego los cargue de nuevo\n", "malo"))
            for kind, nombre in faltan[:60]:
                tr.append((f"  {kind}: {nombre}\n", None))
            if len(faltan) > 60:
                tr.append((f"  ... y {len(faltan) - 60} más\n", None))
        tr.append(("\nElige un draw en el árbol de la izquierda.\n", None))
        self._escribir(tr)
        self._mostrar_imagen_vacia()

    def _mostrar_skin(self, i):
        t = self.trace
        e = t.skins[i]
        val = next((v for v in t.skin_validation if v.get("skin_ref") == e.get("skin_ref", i)), None)
        tr = [(f"Skinning #{i}  (compute shader {e.get('shader')})\n", "titulo"),
              (f"Grupos {e.get('groups')}   vértices: {e.get('vertex_count')}  (origen del conteo: {e.get('vertex_count_source')})\n\n", None)]
        for rol, titulo in (("source", "Entrada: posición/normal/tangente"), ("skin", "Entrada: pesos e índices de hueso"), ("bones", "Matrices de huesos")):
            r = e.get(rol) or {}
            estado = r.get("status", "?")
            tr.append((f"{titulo}: ", None))
            if estado == "ok":
                tr.append((f"{r.get('file', '')}\n", None))
            else:
                tr.append((f"{estado}\n", "malo"))
        o = e.get("output") or {}
        if o:
            tr.append((f"\nSalida (solo existe en la GPU): buffer {o.get('buffer')} offset {o.get('offset')}  {o.get('bytes')} bytes, stride {o.get('stride')}\n", None))
        if val:
            tr.append((f"\nValidación del generador: {val.get('status')}  (posiciones raras {val.get('bad_positions')}, normales {val.get('bad_normals')}, "
                       f"pesos {val.get('bad_weights')}, huesos {val.get('bad_bone_indices')}, huesos disponibles {val.get('bones_available')})\n",
                       "malo" if val.get("status") not in ("ok",) else None))
        tr.append(("\nLos draws que usan esta salida se ven en pose base (sin huesos).\n", None))
        self.draw = None
        self.malla = None
        self._mostrar_imagen_vacia()
        self._escribir(tr)

    def _mostrar_pase(self, n):
        p = self.trace.pases[n]
        self._escribir([(f"Render pass {n}\n", "titulo"),
                        (f"Área: {p['x']},{p['y']}  {p['w']}x{p['h']}   clear_values: {p['clear']}\n{len(p['draws'])} draws\n", None)])

    # ------------------------------------------------------------------ draw
    def _mostrar_draw(self, draw):
        self.draw = draw
        pipe = self.trace.pipelines.get(draw.pipeline) or {}
        self._attrs = X.atributos_del_pipeline(pipe)
        etiquetas = [self._etq_attr(a) for a in self._attrs]
        self.cb_pos.config(values=etiquetas)
        self.cb_uv.config(values=["(ninguno)"] + etiquetas)
        pos = X.atributo_posicion_por_defecto(self._attrs)
        uv = X.atributo_uv_por_defecto(self._attrs, pos) if pos else None
        self.cb_pos.set(self._etq_attr(pos) if pos else "")
        self.cb_uv.set(self._etq_attr(uv) if uv else "(ninguno)")
        self._reconstruir()

    @staticmethod
    def _etq_attr(a):
        return f"loc {a.get('location')}: {a.get('format_name', a.get('format'))} @b{a.get('binding')}+{a.get('offset')}"

    def _attr_elegido(self, combo, permitir_ninguno):
        texto = combo.get()
        if permitir_ninguno and texto == "(ninguno)":
            return "ninguno"
        for a in self._attrs:
            if self._etq_attr(a) == texto:
                return a
        return None

    def _reconstruir(self):
        if self.trace is None or self.draw is None:
            return
        self.malla = X.construir_malla(self.trace, self.draw, self.indice,
                                       attr_pos=self._attr_elegido(self.cb_pos, False),
                                       attr_uv=self._attr_elegido(self.cb_uv, True))
        self._redibujar(forzar=True)
        self._describir_draw()

    def _describir_draw(self):
        t, d, m = self.trace, self.draw, self.malla
        tr = []
        ctx = self._ctx_buf
        if ctx and ctx["trace"] is t and any(d is x for x in ctx["draws"]):
            tr.append((f"Buffer {ctx['nombre']}  -  lo usan {len(ctx['draws'])} draw(s) en esta captura: ", "titulo"))
            for x in ctx["draws"][:40]:
                tr.append((f"#{x.idx}", None, (lambda x=x: self._ir_a_draw(t, x))))
                tr.append(("  ", None))
            if len(ctx["draws"]) > 40:
                tr.append((f"... (+{len(ctx['draws']) - 40})", None))
            tr.append(("\n", None))
            if ctx["otras"]:
                tr.append(("También aparece en: " + ", ".join(ctx["otras"]) + "\n", None))
            tr.append(("\n", None))
        tr.append((t.resumen_draw(d) + "\n", "titulo"))
        pase = t.pases[d.pase]
        tr.append((f"Render pass {pase['indice']}  {pase['w']}x{pase['h']}   command buffer {d.cb}\n", None))
        tr.append((f"Pipeline {d.pipeline}\n\nShaders:\n", "titulo"))
        for etapa, h in t.shaders_de(d):
            nombre = (t.shaders.get(h) or {}).get("file", f"shader_{h}.spv")
            ruta = self.indice.buscar(nombre, t.carpeta)
            if ruta:
                tr.append((f"  {etapa}: ", None))
                tr.append((f"{nombre}\n", None, (lambda r=ruta: self._abrir_shader(r))))
            else:
                tr.append((f"  {etapa}: {nombre}  (FALTA en el volcado)\n", "malo"))
        tr.append(("\nTexturas enlazadas:\n", "titulo"))
        tx = t.texturas_de(d)
        if not tx:
            tr.append(("  (ninguna)\n", None))
        for nset, binding, _el, h, info in tx:
            donde = f"set {nset} binding {binding}"
            if h is None:
                tr.append((f"  {donde}: imagen sin identificar (render target / no volcada)\n", None))
                continue
            nombre = (info or {}).get("file", f"tex_{h}")
            ruta = self.indice.buscar(nombre, t.carpeta) or self.indice.buscar_por_hash("tex", h, t.carpeta)
            if ruta:
                tr.append((f"  {donde}: ", None))
                tr.append((f"{ruta.name}\n", None, (lambda r=ruta: self._abrir_textura(r))))
            else:
                tr.append((f"  {donde}: {nombre}  (FALTA en el volcado)\n", "malo"))
        ub = t.buffers_uniformes_de(d)
        if ub:
            tr.append(("\nBuffers uniformes / storage:\n", "titulo"))
            for b in ub:
                dyn = "" if b["dinamico"] is None else f" +dinámico {b['dinamico']} = {b['offset_efectivo']}"
                tr.append((f"  set {b['set']} binding {b['binding']}  {b['tipo']}  buffer {b['buffer']}  offset {b['offset']}{dyn}  rango {b['rango']}\n", None))
        tr.append(("\nGeometría:\n", "titulo"))
        if m is not None and not m.vacia:
            tr.append((f"  {len(m.pos)} vértices únicos, {len(m.caras)} triángulos"
                       f"{', ' + str(len(m.lineas)) + ' líneas' if len(m.lineas) else ''}\n", None))
            if m.attr_pos:
                tr.append((f"  posición: {self._etq_attr(m.attr_pos)}\n", None))
            tr.append((f"  UV: {self._etq_attr(m.attr_uv) if m.attr_uv else 'no hay'}\n", None))
        elif m is not None:
            tr.append(("  no se pudo reconstruir\n", "malo"))
        for a in (m.avisos if m is not None else []):
            tr.append((f"⚠ {a}\n", "aviso"))
        self._escribir(tr)

    # ------------------------------------------------------------------ modelos a partir de .buf
    @staticmethod
    def _draws_con_buffer(tr, h):
        """Draws de un trace que leen el buffer de hash h (como geometría directa o como región subida por copia)."""
        res = []
        for d in tr.draws:
            usa = False
            g = d.geometria
            if (g.get("index") or {}).get("model") == h:
                usa = True
            if any(v.get("model") == h for v in g.get("vertex", [])):
                usa = True
            if d.indexado and (d.ib or {}).get("model") == h:
                usa = True
            enlazados = {b.get("binding") for b in (tr.pipelines.get(d.pipeline) or {}).get("vertex_bindings", [])}
            if any(vb.get("model") == h for n, vb in d.vbs.items() if n in enlazados):
                usa = True
            if usa:
                res.append(d)
        return res

    def abrir_buffer(self, ruta):
        """Un .buf suelto no dice qué es: se reconstruye con el draw que lo usa en el frame trace
        (de ahí salen el stride, los formatos, la topología y el resto de buffers del modelo)."""
        ruta = Path(ruta)
        try:
            self.app.tabs.select(self.tab)
        except Exception:
            pass
        if X.es_part_vb(ruta):
            self._abrir_part(ruta)
            return
        m = _RE_BUF.match(ruta.name)
        if not m:
            self._escribir([(f"{ruta.name} no tiene el formato vb_/ib_<hash>_<bytes>.buf\n", "malo")])
            return
        h = m.group(1).lower()
        if not self.indice.trazas:
            self._escribir([("No hay capturas de frame (frame_trace.json) en esta carpeta: sin ellas no se sabe cómo interpretar el buffer.\n", "malo")])
            return
        self.lbl_estado.config(text="Buscando qué draws usan " + ruta.name + "...")
        self.app.root.update_idletasks()
        # la captura que escribió el buffer va primero; el resto se revisa por si también lo usa
        candidatas = sorted(self.indice.trazas, key=lambda r: (r.parent != ruta.parent, r.parent.name))
        hallados = []
        for rj in candidatas:
            try:
                if h not in rj.read_text(encoding="utf-8", errors="ignore"):
                    continue
                tr = self._trace_de(rj)
            except Exception:
                self._log("[PestanaTrace] " + traceback.format_exc())
                continue
            draws = self._draws_con_buffer(tr, h)
            if draws:
                hallados.append((tr, draws))
        if not hallados:
            self.draw = self.malla = None
            self._ctx_buf = None
            self._mostrar_imagen_vacia()
            tam = ruta.stat().st_size if ruta.exists() else 0
            self._escribir([(f"{ruta.name}  ({tam} bytes)\n", "titulo"),
                            ("Ningún draw de las capturas encontradas usa este buffer, así que no se conoce su layout "
                             "(stride, formatos, topología). Suele pasar si se volcó en una sesión cuyo frame_trace.json no está.\n", "aviso")])
            self.lbl_estado.config(text="Buffer sin trace asociado")
            return
        tr, draws = hallados[0]
        self._ctx_buf = {"nombre": ruta.name, "trace": tr, "draws": draws, "otras": [t.ruta.parent.name for t, _d in hallados[1:]]}
        self._ir_a_draw(tr, draws[0])

    def _abrir_part(self, ruta):
        """Una Part del volcado de modelos (Models/PartNN-vb0=...): se ve sin necesitar el trace."""
        self.draw = None
        self._ctx_buf = None
        self._attrs = []
        for cb in (self.cb_pos, self.cb_uv):
            cb.config(values=[])
            cb.set("")
        self.malla = X.construir_malla_part(ruta)
        self._redibujar(forzar=True)
        m = self.malla
        tr = [(f"{ruta.name}\n", "titulo")]
        if not m.vacia:
            tr.append((f"{m.info.get('vertices')} vértices (stride {m.info.get('stride')}), {len(m.caras)} triángulos\n", None))
            tr.append((f"Índices: {m.info['ib'].name}\n", None))
            tr.append((f"UV: {'sí' if m.uv is not None else 'no hay'}\n", None))
            if m.info.get("bones"):
                tr.append((f"Huesos: {m.info['bones'].name}\n", None))
            tr.append(("\nTexturas de esta parte:\n", "titulo"))
            if not m.info.get("texturas"):
                tr.append(("  (ninguna copiada)\n", None))
            for tx in m.info.get("texturas", []):
                tr.append(("  ", None))
                tr.append((f"{tx.name}\n", None, (lambda r=tx: self._abrir_textura(r))))
        for a in m.avisos:
            tr.append((f"⚠ {a}\n", "aviso"))
        self._escribir(tr)
        self.lbl_estado.config(text="Parte del volcado de modelos" if not m.vacia else "No se pudo leer la parte")

    def _ir_a_draw(self, tr, draw):
        """Muestra un draw de un trace (cambiando de captura si hace falta) y lo marca en el árbol."""
        if self.trace is None or self.trace.ruta != tr.ruta:
            if not self._cargar_traza(tr.ruta):
                return
            try:
                self.lst_trazas.selection_clear(0, tk.END)
                self.lst_trazas.selection_set(self.indice.trazas.index(tr.ruta))
            except Exception:
                pass
        iid = f"d{draw.idx}"
        try:
            self.arbol.selection_set(iid)
            self.arbol.see(iid)
        except Exception:
            pass
        self._mostrar_draw(draw)

    # ------------------------------------------------------------------ abrir en las otras pestañas
    def _abrir_shader(self, ruta):
        self._abrir_en_app(str(ruta))

    def _abrir_textura(self, ruta):
        cadena = str(ruta)
        for lbl, r in self.app.archivos_mapeados.items():
            if r == cadena:
                self.app.cargar_textura_desde_explorador(lbl)
                return
        for lbl, r in self.app.archivos_mapeados.items():   # misma textura (mismo hash) en otra carpeta del volcado
            if Path(r).name == Path(cadena).name:
                self.app.cargar_textura_desde_explorador(lbl)
                return
        messagebox.showinfo("Textura", "Esta textura no está en la lista del explorador (puede venir de otra carpeta).\n"
                                       "Vuelve a elegir la carpeta raíz para cargarla.")

    def _abrir_en_app(self, cadena):
        if hasattr(self.app, "abrir_archivo_por_ruta"):
            self.app.abrir_archivo_por_ruta(cadena)

    # ------------------------------------------------------------------ dibujo
    def _tam_imagen(self):
        w, h = self.lbl_img.winfo_width(), self.lbl_img.winfo_height()
        return (w, h) if w > 50 and h > 50 else (700, 420)

    def _mostrar_imagen_vacia(self):
        self._pintar(X.renderizar_malla(X.Malla(), *self._tam_imagen()))

    def _pintar(self, imagen_pil):
        self._img_tk = ImageTk.PhotoImage(imagen_pil)   # referencia guardada: si no, Tk la recoge y se ve en blanco
        self.lbl_img.config(image=self._img_tk)

    def _redibujar(self, forzar=False):
        ahora = time.time()
        if not forzar and ahora - self._ultimo_dibujo < 0.04:   # limita la tasa mientras se arrastra
            return
        self._ultimo_dibujo = ahora
        if self.malla is None:
            return
        w, h = self._tam_imagen()
        self._pintar(X.renderizar_malla(self.malla, w, h, self.rot_x, self.rot_y, self.zoom, MODOS.get(self.cb_modo.get(), "alambre")))

    def _inicio_arrastre(self, e):
        self._arrastre = (e.x, e.y)

    def _arrastrar(self, e):
        if self._arrastre is None:
            return
        dx, dy = e.x - self._arrastre[0], e.y - self._arrastre[1]
        self._arrastre = (e.x, e.y)
        self.rot_y += dx * 0.01
        self.rot_x += dy * 0.01
        self._redibujar()

    def _rueda(self, e):
        self.zoom = max(0.1, min(20.0, self.zoom * (1.1 if e.delta > 0 else 1 / 1.1)))
        self._redibujar()

    # ------------------------------------------------------------------ exportar
    def exportar_obj(self):
        if self.malla is None or self.malla.vacia or not len(self.malla.caras):
            messagebox.showinfo("Exportar OBJ", "No hay una malla de triángulos para exportar.")
            return
        info = getattr(self.malla, "info", {}) or {}
        parte = info.get("parte")
        nombre = f"{parte or ('draw_' + str(self.draw.idx if self.draw else 0))}.obj"
        ruta = filedialog.asksaveasfilename(initialfile=nombre, defaultextension=".obj", filetypes=[("OBJ", "*.obj")])
        if not ruta:
            return

        ruta_obj = Path(ruta)
        n = X.exportar_obj(self.malla, ruta, nombre=ruta_obj.stem)
        texturas = info.get("texturas", [])
        exportadas = {}
        errores = []
        if parte and texturas:
            # Reutiliza exactamente el decodificador del visor (KTX2/RAW, ASTC/ETC2
            # y formatos planos), para que el exportador no tenga una segunda ruta
            # de decodificación con resultados distintos.
            decodificador = getattr(self.app, "decode_texture_to_png", None)
            if decodificador is None:
                errores.append("La aplicación no expone el decodificador de texturas; no se pudieron convertir los KTX2/RAW.")

            for tex in texturas:
                nombre_tex = tex.name
                slot = nombre_tex[len(parte):].rsplit(".", 1)[0]
                if not slot:
                    slot = tex.stem
                destino_png = ruta_obj.with_name(f"{ruta_obj.stem}_{slot}.png")
                try:
                    if decodificador is None or not decodificador(str(tex), str(destino_png)):
                        errores.append(f"{nombre_tex}: no se pudo convertir a PNG")
                        continue
                    exportadas[slot.lower()] = destino_png.name
                except Exception as e:
                    errores.append(f"{nombre_tex}: {e}")

            # El OBJ referencia el MTL; Blender cargará automáticamente el mapa difuso.
            # Los demás mapas se conservan como PNG junto al modelo y se anotan en el
            # MTL sin asumir una semántica de shader que el hash.json no demuestra.
            if exportadas:
                ruta_mtl = ruta_obj.with_suffix(".mtl")
                lineas_mtl = [
                    "# Materiales exportados por XXAMI",
                    "newmtl XXAMI_Material",
                    "Ka 1.000000 1.000000 1.000000",
                    "Kd 1.000000 1.000000 1.000000",
                    "Ks 0.000000 0.000000 0.000000",
                    "d 1.0",
                    "illum 1",
                ]
                if "diffuse" in exportadas:
                    lineas_mtl.append(f"map_Kd {exportadas['diffuse']}")
                # No enlazamos BumpMap como mapa de relieve: en volcados ya verificados
                # ese slot puede contener albedo/diffuse pese a su nombre.
                for slot, archivo in sorted(exportadas.items()):
                    if slot != "diffuse":
                        lineas_mtl.append(f"# Slot {slot}: {archivo}")
                ruta_mtl.write_text("\\n".join(lineas_mtl) + "\\n", encoding="utf-8")
                try:
                    contenido = ruta_obj.read_text(encoding="utf-8")
                    lineas = contenido.splitlines()
                    pos = 1 if lineas and lineas[0].startswith("#") else 0
                    lineas[pos:pos] = [f"mtllib {ruta_mtl.name}", "usemtl XXAMI_Material"]
                    ruta_obj.write_text("\\n".join(lineas) + "\\n", encoding="utf-8")
                except Exception as e:
                    errores.append(f"No se pudo enlazar el material al OBJ: {e}")

        resumen = f"{n} triángulos guardados."
        if exportadas:
            resumen += f"\\nTexturas PNG exportadas: {len(exportadas)}."
            resumen += "\\nSe creó un MTL; Diffuse y BumpMap se enlazan cuando están presentes."
        if errores:
            resumen += "\\n\\nAvisos:\\n" + "\\n".join(errores[:10])
        messagebox.showinfo("Exportar OBJ", resumen)
