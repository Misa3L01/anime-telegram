"""Decide a qué canal, sección y episodio corresponde cada archivo, según las relaciones de AniList.

Un canal es una franquicia: la cadena de secuelas que arranca en su primera entrada. Dentro hay
secciones en orden cronológico:
  - temporadas, numeradas dentro de su subserie (Love Live! Sunshine!! empieza otra vez en la 1);
  - películas, OVAs y especiales, ubicados junto a la temporada con la que están relacionados.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable

from .detectar import Deteccion, normalizar

FORMATOS_SERIE = {'TV', 'TV_SHORT', 'ONA'}
_TIPO_EXTRA = {'MOVIE': 'pelicula', 'OVA': 'ova'}
NOMBRE_TIPO = {'temporada': 'Temporada', 'pelicula': 'Película', 'ova': 'OVA', 'especial': 'Especial'}
FUERA_DE_CADENA = 1_000_000

# Entradas que continúan la temporada anterior en vez de empezar una nueva.
_CONTINUACION = re.compile(
    r'\b(?:part|parte|cour)\s*(?:[2-9]|ii|iii|iv)\b|\b(?:2nd|3rd|[4-9]th)\s*cour\b|\b(?:chuuhen|kouhen)\b', re.I)
# Lo que se ignora al comparar títulos para saber si dos entradas son la misma subserie.
_MARCAS = re.compile(
    r'\b(?:\d+(?:st|nd|rd|th)?\s*season|season\s*\d+|(?:second|third|fourth|fifth|final)\s*season|'
    r'part\s*\d+|cour\s*\d+|\d+(?:st|nd|rd|th)\s*cour|zenpen|chuuhen|kouhen|kanketsu\s*hen|'
    r'ii|iii|iv|v|vi|vii|\d+)\b')


class NoReconocido(Exception):
    pass


def _fecha(m: dict) -> int:
    f = m.get('startDate') or {}
    return (f.get('year') or 9999) * 10000 + (f.get('month') or 99) * 100 + (f.get('day') or 99)


def _relaciones(m: dict, tipos: tuple[str, ...]) -> list[dict]:
    return [e['node'] for e in (m.get('relations') or {}).get('edges') or []
            if e['relationType'] in tipos and e['node'].get('type') == 'ANIME']


def _es_serie(m: dict) -> bool:
    return m.get('format') in FORMATOS_SERIE


def _bases(m: dict) -> list[str]:
    bases = []
    for titulo in filter(None, [(m.get('title') or {}).get('romaji'), (m.get('title') or {}).get('english')]):
        completo = normalizar(titulo)
        base = re.sub(r'\s+', ' ', _MARCAS.sub(' ', completo)).strip()
        bases.append(base or completo)
    return bases


def _misma_subserie(bases_subserie: list[str], m: dict) -> bool:
    return any(b == s or b.startswith(s + ' ') for s in bases_subserie for b in _bases(m))


@dataclass
class Seccion:
    clave: str             # 'T:<subserie>:<n>' para temporadas, 'M:<id AniList>' para el resto
    tipo: str              # temporada | pelicula | ova | especial
    numero: int | None     # número de temporada dentro de su subserie
    subserie: str
    subserie_id: int
    titulo: str
    medias: list[dict]
    orden: tuple[int, int]

    @property
    def total(self) -> int | None:
        episodios = [m.get('episodes') for m in self.medias]
        return sum(episodios) if all(episodios) else None

    @property
    def media_id(self) -> int:
        return self.medias[0]['id']

    def nombre(self, varias_subseries: bool) -> str:
        if self.tipo == 'temporada':
            return f'{self.subserie} · Temporada {self.numero}' if varias_subseries else f'Temporada {self.numero}'
        return f'{NOMBRE_TIPO[self.tipo]} · {self.titulo}'


@dataclass
class Resultado:
    raiz: dict
    seccion: Seccion
    episodio: int
    media: dict
    varias_subseries: bool

    @property
    def ubicacion(self) -> str:
        s = self.seccion
        if s.tipo == 'temporada':
            prefijo = f'{s.subserie} · ' if self.varias_subseries else ''
            return f'{prefijo}T{s.numero} E{self.episodio:02d}'
        episodio = f' E{self.episodio:02d}' if (s.total or 1) > 1 else ''
        return f'{NOMBRE_TIPO[s.tipo]}: {s.titulo}{episodio}'


class Resolver:
    def __init__(self, anilist, correcciones: Callable[[], dict[str, int]], idioma: str = 'romaji'):
        self.al = anilist
        self.correcciones = correcciones
        self.idioma = idioma

    def titulo(self, m: dict) -> str:
        t = m.get('title') or {}
        if self.idioma == 'english':
            return t.get('english') or t.get('romaji') or str(m['id'])
        return t.get('romaji') or t.get('english') or str(m['id'])

    def _media(self, id_: int) -> dict:
        m = self.al.media(id_)
        if not m:
            raise NoReconocido(f'AniList no tiene el ID {id_}.')
        return m

    # --- qué anime es ---
    def elegir(self, det: Deteccion) -> dict:
        if not det.titulo:
            raise NoReconocido('No pude sacar el nombre del anime del archivo ni de sus carpetas.')
        correcciones = self.correcciones()
        for clave in ([f'{det.titulo} T{det.temporada}'] if det.temporada else []) + [det.titulo]:
            if normalizar(clave) in correcciones:
                return self._media(correcciones[normalizar(clave)])

        candidatos = self.al.buscar(det.titulo)
        buscado = normalizar(det.titulo)
        mejor, puntaje = None, 0.0
        for i, m in enumerate(candidatos):
            nombres = [m['title'].get('romaji'), m['title'].get('english'), *(m.get('synonyms') or [])]
            parecido = max((SequenceMatcher(None, buscado, normalizar(n)).ratio() for n in nombres if n), default=0)
            if det.es_pelicula:
                parecido += 0.15 if m.get('format') == 'MOVIE' else 0
            elif _es_serie(m):
                parecido += 0.1
            if not det.es_pelicula and (det.episodio or 0) > 1 and m.get('episodes') == 1:
                parecido -= 0.3  # "Algo - 05" no puede ser una película de un solo episodio
            parecido += 0.05 * (1 - i / len(candidatos))  # AniList ya los ordena por relevancia
            if parecido > puntaje:
                mejor, puntaje = m, parecido
        if not mejor or puntaje < 0.6:
            raise NoReconocido(f'AniList no encontró "{det.titulo}" con seguridad.')
        return mejor

    # --- la franquicia ---
    def _vecina(self, m: dict, tipo: str, vistos: set[int]) -> dict | None:
        """Anterior (PREQUEL) o siguiente (SEQUEL) en el tiempo; prefiere temporadas a películas."""
        antes = tipo == 'PREQUEL'
        nodos = [n for n in _relaciones(m, (tipo,)) if n['id'] not in vistos
                 and (_fecha(n) < _fecha(m) if antes else _fecha(n) > _fecha(m))]
        if not nodos:
            return None
        series = [n for n in nodos if _es_serie(n)]
        elegido = (max if antes else min)(series or nodos, key=_fecha)
        return self._media(elegido['id'])

    def raiz(self, m: dict, _profundidad: int = 0) -> dict:
        vistos = {m['id']}
        while (anterior := self._vecina(m, 'PREQUEL', vistos)) is not None:
            m = anterior
            vistos.add(m['id'])
        if not _es_serie(m) and _profundidad < 2:
            # Película u OVA sin precuela: se cuelga de la serie a la que pertenece.
            for tipo in ('PARENT', 'SEQUEL'):
                series = [n for n in _relaciones(m, (tipo,)) if _es_serie(n) and n['id'] not in vistos]
                if series:
                    return self.raiz(self._media(min(series, key=_fecha)['id']), _profundidad + 1)
        return m

    def cadena(self, raiz: dict) -> list[dict]:
        cadena, vistos = [raiz], {raiz['id']}
        while len(cadena) < 80 and (siguiente := self._vecina(cadena[-1], 'SEQUEL', vistos)) is not None:
            vistos.add(siguiente['id'])
            cadena.append(siguiente)
        return cadena

    def secciones(self, cadena: list[dict]) -> tuple[list[Seccion], bool]:
        secciones: list[Seccion] = []
        subserie = None  # (id, título, bases, temporadas hasta ahora)
        cantidad_subseries = 0
        for i, m in enumerate(cadena):
            if not _es_serie(m):
                sub_id, sub_titulo = (subserie[0], subserie[1]) if subserie else (m['id'], self.titulo(m))
                secciones.append(Seccion(f'M:{m["id"]}', _TIPO_EXTRA.get(m.get('format'), 'especial'), None,
                                         sub_titulo, sub_id, self.titulo(m), [m], (2 * i, 0)))
                continue
            if subserie is None or not _misma_subserie(subserie[2], m):
                subserie = [m['id'], self.titulo(m), _bases(m), 0]
                cantidad_subseries += 1
            nombres = ' '.join(filter(None, [m['title'].get('romaji'), m['title'].get('english')]))
            previa = next((s for s in reversed(secciones) if s.tipo == 'temporada'), None)
            if previa and previa.subserie_id == subserie[0] and _CONTINUACION.search(nombres):
                previa.medias.append(m)
                continue
            subserie[3] += 1
            secciones.append(Seccion(f'T:{subserie[0]}:{subserie[3]}', 'temporada', subserie[3], subserie[1],
                                     subserie[0], self.titulo(m), [m], (2 * i, 0)))
        return secciones, cantidad_subseries > 1

    def _extra_suelto(self, m: dict, cadena: list[dict], secciones: list[Seccion]) -> Seccion:
        """Película u OVA que no está en la línea principal: va junto a la entrada con la que se relaciona."""
        posicion = {media['id']: i for i, media in enumerate(cadena)}
        # Después de su precuela (o de la serie madre); si no, antes de su secuela; si no, al final.
        indice, corrimiento = None, 0
        for tipos, corr, elegir in ((('PREQUEL', 'PARENT'), 1, max), (('SEQUEL',), -1, min)):
            indices = [posicion[n['id']] for n in _relaciones(m, tipos) if n['id'] in posicion]
            if indices:
                indice, corrimiento = elegir(indices), corr
                break
        if indice is None:
            duena, orden = (secciones[0] if secciones else None), (FUERA_DE_CADENA, _fecha(m))
        else:
            duena = next(s for s in secciones if any(x['id'] == cadena[indice]['id'] for x in s.medias))
            orden = (2 * indice + corrimiento, _fecha(m))
        sub_id, sub_titulo = (duena.subserie_id, duena.subserie) if duena else (m['id'], self.titulo(m))
        return Seccion(f'M:{m["id"]}', _TIPO_EXTRA.get(m.get('format'), 'especial'), None,
                       sub_titulo, sub_id, self.titulo(m), [m], orden)

    # --- el archivo concreto ---
    def resolver(self, det: Deteccion, forzado: int | None = None) -> Resultado:
        """`forzado`: ID de AniList elegido a mano para este archivo."""
        media = self._media(forzado) if forzado else self.elegir(det)
        raiz = self.raiz(media)
        cadena = self.cadena(raiz)
        secciones, varias = self.secciones(cadena)
        de_media = {m['id']: s for s in secciones for m in s.medias}

        if media['id'] not in de_media:
            if _es_serie(media):
                # Serie que se abre de otra rama (p. ej. un spin-off): tiene su propio canal.
                raiz, cadena = media, self.cadena(media)
                secciones, varias = self.secciones(cadena)
                de_media = {m['id']: s for s in secciones for m in s.medias}
            else:
                seccion = self._extra_suelto(media, cadena, secciones)
                return Resultado(raiz, seccion, self._episodio_extra(det, media), media, varias)

        seccion = de_media[media['id']]
        if seccion.tipo != 'temporada':
            return Resultado(raiz, seccion, self._episodio_extra(det, media), media, varias)

        temporadas = [s for s in secciones if s.tipo == 'temporada' and s.subserie_id == seccion.subserie_id]
        es_base = media['id'] == seccion.subserie_id
        if es_base and det.temporada is None:
            return self._absoluto(raiz, temporadas, det, media, varias)
        if es_base:
            if det.temporada > len(temporadas):
                raise NoReconocido(f'AniList tiene {len(temporadas)} temporada(s) de "{seccion.subserie}" '
                                   f'y el archivo dice T{det.temporada}.')
            seccion, parte = temporadas[det.temporada - 1], det.parte or 1
        else:
            parte = det.parte or next(i for i, m in enumerate(seccion.medias, 1) if m['id'] == media['id'])

        ep = self._episodio(det, media)
        # "Parte 2 - 01" se vuelve el episodio que sigue a la parte 1 (p. ej. 13).
        anteriores = [m.get('episodes') for m in seccion.medias[:parte - 1]]
        if parte > 1 and all(anteriores) and ep <= sum(anteriores):
            ep += sum(anteriores)
        # Numeración corrida ("Jujutsu Kaisen S2 - 30"): se restan las temporadas previas.
        previas = [t.total for t in temporadas[:temporadas.index(seccion)]]
        if seccion.total and ep > seccion.total and all(previas) and 0 < ep - sum(previas) <= seccion.total:
            ep -= sum(previas)
        return Resultado(raiz, seccion, ep, media, varias)

    def _episodio(self, det: Deteccion, media: dict) -> int:
        if det.episodio is not None:
            return det.episodio
        if media.get('episodes') == 1:
            return 1
        raise NoReconocido('No encontré el número de episodio en el nombre del archivo.')

    @staticmethod
    def _episodio_extra(det: Deteccion, media: dict) -> int:
        return det.episodio if det.episodio and (media.get('episodes') or 0) > 1 else 1

    def _absoluto(self, raiz, temporadas: list[Seccion], det: Deteccion, media, varias) -> Resultado:
        """Sin temporada en el nombre: "Jujutsu Kaisen - 30" es el episodio 6 de la T2."""
        resto = self._episodio(det, media)
        for t in temporadas:
            if t.total is None or resto <= t.total:
                return Resultado(raiz, t, resto, media, varias)
            resto -= t.total
        t = temporadas[-1]  # más episodios de los que AniList conoce
        return Resultado(raiz, t, resto + t.total, media, varias)
