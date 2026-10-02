"""Genera src/animetg/web/estaticos/icono.ico (mismo diseño que icono.svg).

    python herramientas/generar_icono.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parents[1] / 'src' / 'animetg' / 'web' / 'estaticos' / 'icono.ico'
LADO = 1024  # se dibuja grande y se achica, para bordes suaves


def dibujar() -> Image.Image:
    escala = LADO / 64
    degradado = Image.new('RGBA', (LADO, LADO))
    inicio, fin = (0x7C, 0x3A, 0xED), (0xDB, 0x27, 0x77)
    pixeles = degradado.load()
    for y in range(LADO):
        for x in range(LADO):
            t = (x + y) / (2 * (LADO - 1))
            pixeles[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(inicio, fin)) + (255,)
    mascara = Image.new('L', (LADO, LADO), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, LADO - 1, LADO - 1), radius=round(15 * escala), fill=255)
    icono = Image.new('RGBA', (LADO, LADO), (0, 0, 0, 0))
    icono.paste(degradado, mask=mascara)
    dibujo = ImageDraw.Draw(icono)
    dibujo.polygon([(25 * escala, 16 * escala), (25 * escala, 44 * escala), (48.5 * escala, 30 * escala)],
                   fill=(255, 255, 255, 255))
    dibujo.rounded_rectangle((14 * escala, 49 * escala, 50 * escala, 53 * escala), radius=round(2 * escala),
                             fill=(255, 255, 255, 140))
    return icono


if __name__ == '__main__':
    imagen = dibujar()
    imagen.save(DESTINO, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128),
                                (256, 256)])
    print(f'Ícono generado en {DESTINO}')
