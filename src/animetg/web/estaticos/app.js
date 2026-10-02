'use strict';

/* ================================================================ utilidades */
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icono = id => `<svg><use href="#i-${id}"/></svg>`;
const portadaUrl = id => `/api/portada/${id}?t=${encodeURIComponent(TOKEN)}`;
const dos = n => String(n).padStart(2, '0');

async function api(metodo, ruta, datos) {
  const r = await fetch(ruta, {
    method: metodo,
    headers: { 'X-Token': TOKEN, 'Content-Type': 'application/json' },
    body: datos === undefined ? undefined : JSON.stringify(datos),
  });
  let cuerpo = null;
  try { cuerpo = await r.json(); } catch { /* respuesta vacía */ }
  if (!r.ok) throw new Error(cuerpo?.error || `Error ${r.status}`);
  return cuerpo;
}

const fmtBytes = b => {
  if (!b) return '0 MB';
  const gb = b / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(gb >= 100 ? 0 : 2)} GB` : `${Math.max(1, Math.round(b / 1024 ** 2))} MB`;
};
const fmtVel = v => (v ? `${(v / 1024 ** 2).toFixed(1)} MB/s` : '—');
const fmtDur = s => {
  if (s == null || !isFinite(s)) return '—';
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min ${dos(ss)} s` : `${ss} s`;
};
const fmtHace = iso => {
  const d = (Date.now() - new Date(iso)) / 1000;
  if (d < 60) return 'recién';
  if (d < 3600) return `hace ${Math.floor(d / 60)} min`;
  if (d < 86400) return `hace ${Math.floor(d / 3600)} h`;
  const dias = Math.floor(d / 86400);
  return dias === 1 ? 'ayer' : `hace ${dias} días`;
};
const fmtFecha = t => {
  const d = new Date(t * 1000);
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())} ${dos(d.getHours())}:${dos(d.getMinutes())}:${dos(d.getSeconds())}`;
};

const ESTADOS = {
  analizando: ['Analizando', 'info'], en_cola: ['En cola', ''], repetido: ['Ya subido', 'acento'],
  preparando: ['Preparando', 'info'], subiendo: ['Subiendo', 'acento'], pendiente: ['Sin reconocer', 'aviso'],
  error: ['Error', 'error'], cancelado: ['Cancelado', 'aviso'],
};
const PROGRAMAS = { ffmpeg: 'ffmpeg', ffprobe: 'ffprobe', siete_zip: '7-Zip' };

/* ================================================================ estado */
const S = {
  estado: null, cola: [], recientes: [], series: [], log: [], logCargado: false,
  vista: 'panel', filtroLog: 'todo', filtroSeries: '', busquedas: {}, pendientesVistos: '',
};

/* ================================================================ avisos y modales */
function avisar(texto, tipo = 'info') {
  const iconos = { ok: 'check', error: 'alerta', aviso: 'alerta', info: 'actividad' };
  const el = document.createElement('div');
  el.className = `aviso ${tipo === 'aviso' ? 'aviso-a' : tipo}`;
  el.innerHTML = `${icono(iconos[tipo] || 'actividad')}<p>${esc(texto)}</p>`;
  $('#avisos').append(el);
  setTimeout(() => el.remove(), tipo === 'error' ? 8000 : 4500);
}

function abrirModal(html, ancho = false) {
  const m = $('#modal');
  m.className = 'modal' + (ancho ? ' ancho' : '');
  m.innerHTML = html;
  $('#velo').hidden = false;
  return m;
}
function cerrarModal() {
  $('#velo').hidden = true;
  $('#modal').innerHTML = '';
}
$('#velo').addEventListener('mousedown', e => { if (e.target.id === 'velo') cerrarModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#velo').hidden) cerrarModal(); });

function confirmar(titulo, texto, boton = 'Aceptar') {
  return new Promise(resolver => {
    const m = abrirModal(`<h2>${esc(titulo)}</h2><p>${esc(texto)}</p>
      <div class="pie-modal"><button class="boton" data-r="0">Cancelar</button>
      <button class="boton primario" data-r="1">${esc(boton)}</button></div>`);
    $$('[data-r]', m).forEach(b => b.onclick = () => { cerrarModal(); resolver(b.dataset.r === '1'); });
  });
}

async function accion(boton, trabajo, exito) {
  if (boton) boton.disabled = true;
  try {
    const r = await trabajo();
    if (exito) avisar(typeof exito === 'function' ? exito(r) : exito, 'ok');
    return r;
  } catch (e) {
    avisar(e.message, 'error');
  } finally {
    if (boton) boton.disabled = false;
  }
}

/* Enlaces externos y carpetas: los abre Windows, no la ventana de la app. */
document.addEventListener('click', e => {
  const externo = e.target.closest('[data-externo]');
  if (externo) {
    e.preventDefault();
    api('POST', '/api/abrir', { que: 'url', valor: externo.getAttribute('href') });
    return;
  }
  const carpeta = e.target.closest('[data-abrir]');
  if (carpeta) accion(null, () => api('POST', '/api/abrir', { que: carpeta.dataset.abrir, valor: carpeta.dataset.valor }));
});

/* ================================================================ navegación */
const VISTAS = {
  panel: ['Panel', pintarPanel],
  series: ['Series', pintarSeries],
  pendientes: ['Pendientes', pintarPendientes],
  actividad: ['Actividad', pintarActividad],
  ajustes: ['Ajustes', pintarAjustes],
};

function irA(vista) {
  if (!VISTAS[vista]) vista = 'panel';
  S.vista = vista;
  history.replaceState(null, '', `${location.search}#${vista}`);
  $$('.menu button').forEach(b => b.classList.toggle('activo', b.dataset.vista === vista));
  S.pendientesVistos = '';
  pintarVista();
  $('.principal').scrollTop = 0;
}
function pintarVista() {
  const [titulo, pintar] = VISTAS[S.vista];
  $('#titulo-vista').textContent = titulo;
  $('#subtitulo-vista').textContent = '';
  $('#acciones-vista').innerHTML = '';
  pintar();
}
$$('.menu button').forEach(b => b.onclick = () => irA(b.dataset.vista));
window.addEventListener('hashchange', () => { if (location.hash.slice(1) !== S.vista) irA(location.hash.slice(1)); });

