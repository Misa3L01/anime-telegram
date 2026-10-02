"""Traducción automática de sinopsis (AniList solo las tiene en inglés), con caché local.

Usa el servicio web público de Google Translate. Si falla, se devuelve el texto original:
una sinopsis en inglés es mejor que ninguna.
"""
import hashlib
import html
import json
import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger('animetg.traductor')

_URL = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl={destino}&dt=t'
_MAXIMO = 4500  # caracteres por pedido


def limpiar_sinopsis(texto: str | None) -> str:
    """Quita HTML y las notas de fuente que agrega AniList ("(Source: ...)", "Note: ...")."""
    texto = html.unescape(re.sub(r'<[^>]+>', '', texto or ''))
    texto = re.sub(r'\(\s*(?:Source|Fuente)\s*:[^)]*\)', '', texto, flags=re.I)
    lineas = [l for l in texto.splitlines() if not re.match(r'\s*(?:Note|Notes|Nota)\s*:', l, re.I)]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lineas)).strip()


def _trozos(texto: str) -> list[str]:
    trozos, actual = [], ''
    for parrafo in texto.split('\n'):
        if actual and len(actual) + len(parrafo) + 1 > _MAXIMO:
            trozos.append(actual)
            actual = ''
        actual = f'{actual}\n{parrafo}' if actual else parrafo
    return trozos + ([actual] if actual else [])


class Traductor:
    def __init__(self, cache):
        self.cache = cache

    def _pedir(self, texto: str, destino: str) -> str:
        cuerpo = urllib.parse.urlencode({'q': texto}).encode()
        pedido = urllib.request.Request(_URL.format(destino=destino), data=cuerpo, headers={
            'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'})
        with urllib.request.urlopen(pedido, timeout=20) as r:
            datos = json.loads(r.read().decode('utf-8'))
        return ''.join(segmento[0] for segmento in datos[0] if segmento and segmento[0])

    def traducir(self, texto: str, destino: str = 'es') -> str:
        if not texto or destino == 'en':
            return texto
        clave = f'trad:{destino}:{hashlib.sha1(texto.encode()).hexdigest()}'
        guardado, _ = self.cache.cache_leer(clave)
        if guardado:
            return guardado
        try:
            traducido = '\n'.join(self._pedir(t, destino) for t in _trozos(texto))
        except Exception as e:  # sin red, cambios del servicio, etc.
            log.warning('No se pudo traducir la sinopsis (%s); queda en inglés.', e)
            return texto
        self.cache.cache_guardar(clave, traducido)
        return traducido
