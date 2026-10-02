import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))  # para importar casos.py

FFMPEG = shutil.which('ffmpeg')


class CacheFija:
    """Respuestas de AniList grabadas (tests/datos/anilist.json): las pruebas no salen a internet."""

    def __init__(self):
        self.datos = json.loads((AQUI / 'datos' / 'anilist.json').read_text(encoding='utf-8'))

    def cache_leer(self, clave):
        return (self.datos[clave], 0) if clave in self.datos else (None, None)

    def cache_guardar(self, clave, valor):
        self.datos[clave] = valor


@pytest.fixture
def sin_red(monkeypatch):
    """Corta AniList y el traductor; las carátulas son imágenes generadas."""
    def prohibido(*_, **__):
        raise AssertionError('la prueba intentó consultar AniList por internet')

    def portada(self, m, carpeta):
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f'{m["id"]}.jpg'
        if not destino.exists():
            Image.new('RGB', (460, 650), (120, 60, 200)).save(destino)
        return destino

    monkeypatch.setattr('animetg.anilist.AniList._consultar', prohibido)
    monkeypatch.setattr('animetg.anilist.AniList.portada', portada)
    monkeypatch.setattr('animetg.traductor.Traductor._pedir', lambda self, texto, destino: f'[{destino}] {texto}')


@pytest.fixture
def anilist(sin_red):
    from animetg.anilist import AniList
    return AniList(CacheFija())


@pytest.fixture
def resolver(anilist):
    from animetg.resolver import Resolver
    return Resolver(anilist, dict, 'romaji')


@pytest.fixture(scope='session')
def videos(tmp_path_factory) -> dict[str, Path]:
    """Videos sintéticos de 20 s (imagen de prueba y un tono), uno por cada formato que puede llegar."""
    if not FFMPEG:
        pytest.skip('necesita ffmpeg')
    carpeta = tmp_path_factory.mktemp('videos')
    (carpeta / 'sub.srt').write_text('1\n00:00:01,000 --> 00:00:04,000\nHola\n', encoding='utf-8')
    fuente = ['-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24:duration=20',
              '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20']
    h264 = ['-c:v', 'libx264', '-preset', 'ultrafast', '-g', '48', '-pix_fmt', 'yuv420p']
    casos = {
        'mp4': (fuente, h264 + ['-c:a', 'aac', '-movflags', '+faststart'], 'mp4'),
        'mp4_lento': (fuente, h264 + ['-c:a', 'aac'], 'mp4'),
        'mkv': (fuente, h264 + ['-c:a', 'aac'], 'mkv'),
        'mkv_subs': (fuente + ['-i', str(carpeta / 'sub.srt')],
                     ['-map', '0', '-map', '1', '-map', '2'] + h264 + ['-c:a', 'aac', '-c:s', 'srt'], 'mkv'),
        'mkv_10bits': (fuente, ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p10le', '-c:a', 'aac'], 'mkv'),
        'mkv_opus': (fuente, h264 + ['-c:a', 'libopus'], 'mkv'),
    }
    rutas = {}
    for nombre, (entradas, opciones, ext) in casos.items():
        destino = carpeta / f'{nombre}.{ext}'
        subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', *entradas, *opciones, str(destino)],
                       check=True)
        rutas[nombre] = destino
    return rutas
