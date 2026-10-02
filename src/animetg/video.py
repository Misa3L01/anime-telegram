"""Revisa cada video con ffprobe y lo deja listo para Telegram, sin recodificar la imagen."""
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_OK = {'h264', 'hevc'}
AUDIO_OK = {'aac', 'mp3'}
CONTENEDOR_MP4 = {'.mp4', '.m4v', '.mov'}
# Sin ventana de consola cuando la app corre con pythonw.
_SIN_VENTANA = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


@dataclass
class Info:
    duracion: float
    ancho: int
    alto: int
    vcodec: str
    pix_fmt: str
    audios: list[str]
    subtitulos: int


@dataclass
class Plan:
    modo: str      # 'video' se ve directo en Telegram; 'archivo' se descarga
    accion: str    # 'directo', 'faststart', 'remux' o 'remux-audio'
    motivo: str


@dataclass
class Preparado:
    archivos: list[Path]
    como_video: bool
    miniatura: Path | None
    infos: list[Info | None] = field(default_factory=list)


def _ejecutar(cmd: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       creationflags=_SIN_VENTANA)
    if r.returncode:
        raise RuntimeError(f'{Path(cmd[0]).stem} falló: {r.stderr.strip()[-600:]}')
    return r


def analizar(ffprobe: str, ruta: Path) -> Info | None:
    try:
        r = _ejecutar([ffprobe, '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', str(ruta)])
    except (RuntimeError, OSError):
        return None
    datos = json.loads(r.stdout or '{}')
    streams = datos.get('streams') or []
    videos = [s for s in streams if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')]
    if not videos:
        return None
    v = videos[0]
    return Info(
        duracion=float((datos.get('format') or {}).get('duration') or v.get('duration') or 0),
        ancho=int(v.get('width') or 0),
        alto=int(v.get('height') or 0),
        vcodec=v.get('codec_name') or '',
        pix_fmt=v.get('pix_fmt') or '',
        audios=[s.get('codec_name') or '' for s in streams if s.get('codec_type') == 'audio'],
        subtitulos=sum(1 for s in streams if s.get('codec_type') == 'subtitle'),
    )


def moov_al_inicio(ruta: Path) -> bool:
    """Un MP4 solo se puede ver mientras carga si su índice (moov) va antes que los datos (mdat)."""
    with open(ruta, 'rb') as f:
        while True:
            cabecera = f.read(8)
            if len(cabecera) < 8:
                return False
            tamano, tipo = int.from_bytes(cabecera[:4], 'big'), cabecera[4:]
            if tipo == b'moov':
                return True
            if tipo == b'mdat':
                return False
            if tamano == 1:
                tamano = int.from_bytes(f.read(8), 'big')
                f.seek(tamano - 16, 1)
            elif tamano >= 8:
                f.seek(tamano - 8, 1)
            else:
                return False


def decidir(ruta: Path, info: Info | None) -> Plan:
    ext = ruta.suffix.lower()
    formato = ext[1:].upper()
    if info is None:
        return Plan('archivo', 'directo', 'No se pudo leer el video; se sube tal cual')
    if info.vcodec not in VIDEO_OK:
        return Plan('archivo', 'directo', f'Video {info.vcodec}: Telegram no lo reproduce')
    if info.vcodec == 'h264' and info.pix_fmt not in ('yuv420p', 'yuvj420p'):
        return Plan('archivo', 'directo', 'H.264 de 10 bits: los celulares no lo reproducen')
    audio_ok = all(a in AUDIO_OK for a in info.audios)
    if ext in CONTENEDOR_MP4:
        if not audio_ok:
            return Plan('video', 'remux-audio', 'MP4; se convierte solo el audio a AAC')
        if not moov_al_inicio(ruta):
            return Plan('video', 'faststart', 'MP4; se reordena para verlo sin descargar')
        return Plan('video', 'directo', 'MP4 listo para ver en Telegram')
    if info.subtitulos:
        return Plan('archivo', 'directo', f'{formato} con subtítulos aparte; se sube tal cual')
    if len(info.audios) > 1:
        return Plan('archivo', 'directo', f'{formato} con {len(info.audios)} audios; se sube tal cual')
    if audio_ok:
        return Plan('video', 'remux', f'{formato} pasado a MP4 sin recodificar')
    return Plan('video', 'remux-audio', f'{formato} pasado a MP4; se convierte solo el audio a AAC')


def _remux(ffmpeg: str, origen: Path, destino: Path, info: Info, convertir_audio: bool) -> None:
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(origen),
           '-map', '0:V:0', '-map', '0:a?', '-c:v', 'copy']
    if info.vcodec == 'hevc':
        cmd += ['-tag:v', 'hvc1']
    cmd += ['-c:a', 'aac', '-b:a', '256k'] if convertir_audio else ['-c:a', 'copy']
    cmd += ['-movflags', '+faststart', str(destino)]
    _ejecutar(cmd)


