"""Operaciones sobre los canales de Telegram: creación, ficha, separadores, subida, índice y orden."""
import asyncio
import html
import logging
import re
import time
from typing import Callable

from telethon import errors
from telethon.tl import functions, types

from .detectar import normalizar
from .resolver import NOMBRE_TIPO, Resultado, Seccion
from .subida import subir_archivo
from .traductor import limpiar_sinopsis
from .video import Preparado

log = logging.getLogger('animetg.canales')

LIMITE_TEXTO = 3800     # Telegram corta los mensajes en 4096 caracteres visibles
LIMITE_ENLACES = 90     # enlaces por mensaje del índice
LIMITE_PIE = 1000       # pie de foto: 1024 caracteres


def _esc(texto) -> str:
    return html.escape(str(texto), quote=False)


def _visible(texto_html: str) -> int:
    return len(html.unescape(re.sub(r'<[^>]+>', '', texto_html)))


def _recortar(texto: str, largo: int) -> str:
    if len(texto) <= largo:
        return texto
    return texto[:largo - 1].rsplit(' ', 1)[0].rstrip(',;:') + '…'


def nombre_seccion(tipo: str, numero: int | None, subserie: str | None, titulo: str, varias: bool) -> str:
    if tipo == 'temporada':
        return f'{subserie} · Temporada {numero}' if varias and subserie else f'Temporada {numero}'
    return f'{NOMBRE_TIPO.get(tipo, "Especial")} · {titulo}'


def _prefijo_hashtag(subserie: str, serie: str) -> str:
    """'Love Live! Sunshine!!' dentro del canal 'Love Live! School idol project' -> 'Sunshine'."""
    propias = set(normalizar(serie).split())
    palabras = [p for p in normalizar(subserie).split() if p not in propias]
    return ''.join(p.capitalize() for p in palabras)[:24]


def _tramos_crecientes(ids: list[int]) -> list[list[int]]:
    """[20, 7, 10, 11] -> [[20], [7, 10, 11]]: cada tramo se reenvía de una vez sin alterar el orden."""
    tramos: list[list[int]] = []
    for i in ids:
        if tramos and i > tramos[-1][-1]:
            tramos[-1].append(i)
        else:
            tramos.append([i])
    return tramos


