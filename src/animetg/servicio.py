"""Orquesta todo: vigila la carpeta, analiza lo que llega, sube en orden y avisa a la interfaz."""
import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .ajustes import Ajustes
from .anilist import AniList, AniListError, resumen
from .bitacora import ManejadorEventos
from .canales import Canales, nombre_seccion
from .credenciales import Credenciales
from .detectar import EXTENSIONES, Deteccion, detectar, normalizar
from .eventos import Bus
from .registro import Registro
from .resolver import NoReconocido, Resolver, Resultado
from .rutas import Rutas
from .sesion import Conexion
from .subida import subir_archivo
from .traductor import Traductor
from .video import Info, Plan, analizar, decidir, preparar

log = logging.getLogger('animetg')

EN_ESPERA = ('en_cola', 'repetido')
EN_CURSO = ('preparando', 'subiendo')


@dataclass(eq=False)
class Item:
    id: str
    ruta: Path
    tamano: int
    estado: str = 'analizando'   # analizando | en_cola | repetido | preparando | subiendo | pendiente | error | cancelado
    det: Deteccion | None = None
    res: Resultado | None = None
    info: Info | None = None
    plan: Plan | None = None
    error: str | None = None
    media_forzada: int | None = None
    progreso: float = 0.0
    velocidad: float = 0.0
    restante: float | None = None
    parte: int = 1
    partes: int = 1
    ultimo_aviso: float = 0.0


def _listar(entrada: Path) -> dict[Path, int]:
    entrada.mkdir(parents=True, exist_ok=True)
    return {p: p.stat().st_size for p in entrada.rglob('*')
            if p.is_file() and p.suffix.lower() in EXTENSIONES}


def _listo(ruta: Path) -> bool:
    """False si otro programa lo sigue escribiendo (por ejemplo, una copia a medias)."""
    if not os.access(ruta, os.W_OK):  # de solo lectura: nadie lo está escribiendo
        return True
    try:
        with open(ruta, 'r+b'):
            return True
    except OSError:
        return False


def _nombre_seguro(texto: str) -> str:
    return ''.join('_' if c in '<>:"/\\|?*' else c for c in texto).strip(' .') or 'Sin nombre'


def _duracion(segundos: float) -> str:
    minutos, segundos = divmod(int(segundos), 60)
    return f'{minutos} min {segundos:02d} s' if minutos else f'{segundos} s'


