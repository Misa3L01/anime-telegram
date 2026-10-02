"""Servidor local de la interfaz.

Solo escucha en 127.0.0.1 y cada pedido a la API tiene que traer el token de la sesión, así que
ninguna otra página abierta en el navegador puede usarlo.
"""
import asyncio
import json
import logging
import re

from aiohttp import WSMsgType, web

from .. import accesos
from ..rutas import ESTATICOS
from ..sesion import ErrorSesion

log = logging.getLogger('animetg.web')


def _linea_log(linea: str) -> dict | None:
    m = re.match(r'(\S+ \S+)\s+(\w+)\s+[\w.]+: (.*)', linea)
    return {'fecha': m.group(1), 'nivel': m.group(2), 'mensaje': m.group(3)} if m else None


def crear_app(servicio, token: str, al_mostrar=None) -> web.Application:
    @web.middleware
    async def seguridad(request: web.Request, handler):
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            raise web.HTTPForbidden(text='Solo se puede usar desde este equipo.')
        if request.path.startswith('/api/') or request.path == '/ws':
            if token not in (request.headers.get('X-Token'), request.query.get('t')):
                raise web.HTTPForbidden(text='Token inválido.')
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except ErrorSesion as e:
            return web.json_response({'error': str(e)}, status=400)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return web.json_response({'error': f'Pedido inválido: {e}'}, status=400)
        except Exception as e:
            log.exception('Error atendiendo %s', request.path)
            return web.json_response({'error': str(e) or e.__class__.__name__}, status=500)

    rutas = web.RouteTableDef()
    s = servicio

    async def cuerpo(request) -> dict:
        return await request.json() if request.can_read_body else {}

    def ok(**datos):
        return web.json_response({'ok': True, **datos})

    @rutas.get('/')
    async def inicio(_):
        return web.FileResponse(ESTATICOS / 'index.html', headers={'Cache-Control': 'no-store'})

    # --- estado ---
    @rutas.get('/api/ping')
    async def ping(_):
        return ok()

    @rutas.get('/api/estado')
    async def estado(_):
        return web.json_response({'estado': s.estado(), 'cola': s.cola(), 'recientes': s.recientes()})

    @rutas.get('/api/recientes')
    async def recientes(_):
        return web.json_response(s.recientes())

    @rutas.get('/api/series')
    async def series(_):
        return web.json_response(s.series())

    @rutas.get('/api/series/{raiz}')
    async def serie(request):
        datos = s.serie(int(request.match_info['raiz']))
        if datos is None:
            raise web.HTTPNotFound()
        return web.json_response(datos)

    @rutas.get('/api/portada/{media}')
    async def portada(request):
        try:
            ruta = await asyncio.to_thread(s.portada, int(request.match_info['media']))
        except Exception:
            ruta = None
        if not ruta:
            raise web.HTTPNotFound()
        return web.FileResponse(ruta, headers={'Cache-Control': 'max-age=604800'})

    @rutas.get('/api/registro')
    async def registro(request):
        cantidad = min(int(request.query.get('n', 300)), 2000)
        archivo = s.rutas.logs / 'animetg.log'
        lineas = archivo.read_text(encoding='utf-8', errors='replace').splitlines()[-cantidad:] \
            if archivo.exists() else []
        return web.json_response([d for d in map(_linea_log, lineas) if d])

    # --- cola ---
    @rutas.post('/api/subir-ahora')
    async def subir_ahora(_):
        s.subir_ahora()
        return ok()

    @rutas.post('/api/pausar')
    async def pausar(request):
        s.pausar(bool((await cuerpo(request)).get('pausado', True)))
        return ok()

    @rutas.post('/api/cancelar')
    async def cancelar(_):
        s.cancelar_actual()
        return ok()

    @rutas.post('/api/items/{id}/{accion}')
    async def accion_item(request):
        item_id, accion = request.match_info['id'], request.match_info['accion']
        if accion == 'reintentar':
            s.reintentar(item_id)
        elif accion == 'quitar':
            s.quitar(item_id)
        elif accion == 'corregir':
            datos = await cuerpo(request)
            await s.corregir(item_id, int(datos['media']), bool(datos.get('recordar', True)))
        else:
            raise web.HTTPNotFound()
        return ok()

    @rutas.get('/api/anilist')
    async def anilist(request):
        texto = request.query.get('q', '').strip()
        return web.json_response(await s.buscar_anilist(texto) if texto else [])

    # --- series ---
    @rutas.post('/api/series/{raiz}/reordenar')
    async def reordenar(request):
        return ok(movidos=await s.reordenar(int(request.match_info['raiz'])))

    @rutas.post('/api/series/{raiz}/ficha')
    async def ficha(request):
        await s.actualizar_ficha(int(request.match_info['raiz']))
        return ok()

    @rutas.post('/api/abrir')
    async def abrir(request):
        datos = await cuerpo(request)
        que, valor = datos['que'], datos.get('valor')
        if que == 'url':
            if not str(valor).startswith('https://'):
                raise ValueError('solo se abren enlaces https')
            import webbrowser
            webbrowser.open(valor)
        else:
            s.abrir(que, valor)
        return ok()

    # --- ajustes ---
    @rutas.get('/api/ajustes')
    async def ver_ajustes(_):
        return web.json_response({'ajustes': s.ajustes.como_dict(), 'accesos': accesos.estado(),
                                  'datos': str(s.rutas.datos)})

    @rutas.put('/api/ajustes')
    async def guardar_ajustes(request):
        errores = await s.guardar_ajustes(await cuerpo(request))
        return web.json_response({'ok': not errores, 'errores': errores, 'ajustes': s.ajustes.como_dict()})

    @rutas.post('/api/accesos')
    async def cambiar_accesos(request):
        datos = await cuerpo(request)
        await asyncio.to_thread(accesos.aplicar, **{k: bool(v) for k, v in datos.items()
                                                    if k in ('escritorio', 'inicio', 'arranque')})
        return web.json_response(accesos.estado())

    @rutas.post('/api/velocidad')
    async def velocidad(_):
        return web.json_response(await s.prueba_velocidad())

    # --- sesión de Telegram ---
    @rutas.post('/api/sesion/api')
    async def sesion_api(request):
        datos = await cuerpo(request)
        api_id, api_hash = str(datos['api_id']).strip(), str(datos['api_hash']).strip()
        if not api_id.isdigit() or not re.fullmatch(r'[0-9a-f]{32}', api_hash):
            raise ErrorSesion('El api_id son solo números y el api_hash tiene 32 letras y números.')
        await s.configurar_api(int(api_id), api_hash)
        return ok()

    @rutas.post('/api/sesion/telefono')
    async def sesion_telefono(request):
        await s.pedir_codigo(str((await cuerpo(request))['telefono']).replace(' ', ''))
        return ok()

    @rutas.post('/api/sesion/codigo')
    async def sesion_codigo(request):
        return ok(resultado=await s.confirmar_codigo(str((await cuerpo(request))['codigo'])))

    @rutas.post('/api/sesion/clave')
    async def sesion_clave(request):
        await s.confirmar_clave(str((await cuerpo(request))['clave']))
        return ok()

    @rutas.post('/api/sesion/cerrar')
    async def sesion_cerrar(_):
        await s.cerrar_sesion()
        return ok()

    # --- ventana ---
    @rutas.post('/api/mostrar')
    async def mostrar(_):
        if al_mostrar:
            al_mostrar()
        return ok()

    @rutas.get('/ws')
    async def eventos(request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        cola = s.bus.suscribir()

        async def enviar():
            while True:
                await ws.send_json(await cola.get())

        envio = asyncio.create_task(enviar())
        try:
            async for mensaje in ws:  # solo para detectar el cierre
                if mensaje.type == WSMsgType.ERROR:
                    break
        finally:
            envio.cancel()
            s.bus.desuscribir(cola)
        return ws

    app = web.Application(middlewares=[seguridad])
    app.add_routes(rutas)
    app.router.add_static('/static/', ESTATICOS, append_version=True)
    return app


async def iniciar(app: web.Application, puerto: int = 0) -> tuple[web.AppRunner, int]:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    sitio = web.TCPSite(runner, '127.0.0.1', puerto)
    await sitio.start()
    return runner, sitio._server.sockets[0].getsockname()[1]
