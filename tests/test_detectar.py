from pathlib import Path

import pytest

from animetg.detectar import detectar, normalizar

RAIZ = Path('Subir')


@pytest.mark.parametrize('archivo, titulo, temporada, episodio, parte, pelicula', [
    ('[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv', 'Sousou no Frieren', None, 5, None, False),
    ('Shingeki no Kyojin Temporada 3 Capitulo 12.mp4', 'Shingeki no Kyojin', 3, 12, None, False),
    ('Shingeki no Kyojin Temporada 3 Parte 2 - 01.mp4', 'Shingeki no Kyojin', 3, 1, 2, False),
    ('Kimetsu_no_Yaiba_S2_-_07_[720p].mp4', 'Kimetsu no Yaiba', 2, 7, None, False),
    ('Jujutsu Kaisen 2nd Season - 03.mkv', 'Jujutsu Kaisen', 2, 3, None, False),
    ('Jujutsu Kaisen Season 2 - 05.mp4', 'Jujutsu Kaisen', 2, 5, None, False),
    ('Dr. Stone S03E05.mkv', 'Dr Stone', 3, 5, None, False),
    ('One Piece 1071 [1080p].mp4', 'One Piece', None, 1071, None, False),
    ('Ep 07 - Chainsaw Man [AnimeFLV].mp4', 'Chainsaw Man', None, 7, None, False),
    ('Love Live! The School Idol Movie.mkv', 'Love Live! The School Idol', None, None, None, True),
    ('[DBD-Raws][Love Live! Superstar!! S1][07][1080P][BDRip][HEVC-10bit][FLAC].mkv', 'Love Live! Superstar!!', 1, 7, None, False),
])
def test_nombres(archivo, titulo, temporada, episodio, parte, pelicula):
    d = detectar(RAIZ / archivo, RAIZ)
    assert normalizar(d.titulo) == normalizar(titulo)
    assert (d.temporada, d.episodio, d.parte, d.es_pelicula) == (temporada, episodio, parte, pelicula)


def test_carpetas_completan_lo_que_falta():
    d = detectar(RAIZ / 'Frieren' / 'Temporada 2' / 'Capitulo 03.mp4', RAIZ)
    assert (d.titulo, d.temporada, d.episodio) == ('Frieren', 2, 3)


def test_numero_solo_toma_el_titulo_de_la_carpeta():
    d = detectar(RAIZ / 'Boku no Hero Academia' / '05.mp4', RAIZ)
    assert (d.titulo, d.episodio) == ('Boku no Hero Academia', 5)


def test_la_carpeta_de_subida_no_cuenta_como_titulo():
    d = detectar(RAIZ / '05.mp4', RAIZ)
    assert d.titulo is None and d.episodio == 5
