# XXAMI Explorer independiente

El explorador Qt vive en `file_explorer_qt.py`. El decodificador compartido está separado en `texture_decoder.py`.

## Dependencia

```bash
python -m pip install -r requirements-explorer.txt
```

## Ejecutar por separado

```bash
python file_explorer_qt.py
python file_explorer_qt.py "D:\\ruta\\a\\XXAMI"\npython file_explorer_qt.py --log-path "D:\\ruta\\xxami_crash_log.txt" "D:\\ruta\\a\\XXAMI"
```

## Generar EXE independiente (Windows)

Desde un entorno Windows con las dependencias instaladas:

```bash
python -m pip install pyinstaller
pyinstaller --icon=explorer_icon.ico --version-file=explorer_file_version_info.txt --noconfirm --clean --windowed --name "AMI Explorer" --add-data "res;res" --add-data "notload.png;." --add-binary "spirv-cross.exe;." --hidden-import texture_decoder --hidden-import ktx2_util --hidden-import xxami_logging --collect-all texture2ddecoder --onefile file_explorer_qt.py
```

Si se distribuye el EXE, conserva la carpeta `res` junto al ejecutable (o ajusta el empaquetado para incluirla). Para convertir SPIR-V a GLSL, `spirv-cross.exe` debe estar disponible junto al programa.

## Ejecución independiente

El explorador y el visor son aplicaciones independientes. Ya no se necesita `gui.py`, la interfaz Tk de DumpAna ni su antigua pestaña `trace_tab.py`.

El explorador se ejecuta con:

```bash
python file_explorer_qt.py
python file_explorer_qt.py "D:\\ruta\\a\\XXAMI"
```

El visor se ejecuta con:

```bash
python model_viewer_qt.py "D:\\ruta\\Frame_Trace_001\\frame_trace.json"
```

Ambos procesos usan `xxami_logging.py` para registrar excepciones y fallos nativos. Cada aplicación puede mantener su propio `xxami_crash_log.txt`; al abrir el visor desde el explorador, este le pasa la ruta de registro para compartir el diagnóstico durante esa sesión.

### Módulos compartidos que deben conservarse

- `xxami_trace.py`: núcleo de reconstrucción de geometría y lectura de Frame Trace, utilizado directamente por el visor.
- `texture_decoder.py` y `ktx2_util.py`: decodificación de texturas y recursos KTX2.
- `xxami_logging.py`: registro de errores y trazas.
- `xxami_render_backend.py`, `xxami_gl.py`, `xxami_wgpu_backend.py`, `xxami_d3d9_backend.py` y `xxami_d3d11_backend.py`: backends gráficos del visor.
- `lang/explorer_lang/` y `lang/viewer_lang/`: catálogos independientes de cada aplicación.

Los archivos de prueba y diagnóstico de Direct3D 9, Direct3D 11 y GPU se conservan en el repositorio. No son dependencias de ejecución obligatorias del explorador.

## Recursos gráficos

Los iconos de ventana personalizados se cargan desde `res/` (PNG RGBA transparente de 256 × 256 px):
- `explorer_icon.png` — ventana principal AMI: Resource Explorer.
- `viewer_icon.png` — ventana principal AMI: 3D Viewer.
- `image_viewer_icon.png` — visor de imágenes y texturas.
- `code_editor_icon.png` — editor de código y texto.

Si alguno falta, el programa conserva un icono de respaldo integrado. En ejecutables PyInstaller, coloca `res/` junto al EXE o inclúyela en el bundle; el cargador busca ambas ubicaciones.

Los iconos de tipo de archivo son opcionales. Se buscan en `res/`:
- `folder.png`
- `spv.png`
- `txt.png`
- `buf.png`
- `xmod.png`
- `mlpk.png`
- `generic.png`
- `ini.png`
- `json.png`
- `glsl.png`
- `asm_s.png` — SPIR-V Assembly (`.s`).

