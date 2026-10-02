from pathlib import Path

import pytest

from animetg.detectar import detectar
from animetg.resolver import NoReconocido
from casos import NO_RECONOCIDOS, ORDEN_LOVE_LIVE, RESOLVER

RAIZ = Path('Subir')


@pytest.mark.parametrize('archivo, canal, ubicacion', RESOLVER)
def test_casos_reales(resolver, archivo, canal, ubicacion):
    res = resolver.resolver(detectar(RAIZ / archivo, RAIZ))
    assert (resolver.titulo(res.raiz), res.ubicacion) == (canal, ubicacion)


@pytest.mark.parametrize('archivo', NO_RECONOCIDOS)
def test_no_reconocidos(resolver, archivo):
    with pytest.raises(NoReconocido):
        resolver.resolver(detectar(RAIZ / archivo, RAIZ))


def test_love_live_queda_en_orden_cronologico(resolver):
    archivos = {ubicacion: archivo for archivo, _, ubicacion in RESOLVER}
    resultados = [resolver.resolver(detectar(RAIZ / archivos[u], RAIZ)) for u in reversed(ORDEN_LOVE_LIVE)]
    ordenados = sorted(resultados, key=lambda r: (r.seccion.orden, r.episodio))
    assert [r.ubicacion for r in ordenados] == ORDEN_LOVE_LIVE
    assert all(r.varias_subseries for r in resultados)


def test_sunshine_numera_sus_temporadas_desde_uno(resolver):
    res = resolver.resolver(detectar(RAIZ / 'Love Live! Sunshine!! S2 - 10.mkv', RAIZ))
    assert (res.seccion.subserie, res.seccion.numero) == ('Love Live! Sunshine!!', 2)


def test_precuela_va_antes_de_la_temporada_1(resolver):
    pelicula = resolver.resolver(detectar(RAIZ / 'Jujutsu Kaisen 0 Pelicula.mp4', RAIZ))
    t1 = resolver.resolver(detectar(RAIZ / 'Jujutsu Kaisen 2nd Season - 03.mkv', RAIZ))
    assert pelicula.seccion.orden < t1.seccion.orden


def test_las_claves_de_la_version_1_se_mantienen(resolver):
    """La migración arma 'T:<raíz>:<n>'; el resolver tiene que producir la misma clave."""
    archivo = next(a for a, _, ubicacion in RESOLVER if 'Superstar!! S2' in a)
    res = resolver.resolver(detectar(RAIZ / archivo, RAIZ))
    assert res.seccion.clave == f'T:{res.raiz["id"]}:2'


def test_correccion_manual(anilist):
    from animetg.detectar import normalizar
    from animetg.resolver import Resolver
    r = Resolver(anilist, lambda: {normalizar('Guardianes de la Noche'): 101922}, 'romaji')
    res = r.resolver(detectar(RAIZ / 'Guardianes de la Noche - 03.mp4', RAIZ))
    assert (r.titulo(res.raiz), res.ubicacion) == ('Kimetsu no Yaiba', 'T1 E03')


def test_eleccion_forzada_para_un_archivo(resolver):
    res = resolver.resolver(detectar(RAIZ / 'cualquier cosa 02.mp4', RAIZ), forzado=154587)
    assert (resolver.titulo(res.raiz), res.ubicacion) == ('Sousou no Frieren', 'T1 E02')
