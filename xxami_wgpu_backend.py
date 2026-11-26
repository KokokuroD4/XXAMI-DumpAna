# -*- coding: utf-8 -*-
"""Renderizador offscreen basado en wgpu-py (Vulkan, DX12 y OpenGL).

La API se fija antes de importar wgpu: wgpu-native crea una instancia global y
no permite cambiar de backend HAL después de enumerar adaptadores.
"""
from __future__ import annotations

import os


class WgpuBackend:
    LABELS = {
        "vulkan": ("Vulkan (wgpu)", "Vulkan", "Vulkan"),
        "dx12": ("Direct3D 12 (wgpu)", "D3D12", "DX12"),
        "wgpu-opengl": ("OpenGL (wgpu)", "OpenGL", "GL"),
    }

    def __init__(self, backend_id):
        if backend_id not in self.LABELS:
            raise ValueError(f"API wgpu no reconocida: {backend_id}")
        self.backend_id = backend_id
        self.label, self.env_backend, self.hal_name = self.LABELS[backend_id]
        self.gpu_preference = "default"
        self.info = {"id": backend_id, "label": self.label}
        self.wgpu = self.adapter = self.device = None
        self.pipeline = self.uniform_buffer = None
        self.vertex_buffer = self.index_buffer = None
        self.color_texture = self.depth_texture = None
        self.bind_group = None
        self.mesh_key = None
        self.texture_key = None
        self.texture = self.sampler = None
        self.size = None
        self.index_count = 0

    def initialize(self):
        # Debe establecerse antes de importar wgpu y de crear su instancia.
        os.environ["WGPU_BACKEND_TYPE"] = self.env_backend
        try:
            import wgpu
            from wgpu.backends.wgpu_native.extras import set_instance_extras
            set_instance_extras(backends=[self.hal_name])
            adapters = wgpu.gpu.enumerate_adapters_sync()
            expected_types = {
                "Vulkan": {"vulkan"},
                "DX12": {"dx12", "d3d12"},
                "GL": {"gl", "opengl"},
            }[self.hal_name]
            candidates = []
            for adapter in adapters:
                reported = str(adapter.info.get("backend_type", "")).casefold()
                # La instancia ya está limitada al HAL. Si el driver informa el
                # backend, se valida; si no lo informa, se confía en esa restricción.
                if not reported or reported in expected_types:
                    candidates.append(adapter)
            if not candidates:
                raise RuntimeError(f"wgpu no encontró adaptadores para {self.hal_name}")
            preferred = self.gpu_preference.casefold()
            if preferred not in ("", "default") and not preferred.startswith("pci-"):
                match = next((a for a in candidates
                              if preferred in str(a.info.get("device", "")).casefold()
                              or preferred in str(a.info.get("description", "")).casefold()
                              or preferred in str(a.summary).casefold()), None)
                if match is None:
                    raise RuntimeError(f"No se encontró el adaptador solicitado: {self.gpu_preference}")
                self.adapter = match
            else:
                self.adapter = next((a for a in candidates
                                     if not a.info.get("is_fallback_adapter", False)), candidates[0])
            self.device = self.adapter.request_device_sync()
            self.wgpu = wgpu
            self._create_pipeline()
            adapter_info = dict(self.adapter.info)
            self.info.update(
                vendor=str(adapter_info.get("vendor", "")),
                renderer=str(adapter_info.get("description", "") or adapter_info.get("device", "")),
                adapter=str(self.adapter.summary),
                backend=self.hal_name,
            )
            return self.info
        except Exception as exc:
            self.close()
            raise RuntimeError(f"No se pudo inicializar {self.label}: {exc}") from exc

    def _create_pipeline(self):
        wgpu = self.wgpu
        device = self.device
        shader = device.create_shader_module(code=r"""
struct Camera {
    mvp: mat4x4<f32>,
    use_texture: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
};
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var color_tex: texture_2d<f32>;
@group(0) @binding(2) var color_sampler: sampler;

struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};
@vertex
fn vs_main(@location(0) position: vec3<f32>, @location(1) uv: vec2<f32>) -> VertexOut {
    var out: VertexOut;
    out.position = camera.mvp * vec4<f32>(position, 1.0);
    out.uv = uv;
    return out;
}
@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    if (camera.use_texture != 0u) {
        return textureSample(color_tex, color_sampler, in.uv);
    }
    return vec4<f32>(0.78, 0.80, 0.83, 1.0);
}
""")
        self.uniform_buffer = device.create_buffer(
            size=80, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.texture = device.create_texture(
            size=(1, 1, 1), mip_level_count=1, sample_count=1,
            dimension="2d", format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.sampler = device.create_sampler(
            mag_filter="linear", min_filter="linear", address_mode_u="repeat",
            address_mode_v="repeat")
        self.pipeline = device.create_render_pipeline(
            layout="auto",
            vertex={
                "module": shader, "entry_point": "vs_main",
                "buffers": [{
                    "array_stride": 20, "step_mode": "vertex",
                    "attributes": [
                        {"format": "float32x3", "offset": 0, "shader_location": 0},
                        {"format": "float32x2", "offset": 12, "shader_location": 1},
                    ],
                }],
            },
            primitive={"topology": "triangle-list", "front_face": "ccw", "cull_mode": "none"},
            depth_stencil={"format": "depth24plus", "depth_write_enabled": True,
                           "depth_compare": "less"},
            fragment={"module": shader, "entry_point": "fs_main",
                      "targets": [{"format": "rgba8unorm"}]},
        )
        self.bind_group_layout = self.pipeline.get_bind_group_layout(0)
        self._update_bind_group()

    def _update_bind_group(self):
        self.bind_group = self.device.create_bind_group(
            layout=self.bind_group_layout,
            entries=[
                {"binding": 0, "resource": {"buffer": self.uniform_buffer, "offset": 0, "size": 80}},
                {"binding": 1, "resource": self.texture.create_view()},
                {"binding": 2, "resource": self.sampler},
            ])

    def _upload_mesh(self, positions, uvs, triangles):
        import numpy as np
        pos = np.asarray(positions, dtype=np.float32)
        faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        if len(pos) == 0 or len(faces) == 0:
            raise ValueError("La malla no contiene triángulos")
        valid = np.isfinite(pos).all(axis=1)
        safe = np.where(valid[:, None], pos, 0.0)
        if valid.any():
            low, high = safe[valid].min(axis=0), safe[valid].max(axis=0)
            center = (low + high) * 0.5
            extent = float((high - low).max())
        else:
            center, extent = np.zeros(3, dtype=np.float32), 1.0
        normalized = (safe - center) / (extent if extent > 1e-12 else 1.0)
        normalized[~valid] = 0
        uv = np.zeros((len(pos), 2), dtype=np.float32) if uvs is None else np.asarray(uvs, dtype=np.float32)
        if len(uv) != len(pos):
            raise ValueError("La cantidad de UV debe coincidir con la de vértices")
        if faces.min() < 0 or faces.max() >= len(pos):
            raise ValueError("La malla contiene índices de triángulos fuera de rango")
        vertices = np.ascontiguousarray(np.column_stack((normalized, uv)), dtype=np.float32)
        indices = np.ascontiguousarray(faces, dtype=np.uint32).reshape(-1)
        wgpu = self.wgpu
        if self.vertex_buffer is not None:
            self.vertex_buffer.destroy()
        if self.index_buffer is not None:
            self.index_buffer.destroy()
        self.vertex_buffer = self.device.create_buffer_with_data(
            data=vertices, usage=wgpu.BufferUsage.VERTEX)
        self.index_buffer = self.device.create_buffer_with_data(
            data=indices, usage=wgpu.BufferUsage.INDEX)
        self.index_count = int(indices.size)
        self.mesh_key = (id(positions), id(uvs), id(triangles), pos.shape, faces.shape)

    def _upload_texture(self, image):
        import hashlib
        import numpy as np
        rgba = np.ascontiguousarray(image.convert("RGBA"), dtype=np.uint8)
        key = (rgba.shape, hashlib.sha1(rgba).digest())
        if key == self.texture_key:
            return
        height, width = rgba.shape[:2]
        if self.texture is not None:
            self.texture.destroy()
        self.texture = self.device.create_texture(
            size=(width, height, 1), mip_level_count=1, sample_count=1,
            dimension="2d", format="rgba8unorm",
            usage=self.wgpu.TextureUsage.TEXTURE_BINDING | self.wgpu.TextureUsage.COPY_DST)
        self.device.queue.write_texture(
            {"texture": self.texture, "mip_level": 0, "origin": (0, 0, 0)},
            rgba, {"offset": 0, "bytes_per_row": width * 4, "rows_per_image": height},
            (width, height, 1))
        self.texture_key = key
        self._update_bind_group()

    def _ensure_targets(self, width, height):
        if self.size == (width, height):
            return
        if self.color_texture is not None:
            self.color_texture.destroy()
            self.depth_texture.destroy()
        self.color_texture = self.device.create_texture(
            size=(width, height, 1), mip_level_count=1, sample_count=1,
            dimension="2d", format="rgba8unorm",
            usage=self.wgpu.TextureUsage.RENDER_ATTACHMENT | self.wgpu.TextureUsage.COPY_SRC)
        self.depth_texture = self.device.create_texture(
            size=(width, height, 1), mip_level_count=1, sample_count=1,
            dimension="2d", format="depth24plus",
            usage=self.wgpu.TextureUsage.RENDER_ATTACHMENT)
        self.size = (width, height)

    def render_image(self, positions, uvs, triangles, texture, width, height,
                     rot_x=0.5, rot_y=0.6, zoom=1.0, pan_x=0.0, pan_y=0.0):
        import numpy as np
        from PIL import Image
        if self.device is None:
            raise RuntimeError("Backend wgpu no inicializado")
        width, height = max(1, int(width)), max(1, int(height))
        pos = np.asarray(positions)
        faces = np.asarray(triangles)
        if not len(pos) or not len(faces):
            return Image.new("RGB", (width, height), (17, 17, 17))
        key = (id(positions), id(uvs), id(triangles), pos.shape, faces.shape)
        if key != self.mesh_key:
            self._upload_mesh(positions, uvs, triangles)
        if texture is not None:
            self._upload_texture(texture)
        elif self.texture_key is not None:
            from PIL import Image as PILImage
            self._upload_texture(PILImage.new("RGBA", (1, 1), (255, 255, 255, 255)))

        cy, sy = np.cos(rot_y), np.sin(rot_y)
        cx, sx = np.cos(rot_x), np.sin(rot_x)
        rotate_y = np.array([[cy, 0, -sy, 0], [0, 1, 0, 0],
                             [sy, 0, cy, 0], [0, 0, 0, 1]], dtype=np.float32)
        rotate_x = np.array([[1, 0, 0, 0], [0, cx, -sx, 0],
                             [0, sx, cx, 0], [0, 0, 0, 1]], dtype=np.float32)
        scale = 0.85 * min(width, height) * float(zoom)
        projection = np.diag([2 * scale / width, 2 * scale / height, 0.4, 1.0]).astype(np.float32)
        projection[2, 3] = 0.5  # WebGPU usa profundidad NDC [0, 1].
        translate = np.eye(4, dtype=np.float32)
        translate[0, 3] = 2.0 * float(pan_x) / width
        translate[1, 3] = -2.0 * float(pan_y) / height
        mvp = translate @ projection @ rotate_x @ rotate_y
        uniform = np.zeros(20, dtype=np.float32)
        uniform[:16] = mvp.T.reshape(-1)
        uniform[16] = 1.0 if texture is not None else 0.0
        self.device.queue.write_buffer(self.uniform_buffer, 0, uniform)
        self._ensure_targets(width, height)

        encoder = self.device.create_command_encoder()
        render_pass = encoder.begin_render_pass(
            color_attachments=[{
                "view": self.color_texture.create_view(), "resolve_target": None,
                "clear_value": (17 / 255, 17 / 255, 17 / 255, 1.0), "load_op": "clear",
                "store_op": "store",
            }],
            depth_stencil_attachment={
                "view": self.depth_texture.create_view(), "depth_clear_value": 1.0,
                "depth_load_op": "clear", "depth_store_op": "store",
            })
        render_pass.set_pipeline(self.pipeline)
        render_pass.set_bind_group(0, self.bind_group)
        render_pass.set_vertex_buffer(0, self.vertex_buffer)
        render_pass.set_index_buffer(self.index_buffer, "uint32")
        render_pass.draw_indexed(self.index_count)
        render_pass.end()
        padded_bytes_per_row = ((width * 4 + 255) // 256) * 256
        readback = self.device.create_buffer(
            size=padded_bytes_per_row * height,
            usage=self.wgpu.BufferUsage.COPY_DST | self.wgpu.BufferUsage.MAP_READ)
        encoder.copy_texture_to_buffer(
            {"texture": self.color_texture, "mip_level": 0, "origin": (0, 0, 0)},
            {"buffer": readback, "offset": 0, "bytes_per_row": padded_bytes_per_row,
             "rows_per_image": height},
            (width, height, 1))
        self.device.queue.submit([encoder.finish()])
        readback.map_sync(self.wgpu.MapMode.READ)
        raw = readback.read_mapped()
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, padded_bytes_per_row)
        rgba = pixels[:, :width * 4].reshape(height, width, 4).copy()
        readback.unmap()
        readback.destroy()
        return Image.fromarray(rgba, "RGBA").convert("RGB")

    def close(self):
        for name in ("vertex_buffer", "index_buffer", "uniform_buffer",
                     "color_texture", "depth_texture", "texture"):
            obj = getattr(self, name, None)
            if obj is not None:
                try:
                    obj.destroy()
                except Exception:
                    pass
                setattr(self, name, None)
        self.device = self.adapter = self.wgpu = None
        self.pipeline = self.bind_group = self.sampler = None
        self.mesh_key = self.texture_key = self.size = None
        self.index_count = 0
