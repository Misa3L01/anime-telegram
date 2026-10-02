"""Accesos directos de Windows: escritorio, menú Inicio e inicio automático con Windows."""
import ctypes
import os
import subprocess
import sys
from pathlib import Path

from . import NOMBRE_APP
from .rutas import ICONO, PROYECTO

_SIN_VENTANA = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_CREAR = (
    '$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:AT_LNK); '
    '$s.TargetPath = $env:AT_EXE; $s.Arguments = $env:AT_ARGS; $s.WorkingDirectory = $env:AT_DIR; '
    '$s.IconLocation = $env:AT_ICO; $s.Description = $env:AT_DESC; $s.Save()'
)


def _escritorio() -> Path:
    ruta = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, ruta) == 0:  # CSIDL_DESKTOPDIRECTORY
        return Path(ruta.value)
    return Path.home() / 'Desktop'


def _lugares() -> dict[str, Path]:
    programas = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
    return {'escritorio': _escritorio(), 'inicio': programas, 'arranque': programas / 'Startup'}


def _lanzador() -> tuple[Path, str]:
    """El ejecutable sin consola que instala pip (anime-telegram.exe) o, si no está, pythonw."""
    scripts = Path(sys.executable).parent
    exe = scripts / 'anime-telegram.exe'
    if exe.exists():
        return exe, ''
    pythonw = scripts / 'pythonw.exe'
    return (pythonw if pythonw.exists() else Path(sys.executable)), '-m animetg'


def ruta(lugar: str) -> Path:
    return _lugares()[lugar] / f'{NOMBRE_APP}.lnk'


def estado() -> dict[str, bool]:
    return {lugar: ruta(lugar).exists() for lugar in _lugares()}


def crear(lugar: str) -> Path:
    destino = ruta(lugar)
    destino.parent.mkdir(parents=True, exist_ok=True)
    exe, argumentos = _lanzador()
    if lugar == 'arranque':
        argumentos = f'{argumentos} --minimizado'.strip()
    entorno = {**os.environ, 'AT_LNK': str(destino), 'AT_EXE': str(exe), 'AT_ARGS': argumentos,
               'AT_DIR': str(PROYECTO), 'AT_ICO': f'{ICONO},0', 'AT_DESC': 'Respaldo de anime en Telegram'}
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', _CREAR],
                   env=entorno, check=True, capture_output=True, creationflags=_SIN_VENTANA)
    return destino


def borrar(lugar: str) -> None:
    ruta(lugar).unlink(missing_ok=True)


def aplicar(escritorio: bool | None = None, inicio: bool | None = None, arranque: bool | None = None) -> None:
    for lugar, valor in (('escritorio', escritorio), ('inicio', inicio), ('arranque', arranque)):
        if valor is True:
            crear(lugar)
        elif valor is False:
            borrar(lugar)