Cada PNG debe ser RGBA de 256 × 256. Si falta alguno, se dibuja un icono vectorial propio con el estilo del explorador anterior. Los controles de atrás, adelante, subir nivel, actualizar y búsqueda cargan ahora `back.png`, `forward.png`, `up.png`, `refresh.png` y `search.png` desde `res/`;  si falta alguno, se dibuja un icono vectorial de respaldo. El botón `+` situado a la derecha de las pestañas permite abrir otra carpeta en una pestaña nueva. En el área de archivos, al hacer clic derecho sobre un espacio vacío aparece un menú contextual con **Nuevo** y **Propiedades**. El submenú **Nuevo** crea archivos `.ini`, `.s` y `.glsl`, o inicializa contenedores `.xmod` y `.mlpk` como ZIP sin compresión. **Propiedades** muestra un recuento recursivo de archivos y carpetas, shaders y texturas agrupados por extensión, buffers `.buf`, `frame_trace.json`, carpetas de modelos `Model_N` y paquetes `.xmod`/`.mlpk`. Los enlaces simbólicos de directorio no se recorren para evitar ciclos. Los cambios de directorio y las actualizaciones usan un trabajador en segundo plano para obtener el listado. Durante el proceso se muestra `res/loading.gif`, el texto **Obteniendo datos...** / **Cargando archivos...** y una barra de progreso; los elementos se incorporan en lotes para mantener la interfaz receptiva. El comando PyInstaller ya incluye `res/` mediante `--add-data "res;res"`, por lo que también empaqueta el GIF. El explorador guarda al cerrarse las carpetas/paquetes abiertos, la pestaña activa y el tamaño/estado de la ventana, y restaura esa sesión al volver a iniciarse (si las rutas siguen existiendo). El botón **Configuración**, situado junto al selector de directorio y antes de la búsqueda, abre las pestañas **General** y **Acerca de**. En General se selecciona el idioma desde catálogos JSON de `lang/explorer_lang/` y se asignan herramientas externas por categoría (textos, shaders, modelos/buffers, texturas, paquetes y otros), de forma independiente para **Gestión** y **Edición**. La configuración se guarda en `explorer.ini` junto al ejecutable del explorador (en ejecución desde código fuente, junto a `file_explorer_qt.py`), separada de la sesión de pestañas. El archivo se crea al iniciar el explorador.

El menú contextual de archivos permite Abrir, Editar, Cortar, Copiar, Renombrar y Eliminar; la selección múltiple se realiza con `Ctrl`/`Shift` o arrastrando sobre el área de iconos. Cortar/Copiar se completa con **Pegar** desde el menú contextual del espacio vacío. Los archivos ordinarios se abren con la aplicación asociada o con la herramienta externa configurada. Para edición externa de archivos dentro de XMOD/MLPK se trabaja sobre una copia temporal y se reescribe el contenedor al finalizar correctamente; también se admiten renombrado y eliminación de entradas/carpetas del paquete. El pegado de elementos desde el portapapeles interno admite directorios del sistema de archivos y contenedores XMOD/MLPK, incluidos los movimientos desde paquetes. En un MLPK, el submenú Nuevo ofrece únicamente la creación de archivos XMOD; dentro de un XMOD se mantienen las opciones de creación habituales. Las texturas KTX2 se decodifican a PNG para el editor externo y solo se sustituyen después de una conversión y validación compatibles; se requiere `ktx.exe` y el formato Vulkan debe estar contemplado en la tabla de conversión. El original se conserva si falla el editor o la conversión.

## Limitaciones de esta primera migración

- La navegación de carpetas y contenedores ZIP, selección, panel de detalles y apertura de editor son independientes.
- KTX2 usa `texture_decoder.py`, `ktx2_util.py`, `texture2ddecoder` y NumPy. Las miniaturas se generan en segundo plano, el panel derecho muestra la textura decodificada y el doble clic abre el visor independiente. BasisLZ sigue sin estar soportado por el decodificador actual.
- El editor permite abrir, editar y guardar `.txt`, `.ini`, `.json` y `.glsl`, con números de línea y resaltado de sintaxis específico para INI, JSON y GLSL.
- Para `.spv`, el botón de decodificación permite extraer GLSL mediante `spirv-cross.exe` o desensamblar a SPIR-V Assembly mediante `spirv-dis.exe`. El ensamblador SPIR-V se guarda siempre con extensión `.s` y puede abrirse directamente en el editor de texto/código. El binario SPIR-V original no se sobrescribe ni se recompila automáticamente. `spirv-cross.exe` y `spirv-dis.exe` deben estar junto al explorador o disponibles en PATH.
- El editor puede guardar cambios de archivos dentro de `.xmod` y el explorador permite añadir/reemplazar entradas del paquete. La escritura de entradas dentro de `.mlpk` también está habilitada; el submenú de creación de estos paquetes se limita a archivos `.xmod`.

## Visor independiente de modelos y Frame Trace

El visor vive en `model_viewer_qt.py`, y utiliza el núcleo de reconstrucción `xxami_trace.py`. Para ejecutarlo:

```bash
python -m pip install -r requirements-model-viewer.txt
python model_viewer_qt.py
python model_viewer_qt.py "D:\\ruta\\Frame_Trace_001\\frame_trace.json"
python model_viewer_qt.py --root "D:\\ruta\\volcado" "D:\\ruta\\volcado\\vb_abc123_4096.buf"
```

