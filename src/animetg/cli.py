"""Línea de comandos. Sin argumentos abre la aplicación de escritorio."""
import argparse
import asyncio
import json
import sys
import urllib.request

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table

from . import NOMBRE_APP, __version__, accesos, bitacora, migracion
from .credenciales import Credenciales
from .rutas import Rutas, por_defecto
from .servicio import Servicio

consola = Console(highlight=False)


def _app_abierta(rutas: Rutas) -> bool:
    try:
        datos = json.loads(rutas.instancia.read_text(encoding='utf-8'))
        pedido = urllib.request.Request(f'http://127.0.0.1:{datos["puerto"]}/api/ping',
                                        headers={'X-Token': datos['token']})
        urllib.request.urlopen(pedido, timeout=2)
        return True
    except Exception:
        return False


def _tamano(b: int) -> str:
    return f'{b / 1024 ** 3:.2f} GB' if b >= 1024 ** 3 else f'{b / 1024 ** 2:.0f} MB'


def estado(servicio: Servicio) -> None:
    series = servicio.series()
    if not series:
        consola.print('Todavía no hay canales.')
        return
    tabla = Table(title=f'{NOMBRE_APP} · {len(series)} canales', title_justify='left')
    for columna, alineacion in (('Serie', 'left'), ('Episodios', 'right'), ('Secciones', 'right'),
                                ('Tamaño', 'right'), ('Última subida', 'left')):
        tabla.add_column(columna, justify=alineacion)
    for s in series:
        tabla.add_row(s['titulo'], str(s['episodios']), str(s['secciones']), _tamano(s['tamano']),
                      (s['ultima'] or '').replace('T', ' '))
    consola.print(tabla)


async def simular(servicio: Servicio) -> None:
    with consola.status('Revisando la carpeta…'):
        await servicio.revisar_carpeta()
    cola = servicio.cola()
    if not cola:
        consola.print(f'No hay videos en {servicio.ajustes.entrada}')
        return
    tabla = Table(title=f'Qué se haría con {len(cola)} archivo(s)', title_justify='left')
    for columna in ('Archivo', 'Canal', 'Dónde', 'Cómo'):
        tabla.add_column(columna, overflow='fold')
    for i in cola:
        if i['estado'] == 'pendiente':
            tabla.add_row(i['archivo'], '[yellow]sin reconocer[/]', i['error'], '')
        elif i['estado'] == 'repetido':
            tabla.add_row(i['archivo'], i['serie'], i['ubicacion'], '[magenta]ya subido[/]')
        else:
            tabla.add_row(i['archivo'], i.get('serie', ''), i.get('ubicacion', ''), i.get('motivo', i['error'] or ''))
    consola.print(tabla)


async def subir(servicio: Servicio) -> int:
    await servicio.iniciar(vigilar=False)
    try:
        if servicio.conexion.estado != 'conectado':
            consola.print('[red]No hay sesión de Telegram.[/] Abre la aplicación y conecta tu cuenta.')
            return 1
        await servicio.revisar_carpeta()
        cola = servicio.bus.suscribir()
        progreso = Progress(TextColumn('{task.description}'), BarColumn(), TextColumn('{task.percentage:>3.0f}%'),
                            TransferSpeedColumn(), TimeRemainingColumn(), console=consola)
        tareas: dict[str, int] = {}

        async def mostrar():
            while True:
                evento = await cola.get()
                if evento['tipo'] != 'item' or evento['datos']['estado'] != 'subiendo':
                    continue
                i = evento['datos']
                if i['id'] not in tareas:
                    tareas[i['id']] = progreso.add_task(f'{i["serie"]} · {i["ubicacion"]}', total=i['tamano'])
                progreso.update(tareas[i['id']], completed=i['progreso'] * i['tamano'])

        with progreso:
            vista = asyncio.create_task(mostrar())
            try:
                await servicio.procesar_cola()
            finally:
                vista.cancel()
        pendientes = [i for i in servicio.cola() if i['estado'] in ('pendiente', 'error')]
        for i in pendientes:
            consola.print(f'[yellow]Sin subir:[/] {i["archivo"]} — {i["error"]}')
        return 1 if pendientes else 0
    finally:
        await servicio.detener()


