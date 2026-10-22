# -*- coding: utf-8 -*-
"""SDL3 + OpenGL capability/context helper for XXAMI-DumpAna.

This module deliberately has no import-time dependency on PySDL3: it loads the
SDL3 shared library at runtime and reports a clear reason when unavailable.
The Tkinter UI can therefore keep using the software renderer on unsupported
systems while the accelerated viewport is being integrated.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import re
from dataclasses import dataclass


@dataclass
class GLStatus:
    available: bool
    message: str
    version: str = ""
    renderer: str = ""
    vendor: str = ""
    major: int = 0
    minor: int = 0


def _sdl_candidates():
    if sys.platform == "win32":
        return ("SDL3.dll", "SDL3")
    if sys.platform == "darwin":
        return ("libSDL3.dylib", "SDL3")
    return ("libSDL3.so.0", "libSDL3.so", "SDL3")


def _load_sdl():
    errors = []
    names = list(_sdl_candidates())
    found = ctypes.util.find_library("SDL3")
    if found:
        names.insert(0, found)
    for name in names:
        try:
            if sys.platform == "win32":
                return ctypes.CDLL(name), name
            return ctypes.CDLL(name), name
        except OSError as exc:
            errors.append(f"{name}: {exc}")
    raise OSError("No se encontró la biblioteca SDL3. " + "; ".join(errors))


class SDL3GLContext:
    """Owns an SDL3 OpenGL window/context. Methods must run on its owner thread."""

    SDL_INIT_VIDEO = 0x00000020
    SDL_WINDOW_OPENGL = 0x00000002
    SDL_WINDOW_RESIZABLE = 0x00000020
    SDL_WINDOW_HIDDEN = 0x00000008
    SDL_GL_CONTEXT_PROFILE_MASK = 21
    SDL_GL_CONTEXT_PROFILE_CORE = 0x0001
    SDL_GL_CONTEXT_PROFILE_COMPATIBILITY = 0x0002
    SDL_GL_CONTEXT_MAJOR_VERSION = 17
    SDL_GL_CONTEXT_MINOR_VERSION = 18
    SDL_GL_DOUBLEBUFFER = 5
    SDL_GL_DEPTH_SIZE = 6

    def __init__(self):
        self.sdl = None
        self.window = None
        self.context = None
        self._initialized = False
        self.status = GLStatus(False, "Contexto OpenGL no inicializado")

    def _function(self, name, restype, argtypes):
        fn = getattr(self.sdl, name)
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    def create(self, title="XXAMI DumpAna — Visor 3D", width=900, height=650,
               minimum=(3, 3), hidden=False):
        """Create a modern OpenGL context, returning GLStatus instead of crashing."""
        try:
            self.sdl, library = _load_sdl()
            init = self._function("SDL_Init", ctypes.c_bool, [ctypes.c_uint32])
            get_error = self._function("SDL_GetError", ctypes.c_char_p, [])
            if not init(self.SDL_INIT_VIDEO):
                raise RuntimeError(self._error(get_error))
            self._initialized = True

            set_attr = self._function("SDL_GL_SetAttribute", ctypes.c_bool,
                                      [ctypes.c_int, ctypes.c_int])
            attrs = (
                (self.SDL_GL_CONTEXT_MAJOR_VERSION, int(minimum[0])),
                (self.SDL_GL_CONTEXT_MINOR_VERSION, int(minimum[1])),
                (self.SDL_GL_CONTEXT_PROFILE_MASK, self.SDL_GL_CONTEXT_PROFILE_CORE),
                (self.SDL_GL_DOUBLEBUFFER, 1),
                (self.SDL_GL_DEPTH_SIZE, 24),
            )
            for attr, value in attrs:
                if not set_attr(attr, value):
                    raise RuntimeError("SDL_GL_SetAttribute: " + self._error(get_error))

            create_window = self._function(
                "SDL_CreateWindow", ctypes.c_void_p,
                [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint64])
            flags = self.SDL_WINDOW_OPENGL | self.SDL_WINDOW_RESIZABLE
            if hidden:
                flags |= self.SDL_WINDOW_HIDDEN
            self.window = create_window(title.encode("utf-8"), int(width), int(height), flags)
            if not self.window:
                raise RuntimeError("SDL_CreateWindow: " + self._error(get_error))

            create_context = self._function("SDL_GL_CreateContext", ctypes.c_void_p,
                                            [ctypes.c_void_p])
            self.context = create_context(self.window)
            if not self.context:
                raise RuntimeError("No se pudo crear contexto OpenGL " +
                                   f"{minimum[0]}.{minimum[1]}: " + self._error(get_error))

            make_current = self._function("SDL_GL_MakeCurrent", ctypes.c_bool,
                                          [ctypes.c_void_p, ctypes.c_void_p])
            if not make_current(self.window, self.context):
                raise RuntimeError("SDL_GL_MakeCurrent: " + self._error(get_error))

            get_proc = self._function("SDL_GL_GetProcAddress", ctypes.c_void_p, [ctypes.c_char_p])
            gl_get_string_ptr = get_proc(b"glGetString")
            if not gl_get_string_ptr:
                raise RuntimeError("El contexto no expone glGetString")
            GL_GET_STRING = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_uint)
            gl_get_string = GL_GET_STRING(gl_get_string_ptr)
            version = self._decode(gl_get_string(0x1F02))
            vendor = self._decode(gl_get_string(0x1F00))
            renderer = self._decode(gl_get_string(0x1F01))
            major, minor = self._parse_version(version)
            if (major, minor) < tuple(minimum):
                raise RuntimeError(
                    f"OpenGL {version} es insuficiente; se requiere {minimum[0]}.{minimum[1]} "
                    "para shaders y texturas aceleradas.")
            self.status = GLStatus(True, f"SDL3 ({library}) · OpenGL {version}",
                                   version, renderer, vendor, major, minor)
            return self.status
        except Exception as exc:
            self.status = GLStatus(False, str(exc))
            self.close()
            return self.status

    @staticmethod
    def _decode(value):
        return value.decode("utf-8", "replace") if value else "desconocido"

    @staticmethod
    def _parse_version(value):
        import re
        match = re.search(r"(\d+)\.(\d+)", value or "")
        return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

    @staticmethod
    def _error(fn):
        value = fn()
        return value.decode("utf-8", "replace") if value else "error SDL sin descripción"

    def close(self):
        if self.sdl is not None:
            try:
                if self.context:
                    fn = self._function("SDL_GL_DestroyContext", None, [ctypes.c_void_p])
                    fn(self.context)
            except Exception:
                pass
            self.context = None
            try:
                if self.window:
                    fn = self._function("SDL_DestroyWindow", None, [ctypes.c_void_p])
                    fn(self.window)
            except Exception:
                pass
            self.window = None
            if self._initialized:
                try:
                    self._function("SDL_QuitSubSystem", None, [ctypes.c_uint32])(self.SDL_INIT_VIDEO)
                except Exception:
                    pass
            self._initialized = False

    def swap(self):
        if self.sdl is not None and self.window and self.context:
            self._function("SDL_GL_SwapWindow", None, [ctypes.c_void_p])(self.window)

    def get_proc_address(self, name):
        if not self.sdl:
            return None
        fn = self._function("SDL_GL_GetProcAddress", ctypes.c_void_p, [ctypes.c_char_p])
        return fn(name.encode("ascii"))

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


# GLSL 330 Core: geometría y UV se procesan en GPU, no por píxel en Python.
VERTEX_SHADER = """#version 330 core
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec2 in_uv;
uniform mat4 u_mvp;
out vec2 uv;
void main() {
    uv = in_uv;
    gl_Position = u_mvp * vec4(in_position, 1.0);
}
"""

FRAGMENT_SHADER = """#version 330 core
in vec2 uv;
uniform sampler2D u_texture;
uniform bool u_use_texture;
uniform float u_alpha_multiplier;
out vec4 out_color;
void main() {
    vec4 texel = u_use_texture ? texture(u_texture, uv) : vec4(0.25, 0.85, 0.48, 1.0);
    texel.a *= u_alpha_multiplier;
    if (texel.a < 0.01) discard;
    out_color = texel;
}
"""


class GLMeshRenderer:
    """Renderizador de triángulos/texturas OpenGL 3.3 Core.

    Requiere un SDL3GLContext ya creado y actual en el hilo llamante.
    Carga una malla indexada una sola vez; la rotación y el dibujo se ejecutan
    en GPU. No depende de PyOpenGL: resuelve las funciones por SDL_GL_GetProcAddress.
    """

    GL_ARRAY_BUFFER = 0x8892
    GL_ELEMENT_ARRAY_BUFFER = 0x8893
    GL_STATIC_DRAW = 0x88E4
    GL_FLOAT = 0x1406
    GL_FALSE = 0
    GL_TRIANGLES = 0x0004
    GL_UNSIGNED_INT = 0x1405
    GL_VERTEX_SHADER = 0x8B31
    GL_FRAGMENT_SHADER = 0x8B30
    GL_COMPILE_STATUS = 0x8B81
    GL_LINK_STATUS = 0x8B82
    GL_INFO_LOG_LENGTH = 0x8B84
    GL_COLOR_BUFFER_BIT = 0x00004000
    GL_DEPTH_BUFFER_BIT = 0x00000100
    GL_DEPTH_TEST = 0x0B71
    GL_TEXTURE_2D = 0x0DE1
    GL_TEXTURE0 = 0x84C0
    GL_TEXTURE_MIN_FILTER = 0x2801
    GL_TEXTURE_MAG_FILTER = 0x2800
    GL_LINEAR = 0x2601
    GL_TEXTURE_WRAP_S = 0x2802
    GL_TEXTURE_WRAP_T = 0x2803
    GL_REPEAT = 0x2901
    GL_RGBA = 0x1908
    GL_UNSIGNED_BYTE = 0x1401
    GL_UNPACK_ALIGNMENT = 0x0CF5
    GL_COLOR_CLEAR_VALUE = 0x0C22

    def __init__(self, context):
        if not context or not context.status.available:
            raise RuntimeError("Se necesita un contexto SDL3/OpenGL válido")
        self.context = context
        self.gl = {}
        self.vao = self.vbo = self.ebo = self.texture = self.program = 0
        self.index_count = 0
        self._load_functions()
        self._create_program()

    def _fn(self, name, restype, args):
        ptr = self.context.get_proc_address(name)
        if not ptr:
            raise RuntimeError("OpenGL no expone " + name)
        fn = ctypes.CFUNCTYPE(restype, *args)(ptr)
        self.gl[name] = fn
        return fn

    def _load_functions(self):
        v = ctypes.c_void_p
        i = ctypes.c_int
        ui = ctypes.c_uint
        sz = ctypes.c_ssize_t
        f = ctypes.c_float
        b = ctypes.c_ubyte
        specs = {
            "glCreateShader": (ui, [ui]), "glShaderSource": (None, [ui, i, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(i)]),
            "glCompileShader": (None, [ui]), "glGetShaderiv": (None, [ui, ui, ctypes.POINTER(i)]),
            "glGetShaderInfoLog": (None, [ui, i, ctypes.POINTER(i), v]), "glCreateProgram": (ui, []),
            "glAttachShader": (None, [ui, ui]), "glLinkProgram": (None, [ui]),
            "glGetProgramiv": (None, [ui, ui, ctypes.POINTER(i)]), "glGetProgramInfoLog": (None, [ui, i, ctypes.POINTER(i), v]),
            "glUseProgram": (None, [ui]), "glGetUniformLocation": (i, [ui, ctypes.c_char_p]),
            "glUniformMatrix4fv": (None, [i, i, b, ctypes.POINTER(f)]), "glUniform1i": (None, [i, i]),
            "glUniform1f": (None, [i, f]), "glGenVertexArrays": (None, [i, ctypes.POINTER(ui)]),
            "glBindVertexArray": (None, [ui]), "glGenBuffers": (None, [i, ctypes.POINTER(ui)]),
            "glBindBuffer": (None, [ui, ui]), "glBufferData": (None, [ui, sz, v, ui]),
            "glEnableVertexAttribArray": (None, [ui]), "glVertexAttribPointer": (None, [ui, i, ui, b, i, v]),
            "glDrawElements": (None, [ui, i, ui, v]), "glEnable": (None, [ui]),
            "glViewport": (None, [i, i, i, i]), "glClearColor": (None, [f, f, f, f]),
            "glClear": (None, [ui]), "glGenTextures": (None, [i, ctypes.POINTER(ui)]),
            "glBindTexture": (None, [ui, ui]), "glTexParameteri": (None, [ui, ui, i]),
            "glPixelStorei": (None, [ui, i]), "glTexImage2D": (None, [ui, i, i, i, i, i, ui, ui, v]),
            "glActiveTexture": (None, [ui]),
        }
        for name, (restype, args) in specs.items():
            self._fn(name, restype, args)

    def _compile(self, kind, source):
        shader = self.gl["glCreateShader"](kind)
        src = ctypes.c_char_p(source.encode("utf-8"))
        self.gl["glShaderSource"](shader, 1, ctypes.byref(src), None)
        self.gl["glCompileShader"](shader)
        ok = ctypes.c_int()
        self.gl["glGetShaderiv"](shader, self.GL_COMPILE_STATUS, ctypes.byref(ok))
        if not ok.value:
            raise RuntimeError("Error compilando shader GLSL")
        return shader

    def _create_program(self):
        vs = self._compile(self.GL_VERTEX_SHADER, VERTEX_SHADER)
        fs = self._compile(self.GL_FRAGMENT_SHADER, FRAGMENT_SHADER)
        self.program = self.gl["glCreateProgram"]()
        self.gl["glAttachShader"](self.program, vs)
        self.gl["glAttachShader"](self.program, fs)
        self.gl["glLinkProgram"](self.program)
        ok = ctypes.c_int()
        self.gl["glGetProgramiv"](self.program, self.GL_LINK_STATUS, ctypes.byref(ok))
        if not ok.value:
            raise RuntimeError("Error enlazando shaders GLSL")
        self.gl["glUseProgram"](self.program)
        self.gl["glUniform1i"](self.gl["glGetUniformLocation"](self.program, b"u_texture"), 0)

    def upload_mesh(self, positions, uvs, triangles):
        """Sube malla (N×3), UV (N×2) y caras (M×3) como buffers estáticos."""
        import numpy as np
        pos = np.ascontiguousarray(positions, dtype=np.float32)
        uv = np.zeros((len(pos), 2), dtype=np.float32) if uvs is None else np.ascontiguousarray(uvs, dtype=np.float32)
        idx = np.ascontiguousarray(triangles, dtype=np.uint32).reshape(-1)
        if len(uv) != len(pos):
            raise ValueError("La cantidad de UV debe coincidir con la de vértices")
        vertices = np.ascontiguousarray(np.column_stack((pos, uv)), dtype=np.float32)
        ui = ctypes.c_uint
        ids = (ui * 1)()
        self.gl["glGenVertexArrays"](1, ids)
        self.vao = ids[0]
        self.gl["glBindVertexArray"](self.vao)
        self.gl["glGenBuffers"](1, ids)
        self.vbo = ids[0]
        self.gl["glBindBuffer"](self.GL_ARRAY_BUFFER, self.vbo)
        self.gl["glBufferData"](self.GL_ARRAY_BUFFER, vertices.nbytes, vertices.ctypes.data_as(ctypes.c_void_p), self.GL_STATIC_DRAW)
        self.gl["glGenBuffers"](1, ids)
        self.ebo = ids[0]
        self.gl["glBindBuffer"](self.GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        self.gl["glBufferData"](self.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx.ctypes.data_as(ctypes.c_void_p), self.GL_STATIC_DRAW)
        stride = 20
        self.gl["glEnableVertexAttribArray"](0)
        self.gl["glVertexAttribPointer"](0, 3, self.GL_FLOAT, self.GL_FALSE, stride, ctypes.c_void_p(0))
        self.gl["glEnableVertexAttribArray"](1)
        self.gl["glVertexAttribPointer"](1, 2, self.GL_FLOAT, self.GL_FALSE, stride, ctypes.c_void_p(12))
        self.index_count = int(idx.size)

    def upload_texture(self, image):
        """Sube una PIL.Image RGBA a la GPU."""
        import numpy as np
        rgba = np.ascontiguousarray(image.convert("RGBA"), dtype=np.uint8)
        ids = (ctypes.c_uint * 1)()
        self.gl["glGenTextures"](1, ids)
        self.texture = ids[0]
        self.gl["glActiveTexture"](self.GL_TEXTURE0)
        self.gl["glBindTexture"](self.GL_TEXTURE_2D, self.texture)
        self.gl["glTexParameteri"](self.GL_TEXTURE_2D, self.GL_TEXTURE_MIN_FILTER, self.GL_LINEAR)
        self.gl["glTexParameteri"](self.GL_TEXTURE_2D, self.GL_TEXTURE_MAG_FILTER, self.GL_LINEAR)
        self.gl["glTexParameteri"](self.GL_TEXTURE_2D, self.GL_TEXTURE_WRAP_S, self.GL_REPEAT)
        self.gl["glTexParameteri"](self.GL_TEXTURE_2D, self.GL_TEXTURE_WRAP_T, self.GL_REPEAT)
        self.gl["glPixelStorei"](self.GL_UNPACK_ALIGNMENT, 1)
        h, w = rgba.shape[:2]
        self.gl["glTexImage2D"](self.GL_TEXTURE_2D, 0, self.GL_RGBA, w, h, 0, self.GL_RGBA, self.GL_UNSIGNED_BYTE, rgba.ctypes.data_as(ctypes.c_void_p))

    def draw(self, width, height, mvp, use_texture=True, alpha_multiplier=1.0):
        """Dibuja con Z-buffer; mvp debe ser una matriz 4×4 en orden column-major."""
        import numpy as np
        mat = np.ascontiguousarray(mvp, dtype=np.float32).T.copy()
        self.gl["glViewport"](0, 0, int(width), int(height))
        self.gl["glEnable"](self.GL_DEPTH_TEST)
        self.gl["glClearColor"](17/255, 17/255, 17/255, 1.0)
        self.gl["glClear"](self.GL_COLOR_BUFFER_BIT | self.GL_DEPTH_BUFFER_BIT)
        self.gl["glUseProgram"](self.program)
        self.gl["glUniformMatrix4fv"](self.gl["glGetUniformLocation"](self.program, b"u_mvp"), 1, self.GL_FALSE, mat.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
        self.gl["glUniform1i"](self.gl["glGetUniformLocation"](self.program, b"u_use_texture"), int(bool(use_texture and self.texture)))
        self.gl["glUniform1f"](self.gl["glGetUniformLocation"](self.program, b"u_alpha_multiplier"), float(alpha_multiplier))
        if self.texture:
            self.gl["glActiveTexture"](self.GL_TEXTURE0)
            self.gl["glBindTexture"](self.GL_TEXTURE_2D, self.texture)
        self.gl["glBindVertexArray"](self.vao)
        self.gl["glDrawElements"](self.GL_TRIANGLES, self.index_count, self.GL_UNSIGNED_INT, None)


    def render_image(self, positions, uvs, triangles, texture, width, height, rot_x=0.5, rot_y=0.6, zoom=1.0):
        """Renderiza una imagen RGB mediante GPU y lee el framebuffer para mostrarlo en Tk."""
        import numpy as np
        from PIL import Image
        pos = np.asarray(positions, dtype=np.float32)
        faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        if len(pos) == 0 or len(faces) == 0:
            return Image.new("RGB", (int(width), int(height)), (17, 17, 17))
        good = np.isfinite(pos).all(axis=1)
        safe = np.where(good[:, None], pos, 0.0)
        center = (safe[good].min(axis=0) + safe[good].max(axis=0)) / 2 if good.any() else np.zeros(3)
        extent = float((safe[good].max(axis=0) - safe[good].min(axis=0)).max()) if good.any() else 1.0
        p = (safe - center) / (extent if extent > 1e-12 else 1.0)
        cy, sy, cx, sx = np.cos(rot_y), np.sin(rot_y), np.cos(rot_x), np.sin(rot_x)
        x1 = p[:, 0] * cy - p[:, 2] * sy
        z1 = p[:, 0] * sy + p[:, 2] * cy
        y2 = p[:, 1] * cx - z1 * sx
        z2 = p[:, 1] * sx + z1 * cx
        scale = 0.85 * min(int(width), int(height)) * float(zoom)
        # NDC keeps the existing Tk viewport dimensions/camera controls.
        transformed = np.column_stack((x1 * scale * 2 / max(1, width),
                                       y2 * scale * 2 / max(1, height),
                                       np.clip(z2, -1.0, 1.0) * 0.8)).astype(np.float32)
        transformed[~good] = 0
        self.upload_mesh(transformed, uvs, faces)
        if texture is not None:
            self.upload_texture(texture)
        else:
            self.texture = 0
        self.draw(width, height, np.eye(4, dtype=np.float32), use_texture=texture is not None)
        read = self._fn("glReadPixels", None, [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                               ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p])
        buf = np.empty((int(height), int(width), 4), dtype=np.uint8)
        read(0, 0, int(width), int(height), self.GL_RGBA, self.GL_UNSIGNED_BYTE, buf.ctypes.data_as(ctypes.c_void_p))
        return Image.fromarray(np.flipud(buf[:, :, :3]).copy(), "RGB")

    def close(self):
        # Los recursos se destruyen al cerrar el contexto; recrear el contexto invalida esta instancia.
        self.vao = self.vbo = self.ebo = self.texture = self.program = 0
        self.index_count = 0
