# Anime Telegram
App de escritorio (pywebview + servidor aiohttp local) que respalda anime en canales privados de Telegram, ordenado por temporadas.

## Entrada
- GUI: `anime-telegram` → `src/animetg/escritorio.py:main`
- CLI: `animetg` → `src/animetg/cli.py:main` (`python -m animetg`)

## Módulos clave (src/animetg/)
- servicio.py: orquesta vigilancia de carpeta, análisis, subida en orden y avisos a la UI
- detectar.py: título/temporada/episodio desde el nombre del archivo y carpetas
- resolver.py: decide canal, sección y episodio según relaciones de AniList
- anilist.py: cliente de AniList; traductor.py: traducción de títulos
- subida.py: subida de archivos grandes con partes en paralelo
- sesion.py / credenciales.py: login Telegram; credenciales en el Administrador de Windows (keyring)
- canales.py, registro.py, migracion.py: canales, registro de lo subido, migración desde la v1
- eventos.py: bus de eventos servicio → ventanas
- web/servidor.py y web/estaticos/: API local e interfaz (HTML/CSS/JS)
- demo.py: Telegram simulado

## Probar sin servicios reales
- `animetg --demo` abre la app con Telegram simulado.
- `animetg servidor --demo` levanta solo la interfaz en el navegador.
- Los tests usan `demo.py` y un AniList grabado (`tests/datos/`); no necesitan red.

## Correr UN test
`.venv\Scripts\python -m pytest tests/test_detectar.py -q --tb=short -x`

## Contratos que no se rompen
- La interfaz de `demo.py` debe imitar lo que la app usa de Telethon.
- Credenciales nunca en archivos: solo keyring; la sesión se guarda como texto.
- Los datos de la v1 (config.ini) no se versionan; `migracion.py` los lee.
- `package-data` incluye `web/estaticos/*`: no mover esa carpeta sin actualizar pyproject.toml.

## No leer
`data/`, `.venv/`, `tests/datos/anilist.json` (grande), README completo (usar grep).
