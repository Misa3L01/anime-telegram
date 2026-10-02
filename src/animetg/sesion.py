"""Conexión con Telegram e inicio de sesión. La sesión se guarda como texto en el
Administrador de credenciales de Windows (ver `credenciales`), nunca en un archivo."""
import logging

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from . import NOMBRE_APP, __version__
from .credenciales import Credenciales

log = logging.getLogger('animetg.sesion')


class ErrorSesion(Exception):
    """Error con un mensaje listo para mostrarle al usuario."""


def _crear_cliente(sesion: str, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(StringSession(sesion), api_id, api_hash,
                          device_model=NOMBRE_APP, app_version=__version__, system_version='Windows',
                          flood_sleep_threshold=6 * 3600)  # si Telegram pide esperar, se espera


class Conexion:
    def __init__(self, credenciales: Credenciales, fabrica=_crear_cliente):
        self.cred = credenciales
        self.fabrica = fabrica
        self.client = None
        self.usuario: dict | None = None
        self._telefono: str | None = None

    @property
    def estado(self) -> str:
        if not self.cred.tiene_api:
            return 'sin_api'
        if self.usuario:
            return 'conectado'
        return 'sin_sesion'

    async def _cliente(self):
        if self.client is None:
            self.client = self.fabrica(self.cred.sesion or '', self.cred.api_id, self.cred.api_hash)
        if not self.client.is_connected():
            await self.client.connect()
        return self.client

    async def conectar(self) -> bool:
        if not self.cred.tiene_api:
            return False
        client = await self._cliente()
        if await client.is_user_authorized():
            await self._cargar_usuario()
            return True
        return False

    async def _cargar_usuario(self) -> None:
        yo = await self.client.get_me()
        nombre = ' '.join(filter(None, [yo.first_name, yo.last_name])) or yo.username or str(yo.id)
        self.usuario = {'id': yo.id, 'nombre': nombre, 'usuario': yo.username, 'premium': bool(getattr(yo, 'premium', False))}

    async def configurar_api(self, api_id: int, api_hash: str) -> None:
        await self.desconectar()
        self.cred.guardar_api(api_id, api_hash.strip())
        self.client, self.usuario = None, None

    async def pedir_codigo(self, telefono: str) -> None:
        client = await self._cliente()
        try:
            await client.send_code_request(telefono)
        except errors.PhoneNumberInvalidError:
            raise ErrorSesion('El número no es válido. Escríbelo con código de país, por ejemplo +54 9 11...')
        except errors.ApiIdInvalidError:
            raise ErrorSesion('api_id o api_hash incorrectos. Revísalos en my.telegram.org.')
        except errors.FloodWaitError as e:
            raise ErrorSesion(f'Telegram pide esperar {e.seconds // 60 + 1} minutos antes de pedir otro código.')
        self._telefono = telefono

    async def confirmar_codigo(self, codigo: str) -> str:
        """Devuelve 'listo' o 'falta_clave' (verificación en dos pasos)."""
        try:
            await self.client.sign_in(self._telefono, codigo.strip())
        except errors.SessionPasswordNeededError:
            return 'falta_clave'
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
            raise ErrorSesion('El código no es correcto o ya venció. Pide uno nuevo.')
        await self._guardar()
        return 'listo'

    async def confirmar_clave(self, clave: str) -> None:
        try:
            await self.client.sign_in(password=clave)
        except errors.PasswordHashInvalidError:
            raise ErrorSesion('La contraseña de verificación en dos pasos no es correcta.')
        await self._guardar()

    async def _guardar(self) -> None:
        self.cred.sesion = self.client.session.save()
        await self._cargar_usuario()
        log.info('Sesión iniciada como %s.', self.usuario['nombre'])

    async def cerrar_sesion(self) -> None:
        if self.client and self.usuario:
            try:
                await self.client.log_out()
            except Exception:
                log.warning('No se pudo avisar a Telegram del cierre de sesión; se borra igual de este equipo.')
        self.cred.sesion = None
        self.client, self.usuario = None, None

    async def desconectar(self) -> None:
        if self.client is not None and self.client.is_connected():
            await self.client.disconnect()