/* ================================================================ barra lateral */
function pintarCuenta() {
  const e = S.estado;
  if (!e) return;
  $('#version').textContent = `Versión ${e.version}`;
  const caja = $('#cuenta');
  if (e.conexion === 'conectado') {
    const u = e.usuario;
    const iniciales = u.nombre.split(/\s+/).map(p => p[0]).join('').slice(0, 2).toUpperCase();
    caja.innerHTML = `<div class="fila"><div class="avatar">${esc(iniciales)}</div><div style="min-width:0">
      <div class="nombre">${esc(u.nombre)}</div><span class="punto ok">Conectado a Telegram</span></div></div>`;
  } else {
    const texto = e.conexion === 'sin_api' ? 'Falta configurar' : 'Sin sesión';
    caja.innerHTML = `<span class="punto aviso">${texto}</span>
      <button class="boton primario chico" style="width:100%;margin-top:10px" id="b-login-barra">${icono('avion')}Conectar Telegram</button>`;
    $('#b-login-barra').onclick = abrirLogin;
  }
  const pendientes = e.contadores.pendientes + e.contadores.errores;
  const insignia = $('#insignia-pendientes');
  insignia.hidden = !pendientes;
  insignia.textContent = pendientes;
}

/* ================================================================ panel */
function pintarPanel() {
  const e = S.estado;
  if (!e) return;
  $('#subtitulo-vista').innerHTML = `Vigilando <b>${esc(e.carpeta)}</b>`;
  $('#acciones-vista').innerHTML = `
    <label class="interruptor" title="Subir los capítulos apenas aparecen en la carpeta">
      <input type="checkbox" id="auto" ${e.automatica ? 'checked' : ''}><span class="pista"></span>Subida automática</label>
    <button class="boton" id="b-pausa"></button>
    <button class="boton" data-abrir="subir">${icono('carpeta')}Abrir carpeta</button>`;
  $('#auto').onchange = ev => accion(null, () => api('PUT', '/api/ajustes', { subida_automatica: ev.target.checked }),
    ev.target.checked ? 'Subida automática activada' : 'Subida automática desactivada');
  $('#b-pausa').onclick = ev => accion(ev.currentTarget, () => api('POST', '/api/pausar', { pausado: !S.estado.pausado }));
  $('#vista').innerHTML = `
    <div id="banners" class="vista" style="gap:12px"></div>
    <div class="grilla-panel">
      <section class="tarjeta" id="tarjeta-actual"></section>
      <section class="tarjeta resumen" id="resumen"></section>
    </div>
    <section class="tarjeta">
      <header><h2>Cola <span class="contador" id="cuenta-cola"></span></h2><div class="acciones" id="acciones-cola"></div></header>
      <div class="lista" id="lista-cola"></div>
    </section>
    <section class="tarjeta">
      <header><h2>Últimas subidas</h2><button class="boton fantasma chico" id="b-ver-series">Ver series</button></header>
      <div class="lista" id="lista-recientes"></div>
    </section>`;
  $('#b-ver-series').onclick = () => irA('series');
  actualizarPanel();
  pintarRecientes();
}

function actualizarPanel() {
  if (S.vista !== 'panel' || !$('#lista-cola')) return;
  const e = S.estado;
  $('#b-pausa').innerHTML = e.pausado ? `${icono('play')}Reanudar` : `${icono('pausa')}Pausar`;
  $('#auto').checked = e.automatica;
  pintarBanners();
  pintarActual();
  pintarResumen();
  pintarCola();
}

function pintarBanners() {
  const e = S.estado, b = [];
  if (e.conexion !== 'conectado') {
    b.push(`<div class="banner info"><div class="icono-banner">${icono('avion')}</div><div>
      <strong>Conecta tu cuenta de Telegram</strong><p>Los capítulos se detectan igual, pero se suben cuando inicias sesión.</p></div>
      <button class="boton primario" data-login>Conectar</button></div>`);
  }
  const faltan = Object.entries(e.programas).filter(([, ok]) => !ok).map(([n]) => PROGRAMAS[n]);
  if (faltan.length) {
    b.push(`<div class="banner aviso"><div class="icono-banner">${icono('alerta')}</div><div>
      <strong>Falta ${esc(faltan.join(', '))}</strong><p>Hace falta para revisar y preparar los videos. Indica dónde está en Ajustes.</p></div>
      <button class="boton" data-ir="ajustes">Ir a Ajustes</button></div>`);
  }
  const pend = e.contadores.pendientes;
  if (pend) {
    b.push(`<div class="banner aviso"><div class="icono-banner">${icono('alerta')}</div><div>
      <strong>${pend} archivo${pend > 1 ? 's' : ''} sin reconocer</strong><p>Elige a qué anime corresponde${pend > 1 ? 'n' : ''} y se ${pend > 1 ? 'suben' : 'sube'} solo${pend > 1 ? 's' : ''}.</p></div>
      <button class="boton" data-ir="pendientes">Revisar</button></div>`);
  }
  const caja = $('#banners');
  caja.innerHTML = b.join('');
  caja.hidden = !b.length;
  $$('[data-login]', caja).forEach(x => x.onclick = abrirLogin);
  $$('[data-ir]', caja).forEach(x => x.onclick = () => irA(x.dataset.ir));
}

