"""Bus de eventos para la interfaz: el servicio publica, cada ventana conectada recibe."""
import asyncio
import threading


class Bus:
    def __init__(self):
        self._suscriptores: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._hilo: int | None = None

    def vincular(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop, self._hilo = loop, threading.get_ident()

    def suscribir(self) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._suscriptores.add(cola)
        return cola

    def desuscribir(self, cola: asyncio.Queue) -> None:
        self._suscriptores.discard(cola)

    def publicar(self, tipo: str, datos=None) -> None:
        """Se puede llamar desde cualquier hilo."""
        evento = {'tipo': tipo, 'datos': datos}
        if self._loop is None or self._loop.is_closed():
            return
        if threading.get_ident() == self._hilo:
            self._entregar(evento)
        else:
            self._loop.call_soon_threadsafe(self._entregar, evento)

    def _entregar(self, evento: dict) -> None:
        for cola in list(self._suscriptores):
            try:
                cola.put_nowait(evento)
            except asyncio.QueueFull:
                pass  # una ventana trabada no frena al resto
