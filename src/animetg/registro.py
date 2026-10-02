"""Base de datos local: canales, secciones, episodios subidos, correcciones y caché.

El esquema se versiona con PRAGMA user_version; `_MIGRACIONES[n]` lleva de la versión n a la n+1.
"""
import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

VERSION = 2

_V2 = '''
CREATE TABLE IF NOT EXISTS cache (
    clave TEXT PRIMARY KEY, valor TEXT NOT NULL, fecha REAL NOT NULL);
CREATE TABLE IF NOT EXISTS series (
    raiz INTEGER PRIMARY KEY, titulo TEXT NOT NULL,
    canal_id INTEGER NOT NULL, canal_hash INTEGER NOT NULL,
    ficha_msg INTEGER, ficha_idioma TEXT, indice TEXT NOT NULL DEFAULT '[]',
    varias_subseries INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS secciones (
    raiz INTEGER NOT NULL, clave TEXT NOT NULL,
    tipo TEXT NOT NULL,              -- temporada | pelicula | ova | especial
    numero INTEGER,                  -- temporada dentro de su subserie
    subserie TEXT, subserie_id INTEGER,
    titulo TEXT NOT NULL, total INTEGER, media_id INTEGER,
    orden_a INTEGER NOT NULL, orden_b INTEGER NOT NULL DEFAULT 0,
    separador_msg INTEGER,
    PRIMARY KEY (raiz, clave));
CREATE TABLE IF NOT EXISTS episodios (
    raiz INTEGER NOT NULL, seccion TEXT NOT NULL, episodio INTEGER NOT NULL,
    parte INTEGER NOT NULL, partes INTEGER NOT NULL,
    msg_id INTEGER NOT NULL, archivo TEXT, tamano INTEGER, segundos REAL, fecha TEXT,
    PRIMARY KEY (raiz, seccion, episodio, parte));
CREATE TABLE IF NOT EXISTS correcciones (
    clave TEXT PRIMARY KEY, texto TEXT NOT NULL, media_id INTEGER NOT NULL);
'''


def _v1_a_v2(db: sqlite3.Connection) -> None:
    """Versión 1 (temporadas numeradas, especiales en la temporada 0) -> secciones."""
    db.execute('ALTER TABLE series RENAME TO series_v1')
    db.execute('ALTER TABLE temporadas RENAME TO temporadas_v1')
    db.execute('ALTER TABLE episodios RENAME TO episodios_v1')
    db.executescript(_V2)
    db.execute('''INSERT INTO series (raiz, titulo, canal_id, canal_hash, ficha_msg, ficha_idioma, indice)
                  SELECT raiz, titulo, canal_id, canal_hash, ficha_msg, 'en', indice FROM series_v1''')
    titulos = dict(db.execute('SELECT raiz, titulo FROM series_v1').fetchall())
    for raiz, numero, titulo, total, separador in db.execute(
            'SELECT raiz, numero, titulo, total, separador_msg FROM temporadas_v1 WHERE numero > 0').fetchall():
        db.execute('''INSERT INTO secciones (raiz, clave, tipo, numero, subserie, subserie_id, titulo, total,
                      orden_a, orden_b, separador_msg) VALUES (?, ?, 'temporada', ?, ?, ?, ?, ?, ?, 0, ?)''',
                   (raiz, f'T:{raiz}:{numero}', numero, titulos.get(raiz), raiz, titulo, total, (numero - 1) * 2,
                    separador))
    for fila in db.execute('SELECT * FROM episodios_v1').fetchall():
        raiz, temporada, episodio, parte, partes, etiqueta, msg_id, archivo, fecha = fila
        if temporada == 0:  # en la v1 el episodio especial era media_id * 1000 + número
            media_id, numero = divmod(episodio, 1000)
            clave = f'M:{media_id}'
            db.execute('''INSERT OR IGNORE INTO secciones (raiz, clave, tipo, titulo, media_id, orden_a, orden_b)
                          VALUES (?, ?, 'especial', ?, ?, 1000000, ?)''',
                       (raiz, clave, (etiqueta or '').split(' · ')[0] or 'Especial', media_id, media_id))
            episodio = numero or 1
        else:
            clave = f'T:{raiz}:{temporada}'
        db.execute('INSERT OR REPLACE INTO episodios VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)',
                   (raiz, clave, episodio, parte, partes, msg_id, archivo, fecha))
    db.execute('DROP TABLE series_v1')
    db.execute('DROP TABLE temporadas_v1')
    db.execute('DROP TABLE episodios_v1')


_MIGRACIONES = {1: _v1_a_v2}


