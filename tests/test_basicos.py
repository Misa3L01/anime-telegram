"""Ajustes, traductor y base de datos."""
import sqlite3

from animetg.ajustes import Ajustes
from animetg.registro import VERSION, Registro
from animetg.traductor import Traductor, limpiar_sinopsis


# --- ajustes ---
def test_ajustes_validan_y_persisten(tmp_path):
    a = Ajustes()
    errores = a.actualizar({'conexiones': 99, 'idioma_sinopsis': 'fr', 'premium': 'true', 'carpeta_subir': ''})
    assert len(errores) == 3 and a.conexiones == 8 and a.premium is True and a.carpeta_subir
    assert a.limite_bytes == 4000 * 1024 * 1024
    a.premium = False
    assert a.limite_bytes == 2000 * 1024 * 1024
    a.premium = True
    a.guardar(tmp_path / 'ajustes.json')
    assert Ajustes.cargar(tmp_path / 'ajustes.json').premium is True


def test_ajustes_ignoran_claves_desconocidas(tmp_path):
    (tmp_path / 'ajustes.json').write_text('{"conexiones": 4, "algo_viejo": 1}', encoding='utf-8')
    assert Ajustes.cargar(tmp_path / 'ajustes.json').conexiones == 4


# --- traductor ---
class _Cache:
    def __init__(self):
        self.d = {}

    def cache_leer(self, k):
        return (self.d[k], 0) if k in self.d else (None, None)

    def cache_guardar(self, k, v):
        self.d[k] = v


def test_limpia_html_y_notas_de_fuente():
    texto = 'Una <i>maga</i> elfa.<br><br>\n\n\n(Source: Crunchyroll)\nNote: lo que sea'
    assert limpiar_sinopsis(texto) == 'Una maga elfa.'


def test_traduce_una_vez_y_guarda(monkeypatch):
    llamadas = []
    monkeypatch.setattr(Traductor, '_pedir', lambda self, t, d: llamadas.append(t) or f'ES:{t}')
    t = Traductor(_Cache())
    assert t.traducir('Hello', 'es') == t.traducir('Hello', 'es') == 'ES:Hello'
    assert len(llamadas) == 1
    assert t.traducir('Hello', 'en') == 'Hello'


def test_si_falla_queda_en_ingles(monkeypatch):
    def falla(*_):
        raise OSError('sin red')
    monkeypatch.setattr(Traductor, '_pedir', falla)
    assert Traductor(_Cache()).traducir('Hello', 'es') == 'Hello'


# --- base de datos ---
_V1 = '''
CREATE TABLE cache (clave TEXT PRIMARY KEY, valor TEXT NOT NULL, fecha REAL NOT NULL);
CREATE TABLE series (raiz INTEGER PRIMARY KEY, titulo TEXT NOT NULL, canal_id INTEGER NOT NULL,
    canal_hash INTEGER NOT NULL, ficha_msg INTEGER, indice TEXT NOT NULL DEFAULT '[]');
CREATE TABLE temporadas (raiz INTEGER, numero INTEGER, titulo TEXT, total INTEGER, separador_msg INTEGER,
    PRIMARY KEY (raiz, numero));
CREATE TABLE episodios (raiz INTEGER, temporada INTEGER, episodio INTEGER, parte INTEGER, partes INTEGER,
    etiqueta TEXT, msg_id INTEGER, archivo TEXT, fecha TEXT, PRIMARY KEY (raiz, temporada, episodio, parte));
INSERT INTO series VALUES (114979, 'Love Live! Superstar!!', 37, 15, 3, '[{"id": 5, "texto": "x"}]');
INSERT INTO temporadas VALUES (114979, 1, 'Love Live! Superstar!!', 12, 7);
INSERT INTO temporadas VALUES (114979, 2, 'Love Live! Superstar!! 2nd Season', 12, 14);
INSERT INTO temporadas VALUES (114979, 0, 'Especiales y películas', NULL, 20);
INSERT INTO episodios VALUES (114979, 1, 7, 1, 1, '07', 13, 'a.mkv', '2026-09-30T20:42:34');
INSERT INTO episodios VALUES (114979, 2, 8, 1, 1, '08', 15, 'b.mkv', '2026-09-30T20:49:48');
INSERT INTO episodios VALUES (114979, 0, 155455000, 1, 1, 'Pelicula X', 21, 'c.mkv', '2026-09-30T21:00:00');
'''


def test_migra_la_base_de_la_version_1(tmp_path):
    ruta = tmp_path / 'registro.db'
    db = sqlite3.connect(ruta)
    db.executescript(_V1)
    db.close()
    reg = Registro(ruta)
    assert reg.db.execute('PRAGMA user_version').fetchone()[0] == VERSION
    serie = reg.serie(114979)
    assert (serie['ficha_idioma'], reg.indice(114979)) == ('en', [{'id': 5, 'texto': 'x'}])
    secciones = {s['clave']: s for s in reg.secciones(114979)}
    assert secciones['T:114979:2']['separador_msg'] == 14
    assert secciones['M:155455']['tipo'] == 'especial'
    episodios = {(e['seccion'], e['episodio']): e['msg_id'] for e in reg.episodios(114979)}
    assert episodios == {('T:114979:1', 7): 13, ('T:114979:2', 8): 15, ('M:155455', 1): 21}
    assert reg.partes_subidas(114979, 'T:114979:1', 7) == ({1}, 1)


def test_base_nueva_arranca_en_la_ultima_version(tmp_path):
    reg = Registro(tmp_path / 'nueva.db')
    assert reg.db.execute('PRAGMA user_version').fetchone()[0] == VERSION
    assert reg.series() == []
