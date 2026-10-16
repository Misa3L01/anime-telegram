import pytest

from animetg.ajustes import Ajustes
from animetg.video import analizar, decidir, moov_al_inicio, preparar

FFPROBE = 'ffprobe'


@pytest.mark.parametrize('caso, modo, accion', [
    ('mp4', 'video', 'directo'),
    ('mp4_lento', 'video', 'faststart'),
    ('mkv', 'video', 'remux'),
    ('mkv_opus', 'video', 'remux-audio'),
    ('mkv_subs', 'archivo', 'directo'),
    ('mkv_10bits', 'archivo', 'directo'),
])
def test_decide_como_subir_cada_formato(videos, caso, modo, accion):
    plan = decidir(videos[caso], analizar(FFPROBE, videos[caso]))
    assert (plan.modo, plan.accion) == (modo, accion)


@pytest.mark.parametrize('caso', ['mp4_lento', 'mkv', 'mkv_opus'])
def test_prepara_mp4_para_ver_sin_descargar(videos, tmp_path, caso):
    original = videos[caso].read_bytes()
    info = analizar(FFPROBE, videos[caso])
    prep = preparar(Ajustes(), videos[caso], info, decidir(videos[caso], info), tmp_path, None)
    assert prep.como_video and len(prep.archivos) == 1
    salida = analizar(FFPROBE, prep.archivos[0])
    assert salida.vcodec == 'h264' and salida.audios == ['aac'] and moov_al_inicio(prep.archivos[0])
    assert abs(salida.duracion - info.duracion) < 0.5
    assert videos[caso].read_bytes() == original  # el original nunca se toca


def test_corta_en_partes_que_se_reproducen_solas(videos, tmp_path):
    ajustes = Ajustes(limite_mb=1)
    info = analizar(FFPROBE, videos['mp4'])
    prep = preparar(ajustes, videos['mp4'], info, decidir(videos['mp4'], info), tmp_path, None)
    assert len(prep.archivos) > 1 and prep.como_video
    assert all(p.stat().st_size <= ajustes.limite_bytes for p in prep.archivos)
    assert abs(sum(i.duracion for i in prep.infos) - info.duracion) < 1


def test_lo_que_no_es_video_se_parte_en_7z(videos, tmp_path):
    ajustes = Ajustes(limite_mb=1)
    if not ajustes.programa_disponible('siete_zip'):
        pytest.skip('necesita 7-Zip')
    # Nombre con corchetes, como los BD-Rips de VCB-Studio.
    original = tmp_path / '[VCB-Studio] Love Live! The School Idol Movie [Ma10p_1080p][x265_flac].mkv'
    original.write_bytes(videos['mkv_subs'].read_bytes())
    info = analizar(FFPROBE, original)
    prep = preparar(ajustes, original, info, decidir(original, info), tmp_path / 'trabajo', None)
    assert not prep.como_video and len(prep.archivos) > 1
    assert [p.suffix for p in prep.archivos][:2] == ['.001', '.002']
