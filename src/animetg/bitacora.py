"""Registro de actividad: archivo rotativo en data/logs y, si hay interfaz, eventos en vivo."""
import logging
from logging.handlers import RotatingFileHandler

from .rutas import Rutas

FORMATO = '%(asctime)s  %(levelname)-7s %(name)s: %(message)s'
log = logging.getLogger('animetg')


def configurar(rutas: Rutas, consola: bool = False) -> logging.Logger:
    if getattr(log, '_configurado', False):
        return log
    rutas.logs.mkdir(parents=True, exist_ok=True)
    archivo = RotatingFileHandler(rutas.logs / 'animetg.log', maxBytes=2_000_000, backupCount=5, encoding='utf-8')
    archivo.setFormatter(logging.Formatter(FORMATO, '%Y-%m-%d %H:%M:%S'))
    raiz = logging.getLogger()
    raiz.addHandler(archivo)
    raiz.setLevel(logging.WARNING)       # librerías: solo avisos y errores
    log.setLevel(logging.INFO)
    if consola:
        from rich.logging import RichHandler
        log.addHandler(RichHandler(show_path=False, markup=False, rich_tracebacks=True))
    log._configurado = True
    return log


class ManejadorEventos(logging.Handler):
    """Manda cada línea del registro a la interfaz (thread-safe: el bus se encarga)."""

    def __init__(self, bus):
        super().__init__(logging.INFO)
        self.bus = bus

    def emit(self, registro: logging.LogRecord) -> None:
        try:
            self.bus.publicar('log', {
                'hora': registro.created,
                'nivel': registro.levelname,
                'mensaje': registro.getMessage(),
            })
        except Exception:  # el registro nunca debe tirar abajo la app
            self.handleError(registro)
