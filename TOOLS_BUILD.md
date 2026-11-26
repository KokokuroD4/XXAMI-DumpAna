# XXAMI Tools — Build and usage guide

This guide covers the two independent Qt applications in XXAMI DumpAna: **AMI Resource Explorer** and **AMI 3D Viewer**. It also documents their shared modules, runtime resources and standalone Windows packaging.

## AMI Resource Explorer

The Qt Explorer is implemented in `file_explorer_qt.py`. Its shared texture decoder is in `texture_decoder.py`.

### Dependencies

```bash
python -m pip install -r requirements-explorer.txt
```

### Run from source

```bash
python file_explorer_qt.py
python file_explorer_qt.py "D:\\path\\to\\XXAMI"
python file_explorer_qt.py --log-path "D:\\path\\xxami_crash_log.txt" "D:\\path\\to\\XXAMI"
```

### Build a standalone Windows executable

Run from a Windows environment with the application dependencies installed:

```bash
python -m pip install pyinstaller
pyinstaller --icon=explorer_icon.ico --version-file=explorer_file_version_info.txt --noconfirm --clean --windowed --name "AMI Explorer" --add-data "res;res" --add-data "notload.png;." --add-binary "spirv-cross.exe;." --hidden-import texture_decoder --hidden-import ktx2_util --hidden-import xxami_logging --collect-all texture2ddecoder --onefile file_explorer_qt.py
```

When distributing the executable, keep the `res` folder next to it (or adjust packaging to include it). For SPIR-V-to-GLSL conversion, `spirv-cross.exe` must be available next to the application or on PATH.

### Explorer features and resources

The Explorer and Viewer are independent applications. The legacy `gui.py`, DumpAna Tk interface and its old `trace_tab.py` tab are no longer required.

The Explorer supports directory and ZIP-based XMOD/MLPK navigation, tabs, multi-selection, file properties, context-menu operations, external tools by resource category, and editing of supported `.txt`, `.ini`, `.json` and `.glsl` files. Files can be opened with their associated application or a configured external tool.

For external editing of files inside XMOD/MLPK packages, the Explorer uses a temporary copy and rewrites the container only after the edit completes successfully. Package entries and folders can also be renamed or removed. Clipboard operations support filesystem directories and XMOD/MLPK contents, including moves from packages. MLPK creation menus offer only XMOD files; XMOD containers retain the usual creation options. KTX2 textures are decoded to PNG for external editing and are replaced only after a compatible conversion and validation. `ktx.exe` is required for the applicable conversion workflow; the original is preserved if editing or conversion fails.

For SPIR-V files, the decode action can extract GLSL with `spirv-cross.exe` or disassemble to SPIR-V Assembly with `spirv-dis.exe`. Assembly files use the `.s` extension and can be opened in the text/code editor. The original SPIR-V binary is not overwritten or automatically recompiled. Both tools must be beside the Explorer or available on PATH.

KTX2 decoding uses `texture_decoder.py`, `ktx2_util.py`, `texture2ddecoder` and NumPy. Thumbnails are generated in the background; the right panel displays the decoded texture and double-click opens the independent image viewer. BasisLZ is not supported by the current decoder.

The editor supports opening, editing and saving `.txt`, `.ini`, `.json` and `.glsl` files, with line numbers and syntax highlighting for INI, JSON and GLSL.

### Shared modules to keep

- `xxami_trace.py`: Frame Trace reading and geometry reconstruction core, used directly by the Viewer.
- `texture_decoder.py` and `ktx2_util.py`: texture and KTX2 decoding.
- `xxami_logging.py`: exception and error logging.
- `xxami_render_backend.py`, `xxami_gl.py`, `xxami_wgpu_backend.py`, `xxami_d3d9_backend.py` and `xxami_d3d11_backend.py`: Viewer graphics backends.
- `lang/explorer_lang/` and `lang/viewer_lang/`: separate language catalogs for each application.

Direct3D 9, Direct3D 11 and GPU diagnostic/test scripts are retained in the repository. They are not mandatory runtime dependencies of the Explorer.

### Explorer images and icons

Window icons are loaded from `res/` (transparent 256 × 256 RGBA PNG files):

- `explorer_icon.png` — AMI Resource Explorer main window.
- `viewer_icon.png` — AMI 3D Viewer main window.
- `image_viewer_icon.png` — image and texture viewer.
- `code_editor_icon.png` — text and code editor.

If an image is missing, the application uses its built-in fallback icon. PyInstaller builds can keep `res/` beside the executable or include it in the bundle; the resource loader checks both locations.

Optional file-type icons are also searched for in `res/`: `folder.png`, `spv.png`, `txt.png`, `buf.png`, `xmod.png`, `mlpk.png`, `generic.png`, `ini.png`, `json.png`, `glsl.png` and `asm_s.png` (SPIR-V Assembly, `.s`). Each PNG should be 256 × 256 RGBA. Missing icons are replaced with vector fallback artwork.

