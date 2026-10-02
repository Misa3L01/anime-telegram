"""Telegram simulado: para probar la interfaz sin tocar una cuenta real y para las pruebas automáticas.

Imita lo que la app usa de Telethon. Las subidas tardan de verdad (latencia por pedido y ancho de
banda compartido), así que la subida en paralelo se nota igual que con Telegram.
"""
import asyncio
import random
from types import SimpleNamespace

from telethon import errors
from telethon.tl import functions, types


class CredencialesMemoria:
    """Igual que `Credenciales`, pero sin tocar el Administrador de credenciales de Windows."""

    def __init__(self, api_id: int | None = 1, api_hash: str | None = 'demo', sesion: str | None = 'demo'):
        self.api_id, self.api_hash, self.sesion = api_id, api_hash, sesion

    def guardar_api(self, api_id, api_hash):
        self.api_id, self.api_hash = api_id, api_hash

    @property
    def tiene_api(self):
        return bool(self.api_id and self.api_hash)

    def borrar_todo(self):
        self.api_id = self.api_hash = self.sesion = None


class ClienteDemo:
    def __init__(self, sesion='', api_id=None, api_hash=None, *, mb_por_segundo=12.0, latencia=0.12):
        self.mb_por_segundo, self.latencia = mb_por_segundo, latencia
        self.chats: dict[int, dict[int, SimpleNamespace]] = {}
        self._contador: dict[int, int] = {}
        self.filtros: list = [types.DialogFilterDefault()]
        self.fijados: list[tuple[int, int]] = []
        self.falla_reenvio_en: int | None = None  # para simular cortes en las pruebas
        self.reenvios = 0
        self.borrados: set[int] = set()  # canales que el usuario eliminó en Telegram
        self._conectado = False
        self._autorizado = bool(sesion)
        self._tubo = asyncio.Lock()
        self.session = SimpleNamespace(save=lambda: 'demo')

    # --- conexión y sesión ---
    def is_connected(self):
        return self._conectado

    async def connect(self):
        self._conectado = True

    async def disconnect(self):
        self._conectado = False

    async def is_user_authorized(self):
        return self._autorizado

    async def get_me(self):
        return SimpleNamespace(id=1, first_name='Cuenta', last_name='Demo', username='demo', premium=False)

    async def send_code_request(self, telefono):
        await asyncio.sleep(0.2)

    async def sign_in(self, telefono=None, codigo=None, password=None):
        self._autorizado = True

    async def log_out(self):
        self._autorizado = False

    # --- mensajes ---
    def _chat(self, peer) -> int:
        chat = getattr(peer, 'channel_id', 0)
        if chat in self.borrados:
            raise errors.ChannelPrivateError(request=None)
        return chat

    def borrar_canal(self, peer) -> None:
        """Como eliminar el canal desde la app de Telegram."""
        chat = self._chat(peer)
        self.chats.pop(chat, None)
        self.borrados.add(chat)

    def _nuevo(self, peer, texto='', **extra):
        chat = self._chat(peer)
        self._contador[chat] = self._contador.get(chat, 0) + 1
        m = SimpleNamespace(id=self._contador[chat], text=texto, action=None, tipo='texto', archivo=None)
        m.__dict__.update(extra)
        self.chats.setdefault(chat, {})[m.id] = m
        return m

    def mensajes(self, peer) -> list[SimpleNamespace]:
        return sorted(self.chats.get(self._chat(peer), {}).values(), key=lambda m: m.id)

    async def _transferir(self, bytes_: int):
        async with self._tubo:  # ancho de banda compartido entre pedidos simultáneos
            await asyncio.sleep(bytes_ / (self.mb_por_segundo * 1024 * 1024))
        await asyncio.sleep(self.latencia)  # ida y vuelta de cada pedido

    async def __call__(self, pedido):
        if isinstance(pedido, functions.channels.CreateChannelRequest):
            canal = SimpleNamespace(id=random.randint(10**9, 2 * 10**9), access_hash=random.getrandbits(62))
            peer = types.InputPeerChannel(canal.id, canal.access_hash)
            self._nuevo(peer, 'Canal creado', action='creado')
            return SimpleNamespace(chats=[canal])
        if isinstance(pedido, functions.channels.EditPhotoRequest):
            self._nuevo(types.InputPeerChannel(pedido.channel.channel_id, 0), 'Foto cambiada', action='foto')
            return None
        if isinstance(pedido, functions.messages.GetDialogFiltersRequest):
            return SimpleNamespace(filters=list(self.filtros))
        if isinstance(pedido, functions.messages.UpdateDialogFilterRequest):
            pedido._bytes()  # comprueba que el objeto se pueda mandar a Telegram
            self.filtros = [f for f in self.filtros if getattr(f, 'id', None) != pedido.id] + [pedido.filter]
            return True
        if isinstance(pedido, functions.upload.SaveBigFilePartRequest):
            await self._transferir(len(pedido.bytes))
            return True
        return True

    async def upload_file(self, archivo, progress_callback=None, **_):
        from pathlib import Path
        tamano = Path(archivo).stat().st_size
        hecho = 0
        while hecho < tamano:  # Telethon sube de a una parte y espera cada confirmación
            pieza = min(512 * 1024, tamano - hecho)
            await self._transferir(pieza)
            hecho += pieza
            if progress_callback:
                progress_callback(hecho, tamano)
        return types.InputFile(id=random.getrandbits(62), parts=1, name=Path(archivo).name, md5_checksum='')

    async def send_file(self, peer, file, caption='', attributes=None, force_document=False, thumb=None,
                        supports_streaming=False, parse_mode=None, **_):
        tipo = 'video' if attributes else 'archivo' if force_document else 'foto'
        nombre = getattr(file, 'name', str(file))
        return self._nuevo(peer, caption or '', tipo=tipo, archivo=nombre, miniatura=thumb)

    async def send_message(self, peer, texto, **_):
        return self._nuevo(peer, texto)

    async def edit_message(self, peer, msg_id, texto, **_):
        self.chats[self._chat(peer)][msg_id].text = texto

    async def pin_message(self, peer, msg, notify=False):
        self.fijados.append((self._chat(peer), msg.id))
        self._nuevo(peer, 'Mensaje fijado', action='fijado')

    async def iter_messages(self, peer, limit=10, min_id=0):
        for m in sorted((m for m in self.chats.get(self._chat(peer), {}).values() if m.id > min_id),
                        key=lambda m: -m.id)[:limit]:
            yield m

    async def delete_messages(self, peer, ids):
        for i in ids:
            self.chats.get(self._chat(peer), {}).pop(i, None)

    async def get_messages(self, peer, limit=None, ids=None):
        mensajes = self.chats.get(self._chat(peer), {})
        if ids is not None:
            return [mensajes.get(i) for i in ids]
        return sorted(mensajes.values(), key=lambda m: -m.id)[:limit]

    async def forward_messages(self, peer, ids, from_peer=None, drop_author=None, silent=None):
        assert drop_author and ids == sorted(ids), 'cada tramo reenviado debe ir en orden creciente'
        copias = []
        for i in ids:
            self.reenvios += 1
            if self.falla_reenvio_en is not None and self.reenvios == self.falla_reenvio_en:
                raise ConnectionError('corte simulado')
            original = self.chats[self._chat(peer)][i]
            extra = {k: v for k, v in original.__dict__.items() if k not in ('id', 'text')}
            copias.append(self._nuevo(peer, original.text, **extra))
        return copias