El menú **Archivo** permite abrir un archivo, abrir una carpeta de volcado, actualizar el índice, exportar la geometría seleccionada a OBJ y salir. El menú **Diagnóstico** permite abrir o exportar el registro `xxami_crash_log.txt`; al iniciarse desde el explorador puede recibir la misma ruta para compartir el diagnóstico durante esa sesión. El menú **Configuración**, junto a Archivo y Diagnóstico, abre las secciones **General** y **Acerca de**. General permite elegir Español, el adaptador gráfico detectado y la API de renderizado. Además de OpenGL 3.3 Core mediante SDL3, el selector puede ofrecer Direct3D 9, Direct3D 11 y los backends offscreen de wgpu-py: Vulkan, Direct3D 12 y OpenGL. Las APIs Direct3D se anuncian solo en Windows y cuando la sonda puede crear un dispositivo en el adaptador gráfico seleccionado. La validación realizada hasta ahora confirma Direct3D 9 en Intel HD Graphics 4600 y Direct3D 11 en Intel HD Graphics 4600 y NVIDIA GTX 1650; esto no implica compatibilidad universal con otros adaptadores. wgpu solicita preferentemente un adaptador de alto rendimiento; la selección manual se intenta resolver por nombre. Las preferencias se guardan en `viewer.ini`, junto al ejecutable o al script. Los catálogos de idioma del visor se ubican en `lang/viewer_lang/`: `es.json` y `en.json`. El idioma seleccionado se guarda en `viewer.ini`, independiente de la configuración del explorador. La lista de APIs se filtra según el adaptador elegido en el selector de GPU: una API compatible con la GTX 1650 puede no aparecer cuando se selecciona la Intel HD Graphics 4600, y viceversa. El botón de preferencia de alto rendimiento solicita a Windows que priorice una GPU para el ejecutable, pero no sustituye la selección manual del adaptador dentro del visor. La detección de GPU utiliza los datos que expone el sistema; la selección efectiva depende del controlador y del sistema operativo. En Windows puede ser necesario asignar la GPU de alto rendimiento desde Configuración de gráficos de Windows. Reconoce capturas `frame_trace.json`, buffers de geometría `vb_`, `ib_`, `vbib_` y las partes `PartNN-vb0=<hash>.buf`. Para un `.buf` abierto desde el explorador, el directorio que lo contiene se usa como raíz de recursos; así el visor puede encontrar capturas y buffers relacionados. También indexa `Models/Model_NN` y carpetas `Models/` que contienen partes directamente.

### Distribución, controles de cámara, gizmo y materiales

- El espacio de trabajo conserva el árbol de capturas y recursos en el extremo izquierdo, el panel vertical de texturas junto al viewport y el visor 3D expandible en el centro. La información del modelo aparece dentro del viewport como un panel semitransparente abatible, anclado de forma independiente a la esquina inferior derecha, debajo del gizmo; no ocupa una columna lateral ni está unido al gizmo.
- Los controles de posición, UV y cámara quedan en una franja compacta bajo el viewport para reservarle la mayor parte de la altura disponible. El panel central y el viewport usan márgenes mínimos y políticas expansibles para aprovechar el ancho y alto restantes de la ventana.
- La casilla **Piso cuadriculado** de la franja de cámara muestra u oculta una cuadrícula de referencia en perspectiva, compuesta detrás de la geometría para que el modelo permanezca visualmente por delante. Es una guía visual del viewport y no altera la malla ni los archivos.

- Arrastrar con el botón izquierdo orbita/rota el modelo; con el botón derecho o central desplaza el modelo dentro del viewport; la rueda ajusta el zoom. El desplazamiento se aplica a la transformación de cámara/proyección en ambos renderizadores (OpenGL y software), nunca al bitmap final, por lo que el fondo y los límites del viewport permanecen fijos.
- También hay controles por teclado cuando el viewport tiene el foco: **W/A/S/D** o flechas para orbitar, **Q/E** para giro horizontal, **Shift + flechas** para desplazar, **+/-** para zoom y **0** para restablecer.
- El gizmo de la esquina superior derecha muestra los ejes **X/Y/Z** en función de la orientación actual. Pulsar cualquiera de los extremos positivos o negativos cambia a la vista correspondiente. La ventana flotante **Información del modelo** se ubica en la esquina inferior derecha, con fondo semitransparente y control de desplegar/plegar; permanece separada del gizmo.
- La lista de texturas conserva los recursos encontrados para el draw. Cada fila tiene su propio selector de tipo (**Ignorar**, **Albedo**, **Lightmap**, **Normal**, **Metallic**, **Roughness**, **Emission**, **AO** u **Opacity**) y una casilla **Invertir** para el alfa de esa textura. «Añadir textura…» permite incorporar recursos adicionales.
- Las texturas no se reasignan silenciosamente por coincidencias de nombre: la primera se propone inicialmente como Albedo y las demás quedan en Ignorar, para que puedas indicar su función según el modelo.

