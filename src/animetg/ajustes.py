"""Preferencias del usuario (data/ajustes.json). Las credenciales van aparte, en `credenciales`."""
import json
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

_OPCIONES = {
    'idioma_titulo': ('romaji', 'english'),
    'idioma_sinopsis': ('es', 'en'),
    'repetidos': ('mover', 'reemplazar'),
}
_RANGOS = {
    'conexiones': (1, 16),
    'segundos_escaneo': (5, 600),
    'limite_mb': (0, 4000),
}


@dataclass
class Ajustes:
    carpeta_subir: str = r'R:\Anime\Subir'
    carpeta_subidos: str = r'R:\Anime\Subidos'
    carpeta_telegram: str = 'Anime'
    idioma_titulo: str = 'romaji'
    idioma_sinopsis: str = 'es'
    premium: bool = False
    subida_automatica: bool = True
    ordenar_automatico: bool = True
    repetidos: str = 'mover'  # si llega un episodio ya subido: 'mover' a _repetidos o 'reemplazar' el de Telegram
    conexiones: int = 8
    segundos_escaneo: int = 15
    limite_mb: int = 0  # 0 = automático según Premium
    ffmpeg: str = 'ffmpeg'
    ffprobe: str = 'ffprobe'
    siete_zip: str = r'C:\Program Files\7-Zip\7z.exe'

    @property
    def entrada(self) -> Path:
        return Path(self.carpeta_subir)

    @property
    def subidos(self) -> Path:
        return Path(self.carpeta_subidos)

    @property
    def limite_bytes(self) -> int:
        # Con margen: Telegram rechaza archivos que llegan justo a su límite (2 GB normal, 4 GB Premium).
        mb = self.limite_mb or (3900 if self.premium else 1950)
        return mb * 1024 * 1024

    def programa(self, nombre: str) -> str:
        valor = getattr(self, nombre)
        return shutil.which(valor) or valor

    def programa_disponible(self, nombre: str) -> bool:
        return Path(self.programa(nombre)).exists()

    def como_dict(self) -> dict:
        return asdict(self)

    def actualizar(self, cambios: dict) -> list[str]:
        """Aplica solo cambios válidos; devuelve los errores encontrados."""
        errores, tipos = [], {f.name: f.type for f in fields(self)}
        for clave, valor in cambios.items():
            if clave not in tipos:
                continue
            tipo = tipos[clave]
            try:
                if tipo in (bool, 'bool'):
                    valor = valor if isinstance(valor, bool) else str(valor).lower() in ('1', 'true', 'si', 'sí')
                elif tipo in (int, 'int'):
                    valor = int(valor)
                else:
                    valor = str(valor).strip()
            except (TypeError, ValueError):
                errores.append(f'{clave}: valor inválido')
                continue
            if clave in _OPCIONES and valor not in _OPCIONES[clave]:
                errores.append(f'{clave}: debe ser uno de {", ".join(_OPCIONES[clave])}')
                continue
            if clave in _RANGOS and not _RANGOS[clave][0] <= valor <= _RANGOS[clave][1]:
                errores.append(f'{clave}: debe estar entre {_RANGOS[clave][0]} y {_RANGOS[clave][1]}')
                continue
            if clave.startswith('carpeta_subi') and not valor:
                errores.append(f'{clave}: no puede quedar vacía')
                continue
            setattr(self, clave, valor)
        return errores

    @classmethod
    def cargar(cls, ruta: Path) -> 'Ajustes':
        ajustes = cls()
        if ruta.exists():
            ajustes.actualizar(json.loads(ruta.read_text(encoding='utf-8')))
        return ajustes

    def guardar(self, ruta: Path) -> None:
        temporal = ruta.with_suffix('.tmp')
        temporal.write_text(json.dumps(self.como_dict(), indent=2, ensure_ascii=False), encoding='utf-8')
        temporal.replace(ruta)