def _fotograma(ffmpeg: str, video: Path, duracion: float, destino: Path) -> Path | None:
    segundo = max(1.0, duracion * 0.1) if duracion else 5.0
    try:
        _ejecutar([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{segundo:.1f}', '-i', str(video),
                   '-frames:v', '1', '-vf', 'scale=320:320:force_original_aspect_ratio=decrease',
                   '-q:v', '4', str(destino)])
    except (RuntimeError, OSError):
        return None
    return destino if destino.exists() else None


def _cortar_video(ffmpeg: str, video: Path, info: Info, limite: int, carpeta: Path) -> list[Path]:
    """Corta en partes que se reproducen solas (sin recodificar)."""
    segundos = info.duracion * (limite * 0.9) / video.stat().st_size
    for _ in range(4):
        cortes = carpeta / 'cortes'
        shutil.rmtree(cortes, ignore_errors=True)
        cortes.mkdir()
        _ejecutar([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video),
                   '-map', '0:V:0', '-map', '0:a?', '-c', 'copy', '-f', 'segment',
                   '-segment_time', f'{segundos:.0f}', '-reset_timestamps', '1',
                   '-segment_format', 'mp4', '-segment_format_options', 'movflags=+faststart',
                   str(cortes / 'parte%03d.mp4')])
        partes = sorted(cortes.glob('parte*.mp4'))
        if partes and all(p.stat().st_size <= limite for p in partes):
            finales = []
            for i, p in enumerate(partes, 1):
                final = carpeta / f'{video.stem} (parte {i} de {len(partes)}).mp4'
                p.replace(final)
                finales.append(final)
            return finales
        segundos *= 0.8
    raise RuntimeError('No pude cortar el video en partes que entren en Telegram.')


def _partir_7z(siete_zip: str, archivo: Path, limite: int, carpeta: Path) -> list[Path]:
    """Para lo que no se puede cortar como video: 7z sin compresión, en volúmenes."""
    if not Path(siete_zip).exists() and not shutil.which(siete_zip):
        raise RuntimeError('Hace falta 7-Zip para partir archivos de más del límite.')
    destino = carpeta / f'{archivo.stem}.7z'
    _ejecutar([siete_zip, 'a', '-t7z', '-mx0', f'-v{limite // (1024 * 1024)}m', '-y', str(destino), str(archivo)])
    return sorted(carpeta.glob(f'{destino.name}.*'), key=lambda p: p.suffix)


def preparar(ajustes, ruta: Path, info: Info | None, plan: Plan, carpeta: Path,
             mini_portada: Path | None) -> Preparado:
    """Deja en `carpeta` lo que haya que subir. El archivo original nunca se modifica."""
    ffmpeg, ffprobe = ajustes.programa('ffmpeg'), ajustes.programa('ffprobe')
    siete_zip, limite = ajustes.programa('siete_zip'), ajustes.limite_bytes
    carpeta.mkdir(parents=True, exist_ok=True)
    fuente = ruta
    if plan.modo == 'video' and plan.accion != 'directo':
        fuente = carpeta / f'{ruta.stem}.mp4'
        _remux(ffmpeg, ruta, fuente, info, convertir_audio=plan.accion == 'remux-audio')

    if plan.modo != 'video':
        archivos = [fuente] if fuente.stat().st_size <= limite else _partir_7z(siete_zip, fuente, limite, carpeta)
        return Preparado(archivos, False, mini_portada, [None] * len(archivos))

    miniatura = _fotograma(ffmpeg, fuente, info.duracion, carpeta / 'miniatura.jpg') or mini_portada
    if fuente.stat().st_size <= limite:
        return Preparado([fuente], True, miniatura, [analizar(ffprobe, fuente) or info])
    try:
        partes = _cortar_video(ffmpeg, fuente, info, limite, carpeta)
    except RuntimeError:
        # Si no se puede cortar limpio, al menos queda respaldado en volúmenes 7z.
        partes = _partir_7z(siete_zip, fuente, limite, carpeta)
        return Preparado(partes, False, mini_portada, [None] * len(partes))
    return Preparado(partes, True, miniatura, [analizar(ffprobe, p) for p in partes])
