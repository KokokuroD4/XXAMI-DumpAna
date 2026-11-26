[![English](https://img.shields.io/badge/Language-English-blue?style=for-the-badge)](README.md) [![Español](https://img.shields.io/badge/Idioma-Espa%C3%B1ol-2ea44f?style=for-the-badge)](README.es.md)

![enter image description here](https://i.ibb.co/XZzXM78Q/Dump-Ana-Logo.png)
# XXAMI DumpAna

**XXAMI DumpAna** es una suite de herramientas para explorar, inspeccionar y visualizar recursos volcados de juegos y aplicaciones Android mediante **XXAMI (Android Model Importer)** y sus mods compatibles.

La suite actual está formada por dos aplicaciones Qt independientes:

- **AMI Resource Explorer** — permite navegar por volcados de recursos, inspeccionar archivos y paquetes, editar archivos de texto y shaders compatibles y gestionar recursos dentro de contenedores XMOD/MLPK.
- **AMI 3D Viewer** — permite inspeccionar geometría reconstruida y texturas a partir de capturas Frame Trace y archivos de buffers relacionados, con distintos backends de renderizado.

El Explorador y el Visor pueden ejecutarse por separado. Cuando ambos están disponibles, el Explorador puede abrir directamente en el Visor los buffers de geometría que reconoce.

## Aplicaciones

### AMI Resource Explorer

- Navegación por directorios y paquetes XMOD/MLPK basados en ZIP.
- Pestañas, selección de archivos, propiedades y operaciones mediante menús contextuales.
- Apertura de archivos con su aplicación asociada o configuración de herramientas externas por categoría de recurso.
- Edición de archivos compatibles `.txt`, `.ini`, `.json` y `.glsl`.
- Decodificación de SPIR-V mediante `spirv-cross.exe` o `spirv-dis.exe`.
- Vista previa de texturas compatibles, incluidos recursos KTX2 mediante el decodificador compartido.
- Añadir, reemplazar, renombrar y eliminar entradas compatibles dentro de paquetes.

### AMI 3D Viewer

- Carga de capturas `frame_trace.json` y sus recursos de buffers de vértices e índices.
- Reconstrucción e inspección de geometría y texturas de modelos.
- Navegación mediante controles de cámara con ratón y teclado, gizmo de ejes y cuadrícula de referencia.
- Asignación de mapas de textura a funciones de material y vista previa aproximada del material.
- Exportación de la geometría seleccionada a OBJ.
- Selección de un backend de renderizado disponible: OpenGL y, cuando el sistema lo permite, rutas basadas en Direct3D y wgpu para Vulkan, Direct3D 12 u OpenGL. Las opciones dependen del sistema operativo, la GPU, los controladores y la inicialización correcta del dispositivo; existe un renderizador por software como alternativa.

## Requisitos

- Windows es necesario para los backends Direct3D y los comandos de compilación PyInstaller incluidos.
- Python y las dependencias indicadas en los archivos específicos de cada aplicación:
  - Explorador: `requirements-explorer.txt`
  - Visor: `requirements-model-viewer.txt`
- Algunos flujos de trabajo requieren herramientas externas. Por ejemplo, la conversión SPIR-V necesita `spirv-cross.exe` y/o `spirv-dis.exe`; los flujos de edición KTX2 pueden requerir `ktx.exe`.

Instala las dependencias desde el directorio del repositorio:

```bash
python -m pip install -r requirements-explorer.txt
python -m pip install -r requirements-model-viewer.txt
```

## Ejecutar desde el código fuente

Iniciar el Explorador:

```bash
python file_explorer_qt.py
```

También se puede indicar un directorio para abrirlo directamente:

```bash
python file_explorer_qt.py "D:\\ruta\\a\\XXAMI"
```

Iniciar el Visor:

```bash
python model_viewer_qt.py
```

Abrir una captura Frame Trace o un buffer relacionado:

```bash
python model_viewer_qt.py "D:\\ruta\\Frame_Trace_001\\frame_trace.json"
python model_viewer_qt.py --root "D:\\ruta\\al\\volcado" "D:\\ruta\\al\\volcado\\vb_example.buf"
```

## Compilar ejecutables independientes para Windows

El Explorador y el Visor pueden empaquetarse por separado con PyInstaller. Los comandos completos, las importaciones ocultas, la gestión de recursos y las notas de distribución se mantienen en **[TOOLS_BUILD.es.md](TOOLS_BUILD.es.md)** (Español) · **[TOOLS_BUILD.md](TOOLS_BUILD.md)** (English).

En las versiones empaquetadas, conserva junto al ejecutable el directorio `lang/` correspondiente para que los catálogos de idioma sigan siendo externos y puedan actualizarse de forma independiente. Mantén también disponibles los recursos necesarios de `res/`, tal como se describe en la guía de compilación.

## Estructura del repositorio

- `file_explorer_qt.py` — AMI Resource Explorer.
- `model_viewer_qt.py` — AMI 3D Viewer.
- `xxami_trace.py` — núcleo compartido de lectura Frame Trace y reconstrucción de geometría.
- `texture_decoder.py`, `ktx2_util.py` — utilidades compartidas para texturas y KTX2.
- `xxami_render_backend.py` y los módulos de backend — selección e implementaciones de renderizado.
- `lang/explorer_lang/` y `lang/viewer_lang/` — catálogos de idioma independientes para cada aplicación.
- `TOOLS_BUILD.es.md` — guía detallada de ejecución y compilación (español).
- `TOOLS_BUILD.md` — detailed build and usage guide (English).

## Aviso de uso de IA

Se han utilizado herramientas de inteligencia artificial como apoyo durante el desarrollo de algunas partes del código fuente. Su uso se limitó a asistir en determinadas tareas de programación y desarrollo; esto no significa que el proyecto haya sido generado íntegramente por IA.

**Todos los aspectos visuales y de diseño del proyecto han sido realizados íntegramente por personas.** Esto incluye la identidad visual, los gráficos, el diseño de las interfaces y los demás elementos visuales, que no han sido generados mediante IA.

## Notas

Este repositorio está orientado a la inspección y visualización de recursos. Las funciones de renderizado y la disponibilidad de cada API varían según el backend y el hardware; la vista previa de materiales es aproximada y no constituye un renderizador PBR completo. Consulta la guía de compilación para conocer los detalles de implementación y las limitaciones actuales.

---
