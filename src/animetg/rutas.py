"""Ubicaciones de la aplicación. Todo lo que genera en uso vive dentro de `data/`."""
import os
from dataclasses import dataclass
from pathlib import Path

PAQUETE = Path(__file__).resolve().parent
PROYECTO = PAQUETE.parent.parent
ESTATICOS = PAQUETE / 'web' / 'estaticos'
ICONO = ESTATICOS / 'icono.ico'


@dataclass(frozen=True)
class Rutas:
    datos: Path

    @property
    def db(self) -> Path:
        return self.datos / 'registro.db'

    @property
    def ajustes(self) -> Path:
        return self.datos / 'ajustes.json'

    @property
    def portadas(self) -> Path:
        return self.datos / 'cache' / 'portadas'

    @property
    def temporal(self) -> Path:
        return self.datos / 'temp'

    @property
    def logs(self) -> Path:
        return self.datos / 'logs'

    @property
    def instancia(self) -> Path:
        return self.datos / 'instancia.json'

    @property
    def webview(self) -> Path:
        return self.datos / 'webview'

    def crear(self) -> 'Rutas':
        for carpeta in (self.datos, self.portadas, self.temporal, self.logs, self.webview):
            carpeta.mkdir(parents=True, exist_ok=True)
        return self


def por_defecto() -> Rutas:
    """`ANIMETG_DATOS` permite usar otra carpeta (pruebas, modo demostración)."""
    return Rutas(Path(os.environ.get('ANIMETG_DATOS') or PROYECTO / 'data'))