La vista Material combina los mapas seleccionados en una previsualización aproximada: lightmap y AO modulan el albedo, normal aplica iluminación aproximada en espacio tangente, metallic/roughness alteran el aspecto, emission añade color y opacity proporciona el alfa. No es un renderizador PBR completo: la normal requiere tangentes y matriz TBN correctas, y metallic/roughness no calculan reflejos físicos. El resultado depende de que los archivos asignados correspondan al modelo y compartan coordenadas UV compatibles.

La vista Material combina los mapas en una previsualización aproximada: lightmap modula el albedo, normal aplica iluminación aproximada en espacio tangente, metallic/roughness alteran el aspecto y emission añade color. No es un renderizador PBR completo: la normal requiere tangentes y matriz TBN correctas, y metallic/roughness no calculan reflejos físicos. El resultado depende de que los archivos asignados correspondan al modelo y compartan coordenadas UV compatibles.

### Compilar el visor por separado (Windows)

```bash
python -m pip install pyinstaller
pyinstaller --icon=viewer_icon.ico --version-file=viewer_file_version_info.txt --noconfirm --clean --onefile --windowed --name "AMI 3D Viewer" --add-data "res;res" --hidden-import xxami_trace --hidden-import xxami_gl --hidden-import xxami_render_backend --hidden-import xxami_wgpu_backend --hidden-import xxami_d3d9_backend --hidden-import xxami_d3d9_probe --hidden-import xxami_d3d11_backend --hidden-import xxami_d3d11_probe --hidden-import texture_decoder --hidden-import ktx2_util --hidden-import xxami_logging --collect-all texture2ddecoder --collect-all wgpu model_viewer_qt.py
```

**Importante:** después de actualizar `xxami_trace.py` o `xxami_gl.py`, vuelve a generar el ejecutable. Un EXE anterior conserva las versiones de esos módulos que se empaquetaron al compilarlo. El visor ahora prioriza los módulos incluidos junto a él y muestra la ruta de `xxami_trace.py` si detecta una copia antigua sin soporte de desplazamiento.

```
```

El diálogo de Configuración se muestra antes de consultar las GPU. La enumeración de adaptadores y la comprobación de APIs se ejecutan en un trabajador en segundo plano; mientras tanto aparece `res/loading.gif`, el texto **Cargando adaptadores gráficos...** y una barra de progreso. El GIF se incluye en el EXE mediante `--add-data "res;res"`. Las consultas PowerShell y WGPU no muestran ventanas de consola auxiliares en Windows. El ejecutable resultante es independiente de DumpAna. Para que el modo Material pueda decodificar KTX2, distribuye también `texture_decoder.py` y `ktx2_util.py` junto al visor o empaquétalos en el ejecutable. La aceleración SDL3/OpenGL sigue disponible. wgpu-py añade backends offscreen para Vulkan, Direct3D 12 y OpenGL; la biblioteca y sus binarios nativos deben incluirse al compilar (por eso el comando usa `--collect-all wgpu`). Si una API o adaptador no está disponible, el visor recurre al renderizador por software. El renderizador acelerado conserva los buffers de geometría y la textura en GPU entre redibujados, y aplica la cámara mediante la matriz MVP; aun así, la lectura del framebuffer y la transferencia a la interfaz tienen un coste, y el rendimiento depende de la GPU/controlador.

### Integración con XXAMI Explorer

Al hacer doble clic en un `.buf` con nombre reconocible, el explorador inicia `model_viewer_qt.py` con `--root` apuntando a la carpeta contenedora del buffer. Si junto al explorador existe `XXAMI Model Viewer.exe` o `model_viewer_qt.exe`, se utiliza ese ejecutable; en caso contrario se ejecuta el script con el intérprete Python actual. Los demás `.buf` conservan su icono genérico.


El panel de texturas permite seleccionar una textura pulsando su nombre; la selección se resalta en verde turquesa y se previsualiza debajo de la lista. El menú contextual con clic derecho sobre la previsualización permite invertir o restaurar el alfa de la textura seleccionada.

Los idiomas se descubren dinámicamente leyendo todos los archivos `lang/explorer_lang/*.json` (nombre de archivo = identificador del idioma). Cada catálogo debe ser un objeto JSON con `name` (nombre visible no vacío) y `strings` (objeto cuyas claves y valores sean cadenas). Los JSON inválidos o con estructura incorrecta se omiten; no existe un límite de idiomas. En compilaciones PyInstaller se busca primero junto al ejecutable y, si no existe esa carpeta, se usa el recurso empaquetado `lang/explorer_lang`.