class Servicio:
    def __init__(self, rutas: Rutas, credenciales: Credenciales | None = None, fabrica_cliente=None,
                 bus: Bus | None = None):
        self.rutas = rutas.crear()
        self.ajustes = Ajustes.cargar(rutas.ajustes)
        self.registro = Registro(rutas.db)
        self.bus = bus or Bus()
        self.anilist = AniList(self.registro)
        self.traductor = Traductor(self.registro)
        self.resolver = Resolver(self.anilist, self.registro.correcciones, self.ajustes.idioma_titulo)
        extra = {'fabrica': fabrica_cliente} if fabrica_cliente else {}
        self.conexion = Conexion(credenciales or Credenciales(), **extra)
        self.canales = Canales(self.registro, self.anilist, self.traductor, self.resolver, self.ajustes, self.rutas)
        self.items: dict[str, Item] = {}
        self.actual: Item | None = None
        self.pausado = False
        self._forzar = False
        self._despertar = asyncio.Event()
        self._mirar_pronto = asyncio.Event()
        self._mantener = asyncio.Event()
        self._previos: dict[Path, int] = {}
        self._ignorados: dict[Path, int] = {}
        self._tareas: list[asyncio.Task] = []
        self._tarea_item: asyncio.Task | None = None
        self._manejador_log: logging.Handler | None = None

    # ------------------------------------------------------------------ ciclo de vida
    async def iniciar(self, vigilar: bool = True) -> None:
        self.bus.vincular(asyncio.get_running_loop())
        self._manejador_log = ManejadorEventos(self.bus)
        log.addHandler(self._manejador_log)
        log.info('Anime Telegram %s iniciado.', __version__)
        await self._conectar()
        if vigilar:
            self._tareas += [asyncio.create_task(self._bucle_escaneo(), name='escaneo'),
                             asyncio.create_task(self._bucle_subida(), name='subida')]
        self._tareas.append(asyncio.create_task(self._bucle_mantenimiento(), name='mantenimiento'))

    async def detener(self) -> None:
        tareas = self._tareas + ([self._tarea_item] if self._tarea_item else [])
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)
        await self.conexion.desconectar()
        if self._manejador_log:
            log.removeHandler(self._manejador_log)
        self.registro.cerrar()

    @property
    def ocupado(self) -> bool:
        return self.actual is not None

    async def _conectar(self) -> None:
        try:
            if await self.conexion.conectar():
                self._al_conectar()
        except Exception as e:  # sin internet, Telegram caído...
            log.warning('No se pudo conectar con Telegram (%s). Se reintenta en un minuto.', e)
        self._publicar_estado()

    def _al_conectar(self) -> None:
        self.canales.client = self.conexion.client
        log.info('Conectado a Telegram como %s.', self.conexion.usuario['nombre'])
        self._despertar.set()
        self._mantener.set()

    # ------------------------------------------------------------------ vigilancia de la carpeta
    async def _bucle_escaneo(self) -> None:
        while True:
            copiando = False
            try:
                copiando = await self.escanear()
            except Exception:
                log.exception('Error revisando la carpeta de subida.')
            try:
                await asyncio.wait_for(self._mirar_pronto.wait(),
                                       timeout=3 if copiando else self.ajustes.segundos_escaneo)
            except asyncio.TimeoutError:
                pass
            self._mirar_pronto.clear()

    async def escanear(self) -> bool:
        """Agrega lo nuevo, quita lo que ya no está. Devuelve True si algo se sigue copiando."""
        actuales = await asyncio.to_thread(_listar, self.ajustes.entrada)
        cambios = False
        for item in list(self.items.values()):
            if item.ruta not in actuales and item.estado not in EN_CURSO:
                del self.items[item.id]
                cambios = True
        self._ignorados = {p: t for p, t in self._ignorados.items() if actuales.get(p) == t}
        en_cola = {i.ruta for i in self.items.values()}
        nuevos = [p for p in actuales if p not in en_cola and p not in self._ignorados]
        # Se agrega recién cuando el tamaño no cambió entre dos revisiones y nadie lo está escribiendo.
        listos = [p for p in nuevos if self._previos.get(p) == actuales[p] and await asyncio.to_thread(_listo, p)]
        self._previos = actuales
        for ruta in sorted(listos):
            item = Item(uuid.uuid4().hex[:10], ruta, actuales[ruta])
            self.items[item.id] = item
            cambios = True
        if cambios:
            self._publicar_cola()
        for item in [i for i in self.items.values() if i.estado == 'analizando']:
            await self._analizar(item)
        return len(listos) < len(nuevos)

    async def _analizar(self, item: Item) -> None:
        try:
            await asyncio.to_thread(self._analizar_sincrono, item)
        except Exception as e:
            item.estado, item.error = 'error', f'No se pudo analizar: {e}'
            log.exception('Error analizando %s', item.ruta.name)
        self._publicar_item(item)
        if item.estado in EN_ESPERA:
            self._despertar.set()

    def _analizar_sincrono(self, item: Item) -> None:
        item.det = detectar(item.ruta, self.ajustes.entrada)
        try:
            item.res = self.resolver.resolver(item.det, item.media_forzada)
        except NoReconocido as e:
            item.estado, item.error, item.res = 'pendiente', str(e), None
            return
        except AniListError as e:
            item.estado, item.error = 'error', f'{e} Usa "Reintentar" cuando vuelva la conexión.'
            return
        item.info = analizar(self.ajustes.programa('ffprobe'), item.ruta)
        item.plan = decidir(item.ruta, item.info)
        hechas, partes = self.registro.partes_subidas(item.res.raiz['id'], item.res.seccion.clave, item.res.episodio)
        item.error = None
        item.estado = 'repetido' if partes and len(hechas) >= partes else 'en_cola'
        try:
            self.anilist.miniatura(item.res.media, self.rutas.portadas)  # para mostrarla en la interfaz
        except Exception:
            pass

    # ------------------------------------------------------------------ subida
    async def _bucle_subida(self) -> None:
        while True:
            await self._despertar.wait()
            self._despertar.clear()
            while (item := self._siguiente()) is not None:
                self._tarea_item = asyncio.create_task(self._procesar(item))
                await asyncio.wait({self._tarea_item})
                self._tarea_item = None

    def _siguiente(self) -> Item | None:
        if self.pausado or self.conexion.estado != 'conectado':
            return None
        candidatos = [i for i in self.items.values() if i.estado in EN_ESPERA]
        if not candidatos:
            self._forzar = False
            return None
        if not (self.ajustes.subida_automatica or self._forzar):
            return None
        return min(candidatos, key=self._orden)

    def _orden(self, item: Item):
        r = item.res
        return self.resolver.titulo(r.raiz).lower(), r.seccion.orden, r.episodio

    async def _procesar(self, item: Item) -> None:
        res = item.res
        serie = _nombre_seguro(self.resolver.titulo(res.raiz))
        trabajo = self.rutas.temporal / 'actual'
        self.actual = item
        try:
            reemplazar: list[int] = []
            if item.estado == 'repetido':
                anteriores = self.registro.mensajes_episodio(res.raiz['id'], res.seccion.clave, res.episodio)
                vigentes = await self.canales.vigentes(res.raiz['id'], anteriores)
                if not anteriores or vigentes is None or len(vigentes) < len(anteriores):
                    # Lo borraron en Telegram (o el canal entero): se olvida y se sube de nuevo.
                    log.info('%s · %s ya no está en Telegram; se sube de nuevo.', serie, res.ubicacion)
                    if vigentes:
                        await self.canales.borrar_mensajes(res.raiz['id'], vigentes)
                    self.registro.quitar_mensajes(res.raiz['id'], anteriores)
                elif self.ajustes.repetidos == 'reemplazar':
                    log.info('%s · %s ya estaba subido; se reemplaza por %s.', serie, res.ubicacion, item.ruta.name)
                    reemplazar = anteriores
                else:
                    log.info('Ya estaba subido, se mueve a _repetidos: %s', item.ruta.name)
                    await asyncio.to_thread(self._mover, item.ruta, Path('_repetidos'))
                    self.items.pop(item.id, None)
                    return
            self._cambiar(item, 'preparando')
            log.info('%s · %s · %s (%s)', serie, res.ubicacion, item.ruta.name, item.plan.motivo)
            peer = await self.canales.canal(res.raiz)
            await self.canales.asegurar_seccion(peer, res)
            mini = await asyncio.to_thread(self._miniatura, res.media)
            await asyncio.to_thread(shutil.rmtree, trabajo, True)
            prep = await asyncio.to_thread(preparar, self.ajustes, item.ruta, item.info, item.plan, trabajo, mini)
            hechas = set() if reemplazar else \
                self.registro.partes_subidas(res.raiz['id'], res.seccion.clave, res.episodio)[0]
            self._cambiar(item, 'subiendo')
            inicio = time.monotonic()
            await self.canales.subir(peer, res, prep, item.ruta.name, hechas,
                                     aviso=lambda *avance: self._avance(item, *avance))
            segundos = time.monotonic() - inicio
            if reemplazar:
                # La versión vieja se borra recién cuando la nueva terminó de subir.
                self.registro.recortar_partes(res.raiz['id'], res.seccion.clave, res.episodio, len(prep.archivos))
                await self.canales.borrar_mensajes(res.raiz['id'], reemplazar)
            await self.canales.actualizar_indice(res.raiz['id'])
            carpeta = 'Especiales' if res.seccion.tipo != 'temporada' else \
                nombre_seccion('temporada', res.seccion.numero, res.seccion.subserie, '', res.varias_subseries)
            await asyncio.to_thread(self._mover, item.ruta, Path(serie) / _nombre_seguro(carpeta))
            log.info('Subido: %s · %s (%s, %.1f MB/s).', serie, res.ubicacion, _duracion(segundos),
                     item.tamano / 1024 / 1024 / max(segundos, 0.001))
            self.items.pop(item.id, None)
            self.bus.publicar('series', {'raiz': res.raiz['id']})
            await self._reordenar_si_corresponde(res.raiz['id'])
        except asyncio.CancelledError:
            item.estado, item.error = 'cancelado', 'Cancelado. Usa "Reintentar" para subirlo.'
            log.info('Subida cancelada: %s', item.ruta.name)
        except Exception as e:
            item.estado, item.error = 'error', str(e) or e.__class__.__name__
            log.exception('Error con %s', item.ruta.name)
        finally:
            await asyncio.to_thread(shutil.rmtree, trabajo, True)
            self.actual = None
            self._publicar_cola()
            self._publicar_estado()

    async def _reordenar_si_corresponde(self, raiz_id: int) -> None:
        """Si llegó algo que va antes de lo ya subido, se reacomoda cuando no queda nada más de esa serie."""
        if not self.ajustes.ordenar_automatico:
            return
        if any(i.res and i.res.raiz['id'] == raiz_id and i.estado in EN_ESPERA for i in self.items.values()):
            return
        try:
            await self.canales.reordenar(raiz_id)
        except Exception:
            log.exception('No se pudo reordenar el canal; se puede reintentar desde Series.')

    def _miniatura(self, media: dict) -> Path | None:
        try:
            return self.anilist.miniatura(media, self.rutas.portadas)
        except Exception:
            return None

    def _cambiar(self, item: Item, estado: str) -> None:
        item.estado, item.progreso, item.velocidad, item.restante = estado, 0.0, 0.0, None
        self._publicar_item(item)
        self._publicar_estado()

    def _avance(self, item: Item, parte: int, partes: int, hecho: int, total: int, velocidad: float,
                restante: float | None) -> None:
        item.parte, item.partes, item.velocidad = parte, partes, velocidad
        item.progreso = ((parte - 1) + (hecho / total if total else 1)) / partes
        if restante is not None and velocidad > 0:
            restante += (partes - parte) * total / velocidad
        item.restante = restante
        ahora = time.monotonic()
        if ahora - item.ultimo_aviso > 0.3 or hecho >= total:
            item.ultimo_aviso = ahora
            self._publicar_item(item)

    def _mover(self, ruta: Path, subcarpeta: Path) -> None:
        destino_dir = self.ajustes.subidos / subcarpeta
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino, n = destino_dir / ruta.name, 2
        while destino.exists():
            destino, n = destino_dir / f'{ruta.stem} ({n}){ruta.suffix}', n + 1
        shutil.move(str(ruta), str(destino))
        # Quita las carpetas que quedaron vacías dentro de la de subida (nunca la carpeta misma).
        entrada, carpeta = self.ajustes.entrada, ruta.parent
        while carpeta != entrada and entrada in carpeta.parents:
            try:
                carpeta.rmdir()
            except OSError:
                break
            carpeta = carpeta.parent

    # ------------------------------------------------------------------ mantenimiento
    async def _bucle_mantenimiento(self) -> None:
        while True:
            try:
                if self.conexion.estado != 'conectado' and self.conexion.cred.tiene_api and self.conexion.cred.sesion:
                    await self._conectar()
                if self.conexion.estado == 'conectado':
                    await self._actualizar_fichas()
            except Exception:
                log.exception('Error en el mantenimiento.')
            try:
                await asyncio.wait_for(self._mantener.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
            self._mantener.clear()

    async def _actualizar_fichas(self) -> None:
        """Rehace las fichas que están en otro idioma (por ejemplo, las de la versión anterior, en inglés)."""
        for fila in self.registro.series():
            if fila['ficha_idioma'] != self.ajustes.idioma_sinopsis:
                try:
                    await self.canales.actualizar_ficha(fila['raiz'])
                except Exception as e:
                    log.warning('No se pudo actualizar la ficha de "%s" (%s).', fila['titulo'], e)

    # ------------------------------------------------------------------ uso sin ventana (línea de comandos)
    async def revisar_carpeta(self) -> None:
        """Dos revisiones seguidas: lo que no cambió de tamaño entre ambas queda en la cola."""
        self.bus.vincular(asyncio.get_running_loop())
        await self.escanear()
        await asyncio.sleep(3)
        await self.escanear()

    async def procesar_cola(self) -> None:
        """Sube todo lo que haya en cola, en orden, y vuelve."""
        self._forzar = True
        while (item := self._siguiente()) is not None:
            await self._procesar(item)

    # ------------------------------------------------------------------ acciones de la interfaz
    def subir_ahora(self) -> None:
        self._forzar, self.pausado = True, False
        self._despertar.set()
        self._publicar_estado()

    def pausar(self, pausado: bool) -> None:
        self.pausado = pausado
        if not pausado:
            self._despertar.set()
        log.info('Subidas %s.', 'en pausa' if pausado else 'reanudadas')
        self._publicar_estado()

    def cancelar_actual(self) -> None:
        if self._tarea_item and not self._tarea_item.done():
            self._tarea_item.cancel()

    def reintentar(self, item_id: str) -> None:
        item = self.items.get(item_id)
        if item and item.estado not in EN_CURSO:
            item.estado, item.error = 'analizando', None
            self._publicar_item(item)
            self._mirar_pronto.set()

    def quitar(self, item_id: str) -> None:
        item = self.items.get(item_id)
        if item and item.estado not in EN_CURSO:
            del self.items[item_id]
            self._ignorados[item.ruta] = item.tamano  # hasta que el archivo cambie o se reinicie la app
            self._publicar_cola()

    async def corregir(self, item_id: str, media_id: int, recordar: bool = True) -> None:
        """El usuario eligió el anime correcto. Si `recordar`, aplica a todo lo que tenga ese nombre."""
        item = self.items.get(item_id)
        if not item or item.estado in EN_CURSO:
            return
        afectados = [item]
        if recordar and item.det and item.det.titulo:
            self.registro.guardar_correccion(normalizar(item.det.titulo), item.det.titulo, media_id)
            log.info('Corrección guardada: "%s" es AniList %s.', item.det.titulo, media_id)
            afectados += [i for i in self.items.values() if i is not item and i.det and i.det.titulo
                          and normalizar(i.det.titulo) == normalizar(item.det.titulo) and i.estado not in EN_CURSO]
        else:
            item.media_forzada = media_id
        for i in afectados:
            i.estado, i.error = 'analizando', None
            self._publicar_item(i)
        for i in afectados:
            await self._analizar(i)

    async def buscar_anilist(self, texto: str) -> list[dict]:
        lista = await asyncio.to_thread(self.anilist.buscar, texto)
        return [{**resumen(m, self.ajustes.idioma_titulo), 'portada': (m.get('coverImage') or {}).get('large')}
                for m in lista]

    async def reordenar(self, raiz_id: int) -> int:
        return await self.canales.reordenar(raiz_id)

    async def actualizar_ficha(self, raiz_id: int) -> None:
        await self.canales.actualizar_ficha(raiz_id)

    def abrir(self, que: str, valor=None) -> None:
        if que == 'canal':
            enlace = self.canales.enlace(int(valor))
            if enlace:
                os.startfile(enlace)
        elif que in ('subir', 'subidos', 'datos', 'logs'):
            carpeta = {'subir': self.ajustes.entrada, 'subidos': self.ajustes.subidos,
                       'datos': self.rutas.datos, 'logs': self.rutas.logs}[que]
            carpeta.mkdir(parents=True, exist_ok=True)
            os.startfile(carpeta)

    async def guardar_ajustes(self, cambios: dict) -> list[str]:
        antes = self.ajustes.como_dict()
        errores = self.ajustes.actualizar(cambios)
        self.ajustes.guardar(self.rutas.ajustes)
        self.resolver.idioma = self.ajustes.idioma_titulo
        if antes['carpeta_subir'] != self.ajustes.carpeta_subir:
            self.items = {k: i for k, i in self.items.items() if i.estado in EN_CURSO}
            self._previos.clear()
            self._mirar_pronto.set()
        if antes['idioma_sinopsis'] != self.ajustes.idioma_sinopsis:
            self._mantener.set()
        if self.ajustes.subida_automatica:
            self._despertar.set()
        log.info('Ajustes guardados.')
        self._publicar_cola()
        self._publicar_estado()
        return errores

    async def prueba_velocidad(self, megas: int = 24) -> dict:
        """Sube datos de relleno sin crear ningún mensaje (Telegram descarta las partes que nadie usa)."""
        if self.conexion.estado != 'conectado':
            raise RuntimeError('Primero inicia sesión en Telegram.')
        archivo = self.rutas.temporal / 'prueba_velocidad.bin'
        await asyncio.to_thread(archivo.write_bytes, os.urandom(megas * 1024 * 1024))
        try:
            resultados = {}
            for conexiones in (1, self.ajustes.conexiones):
                inicio = time.monotonic()
                await subir_archivo(self.conexion.client, archivo, conexiones)
                resultados[conexiones] = megas / (time.monotonic() - inicio)
        finally:
            archivo.unlink(missing_ok=True)
        log.info('Prueba de velocidad: %.1f MB/s de a una parte, %.1f MB/s con %d en paralelo.',
                 resultados[1], resultados[self.ajustes.conexiones], self.ajustes.conexiones)
        return {'una': resultados[1], 'paralelo': resultados[self.ajustes.conexiones],
                'conexiones': self.ajustes.conexiones}

    # --- sesión de Telegram ---
    async def configurar_api(self, api_id: int, api_hash: str) -> None:
        await self.conexion.configurar_api(api_id, api_hash)
        self.canales.client = None
        self._publicar_estado()

    async def pedir_codigo(self, telefono: str) -> None:
        await self.conexion.pedir_codigo(telefono)

    async def confirmar_codigo(self, codigo: str) -> str:
        resultado = await self.conexion.confirmar_codigo(codigo)
        if resultado == 'listo':
            self._al_conectar()
        self._publicar_estado()
        return resultado

    async def confirmar_clave(self, clave: str) -> None:
        await self.conexion.confirmar_clave(clave)
        self._al_conectar()
        self._publicar_estado()

    async def cerrar_sesion(self) -> None:
        self.cancelar_actual()
        await self.conexion.cerrar_sesion()
        self.canales.client = None
        log.info('Sesión de Telegram cerrada en este equipo.')
        self._publicar_estado()

    # ------------------------------------------------------------------ consultas para la interfaz
    def estado(self) -> dict:
        items = list(self.items.values())
        return {
            'version': __version__,
            'conexion': self.conexion.estado,
            'usuario': self.conexion.usuario,
            'pausado': self.pausado,
            'automatica': self.ajustes.subida_automatica,
            'carpeta': str(self.ajustes.entrada),
            'actual': self.actual.id if self.actual else None,
            'programas': {n: self.ajustes.programa_disponible(n) for n in ('ffmpeg', 'ffprobe', 'siete_zip')},
            'contadores': {
                'cola': sum(i.estado in EN_ESPERA + EN_CURSO + ('analizando',) for i in items),
                'pendientes': sum(i.estado == 'pendiente' for i in items),
                'errores': sum(i.estado in ('error', 'cancelado') for i in items),
            },
        }

    def item_dict(self, i: Item) -> dict:
        r = i.res
        carpeta = i.ruta.parent.relative_to(self.ajustes.entrada) if self.ajustes.entrada in i.ruta.parents else None
        datos = {
            'id': i.id, 'archivo': i.ruta.name, 'tamano': i.tamano, 'estado': i.estado, 'error': i.error,
            'carpeta': '' if carpeta in (None, Path('.')) else str(carpeta),
            'detectado': {'titulo': i.det.titulo, 'temporada': i.det.temporada, 'episodio': i.det.episodio}
            if i.det else None,
            'progreso': round(i.progreso, 4), 'velocidad': i.velocidad, 'restante': i.restante,
            'parte': i.parte, 'partes': i.partes,
        }
        if r:
            datos.update(serie=self.resolver.titulo(r.raiz), raiz=r.raiz['id'], media=r.media['id'],
                         ubicacion=r.ubicacion, tipo=r.seccion.tipo, episodio=r.episodio,
                         unico=r.seccion.tipo != 'temporada' and (r.seccion.total or 1) <= 1,
                         seccion=nombre_seccion(r.seccion.tipo, r.seccion.numero, r.seccion.subserie,
                                                r.seccion.titulo, r.varias_subseries))
        if i.plan:
            datos.update(modo=i.plan.modo, motivo=i.plan.motivo,
                         divide=i.tamano > self.ajustes.limite_bytes)
        return datos

    def cola(self) -> list[dict]:
        def clave(i: Item):
            grupo = 0 if i.estado in EN_CURSO else 1 if i.estado in EN_ESPERA + ('analizando',) else 2
            return (grupo, *(self._orden(i) if i.res else ('', (0, 0), 0)), i.ruta.name)
        return [self.item_dict(i) for i in sorted(self.items.values(), key=clave)]

    def recientes(self, cantidad: int = 12) -> list[dict]:
        salida = []
        for e in self.registro.recientes(cantidad):
            fila = self.registro.seccion(e['raiz'], e['seccion'])
            varias = bool(self.registro.serie(e['raiz'])['varias_subseries'])
            nombre = nombre_seccion(fila['tipo'], fila['numero'], fila['subserie'], fila['titulo'], varias)
            salida.append({'serie': e['serie_titulo'], 'raiz': e['raiz'], 'media': fila['media_id'] or e['raiz'],
                           'seccion': nombre, 'episodio': e['episodio'], 'tipo': fila['tipo'],
                           'archivo': e['archivo'], 'fecha': e['fecha'], 'tamano': e['tamano'],
                           'segundos': e['segundos']})
        return salida

    def series(self) -> list[dict]:
        return [{'raiz': f['raiz'], 'titulo': f['titulo'], 'episodios': f['episodios'], 'tamano': f['tamano'],
                 'secciones': f['secciones'], 'ultima': f['ultima']} for f in self.registro.resumen_series()]

    def serie(self, raiz_id: int) -> dict | None:
        fila = self.registro.serie(raiz_id)
        if not fila:
            return None
        varias = bool(fila['varias_subseries'])
        episodios = self.registro.episodios(raiz_id)
        secciones = []
        for s in self.registro.secciones(raiz_id):
            lista = sorted({e['episodio'] for e in episodios if e['seccion'] == s['clave']})
            if not lista:
                continue
            secciones.append({'clave': s['clave'], 'tipo': s['tipo'], 'total': s['total'],
                              'media': s['media_id'] or (s['subserie_id'] if s['numero'] == 1 else raiz_id),
                              'nombre': nombre_seccion(s['tipo'], s['numero'], s['subserie'], s['titulo'], varias),
                              'titulo': s['titulo'], 'subidos': lista})
        return {'raiz': raiz_id, 'titulo': fila['titulo'], 'secciones': secciones,
                'tamano': sum(e['tamano'] or 0 for e in episodios), 'ficha_idioma': fila['ficha_idioma']}

    def portada(self, media_id: int) -> Path | None:
        """Miniatura en caché; si no está, se descarga (se llama desde un hilo)."""
        mini = self.rutas.portadas / f'mini_{media_id}.jpg'
        if mini.exists():
            return mini
        m = self.anilist.media(media_id)
        return self.anilist.miniatura(m, self.rutas.portadas) if m else None

    # ------------------------------------------------------------------ eventos
    def _publicar_estado(self) -> None:
        self.bus.publicar('estado', self.estado())

    def _publicar_cola(self) -> None:
        self.bus.publicar('cola', self.cola())

    def _publicar_item(self, item: Item) -> None:
        self.bus.publicar('item', self.item_dict(item))