class Registro:
    def __init__(self, ruta: Path):
        # Se usa desde el hilo de la app y desde hilos auxiliares: un candado serializa todo.
        self._candado = threading.RLock()
        self.db = sqlite3.connect(ruta, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self._migrar()

    def _migrar(self) -> None:
        with self._candado, self.db:
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            hay_tablas = self.db.execute("SELECT count(*) FROM sqlite_master WHERE name = 'series'").fetchone()[0]
            if version == 0 and hay_tablas:
                version = 1  # base creada por la versión 1, que no numeraba el esquema
            if version == 0:
                self.db.executescript(_V2)
            else:
                while version < VERSION:
                    _MIGRACIONES[version](self.db)
                    version += 1
            self.db.execute(f'PRAGMA user_version = {VERSION}')

    def _todas(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._candado:
            return self.db.execute(sql, args).fetchall()

    def _una(self, sql: str, args=()) -> sqlite3.Row | None:
        with self._candado:
            return self.db.execute(sql, args).fetchone()

    def _escribir(self, sql: str, args=()) -> None:
        with self._candado, self.db:
            self.db.execute(sql, args)

    # --- caché (AniList, traducciones) ---
    def cache_leer(self, clave: str):
        fila = self._una('SELECT valor, fecha FROM cache WHERE clave = ?', (clave,))
        if not fila:
            return None, None
        return json.loads(fila['valor']), time.time() - fila['fecha']

    def cache_guardar(self, clave: str, valor) -> None:
        self._escribir('INSERT OR REPLACE INTO cache VALUES (?, ?, ?)', (clave, json.dumps(valor), time.time()))

    # --- correcciones manuales ---
    def correcciones(self) -> dict[str, int]:
        return {f['clave']: f['media_id'] for f in self._todas('SELECT clave, media_id FROM correcciones')}

    def guardar_correccion(self, clave: str, texto: str, media_id: int) -> None:
        self._escribir('INSERT OR REPLACE INTO correcciones VALUES (?, ?, ?)', (clave, texto, media_id))

    # --- canales ---
    def serie(self, raiz: int) -> sqlite3.Row | None:
        return self._una('SELECT * FROM series WHERE raiz = ?', (raiz,))

    def series(self) -> list[sqlite3.Row]:
        return self._todas('SELECT * FROM series ORDER BY titulo COLLATE NOCASE')

    def guardar_serie(self, raiz: int, titulo: str, canal_id: int, canal_hash: int) -> None:
        self._escribir('INSERT OR REPLACE INTO series (raiz, titulo, canal_id, canal_hash) VALUES (?, ?, ?, ?)',
                       (raiz, titulo, canal_id, canal_hash))

    def guardar_ficha(self, raiz: int, msg_id: int, idioma: str) -> None:
        self._escribir('UPDATE series SET ficha_msg = ?, ficha_idioma = ? WHERE raiz = ?', (msg_id, idioma, raiz))

    def marcar_subseries(self, raiz: int, varias: bool) -> None:
        self._escribir('UPDATE series SET varias_subseries = ? WHERE raiz = ?', (int(varias), raiz))

    def indice(self, raiz: int) -> list[dict]:
        return json.loads(self.serie(raiz)['indice'])

    def guardar_indice(self, raiz: int, mensajes: list[dict]) -> None:
        self._escribir('UPDATE series SET indice = ? WHERE raiz = ?', (json.dumps(mensajes), raiz))

    def olvidar_serie(self, raiz: int) -> None:
        with self._candado, self.db:
            for tabla in ('series', 'secciones', 'episodios'):
                self.db.execute(f'DELETE FROM {tabla} WHERE raiz = ?', (raiz,))

    # --- secciones (temporadas, películas, OVAs) ---
    def guardar_seccion(self, raiz: int, s) -> None:
        """Crea o actualiza la sección sin perder su separador ya publicado."""
        self._escribir('''
            INSERT INTO secciones (raiz, clave, tipo, numero, subserie, subserie_id, titulo, total, media_id,
                                   orden_a, orden_b)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (raiz, clave) DO UPDATE SET tipo = excluded.tipo, numero = excluded.numero,
                subserie = excluded.subserie, subserie_id = excluded.subserie_id, titulo = excluded.titulo,
                total = excluded.total, media_id = excluded.media_id,
                orden_a = excluded.orden_a, orden_b = excluded.orden_b''',
            (raiz, s.clave, s.tipo, s.numero, s.subserie, s.subserie_id, s.titulo, s.total, s.media_id,
             s.orden[0], s.orden[1]))

    def seccion(self, raiz: int, clave: str) -> sqlite3.Row | None:
        return self._una('SELECT * FROM secciones WHERE raiz = ? AND clave = ?', (raiz, clave))

    def secciones(self, raiz: int) -> list[sqlite3.Row]:
        return self._todas('SELECT * FROM secciones WHERE raiz = ? ORDER BY orden_a, orden_b, clave', (raiz,))

    def guardar_separador(self, raiz: int, clave: str, msg_id: int) -> None:
        self._escribir('UPDATE secciones SET separador_msg = ? WHERE raiz = ? AND clave = ?', (msg_id, raiz, clave))

    # --- episodios ---
    def partes_subidas(self, raiz: int, seccion: str, episodio: int) -> tuple[set[int], int | None]:
        filas = self._todas('SELECT parte, partes FROM episodios WHERE raiz = ? AND seccion = ? AND episodio = ?',
                            (raiz, seccion, episodio))
        return {f['parte'] for f in filas}, (filas[0]['partes'] if filas else None)

    def mensajes_episodio(self, raiz: int, seccion: str, episodio: int) -> list[int]:
        return [f['msg_id'] for f in self._todas(
            'SELECT msg_id FROM episodios WHERE raiz = ? AND seccion = ? AND episodio = ? ORDER BY parte',
            (raiz, seccion, episodio))]

    def recortar_partes(self, raiz: int, seccion: str, episodio: int, partes: int) -> None:
        """Al reemplazar un episodio que tenía más partes que la versión nueva."""
        self._escribir('DELETE FROM episodios WHERE raiz = ? AND seccion = ? AND episodio = ? AND parte > ?',
                       (raiz, seccion, episodio, partes))

    def guardar_episodio(self, raiz: int, seccion: str, episodio: int, parte: int, partes: int,
                         msg_id: int, archivo: str, tamano: int, segundos: float) -> None:
        self._escribir('INSERT OR REPLACE INTO episodios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (raiz, seccion, episodio, parte, partes, msg_id, archivo, tamano, segundos,
                        datetime.now().isoformat(timespec='seconds')))

    def episodios(self, raiz: int) -> list[sqlite3.Row]:
        return self._todas('''SELECT e.* FROM episodios e JOIN secciones s ON s.raiz = e.raiz AND s.clave = e.seccion
                              WHERE e.raiz = ? ORDER BY s.orden_a, s.orden_b, s.clave, e.episodio, e.parte''', (raiz,))

    def resumen_series(self) -> list[sqlite3.Row]:
        return self._todas('''
            SELECT se.raiz, se.titulo, se.canal_id, se.ficha_msg,
                   COUNT(DISTINCT e.seccion || ':' || e.episodio) AS episodios,
                   COALESCE(SUM(e.tamano), 0) AS tamano, MAX(e.fecha) AS ultima,
                   (SELECT COUNT(*) FROM secciones s WHERE s.raiz = se.raiz) AS secciones
            FROM series se LEFT JOIN episodios e ON e.raiz = se.raiz
            GROUP BY se.raiz ORDER BY se.titulo COLLATE NOCASE''')

    def recientes(self, cantidad: int = 20) -> list[sqlite3.Row]:
        return self._todas('''SELECT e.*, s.tipo, s.numero, s.titulo AS seccion_titulo, s.media_id,
                                     se.titulo AS serie_titulo
                              FROM episodios e JOIN secciones s ON s.raiz = e.raiz AND s.clave = e.seccion
                              JOIN series se ON se.raiz = e.raiz
                              WHERE e.parte = 1 ORDER BY e.fecha DESC LIMIT ?''', (cantidad,))

    def cambiar_mensajes(self, raiz: int, mapa: dict[int, int]) -> None:
        """Después de reordenar: cada mensaje viejo pasa a apuntar a su copia nueva."""
        with self._candado, self.db:
            for viejo, nuevo in mapa.items():
                self.db.execute('UPDATE episodios SET msg_id = ? WHERE raiz = ? AND msg_id = ?', (nuevo, raiz, viejo))
                self.db.execute('UPDATE secciones SET separador_msg = ? WHERE raiz = ? AND separador_msg = ?',
                                (nuevo, raiz, viejo))

    def quitar_mensajes(self, raiz: int, ids: list[int]) -> None:
        """Olvida mensajes que ya no existen en Telegram (por ejemplo, borrados a mano)."""
        with self._candado, self.db:
            for i in ids:
                self.db.execute('DELETE FROM episodios WHERE raiz = ? AND msg_id = ?', (raiz, i))
                self.db.execute('UPDATE secciones SET separador_msg = NULL WHERE raiz = ? AND separador_msg = ?',
                                (raiz, i))

    def cerrar(self) -> None:
        with self._candado:
            self.db.close()
