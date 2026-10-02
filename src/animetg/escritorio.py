"""Aplicación de escritorio: una ventana nativa (WebView2) sobre la interfaz local.

El servicio y el servidor corren en su propio hilo con un bucle asyncio; la ventana ocupa el hilo
principal, como exige Windows. Si la app ya está abierta, se trae al frente esa ventana.
"""
import argparse
import asyncio
import ctypes
import json
import logging
import os
import secrets
import tempfile
import threading
import urllib.request
from pathlib import Path

from . import NOMBRE_APP, bitacora, migracion
from .credenciales import Credenciales
from .rutas import ICONO, Rutas, por_defecto
from .servicio import Servicio
from .web import servidor

log = logging.getLogger('animetg')


class Motor(threading.Thread):
    """Servicio + servidor web en su propio bucle de eventos."""

    def __init__(self, rutas: Rutas, demo: bool = False, puerto: int = 0):
        super().__init__(name='motor', daemon=True)
        self.rutas, self.demo, self.puerto = rutas, demo, puerto
        self.token = secrets.token_urlsafe(24)
        self.listo = threading.Event()
        self.error: Exception | None = None
        self.servicio: Servicio | None = None
        self.al_mostrar = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._parar: asyncio.Event | None = None

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.puerto}/?t={self.token}'

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._principal())
        except Exception as e:
            self.error = e
            log.exception('El motor de la aplicación se detuvo.')
        finally:
            self.listo.set()
            self._loop.close()

    async def _principal(self) -> None:
        self._parar = asyncio.Event()
        if self.demo:
            from .demo import ClienteDemo, CredencialesMemoria
            velocidad = float(os.environ.get('ANIMETG_DEMO_MBS', '12'))
            self.servicio = Servicio(self.rutas, CredencialesMemoria(),
                                     lambda *a: ClienteDemo(*a, mb_por_segundo=velocidad))
            # La demostración nunca toca las carpetas reales.
            self.servicio.ajustes.actualizar({'carpeta_subir': str(self.rutas.datos / 'Subir'),
                                              'carpeta_subidos': str(self.rutas.datos / 'Subidos')})
        else:
            self.servicio = Servicio(self.rutas)
        await self.servicio.iniciar()
        app = servidor.crear_app(self.servicio, self.token, al_mostrar=lambda: self.al_mostrar and self.al_mostrar())
        runner, self.puerto = await servidor.iniciar(app, self.puerto)
        self.listo.set()
        await self._parar.wait()
        await runner.cleanup()
        await self.servicio.detener()

    def detener(self, espera: float = 20) -> None:
        if self._loop and self._parar and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._parar.set)
            self.join(espera)


def _avisar_otra_instancia(rutas: Rutas) -> bool:
    """Si ya hay una ventana abierta, la trae al frente y devuelve True."""
    try:
        datos = json.loads(rutas.instancia.read_text(encoding='utf-8'))
        pedido = urllib.request.Request(f'http://127.0.0.1:{datos["puerto"]}/api/mostrar', data=b'{}', method='POST',
                                        headers={'X-Token': datos['token'], 'Content-Type': 'application/json'})
        urllib.request.urlopen(pedido, timeout=2)
        return True
    except Exception:
        return False


def _mensaje_error(texto: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, texto, NOMBRE_APP, 0x10)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog='anime-telegram')
    p.add_argument('--minimizado', action='store_true', help='abrir minimizada (inicio con Windows)')
    p.add_argument('--demo', action='store_true', help='modo demostración, con un Telegram simulado')
    args = p.parse_args(argv)

    rutas = Rutas(Path(tempfile.gettempdir()) / 'anime-telegram-demo') if args.demo else por_defecto()
    if args.demo:
        os.environ.setdefault('ANIMETG_DATOS', str(rutas.datos))
    rutas.crear()
    bitacora.configurar(rutas)
    if _avisar_otra_instancia(rutas):
        return
    # Ícono y botón propios en la barra de tareas, separados de Python.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('AnimeTelegram.App')

    if not args.demo:
        try:
            migracion.migrar(rutas, Credenciales())
        except Exception as e:
            log.exception('No se pudieron migrar los datos de la versión anterior.')
            _mensaje_error(f'No se pudieron migrar los datos de la versión anterior:\n{e}\n\n'
                           'Tus archivos viejos no se tocaron. Revisa el registro en data\\logs.')
            return

    motor = Motor(rutas, demo=args.demo)
    motor.start()
    motor.listo.wait(90)
    if motor.error or not motor.puerto:
        _mensaje_error(f'La aplicación no pudo arrancar:\n{motor.error or "tiempo de espera agotado"}')
        return
    rutas.instancia.write_text(json.dumps({'pid': os.getpid(), 'puerto': motor.puerto, 'token': motor.token}),
                               encoding='utf-8')

    import webview
    ventana = webview.create_window(NOMBRE_APP, motor.url, width=1320, height=860, min_size=(1040, 680),
                                    background_color='#0d0f14', minimized=args.minimizado, text_select=True)

    def mostrar():
        ventana.restore()
        ventana.show()

    def al_cerrar():
        if motor.servicio and motor.servicio.ocupado:
            return ventana.create_confirmation_dialog(
                'Hay una subida en curso',
                'Si cierras ahora se cancela, y el episodio se vuelve a subir la próxima vez que abras la aplicación.')
        return True

    motor.al_mostrar = mostrar
    ventana.events.closing += al_cerrar
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(rutas.webview), icon=str(ICONO))
    finally:
        motor.detener()
        rutas.instancia.unlink(missing_ok=True)
