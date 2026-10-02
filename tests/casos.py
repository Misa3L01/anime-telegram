"""Casos reales de nombres de archivo y dónde deben terminar (canal, ubicación).

Los usa test_resolver.py y herramientas/grabar_anilist.py, que guarda las respuestas de AniList
necesarias en tests/datos/anilist.json para que las pruebas corran sin internet.
"""

RESOLVER = [
    # archivo, canal esperado, ubicación esperada
    ('[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv', 'Sousou no Frieren', 'T1 E05'),
    ('Frieren/Temporada 2/Capitulo 03.mp4', 'Sousou no Frieren', 'T2 E03'),
    ('Shingeki no Kyojin Temporada 3 Capitulo 12.mp4', 'Shingeki no Kyojin', 'T3 E12'),
    ('Shingeki no Kyojin Temporada 3 Parte 2 - 01.mp4', 'Shingeki no Kyojin', 'T3 E13'),
    ('Shingeki no Kyojin The Final Season Part 2 - 04.mkv', 'Shingeki no Kyojin', 'T4 E20'),
    ('Jujutsu Kaisen 2nd Season - 03.mkv', 'Jujutsu Kaisen', 'T2 E03'),
    ('Jujutsu Kaisen - 30.mp4', 'Jujutsu Kaisen', 'T2 E06'),
    ('Jujutsu Kaisen 0 Pelicula.mp4', 'Jujutsu Kaisen', 'Película: Jujutsu Kaisen 0'),
    ('Kimetsu no Yaiba Movie Mugen Ressha-hen.mkv', 'Kimetsu no Yaiba', 'Película: Kimetsu no Yaiba: Mugen Ressha-hen'),
    ('Kimetsu no Yaiba Yuukaku-hen - 03.mp4', 'Kimetsu no Yaiba', 'T3 E03'),
    ('Dr. Stone S03E05.mkv', 'Dr. STONE', 'T3 E05'),
    ('One Piece 1071 [1080p].mp4', 'ONE PIECE', 'T1 E1071'),
    ('Love Live! School Idol Project - 05.mkv', 'Love Live! School idol project', 'Love Live! School idol project · T1 E05'),
    ('Love Live! School Idol Project S2 - 03.mkv', 'Love Live! School idol project', 'Love Live! School idol project · T2 E03'),
    ('Love Live! The School Idol Movie.mkv', 'Love Live! School idol project', 'Película: Love Live! The School Idol Movie'),
    ('Love Live! Sunshine!! - 04.mkv', 'Love Live! School idol project', 'Love Live! Sunshine!! · T1 E04'),
    ('Love Live! Sunshine!! S2 - 10.mkv', 'Love Live! School idol project', 'Love Live! Sunshine!! · T2 E10'),
    ('[DBD-Raws][Love Live! Superstar!! S1][07][1080P][BDRip][HEVC-10bit][FLAC].mkv', 'Love Live! Superstar!!', 'T1 E07'),
    ('[DBD-Raws][Love Live! Superstar!! S2][08][1080P][BDRip][HEVC-10bit][FLAC].mkv', 'Love Live! Superstar!!', 'T2 E08'),
    ('Guardianes de la noche - Tren infinito Pelicula.mp4', 'Kimetsu no Yaiba', 'Película: Kimetsu no Yaiba: Mugen Ressha-hen'),
]

# Orden en que deben quedar las secciones del canal de Love Live! (cronología de AniList).
ORDEN_LOVE_LIVE = [
    'Love Live! School idol project · T1 E05',
    'Love Live! School idol project · T2 E03',
    'Película: Love Live! The School Idol Movie',
    'Love Live! Sunshine!! · T1 E04',
    'Love Live! Sunshine!! · T2 E10',
]

NO_RECONOCIDOS = [
    'Cosa rarisima que no existe 05.mp4',
    # AniList solo conoce este nombre para la película; un "05" no puede ser una película.
    'Guardianes de la noche 05.mp4',
]
