[![English](https://img.shields.io/badge/Language-English-2ea44f?style=for-the-badge)](README.md) [![Español](https://img.shields.io/badge/Idioma-Espa%C3%B1ol-blue?style=for-the-badge)](README.es.md)

![enter image description here](https://i.ibb.co/XZzXM78Q/Dump-Ana-Logo.png)
# XXAMI DumpAna

**XXAMI DumpAna** is a toolkit for exploring, inspecting and visualizing resources dumped from Android games and applications using **XXAMI (Android Model Importer)** and compatible mods.

The current suite consists of two independent Qt applications:

- **AMI Resource Explorer** — browse resource dumps, inspect files and packages, edit supported text and shader files, and manage resources inside XMOD/MLPK containers.
- **AMI 3D Viewer** — inspect reconstructed geometry and textures from Frame Trace captures and related buffer files, with selectable rendering backends.

The Explorer and Viewer can be launched independently. When both are available, the Explorer can open recognized geometry buffers directly in the Viewer.

## Applications

### AMI Resource Explorer

- Browse directories and ZIP-based **XMOD** and **MLPK** packages.
- Work with tabs, file selection, file properties and context-menu operations.
- Open files with their associated application or configure external tools for different resource categories.
- Edit supported `.txt`, `.ini`, `.json` and `.glsl` files.
- Decode SPIR-V using `spirv-cross.exe` or `spirv-dis.exe`.
- Preview supported textures, including KTX2 resources through the shared decoder.
- Add, replace, rename and remove supported entries in resource packages.

### AMI 3D Viewer

- Load `frame_trace.json` captures and related vertex/index buffer resources.
- Reconstruct and inspect model geometry and textures.
- Navigate the model with mouse and keyboard camera controls, axis gizmo and reference grid.
- Assign texture maps to material roles and inspect an approximate material preview.
- Export selected geometry to OBJ.
- Select an available rendering backend, including OpenGL and, where supported by the system, Direct3D and wgpu-based Vulkan, Direct3D 12 or OpenGL paths. Available options depend on the operating system, GPU, drivers and successful device initialization; software rendering is available as a fallback.

## Requirements

- Windows is required for the Direct3D backends and the supplied PyInstaller build commands.
- Python and the dependencies listed in the application-specific requirements files:
  - Explorer: `requirements-explorer.txt`
  - Viewer: `requirements-model-viewer.txt`
- Some workflows use external command-line tools. For example, SPIR-V conversion requires `spirv-cross.exe` and/or `spirv-dis.exe`; KTX2 editing workflows may require `ktx.exe`.

Install dependencies from the repository directory:

```bash
python -m pip install -r requirements-explorer.txt
python -m pip install -r requirements-model-viewer.txt
```

## Run from source

Start the Explorer:

```bash
python file_explorer_qt.py
```

Optionally pass a directory to open:

```bash
python file_explorer_qt.py "D:\\path\\to\\XXAMI"
```

Start the Viewer:

```bash
python model_viewer_qt.py
```

Open a Frame Trace capture or a related buffer:

```bash
python model_viewer_qt.py "D:\\path\\Frame_Trace_001\\frame_trace.json"
python model_viewer_qt.py --root "D:\\path\\to\\dump" "D:\\path\\to\\dump\\vb_example.buf"
```

## Building standalone Windows executables

The Explorer and Viewer can be packaged separately with PyInstaller. The complete commands, hidden imports, resource handling and distribution notes are maintained in **[EXPLORER_BUILD.md](EXPLORER_BUILD.md)**.

For packaged builds, keep the appropriate `lang/` directory alongside the executable so language catalogs remain external and independently updateable. Keep the required `res/` resources available as described in the build guide.

## Repository structure

- `file_explorer_qt.py` — AMI Resource Explorer.
- `model_viewer_qt.py` — AMI 3D Viewer.
- `xxami_trace.py` — shared Frame Trace and geometry reconstruction core.
- `texture_decoder.py`, `ktx2_util.py` — shared texture and KTX2 utilities.
- `xxami_render_backend.py` and the backend modules — rendering backend selection and implementations.
- `lang/explorer_lang/` and `lang/viewer_lang/` — independent language catalogs for each application.
- `EXPLORER_BUILD.md` — detailed execution, packaging and resource-distribution guide.

## Notes

This repository is focused on resource inspection and visualization. Rendering features and API availability vary by backend and hardware; the material preview is approximate and is not a full physically based renderer. Consult the build guide for current implementation details and known limitations.

---
