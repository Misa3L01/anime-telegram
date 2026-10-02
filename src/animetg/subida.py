"""Subida de archivos grandes enviando varias partes a la vez.

Telethon sube de a una parte de 512 KB y espera la confirmación de cada una, así que la
velocidad queda limitada por la latencia y no por la conexión. Acá se mantienen varias partes en
vuelo al mismo tiempo; Telegram las acepta en cualquier orden.
"""
import asyncio
import random
import time
from pathlib import Path
from typing import Callable

from telethon.tl import functions, types

PARTE = 512 * 1024
GRANDE = 10 * 1024 * 1024  # desde acá Telegram exige el método para archivos grandes


class Medidor:
    """Calcula velocidad (promedio móvil) y tiempo restante."""

    def __init__(self, total: int, aviso: Callable[[int, int, float, float | None], None] | None):
        self.total, self.aviso = total, aviso
        self.hecho, self.inicio = 0, time.monotonic()
        self._muestras: list[tuple[float, int]] = [(self.inicio, 0)]

    def sumar(self, bytes_: int) -> None:
        self.hecho += bytes_
        ahora = time.monotonic()
        self._muestras.append((ahora, self.hecho))
        while len(self._muestras) > 2 and ahora - self._muestras[0][0] > 8:
            self._muestras.pop(0)
        t0, b0 = self._muestras[0]
        velocidad = (self.hecho - b0) / max(ahora - t0, 0.001)
        restante = (self.total - self.hecho) / velocidad if velocidad > 0 else None
        if self.aviso:
            self.aviso(self.hecho, self.total, velocidad, restante)


async def subir_archivo(client, ruta: Path, conexiones: int = 8,
                        aviso: Callable[[int, int, float, float | None], None] | None = None):
    """Sube `ruta` y devuelve el InputFile listo para `send_file`."""
    tamano = ruta.stat().st_size
    medidor = Medidor(tamano, aviso)
    if tamano <= GRANDE or conexiones <= 1:
        def progreso(actual, _total, ultimo=[0]):
            medidor.sumar(actual - ultimo[0])
            ultimo[0] = actual
        return await client.upload_file(str(ruta), progress_callback=progreso)

    total_partes = (tamano + PARTE - 1) // PARTE
    id_archivo = random.getrandbits(63)
    cola: asyncio.Queue = asyncio.Queue(maxsize=conexiones * 2)

    async def lector():
        with open(ruta, 'rb') as f:
            for numero in range(total_partes):
                datos = await asyncio.to_thread(f.read, PARTE)
                await cola.put((numero, datos))
        for _ in range(conexiones):
            await cola.put(None)

    async def enviador():
        while (pieza := await cola.get()) is not None:
            numero, datos = pieza
            for intento in range(5):
                try:
                    if await client(functions.upload.SaveBigFilePartRequest(id_archivo, numero, total_partes, datos)):
                        break
                except (ConnectionError, asyncio.TimeoutError, OSError):
                    if intento == 4:
                        raise
                await asyncio.sleep(2 * (intento + 1))
            else:
                raise RuntimeError(f'Telegram rechazó la parte {numero} de {ruta.name}.')
            medidor.sumar(len(datos))

    tareas = [asyncio.create_task(lector())] + [asyncio.create_task(enviador()) for _ in range(conexiones)]
    try:
        hechas, _ = await asyncio.wait(tareas, return_when=asyncio.FIRST_EXCEPTION)
        for tarea in hechas:
            tarea.result()  # propaga el primer error
    finally:
        for tarea in tareas:
            tarea.cancel()
    return types.InputFileBig(id_archivo, total_partes, ruta.name)