function nombreItem(i) {
  if (!i.serie) return esc(i.archivo);
  if (i.tipo === 'temporada') return `${esc(i.seccion)} · Episodio ${dos(i.episodio)}`;
  return i.unico ? esc(i.seccion) : `${esc(i.seccion)} · Episodio ${dos(i.episodio)}`;
}
const imgPortada = (media, clase = 'portada') => media
  ? `<img class="${clase}" src="${portadaUrl(media)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
  : `<div class="${clase} portada-vacia">${icono('pelicula')}</div>`;

function pintarActual() {
  const c = $('#tarjeta-actual');
  if (!c) return;
  const e = S.estado;
  const i = S.cola.find(x => x.id === e.actual);
  if (!i) {
    delete c.dataset.id;
    const enCola = S.cola.filter(x => ['en_cola', 'repetido'].includes(x.estado)).length;
    let html;
    if (e.conexion !== 'conectado') {
      html = vacio('avion', 'Esperando la conexión con Telegram', 'Conecta tu cuenta para empezar a subir.',
        '<button class="boton primario" data-login>Conectar Telegram</button>');
    } else if (e.pausado) {
      html = vacio('pausa', 'Subidas en pausa', enCola ? `${enCola} en cola esperando.` : 'No hay nada en cola.',
        `<button class="boton primario" id="b-reanudar">${icono('play')}Reanudar</button>`);
    } else if (!e.automatica && enCola) {
      html = vacio('subir', `${enCola} capítulo${enCola > 1 ? 's' : ''} listo${enCola > 1 ? 's' : ''} para subir`,
        'La subida automática está apagada.', `<button class="boton primario" id="b-subir-ahora">${icono('subir')}Subir ahora</button>`);
    } else {
      html = vacio('check', 'Todo al día', `Deja capítulos en ${e.carpeta} y se suben solos.`,
        `<button class="boton" data-abrir="subir">${icono('carpeta')}Abrir carpeta</button>`);
    }
    c.innerHTML = html;
    $$('[data-login]', c).forEach(x => x.onclick = abrirLogin);
    const r = $('#b-reanudar', c); if (r) r.onclick = ev => accion(ev.currentTarget, () => api('POST', '/api/pausar', { pausado: false }));
    const s = $('#b-subir-ahora', c); if (s) s.onclick = ev => accion(ev.currentTarget, () => api('POST', '/api/subir-ahora'));
    return;
  }
  if (c.dataset.id !== i.id) {
    c.dataset.id = i.id;
    c.innerHTML = `<div class="actual">
      ${imgPortada(i.media, 'portada grande')}
      <div class="datos">
        <div><span class="chip acento" id="act-estado"></span></div>
        <div class="serie">${esc(i.serie)}</div>
        <div class="ubicacion">${nombreItem(i)}</div>
        <div class="archivo" title="${esc(i.archivo)}">${esc(i.archivo)} · ${fmtBytes(i.tamano)} · ${esc(i.motivo || '')}</div>
        <div class="pie">
          <div class="progreso" id="act-barra"><div style="width:0%"></div></div>
          <div class="cifras">
            <span><b id="act-pct">0%</b></span>
            <span>${icono('rayo')} <b id="act-vel">—</b></span>
            <span>${icono('reloj')} <b id="act-resta">—</b></span>
            <span id="act-parte"></span>
            <button class="boton chico peligro" id="b-cancelar">${icono('x')}Cancelar</button>
          </div>
        </div>
      </div></div>`;
    $('#b-cancelar').onclick = async ev => {
      if (await confirmar('Cancelar la subida', `Se detiene "${i.archivo}". Lo ya subido de este archivo se descarta.`, 'Cancelar subida')) {
        accion(ev.currentTarget, () => api('POST', '/api/cancelar'));
      }
    };
  }
  const pct = Math.floor(i.progreso * 100);
  $('#act-estado').textContent = i.estado === 'preparando' ? 'Preparando el video…' : 'Subiendo';
  $('#act-barra').classList.toggle('indeterminado', i.estado === 'preparando');
  $('#act-barra > div').style.width = `${pct}%`;
  $('#act-pct').textContent = i.estado === 'preparando' ? '—' : `${pct}%`;
  $('#act-vel').textContent = fmtVel(i.velocidad);
  $('#act-resta').textContent = i.restante != null ? `${fmtDur(i.restante)} restantes` : '—';
  $('#act-parte').textContent = i.partes > 1 ? `Parte ${i.parte} de ${i.partes}` : '';
}

function vacio(ic, titulo, texto, botones = '') {
  return `<div class="vacio"><div class="icono-vacio">${icono(ic)}</div><strong>${esc(titulo)}</strong><p>${esc(texto)}</p>${botones}</div>`;
}

function pintarResumen() {
  const c = $('#resumen');
  if (!c) return;
  const e = S.estado;
  const total = S.series.reduce((a, s) => a + s.tamano, 0);
  const episodios = S.series.reduce((a, s) => a + s.episodios, 0);
  const m = (ic, etiqueta, valor) => `<div class="metrica"><div class="icono-m">${icono(ic)}</div><div><span>${etiqueta}</span><b>${valor}</b></div></div>`;
  c.innerHTML = m('subir', 'En cola', e.contadores.cola) + m('series', 'Series respaldadas', S.series.length)
    + m('pelicula', 'Episodios subidos', episodios) + m('disco', 'Espacio en Telegram', fmtBytes(total));
}

function pintarCola() {
  const lista = $('#lista-cola');
  if (!lista) return;
  const items = S.cola.filter(i => i.estado !== 'pendiente');
  $('#cuenta-cola').textContent = items.length ? `· ${items.length}` : '';
  const acc = $('#acciones-cola');
  const esperando = items.filter(i => ['en_cola', 'repetido'].includes(i.estado)).length;
  acc.innerHTML = !S.estado.automatica && esperando && !S.estado.actual
    ? `<button class="boton primario chico" id="b-subir-cola">${icono('subir')}Subir ${esperando}</button>` : '';
  const b = $('#b-subir-cola');
  if (b) b.onclick = ev => accion(ev.currentTarget, () => api('POST', '/api/subir-ahora'));
  if (!items.length) {
    lista.innerHTML = `<div class="vacio" style="padding:18px">No hay capítulos en cola.</div>`;
    return;
  }
  lista.innerHTML = items.map(filaItem).join('');
  enlazarFilas(lista);
}

function filaItem(i) {
  const [texto, clase] = ESTADOS[i.estado] || [i.estado, ''];
  const activo = ['preparando', 'subiendo'].includes(i.estado);
  const modo = i.modo === 'video' ? '<span class="chip info">Video</span>' : i.modo ? '<span class="chip">Archivo</span>' : '';
  const divide = i.divide ? '<span class="chip aviso">Se divide</span>' : '';
  let lado = `<span class="chip ${clase}">${texto}</span>`;
  if (i.estado === 'subiendo') {
    lado = `<div class="mini-progreso"><div class="progreso"><div style="width:${Math.floor(i.progreso * 100)}%"></div></div></div>
            <span class="chip acento">${Math.floor(i.progreso * 100)}%</span>`;
  }
  if (['error', 'cancelado'].includes(i.estado)) lado += `<button class="boton chico" data-accion="reintentar" data-id="${i.id}">${icono('refrescar')}Reintentar</button>`;
  if (!activo && i.estado !== 'analizando') lado += `<button class="boton icono fantasma" title="Quitar de la cola" data-accion="quitar" data-id="${i.id}">${icono('x')}</button>`;
  const detalle = i.error ? `<div class="t3" style="color:var(--error)" title="${esc(i.error)}">${esc(i.error)}</div>`
    : `<div class="t3" title="${esc(i.archivo)}">${esc(i.archivo)} · ${fmtBytes(i.tamano)}</div>`;
  return `<div class="fila-item ${activo ? 'activo' : ''}" data-fila="${i.id}">
    ${imgPortada(i.media)}
    <div style="min-width:0"><div class="t1">${esc(i.serie || i.archivo)}</div>
      <div class="t2">${i.serie ? nombreItem(i) : i.estado === 'analizando' ? 'Analizando…' : esc(i.carpeta)}</div>${detalle}</div>
    <div class="lado">${modo}${divide}${lado}</div></div>`;
}

function enlazarFilas(raiz) {
  $$('[data-accion]', raiz).forEach(b => b.onclick = ev => {
    const { accion: que, id } = b.dataset;
    accion(ev.currentTarget, () => api('POST', `/api/items/${id}/${que}`));
  });
}

function pintarRecientes() {
  const lista = $('#lista-recientes');
  if (!lista) return;
  if (!S.recientes.length) {
    lista.innerHTML = `<div class="vacio" style="padding:18px">Todavía no se subió nada.</div>`;
    return;
  }
  lista.innerHTML = S.recientes.map(r => {
    const ep = r.tipo === 'temporada' ? ` · Episodio ${dos(r.episodio)}` : '';
    const vel = r.segundos ? ` · ${fmtVel(r.tamano / r.segundos)}` : '';
    return `<div class="fila-item">${imgPortada(r.media)}
      <div style="min-width:0"><div class="t1">${esc(r.serie)}</div><div class="t2">${esc(r.seccion)}${ep}</div>
      <div class="t3">${esc(r.archivo)}</div></div>
      <div class="lado"><span class="t3">${fmtHace(r.fecha)} · ${fmtBytes(r.tamano)}${vel}</span></div></div>`;
  }).join('');
}

/* ================================================================ series */
function pintarSeries() {
  const total = S.series.reduce((a, s) => a + s.tamano, 0);
  $('#subtitulo-vista').textContent = S.series.length
    ? `${S.series.length} canal${S.series.length > 1 ? 'es' : ''} · ${fmtBytes(total)} respaldados` : '';
  $('#acciones-vista').innerHTML = `<div class="buscador">${icono('buscar')}<input id="filtro-series" class="busqueda" placeholder="Buscar serie" value="${esc(S.filtroSeries)}"></div>`;
  $('#filtro-series').oninput = ev => { S.filtroSeries = ev.target.value; pintarGrillaSeries(); };
  $('#vista').innerHTML = '<div id="grilla"></div>';
  pintarGrillaSeries();
}

function pintarGrillaSeries() {
  const caja = $('#grilla');
  if (!caja) return;
  if (!S.series.length) {
    caja.innerHTML = `<section class="tarjeta">${vacio('series', 'Todavía no hay canales', 'Cada anime que subas tendrá su propio canal privado con carátula, ficha e índice.')}</section>`;
    return;
  }
  const f = S.filtroSeries.trim().toLowerCase();
  const lista = S.series.filter(s => !f || s.titulo.toLowerCase().includes(f));
  caja.innerHTML = lista.length ? `<div class="grilla-series">${lista.map(s => `
    <button class="tarjeta-serie" data-raiz="${s.raiz}">
      <div class="caja-portada">${imgPortada(s.raiz, '')}<span class="cinta">${s.episodios} ep.</span></div>
      <strong>${esc(s.titulo)}</strong>
      <span>${s.secciones} ${s.secciones === 1 ? 'sección' : 'secciones'} · ${fmtBytes(s.tamano)}</span>
    </button>`).join('')}</div>` : `<div class="vacio">Ninguna serie coincide con "${esc(S.filtroSeries)}".</div>`;
  $$('[data-raiz]', caja).forEach(b => b.onclick = () => abrirSerie(Number(b.dataset.raiz)));
}

async function abrirSerie(raiz) {
  let d;
  try { d = await api('GET', `/api/series/${raiz}`); } catch (e) { avisar(e.message, 'error'); return; }
  const episodios = d.secciones.reduce((a, s) => a + s.subidos.length, 0);
  const secciones = d.secciones.map(s => {
    let chips;
    if (s.tipo !== 'temporada' && (s.total || 1) <= 1) {
      chips = `<span class="ep si ancho">${icono('check')} Subida</span>`;
    } else {
      const subidos = new Set(s.subidos);
      const numeros = s.total && s.total <= 500 ? Array.from({ length: Math.max(s.total, Math.max(...s.subidos)) }, (_, k) => k + 1) : s.subidos;
      chips = numeros.map(n => `<span class="ep ${subidos.has(n) ? 'si' : ''}">${dos(n)}</span>`).join('');
    }
    const cuenta = s.total && s.total > 1 ? `<span class="chip ${s.subidos.length >= s.total ? 'ok' : ''}">${s.subidos.length}/${s.total}</span>` : '';
    return `<div class="seccion-det"><h3>${esc(s.nombre)} ${cuenta}</h3><div class="episodios">${chips}</div></div>`;
  }).join('');
  const m = abrirModal(`
    <button class="boton icono fantasma cerrar-modal" data-cerrar title="Cerrar">${icono('x')}</button>
    <div class="detalle-cabecera">${imgPortada(raiz, 'portada grande')}<div>
      <h2>${esc(d.titulo)}</h2>
      <p>${episodios} episodio${episodios === 1 ? '' : 's'} · ${fmtBytes(d.tamano)}${d.ficha_idioma && d.ficha_idioma !== 'es' ? ' · ficha en inglés' : ''}</p>
      <div class="acciones">
        <button class="boton primario" id="b-abrir-canal">${icono('avion')}Abrir en Telegram</button>
        <button class="boton" id="b-reordenar">${icono('orden')}Reordenar</button>
        <button class="boton" id="b-ficha">${icono('ficha')}Actualizar ficha</button>
      </div></div></div>
    ${secciones || '<p class="texto">Sin episodios todavía.</p>'}`, true);
  $('[data-cerrar]', m).onclick = cerrarModal;
  $('#b-abrir-canal', m).onclick = ev => accion(ev.currentTarget, () => api('POST', '/api/abrir', { que: 'canal', valor: raiz }));
  $('#b-reordenar', m).onclick = ev => accion(ev.currentTarget, () => api('POST', `/api/series/${raiz}/reordenar`),
    r => (r.movidos ? `Listo: se movieron ${r.movidos} mensajes.` : 'El canal ya estaba en orden.'));
  $('#b-ficha', m).onclick = ev => accion(ev.currentTarget, () => api('POST', `/api/series/${raiz}/ficha`), 'Ficha actualizada.');
}

/* ================================================================ pendientes */
function pintarPendientes() {
  const pendientes = S.cola.filter(i => i.estado === 'pendiente');
  const errores = S.cola.filter(i => ['error', 'cancelado'].includes(i.estado));
  S.pendientesVistos = [...pendientes, ...errores].map(i => i.id + i.estado).join();
  $('#subtitulo-vista').textContent = 'Archivos que necesitan que elijas el anime correcto, o que fallaron.';
  if (!pendientes.length && !errores.length) {
    $('#vista').innerHTML = `<section class="tarjeta">${vacio('check', 'No hay nada pendiente', 'Todo lo que está en la carpeta se reconoció bien.')}</section>`;
    return;
  }
  const tarjetas = pendientes.map(i => {
    const b = S.busquedas[i.id] || { texto: i.detectado?.titulo || '', resultados: null };
    S.busquedas[i.id] = b;
    const det = i.detectado || {};
    const leido = [det.titulo && `"${det.titulo}"`, det.temporada && `temporada ${det.temporada}`, det.episodio != null && `episodio ${det.episodio}`].filter(Boolean).join(', ');
    return `<section class="tarjeta pendiente" data-item="${i.id}">
      <div class="arriba">${imgPortada(null)}<div style="min-width:0;flex:1">
        <div class="t1" style="font-weight:600">${esc(i.archivo)}</div>
        <div class="texto" style="color:var(--texto-2);font-size:13px">${i.carpeta ? `En ${esc(i.carpeta)} · ` : ''}Se leyó: ${esc(leido || 'nada útil')}</div>
        <div class="motivo">${esc(i.error)}</div></div>
        <button class="boton icono fantasma" title="Quitar de la lista" data-accion="quitar" data-id="${i.id}">${icono('x')}</button></div>
      <div class="buscar-fila"><input value="${esc(b.texto)}" placeholder="Nombre del anime en AniList" data-buscar="${i.id}">
        <button class="boton" data-boton-buscar="${i.id}">${icono('buscar')}Buscar</button></div>
      <div class="opciones" data-opciones="${i.id}">${pintarOpciones(b.resultados)}</div>
      ${det.titulo ? `<label class="interruptor"><input type="checkbox" data-recordar="${i.id}" checked><span class="pista"></span>
        <span>Recordar para todos los archivos llamados "${esc(det.titulo)}"</span></label>` : ''}
    </section>`;
  }).join('');
  const fallidos = errores.length ? `<section class="tarjeta"><header><h2>Con errores</h2></header>
    <div class="lista">${errores.map(filaItem).join('')}</div></section>` : '';
  $('#vista').innerHTML = tarjetas + fallidos;
  enlazarFilas($('#vista'));
  $$('[data-buscar]').forEach(input => {
    input.oninput = () => { S.busquedas[input.dataset.buscar].texto = input.value; };
    input.onkeydown = ev => { if (ev.key === 'Enter') buscarAnime(input.dataset.buscar); };
  });
  $$('[data-boton-buscar]').forEach(b => b.onclick = () => buscarAnime(b.dataset.botonBuscar));
  enlazarOpciones();
  for (const i of pendientes) if (S.busquedas[i.id].resultados === null && S.busquedas[i.id].texto) buscarAnime(i.id);
}

function pintarOpciones(resultados) {
  if (resultados === null) return '';
  if (!resultados.length) return '<div class="texto" style="color:var(--texto-3)">AniList no encontró nada con ese nombre. Prueba con el título en romaji o en inglés.</div>';
  const formatos = { TV: 'Serie', TV_SHORT: 'Serie corta', MOVIE: 'Película', OVA: 'OVA', ONA: 'ONA', SPECIAL: 'Especial', MUSIC: 'Música' };
  return resultados.map(r => `<button class="opcion" data-media="${r.id}">
    <img src="${esc(r.portada || '')}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
    <div style="min-width:0"><strong>${esc(r.titulo)}</strong>${r.alternativo ? `<span>${esc(r.alternativo)}</span><br>` : ''}
    <span>${[formatos[r.formato] || r.formato, r.anio, r.episodios && `${r.episodios} ep.`].filter(Boolean).map(esc).join(' · ')}</span></div>
  </button>`).join('');
}

async function buscarAnime(id) {
  const b = S.busquedas[id];
  const caja = $(`[data-opciones="${id}"]`);
  if (!b || !b.texto.trim() || !caja) return;
  caja.innerHTML = '<div class="texto" style="color:var(--texto-3)">Buscando en AniList…</div>';
  try {
    b.resultados = await api('GET', `/api/anilist?q=${encodeURIComponent(b.texto.trim())}`);
  } catch (e) {
    b.resultados = null;
    caja.innerHTML = `<div class="texto" style="color:var(--error)">${esc(e.message)}</div>`;
    return;
  }
  caja.innerHTML = pintarOpciones(b.resultados);
  enlazarOpciones();
}

function enlazarOpciones() {
  $$('.opcion[data-media]').forEach(op => op.onclick = () => {
    const id = op.closest('[data-item]').dataset.item;
    const recordar = $(`[data-recordar="${id}"]`)?.checked ?? false;
    accion(op, () => api('POST', `/api/items/${id}/corregir`, { media: Number(op.dataset.media), recordar }),
      `Listo: "${op.querySelector('strong').textContent}". Se agrega a la cola.`);
  });
}

/* ================================================================ actividad */
async function pintarActividad() {
  $('#subtitulo-vista').textContent = 'Todo lo que hizo la aplicación, lo más reciente arriba.';
  $('#acciones-vista').innerHTML = `<div class="filtros">
      ${['todo', 'avisos', 'errores'].map(f => `<button class="boton chico ${S.filtroLog === f ? 'activo' : ''}" data-filtro="${f}">${f[0].toUpperCase() + f.slice(1)}</button>`).join('')}
    </div><button class="boton" data-abrir="logs">${icono('carpeta')}Abrir registros</button>`;
  $$('[data-filtro]').forEach(b => b.onclick = () => { S.filtroLog = b.dataset.filtro; pintarActividad(); });
  if (!S.logCargado) {
    $('#vista').innerHTML = '<section class="tarjeta"><div class="vacio">Cargando…</div></section>';
    try { S.log = await api('GET', '/api/registro?n=500'); S.logCargado = true; } catch (e) { avisar(e.message, 'error'); return; }
  }
  if (S.vista !== 'actividad') return;
  $('#vista').innerHTML = '<section class="tarjeta registro" id="registro"></section>';
  pintarRegistro();
}

function pintarRegistro() {
  const caja = $('#registro');
  if (!caja) return;
  const filtro = { todo: () => true, avisos: l => l.nivel !== 'INFO', errores: l => l.nivel === 'ERROR' }[S.filtroLog];
  const lineas = S.log.filter(filtro).slice(-500).reverse();
  caja.innerHTML = lineas.length ? lineas.map(l => `<div class="linea"><span class="fecha">${esc(l.fecha)}</span>
    <span class="${esc(l.nivel)}">${esc({ INFO: 'info', WARNING: 'aviso', ERROR: 'error' }[l.nivel] || l.nivel)}</span>
    <span class="msg">${esc(l.mensaje)}</span></div>`).join('') : '<div class="vacio">No hay nada para mostrar.</div>';
}

/* ================================================================ ajustes */
async function pintarAjustes() {
  let d;
  try { d = await api('GET', '/api/ajustes'); } catch (e) { avisar(e.message, 'error'); return; }
  if (S.vista !== 'ajustes') return;
  const a = d.ajustes, e = S.estado;
  $('#subtitulo-vista').textContent = 'Los cambios se aplican al guardar.';
  $('#acciones-vista').innerHTML = `<button class="boton primario" id="b-guardar">${icono('check')}Guardar cambios</button>`;
  const texto = (clave, etiqueta, ayuda, extra = '') => `<div class="campo"><label for="a-${clave}">${etiqueta}<small>${ayuda}</small></label>
    <div class="con-boton"><input id="a-${clave}" data-ajuste="${clave}" value="${esc(a[clave])}">${extra}</div></div>`;
  const llave = (clave, etiqueta, ayuda, valor = a[clave], datos = `data-ajuste="${clave}"`) => `<div class="campo horizontal">
    <div><span class="etiqueta">${etiqueta}</span><small>${ayuda}</small></div>
    <label class="interruptor"><input type="checkbox" ${datos} ${valor ? 'checked' : ''}><span class="pista"></span></label></div>`;
  const lista = (clave, etiqueta, ayuda, opciones) => `<div class="campo"><label for="a-${clave}">${etiqueta}<small>${ayuda}</small></label>
    <select id="a-${clave}" data-ajuste="${clave}">${opciones.map(([v, t]) => `<option value="${v}" ${a[clave] === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>`;
  const numero = (clave, etiqueta, ayuda, min, max) => `<div class="campo horizontal"><div><span class="etiqueta">${etiqueta}</span><small>${ayuda}</small></div>
    <input type="number" style="width:90px" min="${min}" max="${max}" data-ajuste="${clave}" value="${a[clave]}"></div>`;
  const programa = clave => {
    const ok = e.programas[clave];
    return texto(clave, PROGRAMAS[clave], `<span class="estado-programa"><span class="punto ${ok ? 'ok' : 'error'}">${ok ? 'Encontrado' : 'No encontrado'}</span></span>`);
  };
  const cuenta = e.conexion === 'conectado'
    ? `<div class="campo horizontal"><div><span class="etiqueta">${esc(e.usuario.nombre)}</span><small>${e.usuario.usuario ? '@' + esc(e.usuario.usuario) + ' · ' : ''}${e.usuario.premium ? 'Telegram Premium' : 'Cuenta normal'}</small></div>
       <button class="boton peligro" id="b-cerrar-sesion">${icono('salir')}Cerrar sesión</button></div>`
    : `<div class="campo horizontal"><div><span class="etiqueta">Sin sesión</span><small>Conecta tu cuenta para poder subir.</small></div>
       <button class="boton primario" data-login>${icono('avion')}Conectar</button></div>`;
  const tema = localStorage.getItem('tema') || 'sistema';
  $('#vista').innerHTML = `<div class="grilla-ajustes">
    <section class="tarjeta"><header><h2>${icono('carpeta')}Carpetas</h2></header>
      ${texto('carpeta_subir', 'Carpeta de subida', 'Lo que dejes acá se sube solo.', `<button class="boton" data-abrir="subir">Abrir</button>`)}
      ${texto('carpeta_subidos', 'Carpeta de subidos', 'Adonde se mueve cada archivo ya subido. Nunca se borra nada.', `<button class="boton" data-abrir="subidos">Abrir</button>`)}
    </section>
    <section class="tarjeta"><header><h2>${icono('avion')}Telegram</h2></header>
      ${cuenta}
      ${texto('carpeta_telegram', 'Carpeta de chats', 'Los canales se agrupan en esta carpeta de Telegram. Déjalo vacío para no usarla.')}
      ${llave('premium', 'Telegram Premium', 'Permite archivos de hasta 4 GB en vez de 2 GB.')}
    </section>
    <section class="tarjeta"><header><h2>${icono('series')}Organización</h2></header>
      ${lista('idioma_titulo', 'Nombre de los canales', 'Cómo se llaman los canales y las temporadas.', [['romaji', 'Romaji (Shingeki no Kyojin)'], ['english', 'Inglés (Attack on Titan)']])}
      ${lista('idioma_sinopsis', 'Idioma de las sinopsis', 'AniList solo las tiene en inglés; en español se traducen solas.', [['es', 'Español (traducción automática)'], ['en', 'Inglés (original de AniList)']])}
      ${llave('ordenar_automatico', 'Mantener los canales en orden', 'Si llega un episodio que va antes de otros ya subidos, se reacomoda el canal.')}
    </section>
    <section class="tarjeta"><header><h2>${icono('subir')}Subida</h2></header>
      ${llave('subida_automatica', 'Subida automática', 'Sube apenas aparecen los archivos. Si está apagada, usas "Subir ahora".')}
      ${lista('repetidos', 'Si un episodio ya está subido', 'Por ejemplo, cuando consigues otra versión con subtítulos en español. Si lo borraste en Telegram, se vuelve a subir en ambos casos.', [['mover', 'Dejarlo en Subidos\\_repetidos'], ['reemplazar', 'Reemplazar el que está en Telegram']])}
      ${numero('conexiones', 'Partes en paralelo', 'Más partes a la vez suben más rápido, hasta lo que dé tu conexión.', 1, 16)}
      ${numero('segundos_escaneo', 'Revisar la carpeta cada', 'Segundos entre cada revisión.', 5, 600)}
      <div class="campo horizontal"><div><span class="etiqueta">Prueba de velocidad</span><small id="resultado-velocidad">Mide tu subida real a Telegram sin publicar nada.</small></div>
        <button class="boton" id="b-velocidad">${icono('rayo')}Medir</button></div>
    </section>
    <section class="tarjeta"><header><h2>${icono('ajustes')}Programas</h2></header>
      ${programa('ffmpeg')}${programa('ffprobe')}${programa('siete_zip')}
    </section>
    <section class="tarjeta"><header><h2>${icono('panel')}Windows y apariencia</h2></header>
      ${llave('', 'Acceso en el escritorio', 'Ícono para abrir la aplicación.', d.accesos.escritorio, 'data-acceso="escritorio"')}
      ${llave('', 'Acceso en el menú Inicio', 'Para encontrarla buscando "Anime Telegram".', d.accesos.inicio, 'data-acceso="inicio"')}
      ${llave('', 'Iniciar con Windows', 'Se abre minimizada al prender la PC y sigue vigilando la carpeta.', d.accesos.arranque, 'data-acceso="arranque"')}
      <div class="campo"><label for="tema">Tema</label><select id="tema">
        ${[['sistema', 'Igual que Windows'], ['oscuro', 'Oscuro'], ['claro', 'Claro']].map(([v, t]) => `<option value="${v}" ${tema === v ? 'selected' : ''}>${t}</option>`).join('')}
      </select></div>
      <div class="campo horizontal"><div><span class="etiqueta">Datos de la aplicación</span><small>${esc(d.datos)}</small></div>
        <button class="boton" data-abrir="datos">${icono('carpeta')}Abrir</button></div>
    </section></div>`;
  $$('[data-login]').forEach(x => x.onclick = abrirLogin);
  $('#b-guardar').onclick = ev => guardarAjustes(ev.currentTarget);
  const cerrar = $('#b-cerrar-sesion');
  if (cerrar) cerrar.onclick = async ev => {
    if (await confirmar('Cerrar sesión', 'Se cierra la sesión de Telegram en este equipo. Tus canales no se tocan.', 'Cerrar sesión')) {
      accion(ev.currentTarget, () => api('POST', '/api/sesion/cerrar'), 'Sesión cerrada.');
    }
  };
  $('#b-velocidad').onclick = ev => accion(ev.currentTarget, async () => {
    $('#resultado-velocidad').textContent = 'Midiendo… (tarda unos segundos)';
    const r = await api('POST', '/api/velocidad');
    $('#resultado-velocidad').textContent = `De a una parte: ${r.una.toFixed(1)} MB/s · Con ${r.conexiones} en paralelo: ${r.paralelo.toFixed(1)} MB/s`;
  });
  $$('[data-acceso]').forEach(x => x.onchange = () => accion(null, () => api('POST', '/api/accesos', { [x.dataset.acceso]: x.checked }),
    x.checked ? 'Acceso directo creado.' : 'Acceso directo quitado.'));
  $('#tema').onchange = ev => aplicarTema(ev.target.value, true);
}

function guardarAjustes(boton) {
  const cambios = {};
  $$('[data-ajuste]').forEach(x => {
    cambios[x.dataset.ajuste] = x.type === 'checkbox' ? x.checked : x.type === 'number' ? Number(x.value) : x.value;
  });
  return accion(boton, async () => {
    const r = await api('PUT', '/api/ajustes', cambios);
    if (r.errores.length) throw new Error(r.errores.join(' · '));
    return r;
  }, 'Ajustes guardados.');
}

function aplicarTema(tema, guardar = false) {
  if (tema === 'sistema') delete document.documentElement.dataset.tema;
  else document.documentElement.dataset.tema = tema;
  if (guardar) localStorage.setItem('tema', tema);
}

/* ================================================================ inicio de sesión */
function abrirLogin() {
  let paso = S.estado?.conexion === 'sin_api' ? 'api' : 'telefono';
  const orden = ['api', 'telefono', 'codigo', 'clave'];

  const pintar = (error = '') => {
    const indice = orden.indexOf(paso);
    const pasos = orden.map((_, k) => `<i class="${k <= indice ? 'hecho' : ''}"></i>`).join('');
    const formularios = {
      api: `<h2>Conectar con Telegram</h2>
        <p>Para subir con tu propia cuenta, Telegram pide una clave de API personal. Es gratis y se saca una sola vez.</p>
        <ol><li>Entra a <a href="https://my.telegram.org" data-externo>my.telegram.org</a> e inicia sesión con tu número.</li>
        <li>Abre <b>API development tools</b> y crea una app con cualquier nombre.</li>
        <li>Copia acá el <b>api_id</b> y el <b>api_hash</b>.</li></ol>
        <div class="campo"><label for="l-id">api_id</label><input id="l-id" inputmode="numeric" autocomplete="off"></div>
        <div class="campo"><label for="l-hash">api_hash</label><input id="l-hash" autocomplete="off" spellcheck="false"></div>
        <small style="color:var(--texto-3)">Se guardan en el Administrador de credenciales de Windows, no en un archivo.</small>`,
      telefono: `<h2>Tu número de teléfono</h2><p>Telegram te va a mandar un código a la app (no por SMS).</p>
        <div class="campo"><label for="l-tel">Número con código de país</label><input id="l-tel" type="tel" placeholder="+54 9 11 1234 5678" autocomplete="tel"></div>`,
      codigo: `<h2>Código de Telegram</h2><p>Escribe el código que te llegó en la app de Telegram.</p>
        <div class="campo"><label for="l-cod">Código</label><input id="l-cod" inputmode="numeric" autocomplete="one-time-code"></div>`,
      clave: `<h2>Verificación en dos pasos</h2><p>Tu cuenta tiene contraseña adicional. Escríbela para terminar.</p>
        <div class="campo"><label for="l-clave">Contraseña</label><input id="l-clave" type="password" autocomplete="current-password"></div>`,
    };
    const m = abrirModal(`<div class="pasos">${pasos}</div>${formularios[paso]}
      ${error ? `<div class="error-form">${esc(error)}</div>` : ''}
      <div class="pie-modal"><button class="boton" data-cerrar>Cancelar</button>
      <button class="boton primario" id="l-seguir">${paso === 'api' ? 'Continuar' : paso === 'telefono' ? 'Enviar código' : 'Confirmar'}</button></div>`);
    $('[data-cerrar]', m).onclick = cerrarModal;
    const primero = $('input', m);
    if (primero) primero.focus();
    $$('input', m).forEach(x => x.onkeydown = ev => { if (ev.key === 'Enter') $('#l-seguir').click(); });
    $('#l-seguir', m).onclick = async ev => {
      ev.currentTarget.disabled = true;
      try {
        if (paso === 'api') {
          await api('POST', '/api/sesion/api', { api_id: $('#l-id').value, api_hash: $('#l-hash').value });
          paso = 'telefono';
        } else if (paso === 'telefono') {
          await api('POST', '/api/sesion/telefono', { telefono: $('#l-tel').value });
          paso = 'codigo';
        } else if (paso === 'codigo') {
          const r = await api('POST', '/api/sesion/codigo', { codigo: $('#l-cod').value });
          if (r.resultado === 'falta_clave') paso = 'clave';
          else return terminar();
        } else {
          await api('POST', '/api/sesion/clave', { clave: $('#l-clave').value });
          return terminar();
        }
        pintar();
      } catch (e) {
        pintar(e.message);
      }
    };
  };
  const terminar = () => { cerrarModal(); avisar('Cuenta conectada. Ya se puede subir.', 'ok'); };
  pintar();
}

/* ================================================================ eventos en vivo */
function manejar({ tipo, datos }) {
  if (tipo === 'estado') {
    S.estado = datos;
    pintarCuenta();
    if (S.vista === 'panel') actualizarPanel();
  } else if (tipo === 'cola') {
    S.cola = datos;
    alCambiarCola();
  } else if (tipo === 'item') {
    const k = S.cola.findIndex(i => i.id === datos.id);
    const cambioEstado = k < 0 || S.cola[k].estado !== datos.estado;
    if (k < 0) S.cola.push(datos); else S.cola[k] = datos;
    if (S.vista === 'panel') {
      if (datos.id === S.estado?.actual) pintarActual();
      const fila = $(`[data-fila="${datos.id}"]`);
      if (fila && !cambioEstado) { fila.outerHTML = filaItem(datos); enlazarFilas($('#lista-cola')); } else if (cambioEstado) pintarCola();
    }
    if (cambioEstado) alCambiarCola();
  } else if (tipo === 'log') {
    const linea = { fecha: fmtFecha(datos.hora), nivel: datos.nivel, mensaje: datos.mensaje };
    S.log.push(linea);
    if (S.log.length > 2000) S.log.shift();
    if (S.vista === 'actividad') pintarRegistro();
    if (datos.nivel === 'ERROR') avisar(datos.mensaje, 'error');
    else if (datos.nivel === 'WARNING') avisar(datos.mensaje, 'aviso');
    else if (datos.mensaje.startsWith('Subido:')) avisar(datos.mensaje.replace('Subido: ', 'Subido · '), 'ok');
  } else if (tipo === 'series') {
    refrescarListas();
  }
}

function alCambiarCola() {
  if (S.vista === 'panel') { pintarCola(); pintarActual(); }
  if (S.vista === 'pendientes') {
    const firma = S.cola.filter(i => ['pendiente', 'error', 'cancelado'].includes(i.estado)).map(i => i.id + i.estado).join();
    if (firma !== S.pendientesVistos) pintarPendientes();
  }
}

async function refrescarListas() {
  try {
    [S.series, S.recientes] = await Promise.all([api('GET', '/api/series'), api('GET', '/api/recientes')]);
  } catch { return; }
  if (S.vista === 'panel') { pintarResumen(); pintarRecientes(); }
  if (S.vista === 'series') pintarGrillaSeries();
}

let reconexion = 0;
function conectarEventos() {
  const ws = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(TOKEN)}`);
  ws.onopen = async () => {
    reconexion = 0;
    $('#desconectado').hidden = true;
    try {
      const [d, series] = await Promise.all([api('GET', '/api/estado'), api('GET', '/api/series')]);
      Object.assign(S, { estado: d.estado, cola: d.cola, recientes: d.recientes, series });
      pintarCuenta();
      pintarVista();
    } catch (e) { avisar(e.message, 'error'); }
  };
  ws.onmessage = ev => manejar(JSON.parse(ev.data));
  ws.onclose = () => {
    $('#desconectado').hidden = false;
    setTimeout(conectarEventos, Math.min(1000 * 2 ** reconexion++, 8000));
  };
}

aplicarTema(localStorage.getItem('tema') || 'sistema');
irA(location.hash.slice(1) || 'panel');
conectarEventos();