async def reordenar(servicio: Servicio) -> None:
    await servicio.iniciar(vigilar=False)
    try:
        for s in servicio.series():
            movidos = await servicio.reordenar(s['raiz'])
            consola.print(f'{s["titulo"]}: ' + (f'se movieron {movidos} mensajes' if movidos else 'ya estaba en orden'))
    finally:
        await servicio.detener()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog='animetg', description=f'{NOMBRE_APP} {__version__}: respaldo de anime en '
                                                            'canales privados de Telegram.')
    p.add_argument('--minimizado', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--demo', action='store_true', help='abre la aplicación con un Telegram simulado')
    sub = p.add_subparsers(dest='comando', metavar='comando')
    sub.add_parser('abrir', help='abre la aplicación (lo mismo que sin comando)')
    sub.add_parser('estado', help='resumen de los canales respaldados')
    sub.add_parser('simular', help='qué se haría con lo que hay en la carpeta, sin subir nada')
    sub.add_parser('subir', help='sube todo lo que haya en la carpeta y termina, sin ventana')
    sub.add_parser('reordenar', help='ordena todos los canales')
    acc = sub.add_parser('accesos', help='crea los accesos directos en el escritorio y el menú Inicio')
    acc.add_argument('--quitar', action='store_true', help='los quita en vez de crearlos')
    srv = sub.add_parser('servidor', help='solo la interfaz web, sin ventana (desarrollo)')
    srv.add_argument('--puerto', type=int, default=8765)
    srv.add_argument('--demo', action='store_true')
    args = p.parse_args(argv)

    if args.comando in (None, 'abrir'):
        from .escritorio import main as abrir
        abrir((['--minimizado'] if args.minimizado else []) + (['--demo'] if args.demo else []))
        return
    if args.comando == 'accesos':
        accesos.aplicar(escritorio=not args.quitar, inicio=not args.quitar)
        consola.print('Accesos directos ' + ('quitados.' if args.quitar else 'creados en el escritorio y el menú Inicio.'))
        return
    if args.comando == 'servidor':
        _servidor(args.puerto, args.demo)
        return

    rutas = por_defecto()
    bitacora.configurar(rutas, consola=args.comando in ('subir', 'reordenar'))
    if args.comando in ('subir', 'reordenar') and _app_abierta(rutas):
        consola.print('[yellow]La aplicación está abierta y ya se encarga de esto.[/] Ciérrala para usar este comando.')
        sys.exit(1)
    migracion.migrar(rutas, Credenciales())
    servicio = Servicio(rutas)
    if args.comando == 'estado':
        estado(servicio)
        servicio.registro.cerrar()
    elif args.comando == 'simular':
        asyncio.run(simular(servicio))
        servicio.registro.cerrar()
    elif args.comando == 'subir':
        sys.exit(asyncio.run(subir(servicio)))
    elif args.comando == 'reordenar':
        asyncio.run(reordenar(servicio))


def _servidor(puerto: int, demo: bool) -> None:
    import tempfile
    from pathlib import Path
    from .escritorio import Motor
    rutas = Rutas(Path(tempfile.gettempdir()) / 'anime-telegram-demo') if demo else por_defecto()
    rutas.crear()
    bitacora.configurar(rutas)
    motor = Motor(rutas, demo=demo, puerto=puerto)
    motor.start()
    motor.listo.wait(90)
    if motor.error:
        consola.print(f'[red]No arrancó:[/] {motor.error}')
        sys.exit(1)
    consola.print(f'Interfaz en {motor.url}  (Ctrl+C para salir)')
    try:
        motor.join()
    except KeyboardInterrupt:
        motor.detener()
