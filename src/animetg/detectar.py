"""Saca título, temporada y episodio del nombre del archivo (y de sus carpetas)."""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import anitopy

EXTENSIONES = {'.mp4', '.mkv', '.avi', '.m4v', '.mov', '.webm', '.ts', '.wmv', '.flv'}


@dataclass
class Deteccion:
    titulo: str | None
    temporada: int | None
    episodio: int | None
    parte: int | None
    es_pelicula: bool


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', texto.lower()).strip()


_SEP = r'[\s._-]*'
_RE_SXXEXX = re.compile(r'(?<![a-z0-9])s(\d{1,2})e(\d{1,4})(?![0-9])', re.I)
# El orden importa: "2nd Season - 03" es temporada 2, no 3.
_RE_TEMPORADA = [
    re.compile(r'\b(\d{1,2})\s*(?:st|nd|rd|th|ra|da|ta|va|na|ma|a|°|º)?' + _SEP + r'(?:temporada|season)\b', re.I),
    re.compile(r'\b(?:temporada|temp|season)[\s._]*(\d{1,2})\b', re.I),
    re.compile(r'(?<![a-z0-9])[ts](\d{1,2})(?![a-z0-9])', re.I),
]
_RE_PARTE = [
    re.compile(r'\b(?:parte|part|cour)' + _SEP + r'(\d)\b', re.I),
    re.compile(r'\b(\d)\s*(?:nd|rd|th|da|ra|ta)?' + _SEP + r'(?:cour|parte)\b', re.I),
]
_RE_EPISODIO = re.compile(
    r'\b(?:cap[ií]tulo|cap|episodio|epis[oó]dio|episode|ep)' + _SEP + r'(\d{1,4})\b', re.I)
_RE_PELICULA = re.compile(r'\b(?:pel[ií]cula|movie|gekijouban|gekijoban)\b', re.I)
_RE_CORCHETES = re.compile(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}')


def _extraer(patrones, texto):
    for patron in patrones:
        m = patron.search(texto)
        if m:
            return int(m.group(1)), texto[:m.start()] + ' ' + texto[m.end():]
    return None, texto


def _numero(valor) -> int | None:
    if isinstance(valor, list):
        valor = valor[0] if valor else None
    if valor is None:
        return None
    m = re.search(r'\d+', str(valor))
    return int(m.group()) if m else None


def _limpiar_titulo(texto: str) -> str | None:
    texto = re.sub(r'[\s._]+', ' ', texto).strip(' -')
    if not texto or texto.isdigit():
        return None
    return texto


def _desde_nombre(nombre: str, extension: str) -> Deteccion:
    temporada = episodio = None
    m = _RE_SXXEXX.search(nombre)
    if m:
        temporada, episodio = int(m.group(1)), int(m.group(2))
        nombre = nombre[:m.start()] + ' - ' + nombre[m.end():]
    es_pelicula = bool(_RE_PELICULA.search(nombre))
    nombre = _RE_PELICULA.sub(' ', nombre)
    if temporada is None:
        temporada, nombre = _extraer(_RE_TEMPORADA, nombre)
    parte, nombre = _extraer(_RE_PARTE, nombre)
    m = _RE_EPISODIO.search(nombre)
    if m and episodio is None:
        episodio = int(m.group(1))
        nombre = nombre[:m.start()] + ' - ' + nombre[m.end():]

    datos = anitopy.parse(nombre + extension) or {}
    titulo = datos.get('anime_title')
    if temporada is None:
        temporada = _numero(datos.get('anime_season'))
    if episodio is None:
        episodio = _numero(datos.get('episode_number'))
    if titulo and titulo.strip().isdigit() and episodio is None:
        episodio, titulo = int(titulo), None
    if str(datos.get('anime_type') or '').lower() == 'movie':
        es_pelicula = True
    return Deteccion(_limpiar_titulo(titulo or ''), temporada, episodio, parte, es_pelicula)


def _desde_carpeta(nombre: str) -> Deteccion:
    temporada, nombre = _extraer(_RE_TEMPORADA, nombre)
    parte, nombre = _extraer(_RE_PARTE, nombre)
    es_pelicula = bool(_RE_PELICULA.search(nombre))
    nombre = _RE_PELICULA.sub(' ', _RE_CORCHETES.sub(' ', nombre))
    return Deteccion(_limpiar_titulo(nombre), temporada, None, parte, es_pelicula)


def detectar(ruta: Path, raiz: Path) -> Deteccion:
    """Lo que dice el nombre del archivo manda; las carpetas completan lo que falte."""
    d = _desde_nombre(ruta.stem, ruta.suffix)
    carpeta = ruta.parent
    while carpeta != raiz and carpeta != carpeta.parent and (d.titulo is None or d.temporada is None):
        c = _desde_carpeta(carpeta.name)
        if d.temporada is None and c.temporada is not None:
            d.temporada = c.temporada
        if d.parte is None and c.parte is not None:
            d.parte = c.parte
        if d.titulo is None and c.titulo:
            d.titulo = c.titulo
            d.es_pelicula = d.es_pelicula or c.es_pelicula
        carpeta = carpeta.parent
    return d
