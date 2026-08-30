/**
 * Simulador del flujo n8n sin n8n: ejecuta el JS de cada nodo Code contra payloads de
 * ejemplo y muestra qué responde el webhook. Sirve para verificar la lógica del plano de
 * control (contadores, órdenes, informe) antes de importar el flujo o tras editarlo.
 *
 *   node n8n/simular_flujo.js
 *
 * No toca la red ni el disco: los nodos de archivo del flujo no se simulan.
 */
const fs = require('fs');
const path = require('path');

const flujo = JSON.parse(fs.readFileSync(path.join(__dirname, 'flujo_hermes_brain.json'), 'utf8'));
const TOKEN = 'token-de-prueba';
const estatico = {};
const salidas = {};

function codigoDe(nombre) {
  const nodo = flujo.nodes.find((n) => n.name === nombre);
  if (!nodo) { throw new Error(`No existe el nodo "${nombre}" en el flujo`); }
  return nodo.parameters.jsCode;
}

function correr(nombre, entrada) {
  const contexto = {
    $input: { first: () => ({ json: entrada }) },
    $env: { HERMES_TOKEN: TOKEN },
    $getWorkflowStaticData: () => estatico,
    $now: { toMillis: () => Date.now() },
  };
  const fn = new Function('$input', '$env', '$getWorkflowStaticData', '$now',
    `${codigoDe(nombre)}`);
  const items = fn(contexto.$input, contexto.$env, contexto.$getWorkflowStaticData, contexto.$now);
  salidas[nombre] = items;
  return items;
}

const sobre = (cuerpo, consulta = {}) => ({
  headers: { 'x-hermes-token': TOKEN }, body: cuerpo, query: consulta, params: {},
});

const LOTE = 'lote-simulado';
let fallos = 0;
function comprobar(descripcion, condicion) {
  console.log(`${condicion ? '  ok  ' : ' FALLA'}  ${descripcion}`);
  if (!condicion) { fallos += 1; }
}

// 1. Inventario -------------------------------------------------------------
let r = correr('Registrar inventario', sobre({
  lote: LOTE, host: 'PC-CONSULTA', carpetas: 2,
  inventario: { vistos: 1200, nuevos: 1150, repetidos: 50, ilegibles: 0 },
}));
comprobar('el inventario abre el lote', r[0].json.ok && r[0].json.lote === LOTE);
comprobar('la acción inicial es seguir', estatico.accion === 'seguir');

// 2. Resultados en dos tandas ----------------------------------------------
const registros = (n, estado) => Array.from({ length: n }, (_, i) => ({
  id: `sha${estado}${i}`, ext: '.pdf', clasificacion: 'cientifico', estado, score: 8.5,
  duracion_s: 42.1, md: estado === 'hecho', notion: estado === 'hecho', error: '',
}));
correr('Acumular resultados', sobre({ lote: LOTE, host: 'PC-CONSULTA', registros: registros(20, 'hecho') }));
r = correr('Acumular resultados', sobre({
  lote: LOTE, host: 'PC-CONSULTA',
  registros: [...registros(5, 'omitido'), ...registros(3, 'dudoso'), ...registros(2, 'error')],
}));
comprobar('contador de hechos = 20', r[0].json.contadores.hecho === 20);
comprobar('contador de dudosos = 3', r[0].json.contadores.dudoso === 3);
comprobar('procesados acumulados = 30', r[0].json.procesados === 30);

// 3. Control y mando --------------------------------------------------------
r = correr('Ordenes al worker', sobre({ lote: LOTE, avance: { procesados: 30, total: 1150 } }));
comprobar('sin órdenes pendientes el worker sigue', r[0].json.accion === 'seguir');
correr('Fijar accion', sobre({}, { token: TOKEN, accion: 'pausa', mensaje: 'reunión' }));
r = correr('Ordenes al worker', sobre({ lote: LOTE }));
comprobar('tras el mando, el worker recibe pausa', r[0].json.accion === 'pausa');
comprobar('el mensaje del mando llega al worker', r[0].json.mensaje === 'reunión');
correr('Fijar accion', sobre({}, { token: TOKEN, accion: 'seguir' }));

// 4. Fin de lote ------------------------------------------------------------
r = correr('Armar informe', sobre({
  lote: LOTE, host: 'PC-CONSULTA',
  resumen: { hecho: 20, omitido: 5, dudoso: 3, error: 2, total: 30 },
  clasificaciones: { cientifico: 20, no_cientifico: 5, clinico: 4, dudoso: 3 },
  dudosos: 3,
  errores: [{ id: 'sha0001', error: 'timeout tras 900s' }],
}));
const informe = r[0].json.informe;
comprobar('el informe nombra el lote', informe.includes(LOTE));
comprobar('el informe incluye la tabla de estado', informe.includes('| hecho | 20 |'));
comprobar('el informe explica cómo revisar los dudosos', informe.includes('hermes_brain.py revisar'));
comprobar('el aviso resume el lote', /3 dudosos por revisar/.test(r[0].json.aviso));
comprobar('el lote queda cerrado', estatico.lotes[LOTE].cerrado === true);

// 5. Vigilancia -------------------------------------------------------------
r = correr('Revisar latido', sobre({}));
comprobar('un lote cerrado no dispara alerta', r.length === 0);
estatico.lotes['lote-colgado'] = {
  host: 'PC-CONSULTA', cerrado: false, procesados: 7,
  ultimo_latido: Date.now() - 60 * 60 * 1000,
};
r = correr('Revisar latido', sobre({}));
comprobar('un lote sin latido dispara alerta', r.length === 1 && r[0].json.lote === 'lote-colgado');

// 6. Token inválido ---------------------------------------------------------
let rechazado = false;
try {
  correr('Registrar inventario', { headers: { 'x-hermes-token': 'malo' }, body: { lote: 'x' } });
} catch (e) { rechazado = /Token invalido/.test(e.message); }
comprobar('un token inválido es rechazado', rechazado);

console.log(`\n--- informe generado ---\n${informe}`);
console.log(fallos === 0 ? '\nSimulación completa: sin fallos.' : `\n${fallos} comprobación(es) fallida(s).`);
process.exit(fallos === 0 ? 0 : 1);