The navigation and search controls load `back.png`, `forward.png`, `up.png`, `refresh.png` and `search.png` from `res/`; vector fallbacks are drawn if any are missing. The `+` button beside the tabs opens another folder in a new tab.

Right-clicking empty space in the file area opens a context menu with **New** and **Properties**. **New** creates `.ini`, `.s` and `.glsl` files, or initializes `.xmod` and `.mlpk` containers as uncompressed ZIP files. **Properties** shows recursive file/folder counts and groups shaders and textures by extension, buffers (`.buf`), `frame_trace.json`, `Model_N` model folders and `.xmod`/`.mlpk` packages. Directory symlinks are not traversed, preventing cycles.

Directory changes and refreshes use a background worker. While data is being collected, the UI displays `res/loading.gif`, a loading message and a progress bar; entries are inserted in batches to keep the interface responsive. The Explorer saves open folders/packages, the active tab and window size/state on exit, and restores the session when paths still exist.

The **Settings** button opens **General** and **About**. General selects the language from JSON catalogs in `lang/explorer_lang/` and assigns external tools by resource category (text, shaders, models/buffers, textures, packages and other files), independently for **Management** and **Editing**. Settings are stored in `explorer.ini` beside the Explorer executable, or beside `file_explorer_qt.py` when run from source. The file is created at startup.

Language catalogs are discovered dynamically from all `lang/explorer_lang/*.json` files (the filename is the language identifier). Each catalog must be a JSON object with a non-empty `name` and a `strings` object whose keys and values are strings. Invalid JSON or malformed catalogs are skipped; there is no fixed language limit. In PyInstaller builds, the application first checks beside the executable and falls back to bundled `lang/explorer_lang` resources if the external folder is absent.

## AMI 3D Viewer

The Viewer is implemented in `model_viewer_qt.py` and uses `xxami_trace.py` for Frame Trace reconstruction.

### Dependencies and launch

```bash
python -m pip install -r requirements-model-viewer.txt
python model_viewer_qt.py
python model_viewer_qt.py "D:\\path\\Frame_Trace_001\\frame_trace.json"
python model_viewer_qt.py --root "D:\\path\\to\\dump" "D:\\path\\to\\dump\\vb_abc123_4096.buf"
```

The **File** menu opens a file or dump folder, refreshes the index, exports selected geometry to OBJ and exits. The **Diagnostics** menu opens or exports `xxami_crash_log.txt`. When launched from the Explorer, the Viewer can receive the same log path to share diagnostics for that session.

The Viewer recognizes `frame_trace.json` captures, geometry buffers named `vb_`, `ib_`, `vbib_` and parts named `PartNN-vb0=<hash>.buf`. When a `.buf` is opened from the Explorer, its containing directory is used as the resource root so related captures and buffers can be found. The index also recognizes `Models/Model_NN` and `Models/` folders that contain parts directly.

### Graphics settings and rendering APIs

The **Settings** menu, beside File and Diagnostics, opens **General** and **About**. General allows the user to select the language, detected graphics adapter and rendering API.

The Viewer supports SDL3/OpenGL 3.3 Core and may offer Direct3D 9, Direct3D 11 and wgpu-py offscreen backends: Vulkan, Direct3D 12 and OpenGL. Direct3D APIs are listed only on Windows and only when the probe can create a device on the selected adapter. Validation to date confirms Direct3D 9 on Intel HD Graphics 4600 and Direct3D 11 on Intel HD Graphics 4600 and NVIDIA GTX 1650; this does not imply universal compatibility with other adapters.

wgpu prefers a high-performance adapter; manual selection is matched by name where possible. Settings are stored in `viewer.ini` beside the executable or source script. Viewer language catalogs are in `lang/viewer_lang/` (`es.json` and `en.json`). The selected language is saved in `viewer.ini`, independently of Explorer settings.

The API list is filtered according to the adapter selected in the GPU selector. An API that is compatible with the GTX 1650 may not appear when Intel HD Graphics 4600 is selected, and vice versa. The high-performance preference button asks Windows to prioritize a GPU for the executable; it does not replace adapter selection inside the Viewer. Actual GPU selection depends on the operating system and driver. On Windows, it may be necessary to assign the high-performance GPU in Windows Graphics settings.

The Settings dialog appears before GPU queries begin. Adapter enumeration and API checks run in a background worker; while they are running, the UI shows `res/loading.gif`, a loading message and a progress bar. The GIF is included through `--add-data "res;res"`. PowerShell and WGPU probe subprocesses do not show auxiliary console windows on Windows.

### Viewer layout, camera and materials

The workspace keeps the capture/resource tree on the left, a vertical texture panel beside the viewport and an expandable 3D viewport in the center. Model information appears in a collapsible semi-transparent overlay anchored independently to the lower-right corner, below the gizmo; it does not occupy a side column or attach to the gizmo.

Position, UV and camera controls are in a compact strip below the viewport to preserve viewing space. The central panel and viewport expand to use the remaining window area.