class Canales:
    def __init__(self, registro, anilist, traductor, resolver, ajustes, rutas):
        self.reg, self.al, self.traductor, self.resolver = registro, anilist, traductor, resolver
        self.ajustes, self.rutas = ajustes, rutas
        self.client = None  # lo asigna el servicio al conectarse
        self._verificados: set[int] = set()

    # --- utilidades ---
    @staticmethod
    def _peer(fila) -> types.InputPeerChannel:
        return types.InputPeerChannel(fila['canal_id'], fila['canal_hash'])

    def enlace(self, raiz_id: int, msg_id: int | None = None) -> str | None:
        """Enlace que abre el canal en la app de Telegram para escritorio."""
        fila = self.reg.serie(raiz_id)
        if not fila:
            return None
        return f'tg://privatepost?channel={fila["canal_id"]}&post={msg_id or fila["ficha_msg"] or 1}'

    async def _sinopsis(self, m: dict) -> str:
        texto = limpiar_sinopsis(m.get('description'))
        return await asyncio.to_thread(self.traductor.traducir, texto, self.ajustes.idioma_sinopsis)

    async def _portada(self, m: dict):
        try:
            return await asyncio.to_thread(self.al.portada, m, self.rutas.portadas)
        except Exception as e:
            log.warning('No se pudo descargar la carátula de %s (%s).', self.resolver.titulo(m), e)
            return None

    async def _limpiar_avisos(self, peer) -> None:
        """Borra los avisos automáticos ("canal creado", "foto cambiada", "mensaje fijado")."""
        avisos = [m.id async for m in self.client.iter_messages(peer, limit=10) if m.action]
        if avisos:
            await self.client.delete_messages(peer, avisos)

    async def vigentes(self, raiz_id: int, ids: list[int]) -> list[int] | None:
        """Cuáles de esos mensajes siguen en Telegram. None si el canal ya no existe."""
        fila = self.reg.serie(raiz_id)
        if not fila:
            return None
        if not ids:
            return []
        try:
            mensajes = await self.client.get_messages(self._peer(fila), ids=ids)
        except (errors.ChannelInvalidError, errors.ChannelPrivateError, ValueError):
            self._verificados.discard(raiz_id)  # canal() lo va a crear de nuevo
            return None
        return [i for i, m in zip(ids, mensajes) if m is not None]

    async def borrar_mensajes(self, raiz_id: int, ids: list[int]) -> None:
        if ids:
            await self.client.delete_messages(self._peer(self.reg.serie(raiz_id)), ids)

    # --- canal y ficha ---
    async def canal(self, raiz: dict) -> types.InputPeerChannel:
        fila = self.reg.serie(raiz['id'])
        if fila:
            peer = self._peer(fila)
            if raiz['id'] in self._verificados:
                return peer
            try:
                await self.client.get_messages(peer, limit=1)
                self._verificados.add(raiz['id'])
                return peer
            except (errors.ChannelInvalidError, errors.ChannelPrivateError, ValueError):
                log.warning('El canal de "%s" ya no existe; se crea de nuevo. Lo subido antes hay que volver '
                            'a ponerlo en la carpeta de subida.', fila['titulo'])
                self.reg.olvidar_serie(raiz['id'])
        return await self._crear_canal(raiz)

    async def _crear_canal(self, raiz: dict) -> types.InputPeerChannel:
        titulo = self.resolver.titulo(raiz)
        log.info('Creando canal privado "%s".', titulo)
        r = await self.client(functions.channels.CreateChannelRequest(
            title=titulo[:128], about=f'Respaldo de {titulo}'[:255], broadcast=True))
        canal = r.chats[0]
        self.reg.guardar_serie(raiz['id'], titulo, canal.id, canal.access_hash)
        peer = types.InputPeerChannel(canal.id, canal.access_hash)
        self._verificados.add(raiz['id'])

        texto = await self._ficha(raiz)
        portada = await self._portada(raiz)
        if portada:
            foto = await self.client.upload_file(str(portada))
            await self.client(functions.channels.EditPhotoRequest(
                types.InputChannel(canal.id, canal.access_hash), types.InputChatUploadedPhoto(file=foto)))
            ficha = await self.client.send_file(peer, str(portada), caption=texto, parse_mode='html')
        else:
            ficha = await self.client.send_message(peer, texto, parse_mode='html', link_preview=False)
        await self.client.pin_message(peer, ficha, notify=False)
        self.reg.guardar_ficha(raiz['id'], ficha.id, self.ajustes.idioma_sinopsis)

        indice = await self.client.send_message(peer, '<b>Índice</b>\nSe actualiza solo.', parse_mode='html')
        await self.client.pin_message(peer, indice, notify=False)
        self.reg.guardar_indice(raiz['id'], [{'id': indice.id, 'texto': ''}])

        await self._limpiar_avisos(peer)
        await self._agregar_a_carpeta(peer)
        return peer

    async def _ficha(self, raiz: dict) -> str:
        titulo = self.resolver.titulo(raiz)
        t = raiz.get('title') or {}
        otro = t.get('english') if self.ajustes.idioma_titulo != 'english' else t.get('romaji')
        lineas = [f'<b>{_esc(titulo)}</b>']
        if otro and normalizar(otro) != normalizar(titulo):
            lineas.append(f'<i>{_esc(otro)}</i>')
        datos = [str(raiz.get('seasonYear') or ''), ', '.join((raiz.get('genres') or [])[:4])]
        lineas.append(_esc(' · '.join(d for d in datos if d)))
        if raiz.get('siteUrl'):
            lineas.append(f'<a href="{_esc(raiz["siteUrl"])}">Ver en AniList</a>')
        texto = '\n'.join(lineas)
        sinopsis = await self._sinopsis(raiz)
        espacio = LIMITE_PIE - _visible(texto) - 2
        if sinopsis and espacio > 80:
            texto += '\n\n' + _esc(_recortar(sinopsis, espacio))
        return texto

    async def actualizar_ficha(self, raiz_id: int) -> None:
        """Rehace la ficha fijada (por ejemplo, para pasar la sinopsis al español)."""
        fila = self.reg.serie(raiz_id)
        if not fila or not fila['ficha_msg']:
            return
        raiz = await asyncio.to_thread(self.al.media, raiz_id)
        texto = await self._ficha(raiz)
        try:
            await self.client.edit_message(self._peer(fila), fila['ficha_msg'], texto, parse_mode='html',
                                           link_preview=False)
        except errors.MessageNotModifiedError:
            pass
        self.reg.guardar_ficha(raiz_id, fila['ficha_msg'], self.ajustes.idioma_sinopsis)
        log.info('Ficha de "%s" actualizada.', fila['titulo'])

    async def _agregar_a_carpeta(self, peer: types.InputPeerChannel) -> None:
        nombre = self.ajustes.carpeta_telegram
        if not nombre:
            return
        try:
            r = await self.client(functions.messages.GetDialogFiltersRequest())
            filtros = getattr(r, 'filters', r)
            carpeta = next((f for f in filtros if isinstance(f, types.DialogFilter)
                            and getattr(f.title, 'text', f.title) == nombre), None)
            if carpeta is None:
                ids = [f.id for f in filtros if hasattr(f, 'id')]
                carpeta = types.DialogFilter(id=max(ids + [1]) + 1, title=types.TextWithEntities(nombre, []),
                                             pinned_peers=[], include_peers=[], exclude_peers=[])
            if not any(getattr(p, 'channel_id', None) == peer.channel_id for p in carpeta.include_peers):
                carpeta.include_peers.append(peer)
                await self.client(functions.messages.UpdateDialogFilterRequest(id=carpeta.id, filter=carpeta))
        except errors.RPCError as e:
            log.warning('No se pudo agregar el canal a la carpeta "%s" (%s).', nombre, e.__class__.__name__)

    # --- secciones ---
    async def asegurar_seccion(self, peer, res: Resultado) -> None:
        """Registra la sección y, la primera vez, publica su carátula y sinopsis como separador."""
        raiz_id = res.raiz['id']
        self.reg.guardar_seccion(raiz_id, res.seccion)
        self.reg.marcar_subseries(raiz_id, res.varias_subseries)
        if self.reg.seccion(raiz_id, res.seccion.clave)['separador_msg']:
            return
        texto = await self._texto_separador(res.seccion, res.varias_subseries)
        portada = await self._portada(res.seccion.medias[0])
        if portada:
            msg = await self.client.send_file(peer, str(portada), caption=texto, parse_mode='html')
        else:
            msg = await self.client.send_message(peer, texto, parse_mode='html', link_preview=False)
        self.reg.guardar_separador(raiz_id, res.seccion.clave, msg.id)

    async def _texto_separador(self, s: Seccion, varias: bool) -> str:
        m = s.medias[0]
        nombre = nombre_seccion(s.tipo, s.numero, s.subserie, s.titulo, varias)
        lineas = [f'<b>{_esc(nombre)}</b>']
        if s.tipo == 'temporada' and normalizar(s.titulo) not in (normalizar(nombre), normalizar(s.subserie or '')):
            lineas.append(_esc(s.titulo))
        if s.tipo == 'temporada' or (s.total or 0) > 1:
            episodios = f'{s.total} episodios' if s.total else 'En emisión'
        else:
            episodios = ''
        lineas.append(_esc(' · '.join(d for d in (episodios, str(m.get('seasonYear') or '')) if d)))
        texto = '\n'.join(l for l in lineas if l)
        sinopsis = await self._sinopsis(m)
        espacio = min(LIMITE_PIE - _visible(texto) - 2, 700)
        if sinopsis and espacio > 80:
            texto += '\n\n' + _esc(_recortar(sinopsis, espacio))
        return texto

    # --- episodios ---
    def _texto_episodio(self, res: Resultado, parte: int, partes: int) -> str:
        serie = self.resolver.titulo(res.raiz)
        s = res.seccion
        if s.tipo == 'temporada':
            nombre = nombre_seccion(s.tipo, s.numero, s.subserie, s.titulo, res.varias_subseries)
            linea = f'{nombre} · Episodio {res.episodio:02d}'
            prefijo = _prefijo_hashtag(s.subserie, serie) if res.varias_subseries else ''
            etiquetas = f'#{prefijo}T{s.numero} #{prefijo}T{s.numero}E{res.episodio:02d}'
        else:
            linea = nombre_seccion(s.tipo, None, None, s.titulo, False)
            if (s.total or 1) > 1:
                linea += f' · Episodio {res.episodio:02d}'
            etiquetas = '#' + {'pelicula': 'Pelicula', 'ova': 'OVA'}.get(s.tipo, 'Especial')
        if partes > 1:
            linea += f' · Parte {parte} de {partes}'
        return f'<b>{_esc(serie)}</b>\n{_esc(linea)}\n{etiquetas}'

    async def subir(self, peer, res: Resultado, prep: Preparado, nombre_original: str, ya_subidas: set[int],
                    aviso: Callable[[int, int, int, int, float, float | None], None] | None = None) -> None:
        """Sube cada parte; `aviso(parte, partes, hecho, total, velocidad, restante)` informa el avance."""
        partes = len(prep.archivos)
        for parte, (archivo, info) in enumerate(zip(prep.archivos, prep.infos), 1):
            if parte in ya_subidas:
                continue
            inicio = time.monotonic()
            subido = await subir_archivo(
                self.client, archivo, self.ajustes.conexiones,
                aviso=(lambda h, t, v, r, p=parte: aviso(p, partes, h, t, v, r)) if aviso else None)
            opciones = dict(caption=self._texto_episodio(res, parte, partes), parse_mode='html',
                            thumb=str(prep.miniatura) if prep.miniatura else None)
            if prep.como_video and info:
                opciones.update(supports_streaming=True, attributes=[types.DocumentAttributeVideo(
                    duration=info.duracion, w=info.ancho, h=info.alto, supports_streaming=True)])
            else:
                opciones.update(force_document=True)
            msg = await self.client.send_file(peer, subido, **opciones)
            self.reg.guardar_episodio(res.raiz['id'], res.seccion.clave, res.episodio, parte, partes, msg.id,
                                      nombre_original, archivo.stat().st_size, time.monotonic() - inicio)

    # --- índice fijado ---
    def _piezas_indice(self, raiz_id: int) -> list[tuple[str, int]]:
        """Trocitos del índice: (html, largo visible). Cada trocito tiene un enlace."""
        serie = self.reg.serie(raiz_id)
        varias = bool(serie['varias_subseries'])

        def enlace(msg_id, texto):
            return f'<a href="https://t.me/c/{serie["canal_id"]}/{msg_id}">{_esc(texto)}</a>'

        episodios = self.reg.episodios(raiz_id)
        piezas = []
        for s in self.reg.secciones(raiz_id):
            lista = [e for e in episodios if e['seccion'] == s['clave']]
            if not lista:
                continue
            nombre = nombre_seccion(s['tipo'], s['numero'], s['subserie'], s['titulo'], varias)
            if s['tipo'] == 'temporada' and normalizar(s['titulo']) != normalizar(s['subserie'] or ''):
                nombre += f' · {s["titulo"]}'  # "Temporada 3 · Kimetsu no Yaiba: Yuukaku-hen"
            cuenta = len({e['episodio'] for e in lista})
            cuenta = f'{cuenta}/{s["total"]}' if s['total'] and s['total'] > 1 else ''
            cabecera = enlace(s['separador_msg'], nombre) if s['separador_msg'] else _esc(nombre)
            piezas.append((f'\n<b>{cabecera}</b>' + (f' ({cuenta})' if cuenta else '') + '\n',
                           len(nombre) + len(cuenta) + 5))
            unico = (s['total'] or 1) <= 1 and s['tipo'] != 'temporada'
            for e in lista:
                texto = 'Ver' if unico else f'{e["episodio"]:02d}'
                if e['partes'] > 1:
                    texto += f' ({e["parte"]}/{e["partes"]})'
                piezas.append((enlace(e['msg_id'], texto) + ' ', len(texto) + 1))
        return piezas

    async def actualizar_indice(self, raiz_id: int) -> None:
        fila = self.reg.serie(raiz_id)
        peer = self._peer(fila)
        mensajes, actual, largo, enlaces = [], '<b>Índice</b>\n', 8, 0
        for pieza, visible in self._piezas_indice(raiz_id):
            if largo + visible > LIMITE_TEXTO or enlaces + 1 > LIMITE_ENLACES:
                mensajes.append(actual.rstrip())
                actual, largo, enlaces = '<b>Índice (sigue)</b>\n', 14, 0
            actual, largo, enlaces = actual + pieza, largo + visible, enlaces + 1
        mensajes.append(re.sub(r' +\n', '\n', actual).rstrip())

        guardados = self.reg.indice(raiz_id)
        nuevos = []
        for i, texto in enumerate(mensajes):
            if i < len(guardados):
                if guardados[i]['texto'] != texto:
                    try:
                        await self.client.edit_message(peer, guardados[i]['id'], texto, parse_mode='html',
                                                       link_preview=False)
                    except errors.MessageNotModifiedError:
                        pass
                nuevos.append({'id': guardados[i]['id'], 'texto': texto})
            else:
                msg = await self.client.send_message(peer, texto, parse_mode='html', link_preview=False)
                await self.client.pin_message(peer, msg, notify=False)
                await self._limpiar_avisos(peer)
                nuevos.append({'id': msg.id, 'texto': texto})
        for sobrante in guardados[len(mensajes):]:
            if sobrante['texto'] != '—':
                await self.client.edit_message(peer, sobrante['id'], '—')
            nuevos.append({'id': sobrante['id'], 'texto': '—'})
        self.reg.guardar_indice(raiz_id, nuevos)

    # --- orden del canal ---
    async def reordenar(self, raiz_id: int) -> int:
        """Deja el canal en el orden de las secciones. Devuelve cuántos mensajes movió.

        Telegram no permite mover mensajes: se reenvían dentro del mismo canal (sin volver a subir
        nada y sin el "reenviado de") desde el primero fuera de lugar, y se borran los originales.
        La ficha y el índice no se tocan.
        """
        fila = self.reg.serie(raiz_id)
        peer = self._peer(fila)
        pendientes, _ = self.reg.cache_leer(f'borrar:{raiz_id}')
        if pendientes:  # originales que una vez anterior no se alcanzaron a borrar
            await self.client.delete_messages(peer, pendientes)
            self.reg.cache_guardar(f'borrar:{raiz_id}', [])

        episodios = self.reg.episodios(raiz_id)
        deseado = []
        for s in self.reg.secciones(raiz_id):
            if s['separador_msg']:
                deseado.append(s['separador_msg'])
            deseado += [e['msg_id'] for e in episodios if e['seccion'] == s['clave']]
        if not deseado:
            return 0

        # Lo que se borró a mano en Telegram se saca del registro, para poder volver a subirlo.
        existentes = await self.client.get_messages(peer, ids=deseado)
        borrados = {i for i, m in zip(deseado, existentes) if m is None}
        if borrados:
            self.reg.quitar_mensajes(raiz_id, list(borrados))
            log.warning('%d mensaje(s) de "%s" ya no están en Telegram; si quieres volver a subirlos, '
                        'pon los archivos otra vez en la carpeta de subida.', len(borrados), fila['titulo'])
            deseado = [i for i in deseado if i not in borrados]

        desde = next((k for k, (a, b) in enumerate(zip(deseado, sorted(deseado))) if a != b), None)
        if desde is None:
            if borrados:
                await self.actualizar_indice(raiz_id)
            return 0

        ultimo = (await self.client.get_messages(peer, limit=1))[0].id
        copias: dict[int, int] = {}
        try:
            for tramo in _tramos_crecientes(deseado[desde:]):
                for i in range(0, len(tramo), 100):
                    lote = tramo[i:i + 100]
                    nuevos = await self.client.forward_messages(peer, lote, from_peer=peer,
                                                                drop_author=True, silent=True)
                    if len(nuevos) != len(lote) or any(n is None for n in nuevos):
                        raise RuntimeError('Telegram no copió todos los mensajes.')
                    copias.update((viejo, nuevo.id) for viejo, nuevo in zip(lote, nuevos))
        except Exception:
            # Si falla a medias se borra todo lo creado desde que empezó (incluso copias que Telegram
            # hizo sin alcanzar a confirmar) y el canal queda como estaba.
            try:
                sobrantes = [m.id async for m in self.client.iter_messages(peer, min_id=ultimo)]
                if sobrantes:
                    await self.client.delete_messages(peer, sobrantes)
            except Exception:
                log.warning('Puede que al final del canal "%s" hayan quedado episodios repetidos; '
                            'se pueden borrar a mano.', fila['titulo'])
            raise
        self.reg.cambiar_mensajes(raiz_id, copias)
        try:
            await self.client.delete_messages(peer, list(copias))
        except Exception:
            self.reg.cache_guardar(f'borrar:{raiz_id}', list(copias))  # se reintenta la próxima vez
            raise
        await self.actualizar_indice(raiz_id)
        log.info('"%s" reordenado (%d mensajes).', fila['titulo'], len(copias))
        return len(copias)
