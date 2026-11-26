## Iconos de ventana

Todos estos archivos son opcionales; deben ser PNG cuadrados de **256 × 256 px**, RGBA con fondo transparente:

| Archivo | Uso |
|---|---|
| `explorer_icon.png` | Ventana principal **AMI: Resource Explorer** |
| `viewer_icon.png` | Ventana principal **AMI: 3D Viewer** |
| `image_viewer_icon.png` | Visor interno de imágenes y texturas |
| `code_editor_icon.png` | Editor interno de código y texto |

El explorador y el visor cargan estos recursos para la barra de título y el icono de la aplicación. El visor de imágenes y el editor usan sus respectivos iconos. Si falta un PNG o no puede cargarse, se utiliza el icono de respaldo integrado.

# Recursos gráficos del explorador XXAMI

Todos los PNG deben ser cuadrados de **256 × 256 px**, con fondo transparente (RGBA). El explorador los escala al tamaño de cada control. Colócalos en esta carpeta `res/`, junto a `gui.py` y `file_explorer.py`.

## Iconos de archivos (cuadrícula y panel de detalles)

| Archivo | Uso |
|---|---|
| `spv.png` | Shader SPIR-V binario (`.spv`) |
| `txt.png` | Archivo de texto / GLSL / SPIR-V textual (`.txt`) y ensamblador SPIR-V (`.s`) |
| `buf.png` | Buffer binario genérico (`.buf`) |
| `model_buf.png` | Buffer de geometría reconocible por el visor de modelos (`vb_`, `ib_`, `vbib_`, `PartNN-vb0=`) |
| `generic.png` | Tipo de archivo sin icono específico |
| `folder.png` | Carpeta |
| `xmod.png` | Contenedor de mod XMOD |
| `mlpk.png` | Contenedor de mod MLPK |
| `ini.png` | Archivo de configuración INI |
| `json.png` | Archivo JSON |
| `glsl.png` | Shader GLSL |\n| `asm_s.png` | Ensamblador SPIR-V (`.s`) |

Las texturas KTX2 tienen miniaturas generadas a partir de su contenido, no necesitan icono.

## Iconos de controles

| Archivo | Uso |
|---|---|
| `back.png` | Navegación atrás |
| `forward.png` | Navegación adelante |
| `refresh.png` | Actualizar carpeta |
| `search.png` | Icono de búsqueda |
| `up.png` | Subir un nivel en la navegación |

## Recomendaciones visuales

- Mantener siluetas legibles a 38–82 px, porque los PNG se reducen en la interfaz.
- Usar trazos claros y contraste alto sobre fondo oscuro.
- No incluir texto pequeño; los nombres de extensión ya aparecen debajo de cada icono.
- Los iconos provisionales dibujados por código se usan automáticamente mientras falte cada PNG.


## Nota sobre la interfaz Qt independiente

`file_explorer_qt.py` reutiliza los iconos de archivo indicados arriba. La versión Qt utiliza los mismos nombres de PNG cuando están presentes. Si falta un recurso, dibuja un icono vectorial con el estilo de los iconos de respaldo del explorador anterior; esto también se aplica a atrás, adelante, actualizar y búsqueda. Los iconos personalizados pueden añadirse en esta carpeta sin modificar código. El editor incluye números de línea y resaltado específico para INI, JSON y GLSL; sus botones de guardar y decodificar SPIR-V usan iconos vectoriales integrados.
