"""Flujo completo contra el Telegram simulado: canales, secciones, índice, orden, errores."""
import asyncio
import re
import shutil
import time

import pytest
from telethon.extensions import html as tl_html

from animetg.demo import ClienteDemo, CredencialesMemoria
from animetg.rutas import Rutas
from animetg.servicio import Servicio
from animetg.subida import subir_archivo
from conftest import CacheFija

FRIEREN, SUPERSTAR, LOVE_LIVE = 154587, 114979, 15051


@pytest.fixture
async def servicio(tmp_path, sin_red):
    clientes = []

    def fabrica(*args):
        clientes.append(ClienteDemo(*args, mb_por_segundo=500, latencia=0))
        return clientes[-1]

    s = Servicio(Rutas(tmp_path / 'data'), CredencialesMemoria(), fabrica)
    for clave, valor in CacheFija().datos.items():
        s.registro.cache_guardar(clave, valor)
    s.ajustes.actualizar({'carpeta_subir': str(tmp_path / 'Subir'), 'carpeta_subidos': str(tmp_path / 'Subidos')})
    await s.iniciar(vigilar=False)
    s.tg = clientes[0]
    yield s
    await s.detener()


async def poner(s, videos, *archivos, procesar=True):
    for nombre, caso in archivos:
        destino = s.ajustes.entrada / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(videos[caso], destino)
    await s.revisar_carpeta()
    if procesar:
        await s.procesar_cola()


def canal(s, raiz) -> list[str]:
    """El canal tal como se ve: una línea por mensaje (sin avisos automáticos)."""
    fila = s.registro.serie(raiz)
    salida = []
    for m in s.tg.mensajes(type('P', (), {'channel_id': fila['canal_id']})()):
        visible = tl_html.parse(m.text)[0]
        lineas = visible.split('\n')
        if m.id == fila['ficha_msg']:
            salida.append('FICHA')
        elif visible.startswith('Índice'):
            salida.append('ÍNDICE')
        elif m.tipo in ('video', 'archivo'):
            salida.append(lineas[1])
        else:
            salida.append(lineas[0])
    return salida


def indice(s, raiz) -> str:
    return '\n'.join(m['texto'] for m in s.registro.indice(raiz))


async def test_sube_en_orden_y_reacomoda(servicio, videos):
    s = servicio
    await poner(s, videos, ('Love Live! Superstar!! S1 - 07.mkv', 'mkv_subs'), ('Love Live! Superstar!! S2 - 08.mkv', 'mkv'))
    await poner(s, videos, ('Love Live! Superstar!! S1 - 03.mkv', 'mkv_subs'))
    assert canal(s, SUPERSTAR) == [
        'FICHA', 'ÍNDICE',
        'Temporada 1', 'Temporada 1 · Episodio 03', 'Temporada 1 · Episodio 07',
        'Temporada 2', 'Temporada 2 · Episodio 08',
    ]
    texto = tl_html.parse(indice(s, SUPERSTAR))[0]
    assert 'Temporada 1 (2/12)\n03 07' in texto and 'Temporada 2 · Love Live! Superstar!! 2nd Season (1/12)\n08' in texto
    assert '[es]' in s.tg.mensajes(s.canales._peer(s.registro.serie(SUPERSTAR)))[0].text  # sinopsis traducida
    subidos = sorted(p.relative_to(s.ajustes.subidos).as_posix() for p in s.ajustes.subidos.rglob('*.mkv'))
    assert subidos == ['Love Live! Superstar!!/Temporada 1/Love Live! Superstar!! S1 - 03.mkv',
                       'Love Live! Superstar!!/Temporada 1/Love Live! Superstar!! S1 - 07.mkv',
                       'Love Live! Superstar!!/Temporada 2/Love Live! Superstar!! S2 - 08.mkv']
    tipos = {m.tipo for m in s.tg.mensajes(s.canales._peer(s.registro.serie(SUPERSTAR))) if m.tipo != 'texto'}
    assert tipos == {'foto', 'archivo', 'video'}  # el MKV con subtítulos va como archivo; el otro, como video