The **Grid floor** checkbox shows or hides a perspective reference grid behind the geometry. It is a viewport guide and does not modify the mesh or files.

Mouse controls: left-drag orbits/rotates the model; right- or middle-drag pans the model in the viewport; the wheel zooms. Panning changes the camera/projection transform in both renderers (OpenGL and software), never the final bitmap, so the background and viewport bounds remain fixed.

Keyboard controls when the viewport has focus: **W/A/S/D** or arrow keys to orbit, **Q/E** for horizontal rotation, **Shift + arrows** to pan, **+/-** to zoom and **0** to reset.

The upper-right gizmo displays **X/Y/Z** axes according to the current orientation. Clicking a positive or negative axis endpoint switches to the corresponding view. The **Model Information** floating panel is in the lower-right corner, with a semi-transparent background and collapse/expand control, separate from the gizmo.

The texture list keeps resources found for the draw. Each row has a role selector (**Ignore**, **Albedo**, **Lightmap**, **Normal**, **Metallic**, **Roughness**, **Emission**, **AO** or **Opacity**) and an **Invert** checkbox for that texture's alpha. **Add texture…** adds other resources. Textures are not silently reassigned based on filename matches: the first is initially suggested as Albedo and the rest are set to Ignore, so the user can choose their roles.

The Material view combines selected maps into an approximate preview: lightmap and AO modulate albedo, normal maps provide approximate tangent-space lighting, metallic/roughness change the appearance, emission adds color and opacity supplies alpha. This is not a full PBR renderer: normal mapping requires correct tangents and TBN matrix, while metallic/roughness do not calculate physically based reflections. Results depend on the assigned files belonging to the model and sharing compatible UV coordinates.

### Build a standalone Viewer executable (Windows)

```bash
python -m pip install pyinstaller
pyinstaller --icon=viewer_icon.ico --version-file=viewer_file_version_info.txt --noconfirm --clean --onefile --windowed --name "AMI 3D Viewer" --add-data "res;res" --hidden-import xxami_trace --hidden-import xxami_gl --hidden-import xxami_render_backend --hidden-import xxami_wgpu_backend --hidden-import xxami_d3d9_backend --hidden-import xxami_d3d9_probe --hidden-import xxami_d3d11_backend --hidden-import xxami_d3d11_probe --hidden-import texture_decoder --hidden-import ktx2_util --hidden-import xxami_logging --collect-all texture2ddecoder --collect-all wgpu model_viewer_qt.py
```

**Important:** after updating `xxami_trace.py` or `xxami_gl.py`, rebuild the executable. An existing EXE contains the versions of those modules that were packaged at build time. The Viewer prioritizes modules included alongside it and displays the `xxami_trace.py` path if it detects an old copy without pan support.

The resulting executable is independent of DumpAna. For Material mode to decode KTX2, also distribute `texture_decoder.py` and `ktx2_util.py` beside the Viewer or package them into the executable.

SDL3/OpenGL acceleration remains available. wgpu-py adds offscreen Vulkan, Direct3D 12 and OpenGL backends; its library and native binaries must be included when building (hence `--collect-all wgpu`). If an API or adapter is unavailable, the Viewer falls back to software rendering. The accelerated renderer keeps geometry buffers and textures on the GPU between redraws and applies the camera through the MVP matrix. Framebuffer readback and transfer to the UI still have a cost, and performance depends on the GPU and driver.

### Integration with the Explorer

Double-clicking a recognized `.buf` launches `model_viewer_qt.py` with `--root` set to the buffer's containing folder. If `XXAMI Model Viewer.exe` or `model_viewer_qt.exe` is beside the Explorer, that executable is used; otherwise, the script is launched with the current Python interpreter. Other `.buf` files keep their generic icon.

The texture panel lets the user select a texture by clicking its name; the selected row is highlighted in turquoise green and its preview appears below the list. Right-clicking the preview opens a context menu to invert or restore the selected texture's alpha.

## Distribution notes

- Keep each application's language catalogs in the external `lang/` directory beside the executable: `lang/explorer_lang/` for the Explorer and `lang/viewer_lang/` for the Viewer. The language folders are independent and should not be merged.
- Keep the required `res/` resources available beside the executable or bundle them with `--add-data "res;res"`. The commands above include this resource directory.
- The Explorer build command also includes `notload.png` and `spirv-cross.exe`; make sure those files exist at the specified source paths when building.
- The Viewer build collects `texture2ddecoder` and `wgpu`, and declares the graphics/backend modules as hidden imports.
- The Explorer and Viewer use separate configuration files: `explorer.ini` and `viewer.ini`. Their language selections and settings are independent.
- The build commands target Windows. Direct3D backends are Windows-only; available rendering APIs depend on successful device initialization, adapter and driver support.
- If a graphics API cannot be initialized, the Viewer can use its software renderer. Do not assume that every API is available on every GPU.

