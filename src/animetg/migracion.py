"""Pasa los datos de la versión 1 (scripts sueltos) al formato de la aplicación.

- config.ini      -> data/ajustes.json + api_id/api_hash en el Administrador de credenciales
- anime.session   -> sesión en el Administrador de credenciales (deja de existir el archivo)
- correcciones.ini, registro.db, caché y registro -> data/
Cada paso borra el archivo viejo solo después de comprobar que el dato quedó guardado.
"""
import configparser
import logging
import re
import shutil
from pathlib import Path

from .ajustes import Ajustes
from .credenciales import Credenciales
from .detectar import normalizar
from .registro import Registro
from .rutas import PROYECTO, Rutas

log = logging.getLogger('animetg.migracion')


def _ini(ruta: Path) -> configparser.ConfigParser:
    ini = configparser.ConfigParser(delimiters=('=',), interpolation=None)
    ini.optionxform = str
    ini.read(ruta, encoding='utf-8-sig')
    return ini


def _mover(origen: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origen), str(destino))


def migrar(rutas: Rutas, credenciales: Credenciales, origen: Path = PROYECTO) -> list[str]:
    rutas.crear()
    hechos = []

    viejo_db = origen / 'registro.db'
    if viejo_db.exists() and not rutas.db.exists():
        _mover(viejo_db, rutas.db)
        for sufijo in ('-wal', '-shm', '-journal'):
            extra = origen / f'registro.db{sufijo}'
            if extra.exists():
                _mover(extra, rutas.db.with_name(rutas.db.name + sufijo))
        hechos.append('registro de subidas')

    config = origen / 'config.ini'
    if config.exists():
        ini = _ini(config)

        def leer(seccion, clave):
            return ini.get(seccion, clave, fallback=None)

        api_id, api_hash = (leer('telegram', 'api_id') or '').strip(), (leer('telegram', 'api_hash') or '').strip()
        if api_id.isdigit() and api_hash:
            credenciales.guardar_api(int(api_id), api_hash)
            if credenciales.api_id != int(api_id) or credenciales.api_hash != api_hash:
                raise RuntimeError('No se pudieron guardar las credenciales en Windows.')
        cambios = {}
        for seccion, clave, nueva in (('carpetas', 'subir', 'carpeta_subir'), ('carpetas', 'subidos', 'carpeta_subidos'),
                                      ('opciones', 'carpeta_telegram', 'carpeta_telegram'),
                                      ('opciones', 'idioma_titulo', 'idioma_titulo'),
                                      ('opciones', 'ordenar_automatico', 'ordenar_automatico'),
                                      ('programas', 'ffmpeg', 'ffmpeg'), ('programas', 'ffprobe', 'ffprobe'),
                                      ('programas', '7zip', 'siete_zip')):
            valor = leer(seccion, clave)
            if valor is not None:
                cambios[nueva] = valor.strip()
        limite = (leer('opciones', 'limite_mb') or '').strip()
        if limite.isdigit():
            cambios['premium'] = int(limite) >= 4000
        ajustes = Ajustes.cargar(rutas.ajustes)
        ajustes.actualizar(cambios)
        ajustes.guardar(rutas.ajustes)
        config.unlink()
        hechos.append('configuración y credenciales')

    correcciones = origen / 'correcciones.ini'
    if correcciones.exists():
        ini = _ini(correcciones)
        if ini.has_section('correcciones'):
            registro = Registro(rutas.db)
            try:
                for clave, valor in ini.items('correcciones'):
                    m = re.search(r'\d+', valor)
                    if m:
                        registro.guardar_correccion(normalizar(clave), clave, int(m.group()))
            finally:
                registro.cerrar()
        correcciones.unlink()
        hechos.append('correcciones')

    sesion = origen / 'anime.session'
    if sesion.exists():
        from telethon.sessions import SQLiteSession, StringSession
        vieja = SQLiteSession(str(sesion.with_suffix('')))
        try:
            texto = StringSession.save(vieja) if vieja.auth_key else ''
        finally:
            vieja.close()
        if texto:
            credenciales.sesion = texto
            if credenciales.sesion != texto:
                raise RuntimeError('No se pudo guardar la sesión de Telegram en Windows.')
        sesion.unlink()
        sesion.with_name('anime.session-journal').unlink(missing_ok=True)
        hechos.append('sesión de Telegram')

    viejas_portadas = origen / 'cache' / 'portadas'
    if viejas_portadas.is_dir():
        for archivo in viejas_portadas.iterdir():
            if not (rutas.portadas / archivo.name).exists():
                _mover(archivo, rutas.portadas / archivo.name)
        shutil.rmtree(origen / 'cache', ignore_errors=True)

    viejo_log = origen / 'registro.log'
    if viejo_log.exists():
        _mover(viejo_log, rutas.logs / 'version-1.log')
    shutil.rmtree(origen / 'temp', ignore_errors=True)

    if hechos:
        log.info('Datos de la versión anterior migrados: %s.', ', '.join(hechos))
    return hechos
