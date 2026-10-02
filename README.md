# Anime Telegram

Aplicación de escritorio para Windows que respalda anime en canales privados de Telegram, un
canal por franquicia, con carátula, sinopsis en español, temporadas y películas en orden
cronológico y un índice fijado que se actualiza solo.

## Uso

Abre **Anime Telegram** desde el escritorio o el menú Inicio. La primera vez pide conectar la cuenta de
Telegram (api_id y api_hash de [my.telegram.org](https://my.telegram.org), número y código).

Después todo es automático: lo que dejes en la carpeta de subida (por defecto `R:\Anime\Subir`) se
detecta, se ordena y se sube. Cuando termina, cada archivo se mueve a `R:\Anime\Subidos\<Serie>\<Temporada>`.
Nunca se borra nada.

| Pantalla | Para qué |
|---|---|
| **Panel** | Lo que se está subiendo (progreso, velocidad, tiempo restante), la cola y lo último subido. |
| **Series** | Todos los canales. Al abrir uno se ve qué episodios hay y cuáles faltan, y se puede abrir en Telegram, reordenar o actualizar la ficha. |
| **Pendientes** | Archivos que no se reconocieron: se busca el anime en AniList y se elige. La elección se recuerda para los demás archivos con ese nombre. |
| **Actividad** | Registro de todo lo que hizo la aplicación. |
| **Ajustes** | Carpetas, cuenta, idioma, subida automática, partes en paralelo, prueba de velocidad, accesos directos e inicio con Windows. |

## Cómo organiza los canales

Cada canal es una franquicia según las relaciones de AniList, y adentro tiene secciones en orden:

- **Temporadas**, numeradas dentro de su subserie. Love Live! queda así: *School idol project* T1, T2 y
  Película, y después *Sunshine!!* T1, T2 y Película, todo en un mismo canal.
- **Películas, OVAs y especiales**, junto a la temporada con la que están relacionados. Por ejemplo,
  *Jujutsu Kaisen 0* va antes de la T1 porque es la precuela, y *Mugen Ressha-hen* va entre la T1 y la T2.
- Las partes de una misma temporada (*Part 2*, *Cour 2*) se juntan: "Temporada 3 Parte 2 - 01" es la T3 E13.

Si llega un episodio que va antes de otros ya subidos, el canal se reacomoda solo. Se reenvía lo que
quedó fuera de lugar dentro del mismo canal, sin volver a subir nada.

### Formatos

| Llega como | Se sube como |
|---|---|
| MP4 | Video, se ve directo en Telegram |
| MKV sin subtítulos aparte y con un solo audio | Pasa a MP4 sin recodificar (segundos) y se ve directo |
| MKV con subtítulos aparte o varios audios | Archivo tal cual, para no perder nada |
| Más de 2 GB (4 GB con Premium) | Partes que se reproducen solas; si no se puede, volúmenes 7z sin compresión |

## Dónde quedan las cosas

| Qué | Dónde |
|---|---|
| Programa | `R:\anime-telegram\src\animetg` |
| Datos (registro, caché, ajustes, registros) | `R:\anime-telegram\data` |
| api_id, api_hash y sesión de Telegram | Administrador de credenciales de Windows (`anime-telegram`) |

La sesión da acceso a la cuenta, por eso no se guarda en ningún archivo.

## Línea de comandos

```bash
animetg              # abre la aplicación
animetg estado       # resumen de canales
animetg simular      # qué haría con lo que hay en la carpeta, sin subir nada
animetg subir        # sube todo y termina, sin ventana
animetg reordenar    # ordena todos los canales
animetg accesos      # crea los accesos directos
animetg --demo       # abre la aplicación con un Telegram simulado
```

(`animetg` está en `R:\anime-telegram\.venv\Scripts`.)

## Desarrollo

```bash
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

- Las pruebas no usan internet: AniList responde desde `tests/datos/anilist.json`, que se regenera con
  `herramientas/grabar_anilist.py`, y Telegram es el simulador de `animetg.demo`.
- `animetg servidor --demo` levanta solo la interfaz en el navegador, útil para trabajar en el diseño.

| Módulo | Responsabilidad |
|---|---|
| `detectar` | Título, temporada y episodio a partir del nombre y las carpetas |
| `anilist`, `resolver` | Qué anime es, a qué canal y sección va |
| `video` | ffprobe, conversión sin recodificar y cortes |
| `subida` | Subida con varias partes en paralelo |
| `canales` | Canal, ficha, separadores, índice y reordenamiento en Telegram |
| `servicio` | Vigila la carpeta, mantiene la cola y coordina todo |
| `web`, `escritorio` | Interfaz (servidor local con token + ventana WebView2) |
| `registro`, `migracion` | Base de datos con migraciones versionadas y paso desde la versión 1 |