async def test_love_live_sunshine_y_pelicula_en_un_mismo_canal(servicio, videos):
    s = servicio
    await poner(s, videos, ('Love Live! Sunshine!! - 04.mkv', 'mkv'), ('Love Live! School Idol Project - 05.mkv', 'mkv'))
    await poner(s, videos, ('Love Live! The School Idol Movie.mkv', 'mkv'))
    assert canal(s, LOVE_LIVE) == [
        'FICHA', 'ÍNDICE',
        'Love Live! School idol project · Temporada 1', 'Love Live! School idol project · Temporada 1 · Episodio 05',
        'Película · Love Live! The School Idol Movie', 'Película · Love Live! The School Idol Movie',
        'Love Live! Sunshine!! · Temporada 1', 'Love Live! Sunshine!! · Temporada 1 · Episodio 04',
    ]
    textos = [m.text for m in s.tg.mensajes(s.canales._peer(s.registro.serie(LOVE_LIVE)))]
    assert any('#SunshineT1E04' in t for t in textos) and any('#Pelicula' in t for t in textos)
    assert 'Ver' in tl_html.parse(indice(s, LOVE_LIVE))[0]  # la película aparece como un solo enlace


async def test_repetido_va_a_su_carpeta(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'))
    await poner(s, videos, ('[Otro] Sousou no Frieren - 01 (720p).mp4', 'mp4'))
    assert (s.ajustes.subidos / '_repetidos' / '[Otro] Sousou no Frieren - 01 (720p).mp4').exists()
    assert canal(s, FRIEREN).count('Temporada 1 · Episodio 01') == 1


async def test_pendiente_se_corrige_y_se_recuerda(servicio, videos):
    s = servicio
    await poner(s, videos, ('Cosa rarisima que no existe 05.mp4', 'mp4'), ('Cosa rarisima que no existe 06.mp4', 'mp4'),
                procesar=False)
    pendientes = [i for i in s.items.values() if i.estado == 'pendiente']
    assert len(pendientes) == 2
    await s.corregir(pendientes[0].id, FRIEREN, recordar=True)
    assert {i.estado for i in s.items.values()} == {'en_cola'}
    await s.procesar_cola()
    assert canal(s, FRIEREN)[-2:] == ['Temporada 1 · Episodio 05', 'Temporada 1 · Episodio 06']
    assert s.registro.correcciones() == {'cosa rarisima que no existe': FRIEREN}


async def test_lo_borrado_a_mano_se_olvida(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'), ('Sousou no Frieren - 02.mp4', 'mp4'))
    peer = s.canales._peer(s.registro.serie(FRIEREN))
    episodio_2 = next(e['msg_id'] for e in s.registro.episodios(FRIEREN) if e['episodio'] == 2)
    await s.tg.delete_messages(peer, [episodio_2])
    assert await s.reordenar(FRIEREN) == 0
    assert [e['episodio'] for e in s.registro.episodios(FRIEREN)] == [1]
    assert '02' not in tl_html.parse(indice(s, FRIEREN))[0].split('\n')[-1]


async def test_lo_borrado_en_telegram_se_vuelve_a_subir(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'))
    peer = s.canales._peer(s.registro.serie(FRIEREN))
    await s.tg.delete_messages(peer, s.registro.mensajes_episodio(FRIEREN, f'T:{FRIEREN}:1', 1))
    await poner(s, videos, ('[Subs ES] Sousou no Frieren - 01.mkv', 'mkv_subs'))
    assert canal(s, FRIEREN).count('Temporada 1 · Episodio 01') == 1
    assert not (s.ajustes.subidos / '_repetidos').exists()


async def test_canal_borrado_se_crea_de_nuevo(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'), ('Sousou no Frieren - 02.mp4', 'mp4'))
    viejo = s.registro.serie(FRIEREN)['canal_id']
    s.tg.borrar_canal(s.canales._peer(s.registro.serie(FRIEREN)))
    await poner(s, videos, ('[Subs ES] Sousou no Frieren - 01.mkv', 'mkv_subs'),
                ('[Subs ES] Sousou no Frieren - 02.mkv', 'mkv_subs'))
    assert s.registro.serie(FRIEREN)['canal_id'] != viejo
    assert canal(s, FRIEREN) == ['FICHA', 'ÍNDICE', 'Temporada 1',
                                 'Temporada 1 · Episodio 01', 'Temporada 1 · Episodio 02']
    assert not (s.ajustes.subidos / '_repetidos').exists()


async def test_reemplazar_por_otra_version(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'), ('Sousou no Frieren - 02.mp4', 'mp4'))
    clave = f'T:{FRIEREN}:1'
    viejo = s.registro.mensajes_episodio(FRIEREN, clave, 1)
    s.ajustes.repetidos = 'reemplazar'
    await poner(s, videos, ('[Subs ES] Sousou no Frieren - 01.mkv', 'mkv_subs'))
    assert canal(s, FRIEREN)[3:] == ['Temporada 1 · Episodio 01', 'Temporada 1 · Episodio 02']  # sigue en orden
    nuevo = s.registro.mensajes_episodio(FRIEREN, clave, 1)
    chat = s.tg.chats[s.registro.serie(FRIEREN)['canal_id']]
    assert len(nuevo) == 1 and nuevo != viejo and chat[nuevo[0]].tipo == 'archivo'
    assert all(i not in chat for i in viejo)  # la versión vieja se borró
    assert (s.ajustes.subidos / 'Sousou no Frieren' / 'Temporada 1' / '[Subs ES] Sousou no Frieren - 01.mkv').exists()


async def test_por_defecto_los_repetidos_no_se_suben(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'))
    viejo = s.registro.mensajes_episodio(FRIEREN, f'T:{FRIEREN}:1', 1)
    await poner(s, videos, ('[Subs ES] Sousou no Frieren - 01.mkv', 'mkv_subs'))
    assert s.registro.mensajes_episodio(FRIEREN, f'T:{FRIEREN}:1', 1) == viejo
    assert (s.ajustes.subidos / '_repetidos' / '[Subs ES] Sousou no Frieren - 01.mkv').exists()


async def test_corte_a_mitad_de_reordenar_no_deja_duplicados(servicio, videos):
    s = servicio
    s.ajustes.ordenar_automatico = False
    await poner(s, videos, ('Sousou no Frieren - 03.mp4', 'mp4'), ('Sousou no Frieren - 04.mp4', 'mp4'))
    await poner(s, videos, ('Sousou no Frieren - 02.mp4', 'mp4'))
    antes = canal(s, FRIEREN)
    s.tg.falla_reenvio_en = s.tg.reenvios + 2
    with pytest.raises(ConnectionError):
        await s.reordenar(FRIEREN)
    assert canal(s, FRIEREN) == antes
    s.tg.falla_reenvio_en = None
    assert await s.reordenar(FRIEREN) == 3
    assert canal(s, FRIEREN)[3:] == ['Temporada 1 · Episodio 02', 'Temporada 1 · Episodio 03', 'Temporada 1 · Episodio 04']


async def test_archivo_grande_se_sube_en_partes(servicio, videos):
    s = servicio
    s.ajustes.limite_mb = 1
    await poner(s, videos, ('Sousou no Frieren - 09.mp4', 'mp4'))
    partes = [l for l in canal(s, FRIEREN) if 'Episodio 09' in l]
    assert len(partes) > 1 and partes[0].endswith(f'Parte 1 de {len(partes)}')
    assert f'09 (1/{len(partes)})' in tl_html.parse(indice(s, FRIEREN))[0]


async def test_fichas_viejas_pasan_al_espanol(servicio, videos):
    s = servicio
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'))
    s.registro.guardar_ficha(FRIEREN, s.registro.serie(FRIEREN)['ficha_msg'], 'en')
    peer = s.canales._peer(s.registro.serie(FRIEREN))
    s.tg.chats[peer.channel_id][s.registro.serie(FRIEREN)['ficha_msg']].text = 'ficha vieja'
    await s._actualizar_fichas()
    assert '[es]' in s.tg.chats[peer.channel_id][s.registro.serie(FRIEREN)['ficha_msg']].text
    assert s.registro.serie(FRIEREN)['ficha_idioma'] == 'es'


async def test_subida_en_paralelo_es_mas_rapida(tmp_path):
    archivo = tmp_path / 'grande.bin'
    archivo.write_bytes(b'\0' * 12 * 1024 * 1024)
    cliente = ClienteDemo(mb_por_segundo=60, latencia=0.05)
    tiempos = {}
    for conexiones in (1, 8):
        inicio = time.monotonic()
        await subir_archivo(cliente, archivo, conexiones)
        tiempos[conexiones] = time.monotonic() - inicio
    assert tiempos[8] < tiempos[1] * 0.6


async def test_error_en_un_archivo_no_frena_a_los_demas(servicio, videos, monkeypatch):
    s = servicio
    original = s.canales.subir

    async def subir_con_falla(peer, res, *args, **kwargs):
        if res.episodio == 1:
            raise RuntimeError('Telegram no responde')
        return await original(peer, res, *args, **kwargs)

    monkeypatch.setattr(s.canales, 'subir', subir_con_falla)
    await poner(s, videos, ('Sousou no Frieren - 01.mp4', 'mp4'), ('Sousou no Frieren - 02.mp4', 'mp4'))
    estados = {i.ruta.name: (i.estado, i.error) for i in s.items.values()}
    assert estados == {'Sousou no Frieren - 01.mp4': ('error', 'Telegram no responde')}
    assert canal(s, FRIEREN)[-1] == 'Temporada 1 · Episodio 02'
    assert (s.ajustes.entrada / 'Sousou no Frieren - 01.mp4').exists()  # se queda para reintentar
