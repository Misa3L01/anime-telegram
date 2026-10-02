"""Graba las respuestas de AniList que usan las pruebas en tests/datos/anilist.json.

    python herramientas/grabar_anilist.py

Se vuelve a correr solo si se agregan casos a tests/casos.py. Las sinopsis no se guardan.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / 'tests'))

from casos import NO_RECONOCIDOS, RESOLVER  # noqa: E402

from animetg.anilist import AniList  # noqa: E402
from animetg.detectar import detectar  # noqa: E402
from animetg.resolver import NoReconocido, Resolver  # noqa: E402

DESTINO = RAIZ / 'tests' / 'datos' / 'anilist.json'


class CacheMemoria:
    def __init__(self):
        self.datos = {}

    def cache_leer(self, clave):
        return (self.datos[clave], 0) if clave in self.datos else (None, None)

    def cache_guardar(self, clave, valor):
        self.datos[clave] = valor


def main():
    cache = CacheMemoria()
    resolver = Resolver(AniList(cache), dict, 'romaji')
    entrada = Path('Subir')
    for archivo, *_ in RESOLVER:
        resolver.resolver(detectar(entrada / archivo, entrada))
    for archivo in NO_RECONOCIDOS:
        try:
            resolver.resolver(detectar(entrada / archivo, entrada))
        except NoReconocido:
            pass
    for clave, valor in cache.datos.items():
        if clave.startswith('media:'):
            valor['description'] = 'Sinopsis de prueba.'
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(cache.datos, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(cache.datos)} respuestas guardadas en {DESTINO}')


if __name__ == '__main__':
    main()
