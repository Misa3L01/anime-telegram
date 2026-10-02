"""Credenciales de Telegram guardadas en el Administrador de credenciales de Windows.

Ni el api_hash ni la sesión (que da acceso a la cuenta) quedan en archivos de texto.
"""
import keyring
from keyring.errors import PasswordDeleteError

SERVICIO = 'anime-telegram'


class Credenciales:
    def __init__(self, servicio: str = SERVICIO):
        self.servicio = servicio

    def _leer(self, clave: str) -> str | None:
        return keyring.get_password(self.servicio, clave)

    def _guardar(self, clave: str, valor: str | None) -> None:
        if valor:
            keyring.set_password(self.servicio, clave, valor)
            return
        try:
            keyring.delete_password(self.servicio, clave)
        except PasswordDeleteError:
            pass

    @property
    def api_id(self) -> int | None:
        valor = self._leer('api_id')
        return int(valor) if valor and valor.isdigit() else None

    @property
    def api_hash(self) -> str | None:
        return self._leer('api_hash')

    def guardar_api(self, api_id: int, api_hash: str) -> None:
        self._guardar('api_id', str(api_id))
        self._guardar('api_hash', api_hash)

    @property
    def tiene_api(self) -> bool:
        return bool(self.api_id and self.api_hash)

    @property
    def sesion(self) -> str | None:
        return self._leer('sesion')

    @sesion.setter
    def sesion(self, valor: str | None) -> None:
        self._guardar('sesion', valor)

    def borrar_todo(self) -> None:
        for clave in ('api_id', 'api_hash', 'sesion'):
            self._guardar(clave, None)
