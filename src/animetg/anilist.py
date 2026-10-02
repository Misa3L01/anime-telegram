"""Cliente de AniList (gratis, sin clave) con caché en la base local."""
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .detectar import normalizar

log = logging.getLogger('animetg.anilist')

URL = 'https://graphql.anilist.co'
AGENTE = 'anime-telegram/2.0 (respaldo personal)'
_CAMPOS = '''id format status episodes seasonYear startDate { year month day }
title { romaji english } synonyms genres description(asHtml: false)
coverImage { extraLarge large } siteUrl
relations { edges { relationType node { id type format startDate { year month day } title { romaji english } } } }'''
_BUSCAR = 'query ($s: String) { Page(perPage: 10) { media(search: $s, type: ANIME) { %s } } }' % _CAMPOS
_POR_ID = 'query ($id: Int) { Media(id: $id, type: ANIME) { %s } }' % _CAMPOS

_DIA = 24 * 3600


class AniListError(RuntimeError):
    pass


class AniList:
    def __init__(self, cache):
        """`cache` es cualquier objeto con cache_leer / cache_guardar (normalmente el Registro)."""
        self.cache = cache
        self._ultima = 0.0

    def _consultar(self, query: str, variables: dict):
        cuerpo = json.dumps({'query': query, 'variables': variables}).encode()
        for intento in range(6):
            # AniList permite unas 30 consultas por minuto.
            espera = self._ultima + 2.1 - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
            pedido = urllib.request.Request(URL, data=cuerpo, headers={
                'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': AGENTE})
            try:
                with urllib.request.urlopen(pedido, timeout=30) as r:
                    return json.load(r)['data']
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 429 or e.code >= 500:
                    espera = int(e.headers.get('Retry-After') or 10 * (intento + 1))
                    log.info('AniList pidió esperar %s s', espera)
                    time.sleep(espera)
                    continue
                raise AniListError(f'AniList respondió {e.code}') from e
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(5 * (intento + 1))
        raise AniListError('AniList no responde; se vuelve a intentar más tarde.')

    def _guardar(self, m: dict) -> None:
        self.cache.cache_guardar(f'media:{m["id"]}', m)

    def media(self, id_: int) -> dict | None:
        m, edad = self.cache.cache_leer(f'media:{id_}')
        # Lo terminado casi no cambia; lo que está en emisión se refresca a diario.
        if m and edad < (30 * _DIA if m.get('status') == 'FINISHED' else _DIA):
            return m
        try:
            datos = self._consultar(_POR_ID, {'id': id_})
        except AniListError:
            if m:  # sin conexión: mejor un dato viejo que nada
                return m
            raise
        nuevo = datos and datos.get('Media')
        if nuevo:
            self._guardar(nuevo)
            return nuevo
        return m

    def buscar(self, texto: str) -> list[dict]:
        clave = f'buscar:{normalizar(texto)}'
        ids, edad = self.cache.cache_leer(clave)
        if ids is not None and edad < 7 * _DIA:
            return [m for m in (self.media(i) for i in ids) if m]
        datos = self._consultar(_BUSCAR, {'s': texto}) or {}
        lista = (datos.get('Page') or {}).get('media') or []
        for m in lista:
            self._guardar(m)
        self.cache.cache_guardar(clave, [m['id'] for m in lista])
        return lista

    def portada(self, m: dict, carpeta: Path) -> Path | None:
        url = (m.get('coverImage') or {}).get('extraLarge') or (m.get('coverImage') or {}).get('large')
        if not url:
            return None
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f'{m["id"]}{Path(url).suffix or ".jpg"}'
        if not destino.exists():
            pedido = urllib.request.Request(url, headers={'User-Agent': AGENTE})
            with urllib.request.urlopen(pedido, timeout=60) as r:
                temporal = destino.with_suffix('.descarga')
                temporal.write_bytes(r.read())
                temporal.replace(destino)
        return destino

    def miniatura(self, m: dict, carpeta: Path, lado: int = 320) -> Path | None:
        """JPEG de máximo `lado` px: lo que Telegram acepta como miniatura y lo que usa la interfaz."""
        destino = carpeta / f'mini_{m["id"]}.jpg'
        if destino.exists():
            return destino
        portada = self.portada(m, carpeta)
        if portada is None:
            return None
        with Image.open(portada) as img:
            img = img.convert('RGB')
            img.thumbnail((lado, lado))
            img.save(destino, 'JPEG', quality=85)
        return destino


def resumen(m: dict, idioma: str = 'romaji') -> dict:
    """Lo mínimo que necesita la interfaz para mostrar una opción."""
    t = m.get('title') or {}
    principal = (t.get('english') if idioma == 'english' else t.get('romaji')) or t.get('romaji') or t.get('english')
    return {
        'id': m['id'],
        'titulo': principal,
        'alternativo': t.get('english') if principal != t.get('english') else t.get('romaji'),
        'formato': m.get('format'),
        'anio': m.get('seasonYear') or (m.get('startDate') or {}).get('year'),
        'episodios': m.get('episodes'),
        'url': m.get('siteUrl'),
    }
