import json
import os
import sqlite3

import pytest
from aiohttp.test_utils import TestClient, TestServer
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession, StringSession

from animetg.ajustes import Ajustes
from animetg.demo import ClienteDemo, CredencialesMemoria
from animetg.migracion import migrar
from animetg.registro import Registro
from animetg.rutas import Rutas
from animetg.servicio import Servicio
from animetg.web.servidor import crear_app
from test_basicos import _V1


@pytest.fixture
async def cliente_web(tmp_path, sin_red):
    s = Servicio(Rutas(tmp_path / 'data'), CredencialesMemoria(), lambda *a: ClienteDemo(*a))
    s.ajustes.actualizar({'carpeta_subir': str(tmp_path / 'Subir')})
    await s.iniciar(vigilar=False)
    async with TestClient(TestServer(crear_app(s, 'secreto'))) as cliente:
        yield cliente
    await s.detener()


async def test_la_api_exige_el_token(cliente_web):
    assert (await cliente_web.get('/api/estado')).status == 403
    assert (await cliente_web.get('/api/estado?t=otro')).status == 403
    r = await cliente_web.get('/api/estado', headers={'X-Token': 'secreto'})
    datos = await r.json()
    assert r.status == 200 and datos['estado']['conexion'] == 'conectado'
    assert (await cliente_web.get('/')).status == 200  # la página en sí no expone datos


async def test_ajustes_invalidos_devuelven_errores(cliente_web):
    r = await cliente_web.put('/api/ajustes', json={'conexiones': 99, 'idioma_titulo': 'english'},
                              headers={'X-Token': 'secreto'})
    datos = await r.json()
    assert datos['errores'] and datos['ajustes']['idioma_titulo'] == 'english' and datos['ajustes']['conexiones'] == 8


async def test_api_hash_con_formato_malo(cliente_web):
    r = await cliente_web.post('/api/sesion/api', json={'api_id': '12', 'api_hash': 'corto'},
                               headers={'X-Token': 'secreto'})
    assert r.status == 400 and 'api_hash' in (await r.json())['error']


def test_migra_la_instalacion_de_la_version_1(tmp_path):
    vieja = tmp_path / 'v1'
    vieja.mkdir()
    (vieja / 'config.ini').write_text(
        '[telegram]\napi_id = 123456\napi_hash = 0123456789abcdef0123456789abcdef\n'
        '[carpetas]\nsubir = D:\\Anime\\Entrada\nsubidos = D:\\Anime\\Listos\n'
        '[opciones]\ncarpeta_telegram =\nidioma_titulo = english\nlimite_mb = 4000\nordenar_automatico = no\n',
        encoding='utf-8')
    (vieja / 'correcciones.ini').write_text(
        '[correcciones]\nGuardianes de la Noche = https://anilist.co/anime/101922\n', encoding='utf-8')
    db = sqlite3.connect(vieja / 'registro.db')
    db.executescript(_V1)
    db.close()
    sesion = SQLiteSession(str(vieja / 'anime'))
    sesion.set_dc(2, '149.154.167.51', 443)
    sesion.auth_key = AuthKey(os.urandom(256))
    sesion.save()
    clave_original = sesion.auth_key.key
    sesion.close()
    (vieja / 'cache' / 'portadas').mkdir(parents=True)
    (vieja / 'cache' / 'portadas' / '1.jpg').write_bytes(b'jpg')
    (vieja / 'registro.log').write_text('log viejo', encoding='utf-8')

    rutas, cred = Rutas(tmp_path / 'data'), CredencialesMemoria(None, None, None)
    hechos = migrar(rutas, cred, origen=vieja)

    assert hechos == ['registro de subidas', 'configuración y credenciales', 'correcciones', 'sesión de Telegram']
    assert (cred.api_id, cred.api_hash) == (123456, '0123456789abcdef0123456789abcdef')
    restaurada = StringSession(cred.sesion)
    assert (restaurada.dc_id, restaurada.port, restaurada.auth_key.key) == (2, 443, clave_original)
    a = Ajustes.cargar(rutas.ajustes)
    assert (a.carpeta_subir, a.carpeta_telegram, a.idioma_titulo, a.premium, a.ordenar_automatico) == \
        ('D:\\Anime\\Entrada', '', 'english', True, False)
    assert 'api_hash' not in rutas.ajustes.read_text(encoding='utf-8')
    reg = Registro(rutas.db)
    assert reg.correcciones() == {'guardianes de la noche': 101922} and reg.serie(114979)
    assert (rutas.portadas / '1.jpg').exists() and (rutas.logs / 'version-1.log').exists()
    assert sorted(p.name for p in vieja.iterdir()) == []  # no queda nada viejo (ni secretos) suelto
    assert migrar(rutas, cred, origen=vieja) == []  # una segunda vez no hace nada
