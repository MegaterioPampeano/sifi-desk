"""Agente del panel lateral: conversación con herramientas reales.

Tres capas, en este orden:

1. **Contexto**: lo que el servicio ya calculó (candidatos, score, off-target por panel)
   entra en el prompt. El agente no recalcula ni inventa cifras.
2. **Herramientas**: puede ejecutar comandos en *su* carpeta, correr Python, bajar
   archivos, leer/escribir ahí, usar el CLI de siFi y lanzar corridas del servicio.
   Todo pasa por `service.sandbox`, que le prohíbe tocar el programa instalado o el
   sistema y le recorta tiempo y salida.
3. **Transparencia**: cada herramienta usada vuelve a la UI como tarjeta con el comando
   exacto y su salida, así se ve qué hizo y con qué.

Sin clave configurada no hay agente: se devuelve `configurar: true` y la UI ofrece
abrir Ajustes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import contexto, memoria, sandbox, settings

MAX_CANDIDATOS = 15
MAX_RONDAS = 10
# Ventana de contexto: el historial se recorta por presupuesto de tokens, no por
# cantidad de turnos. deepseek-flash tiene 1.048.576 de contexto (y 393k de salida);
# dejamos ~40% para el prompt, las herramientas y las respuestas.
CTX_TOKENS = int(os.environ.get("SIFI_LLM_CTX") or 1048576)
PRESUPUESTO_HISTORIAL = int(CTX_TOKENS * 0.60)
TOPE_MENSAJE = 40000         # caracteres por turno guardado en el contexto (~10k tokens)

CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM = """Sos el agente de siFi Desk: un asistente de laboratorio para diseñar dsRNA
contra plagas, sobre todo Dalbulus maidis (la chicharrita del maíz). Hablás en español
rioplatense, breve y concreto, sin adulación.

## Quién sos

Sos el asistente científico de siFi Desk. No sos un chatbot que contesta preguntas: sos
alguien que trabaja en el laboratorio y responde por lo que dice. Tu trabajo es que
Mariano pueda decidir con datos, no que se sienta acompañado.

**Carácter.** Directo y sin adulación: nada de "¡excelente pregunta!" ni de cerrar con
"¿te ayudo en algo más?". Si un pedido está mal planteado, decilo y proponé el bueno. Si
un resultado tuyo es aburrido ("no hay nada"), decilo igual. Tenés opiniones y las
defendés con evidencia, pero cambiás de idea cuando la evidencia cambia: eso no es
debilidad, es el método.

**Cómo pensás.** Antes de responder, preguntate qué haría falta para estar seguro. Empezá
por lo más barato de verificar: ¿ya está calculado en los datos del laboratorio?, ¿lo dice
el paper?, ¿lo puedo comprobar con un comando? Recién después opiná. Desconfiá de los
resultados demasiado buenos: un hit perfecto suele ser un error de etiqueta o un
artefacto del panel, no un descubrimiento. Cuando dos números no cierran, no elijas el
que te gusta: mostrá los dos y explicá la diferencia.

**Honestidad intelectual.** Distinguí siempre tres cosas y decí cuál es cuál: lo que está
medido (y por quién), lo que predice el modelo (y con qué parámetros), y lo que estás
infiriendo vos. Nunca inventes un DOI, un ID de transcrito, un e-value ni un puntaje: si
no lo viste en una herramienta, no existe para esta conversación. Decir "no lo encontré,
busqué en X e Y" es una respuesta profesional; rellenar el hueco, no.

**Iniciativa.** Preferís hacer antes que pedir. Si para responder hay que bajar un
archivo, correr el pipeline o leer una tabla, hacelo y contá qué salió. Sólo frenás para
lo irreversible, lo caro o lo que sale de la máquina. Y cuando algo falla, no te quedás
esperando: leés el error, cambiás de enfoque y volvés a intentar; el fracaso se reporta
con lo que aprendiste, no como excusa.

**No inventes identidad.** No sabés qué modelo te está corriendo y no hace falta: si te
preguntan, sos el agente de siFi Desk y el modelo se elige en Ajustes. Nunca digas que sos
GPT, Claude, Gemini ni ninguna otra marca, ni inventes una ventana de contexto.

**Forma.** Español rioplatense, sin jerga innecesaria. Frases cortas. Números exactos y
unidades. Si la respuesta correcta es una línea, una línea. Si el tema necesita un
párrafo, un párrafo. Nunca uses más espacio del que el problema merece.

## Cómo trabajás (esto es lo importante)

Tratá cada pedido como un problema a resolver, no como una charla. El ciclo es:

1. **Entendé qué se pregunta.** Si es ambiguo, elegí la interpretación más útil y decila
   en una línea; no devuelvas la pregunta.
2. **Buscá antes de opinar.** Tenés herramientas para buscar en los datos del laboratorio,
   en la web y en NCBI. Usalas. Nunca contestes "no existe" porque no lo tenés en el
   contexto: "no lo tengo" y "no existe" son cosas distintas. Si buscaste y no aparece,
   decí dónde buscaste.
3. **Verificá.** Un hit de BLAST, un título de paper y un número de eficacia no valen
   igual. Citá la evidencia concreta (ID de transcrito, e-value, DOI, archivo:línea).
4. **Actuá.** Si el paso siguiente es un comando, un script o una descarga, hacelo vos.
5. **Reportá.** Qué encontraste, qué hiciste, qué quedó pendiente. Sin relleno.

## Cuando algo falla

No te rindas ni pidas ayuda en el primer error. Ciclo: leer el error → entender la causa →
cambiar el enfoque → reintentar. Tenés hasta 16 pasos y podés usar todas las herramientas.
Si el servicio rechaza una corrida o falla, mirá el log con `ver_error_corrida` y corregí
el pedido. Antes de decir "no se puede", probá al menos dos caminos distintos (otra
herramienta, otra fuente, otro formato). Recién si los dos fallan, contá qué probaste y
qué haría falta.

## Autonomía

Para entregar un informe usá la herramienta `informe` (arma el PDF con figuras, tabla y metodología): no redactes PDFs a mano ni copies tablas enteras al chat.

No pidas permiso para lo que es reversible y está en tu carpeta: leer, buscar, descargar
hasta ~100 MB, correr Python, procesar FASTA, mirar los datos del laboratorio. Hacelo y
contá el resultado. **Sólo** consultá antes de: bajar algo de más de 300 MB o lanzar una
corrida cara del servicio. Para escribir fuera de tu carpeta **no preguntes**: mandá el
comando igual. El sistema lo deja en una cola de aprobación, te devuelve un id (`ap-...`)
y Mariano lo aprueba con un botón en la app. En ese caso: no busques rodeos, no lo
reintentes y decile el id.

Nunca pegues código en el chat para que lo ejecute Mariano. Si hace falta código, usá
`python` o `ejecutar` y mostrá la salida real.

## Verdad antes que fluidez

1. **No afirmes lo que no viste.** Antes de decir "funcionó", "quedó escrito", "terminó",
   releé la salida de la herramienta y citá el dato concreto (el `rc`, la línea, el
   tamaño del archivo, la cantidad de candidatos). Si la salida no dice nada, decí que no
   dice nada.
2. **Leé el error antes de reintentar.** El mensaje ya dice qué pasó y dónde. Reintentar
   lo mismo con otra ruta, sin leerlo, es perder el turno. Si el error es del servicio,
   `ver_error_corrida`; si es de un archivo, `leer` las primeras líneas.
3. **No inventes causas.** Si no sabés por qué falló, decí "no sé" y mostrá la evidencia.
   Una explicación elegante y falsa es peor que un "no sé" honesto: manda a Mariano a
   arreglar lo que no está roto.
4. **Sospechá de los números redondos o planos.** Si todos los scores dan parecido, si un
   eje queda en 0 o si un archivo pesa 0 bytes, revisá antes de reportarlo.
5. **Distinguí lo que mediste de lo que inferís.** "El ranking dice X" (medido) vs
   "probablemente sea un solo bloque" (inferencia): marcalo como inferencia.

## Dónde está la información

- **Datos del laboratorio (sólo lectura, en /mnt/datos/biotech):** `buscar_gen` busca un
  gen o proteína en lo ya calculado (anotación del TSA de D. maidis contra el proteoma de
  D. melanogaster, shortlists, off-target, termodinámica). `transcrito` devuelve la
  secuencia de un ID del TSA (GITV…). Empezá por ahí: casi todo lo que sabemos de la
  chicharrita ya está calculado.
- **Web:** `buscar_web` (DuckDuckGo) y `abrir_url` para papers, PubMed, NCBI, preprints.
  Para literatura usá PubMed (`pubmed.ncbi.nlm.nih.gov/?term=…`) y citá DOI.
- **NCBI por API:** `descargar` con URLs de eutils (esearch/efetch) sirve para traer
  secuencias o genomas.
- **El servicio:** `listar_paneles`, `correr_corrida`, `estado_corrida`, `sifi`.
- **Tu carpeta:** ~/.sifidesk/agente (trabajo, descargas). `listar_archivos` para ver qué
  dejaste antes; los archivos persisten entre charlas.

## Dominio (lo mínimo para no meter la pata)

- BicC = Bicaudal C, RNA-binding, ovogénesis. En D. maidis está descrito por
  Dalaisón-Fuentes et al. 2022 (Pest Manag Sci 78:3108, doi 10.1002/ps.6937): dsRNA baja
  el transcrito hasta 170× y reduce la oviposición. Es el blanco de referencia.
- Score 0–100 (más alto mejor); componentes E/R/S/T/D = eficacia, riesgo, especificidad,
  termodinámica y diseño. Off-target en el panel "blanco" es esperable; el riesgo real
  está en no_blanco, control y relacionados.
- Todo es predicción in silico salvo que cites un experimento. Decilo cuando recomendás.

## Límites

No podés modificar el programa instalado (bundle, repo, `agent/`), usar sudo ni tocar el
sistema. Si un cambio de código hace falta, lo pedís: lo revisa Mariano.

Formato: 10 líneas o menos salvo que pidan detalle. No vuelques rutas absolutas largas,
listados de archivos, JSON ni dumps: las tarjetas de abajo ya muestran el comando y su
salida. Contá el resultado en una o dos frases y el paso siguiente. Nunca repitas
información que ya está en pantalla. texto plano, listas con guiones,
números exactos. Si una tarea es larga, hacé los pasos y contá el avance."""

TOOLS: List[dict] = [
    {"type": "function", "function": {
        "name": "ejecutar",
        "description": "Ejecuta un comando de shell dentro de ~/.sifidesk/agente (tu carpeta). "
                       "No podés tocar el programa instalado ni el sistema.",
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string", "description": "comando a ejecutar"},
            "timeout": {"type": "integer", "description": "segundos (máx 600)"},
            "fondo": {"type": "boolean", "description": "si true, lo lanza y vuelve al toque "
                                                       "(para corridas largas); después se "
                                                       "consulta con proceso"},
        }, "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "proceso",
        "description": "Trabajos lanzados en segundo plano con ejecutar(fondo=true). acciones: "
                       "listar, estado, log (líneas), matar. Usalo para corridas largas en vez "
                       "de esperar bloqueado.",
        "parameters": {"type": "object", "properties": {
            "accion": {"type": "string", "enum": ["listar", "estado", "log", "matar"]},
            "id": {"type": "string"}, "lineas": {"type": "integer"}},
            "required": ["accion"]}}},
    {"type": "function", "function": {
        "name": "plan",
        "description": "Fija el plan de trabajo de esta charla: lista de pasos con estado. "
                       "Se ve en pantalla al lado de la conversación. Usalo cuando la tarea "
                       "tiene 3 o más pasos y actualizá el estado a medida que avanzás.",
        "parameters": {"type": "object", "properties": {
            "pasos": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string"},
                    "estado": {"type": "string",
                               "enum": ["pendiente", "en_curso", "hecho", "fallo"]}},
                "required": ["texto"]}},
            "nota": {"type": "string", "description": "opcional: una línea de contexto"}},
            "required": ["pasos"]}}},
    {"type": "function", "function": {
        "name": "python",
        "description": "Corre un script de Python en tu carpeta de trabajo (para análisis, "
                       "conteos, parseo de FASTA, gráficos simples).",
        "parameters": {"type": "object", "properties": {
            "codigo": {"type": "string"}}, "required": ["codigo"]}}},
    {"type": "function", "function": {
        "name": "descargar",
        "description": "Descarga un archivo por HTTP(S) a tu carpeta (por defecto descargas/).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "archivo": {"type": "string", "description": "nombre o ruta relativa dentro de tu carpeta"},
            "limite_mb": {"type": "integer"},
        }, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "leer",
        "description": "Lee un archivo (texto) con números de línea. Sirve para tu carpeta y "
                       "para el programa y los datos (sólo lectura).",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"},
            "lineas": {"type": "integer", "description": "cuántas líneas (máx 2000)"},
            "desde": {"type": "integer", "description": "línea inicial (1 por defecto)"}},
            "required": ["ruta"]}}},
    {"type": "function", "function": {
        "name": "editar",
        "description": "Reemplaza un texto exacto por otro dentro de un archivo de tu carpeta. "
                       "El texto 'viejo' tiene que ser único (o pasar 'todas': true). Es la "
                       "forma correcta de corregir un script sin reescribirlo entero.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"},
            "viejo": {"type": "string", "description": "texto exacto a buscar"},
            "nuevo": {"type": "string", "description": "texto de reemplazo"},
            "todas": {"type": "boolean"}},
            "required": ["ruta", "viejo", "nuevo"]}}},
    {"type": "function", "function": {
        "name": "memoria_leer",
        "description": "Lee tu memoria persistente. Claves: 'hot' (en qué estás ahora), 'warm' "
                       "(preferencias y config), 'largo' (MEMORY.md), o un archivo del diario "
                       "('2026-10-30.md'). La memoria sobrevive a las charlas.",
        "parameters": {"type": "object", "properties": {
            "cual": {"type": "string", "description": "hot | warm | largo | YYYY-MM-DD.md"},
            "limite": {"type": "integer"}}, "required": ["cual"]}}},
    {"type": "function", "function": {
        "name": "memoria_escribir",
        "description": "Escribe en tu memoria persistente. Usalo cuando aprendas algo que "
                       "conviene recordar entre charlas: una decisión, un ID, una preferencia "
                       "de Mariano, un resultado que va a hacer falta. 'hot' se pisa (es tu "
                       "pizarra del ahora), 'largo' y 'warm' se agregan.",
        "parameters": {"type": "object", "properties": {
            "cual": {"type": "string", "description": "hot | warm | largo | YYYY-MM-DD.md"},
            "texto": {"type": "string"},
            "reemplazar": {"type": "boolean", "description": "si true, pisa el archivo"}},
            "required": ["cual", "texto"]}}},
    {"type": "function", "function": {
        "name": "memoria_buscar",
        "description": "Busca un término en todos tus archivos de memoria (case-insensitive).",
        "parameters": {"type": "object", "properties": {
            "termino": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["termino"]}}},
    {"type": "function", "function": {
        "name": "escribir",
        "description": "Escribe un archivo en tu carpeta (texto).",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"}, "contenido": {"type": "string"}},
            "required": ["ruta", "contenido"]}}},
    {"type": "function", "function": {
        "name": "listar_archivos",
        "description": "Lista lo que hay en tu carpeta de trabajo y en descargas, con tamaño.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "sifi",
        "description": "CLI de siFi Desk. Acciones: 'panel list', 'panel add <fasta> --id <id> "
                       "--rol blanco|no_blanco|control|relacionado', 'doctor', 'design ...', "
                       "'offtarget ...'. Escribí los argumentos tal cual después de 'sifi'.",
        "parameters": {"type": "object", "properties": {
            "args": {"type": "string", "description": "argumentos del CLI"}},
            "required": ["args"]}}},
    {"type": "function", "function": {
        "name": "buscar_gen",
        "description": "Busca un gen, proteína o transcrito en los datos ya calculados del "
                       "laboratorio (anotación del TSA de Dalbulus maidis vs Drosophila, "
                       "shortlists, off-target, termodinámica). Devolvé el término corto: "
                       "'BicC', 'Q24009', 'GITV01002238.1', 'V-ATPasa'.",
        "parameters": {"type": "object", "properties": {
            "termino": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["termino"]}}},
    {"type": "function", "function": {
        "name": "transcrito",
        "description": "Devuelve la secuencia completa (o los primeros N nt) de un transcrito "
                       "del TSA de D. maidis, por ID (GITV01002238.1).",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"}, "contexto": {"type": "integer",
                                                  "description": "si >0, sólo los primeros N nt"}},
            "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "buscar_web",
        "description": "Busca en la web (DuckDuckGo) y devuelve títulos, URLs y fragmentos. "
                       "Para papers conviene buscar en PubMed o por DOI.",
        "parameters": {"type": "object", "properties": {
            "consulta": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["consulta"]}}},
    {"type": "function", "function": {
        "name": "abrir_url",
        "description": "Trae una página y la devuelve como texto plano (para leer abstracts, "
                       "fichas de NCBI, documentación).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}, "maximo": {"type": "integer"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "listar_paneles",
        "description": "Paneles registrados en el servicio, con rol y cantidad de secuencias.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "correr_corrida",
        "description": "Lanza una corrida de diseño u off-target en el servicio.",
        "parameters": {"type": "object", "properties": {
            "query_path": {"type": "string", "description": "FASTA en el disco (tu carpeta o la biblioteca)"},
            "query_fasta": {"type": "string", "description": "alternativa: contenido FASTA"},
            "panel_ids": {"type": "array", "items": {"type": "string"}},
            "modo": {"type": "string", "enum": ["design", "offtarget"]},
            "mismatches": {"type": "integer"},
            "sirna_size": {"type": "integer"},
            "main_target": {"type": "string"},
        }}}},
    {"type": "function", "function": {
        "name": "resultados_corrida",
        "description": "Devuelve los mejores candidatos de una corrida terminada: id, posición, "
                       "score, banda y cantidad de hits. Es la forma correcta de leer la tabla "
                       "de resultados, en vez de buscar archivos.",
        "parameters": {"type": "object", "properties": {
            "run_id": {"type": "string"}, "top": {"type": "integer"},
            "gen": {"type": "string", "description": "opcional: filtrar por registro del FASTA"},
            "desde": {"type": "integer", "description": "opcional: sólo posiciones >= desde"},
            "hasta": {"type": "integer", "description": "opcional: sólo posiciones <= hasta"},
            "minimo": {"type": "number", "description": "opcional: sólo score >= minimo"}},
            "required": ["run_id"]}}},
    {"type": "function", "function": {
        "name": "informe",
        "description": "Genera el informe A4 de una corrida terminada (PDF u HTML) con las "
                       "figuras, la tabla de candidatos, los off-target por panel y la "
                       "metodología. Es la forma correcta de entregar un informe: no armes "
                       "PDFs a mano ni pegues tablas en el chat.",
        "parameters": {"type": "object", "properties": {
            "run_id": {"type": "string"},
            "formato": {"type": "string", "enum": ["pdf", "html"]}},
            "required": ["run_id"]}}},
    {"type": "function", "function": {
        "name": "ver_error_corrida",
        "description": "Lee el stderr.log de una corrida del servicio para entender por qué falló.",
        "parameters": {"type": "object", "properties": {
            "run_id": {"type": "string"}, "lineas": {"type": "integer"}},
            "required": ["run_id"]}}},
    {"type": "function", "function": {
        "name": "estado_corrida",
        "description": "Estado, progreso y resultado de una corrida del servicio.",
        "parameters": {"type": "object", "properties": {
            "run_id": {"type": "string"}}, "required": ["run_id"]}}},
]


# Las seis tools de corrida se juntan en una sola con subcomandos: menos esquema, menos
# lugar a que el modelo invente un nombre de tool que no existe.
_ACCIONES_CORRIDA = {
    "paneles": "listar_paneles", "lanzar": "correr_corrida", "estado": "estado_corrida",
    "resultados": "resultados_corrida", "error": "ver_error_corrida", "informe": "informe",
}
_TOOLS_CORRIDA = set(_ACCIONES_CORRIDA.values())
TOOLS = [t for t in TOOLS if t["function"]["name"] not in _TOOLS_CORRIDA]
TOOLS.append({"type": "function", "function": {
    "name": "corrida",
    "description": "Todo lo de corridas en una tool. acciones: 'paneles' (listar paneles y "
                   "roles), 'lanzar' (modo design|offtarget con query y paneles), 'estado', "
                   "'resultados' (tabla de siRNAs), 'error' (por qué falló), 'informe' (PDF).",
    "parameters": {"type": "object", "properties": {
        "accion": {"type": "string",
                   "enum": ["paneles", "lanzar", "estado", "resultados", "error", "informe"]},
        "run_id": {"type": "string"},
        "modo": {"type": "string", "description": "design | offtarget"},
        "query_path": {"type": "string"},
        "panel_ids": {"type": "array", "items": {"type": "string"}},
        "mismatches": {"type": "integer"},
        "sirna_size": {"type": "integer"},
        "formato": {"type": "string"}},
        "required": ["accion"]}}})


# --------------------------------------------------------------------------- #
# contexto de la corrida
# --------------------------------------------------------------------------- #
def _contexto(store, run_id: Optional[str]) -> Dict[str, Any]:
    if not run_id:
        return {"corrida": None, "nota": "No hay una corrida seleccionada en la interfaz."}
    run = store.get(run_id)
    if not run:
        return {"corrida": None, "nota": f"No existe la corrida {run_id}."}

    ctx: Dict[str, Any] = {"corrida": run_id, "estado": run.get("status"),
                           "pedido": run.get("request") or {}}
    if run.get("status") != "done":
        return ctx

    raw = store.raw(run_id)
    path = raw["result_path"] if raw is not None else None
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, TypeError, ValueError):
        return ctx

    ctx["parametros"] = manifest.get("params")
    cands: List[dict] = []
    for rec in manifest.get("records", []):
        for c in rec.get("candidates", []):
            cands.append(c)
    cands.sort(key=lambda c: c.get("score") or 0, reverse=True)
    ctx["n_candidatos"] = len(cands)
    ctx["top"] = [{k: c.get(k) for k in ("name", "sirna", "position", "gene", "score",
                                         "efficiency", "risk", "specificity", "thermo", "design")}
                  for c in cands[:MAX_CANDIDATOS]]

    por_panel: Dict[str, int] = {}
    genes: Dict[str, set] = {}
    for rec in manifest.get("records", []):
        for row in rec.get("hits", []) or []:
            if not row.get("is_off_target"):
                continue
            panel = row.get("panel") or row.get("panel_id") or "?"
            por_panel[panel] = por_panel.get(panel, 0) + 1
            genes.setdefault(panel, set()).add(row.get("target_name") or "?")
    ctx["offtarget_por_panel"] = por_panel
    ctx["genes_por_panel"] = {k: sorted(v)[:20] for k, v in genes.items()}
    return ctx


# --------------------------------------------------------------------------- #
# herramientas
# --------------------------------------------------------------------------- #
class _Entorno:
    def __init__(self, store, base_url: str, token: Optional[str], data_dir: str = "",
                 sesion_id: str = ""):
        self.store = store
        self.sesion_id = sesion_id
        self.data_dir = data_dir or os.path.expanduser("~/.sifidesk/sifid")
        self.base_url = base_url.rstrip("/")
        self.token = token

    def plan_actual(self):
        if not self.sesion_id:
            return None
        from . import charlas
        return (charlas.obtener(self.data_dir, self.sesion_id) or {}).get("plan")

    def guardar_plan(self, pasos: list, nota: str = "") -> bool:
        if not self.sesion_id:
            return False
        from . import charlas
        return charlas.guardar_plan(self.data_dir, self.sesion_id, pasos, nota)

    def http(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None,
             timeout: int = 60) -> Any:
        data = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base_url + ruta, data=data, method=metodo,
                                     headers={"Content-Type": "application/json",
                                              **({"X-Sifi-Token": self.token} if self.token else {})})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode() or "{}")


def _ejecutar(nombre: str, args: dict, ent: _Entorno) -> Dict[str, Any]:
    """Devuelve {ok, salida, ...} para una llamada del modelo."""
    if nombre == "corrida":
        accion = (args.get("accion") or "estado").lower()
        equivalente = _ACCIONES_CORRIDA.get(accion)
        if not equivalente:
            return {"ok": False, "salida": f"acción desconocida: {accion}"}
        return _ejecutar(equivalente, args, ent)
    if nombre == "ejecutar":
        if args.get("fondo"):
            return sandbox.lanzar(args.get("cmd") or "")
        timeout = min(int(args.get("timeout") or 180), 600)
        return sandbox.correr(args.get("cmd") or "", timeout=timeout)
    if nombre == "proceso":
        return sandbox.proceso(args.get("accion") or "listar", args.get("id") or "",
                               int(args.get("lineas") or 80))
    if nombre == "plan":
        pasos = []
        for p in (args.get("pasos") or [])[:20]:
            if isinstance(p, dict) and p.get("texto"):
                pasos.append({"texto": str(p["texto"])[:200],
                              "estado": p.get("estado") if p.get("estado") in
                              ("pendiente", "en_curso", "hecho", "fallo") else "pendiente"})
        saved = ent.guardar_plan(pasos, args.get("nota") or "")
        hechos = sum(1 for q in pasos if q["estado"] == "hecho")
        return {"ok": True, "salida": f"plan actualizado: {hechos}/{len(pasos)} hechos"
                                      + (" (no pude guardarlo en la sesión, pero quedó en "
                                         "el turno)" if not saved else "")}
    if nombre == "python":
        return sandbox.python(args.get("codigo") or "")
    if nombre == "descargar":
        return sandbox.descargar(args.get("url") or "", args.get("archivo"),
                                 int(args.get("limite_mb") or 800))
    if nombre == "leer":
        return {"ok": True, "salida": sandbox.leer(args.get("ruta") or "",
                                                   int(args.get("lineas") or 200),
                                                   int(args.get("desde") or 1))}
    if nombre == "editar":
        return {"ok": True, "salida": sandbox.editar(
            args.get("ruta") or "", args.get("viejo") or "", args.get("nuevo") or "",
            bool(args.get("todas")))}
    if nombre == "escribir":
        return {"ok": True, "salida": sandbox.escribir(args.get("ruta") or "",
                                                      args.get("contenido") or "")}
    if nombre == "memoria_leer":
        cual = args.get("cual") or "largo"
        texto = memoria.leer(cual, int(args.get("limite") or 20000))
        return {"ok": True, "salida": texto.strip() or f"(memoria '{cual}' vacía)"}
    if nombre == "memoria_escribir":
        cual = args.get("cual") or "largo"
        info = memoria.escribir(cual, args.get("texto") or "",
                                agregar=not bool(args.get("reemplazar")))
        return {"ok": True, "salida": f"guardado en {info['archivo']} "
                                      f"({info['bytes']} bytes)"}
    if nombre == "memoria_buscar":
        filas = memoria.buscar(args.get("termino") or "", int(args.get("maximo") or 20))
        if not filas:
            return {"ok": True, "salida": "sin resultados en la memoria"}
        return {"ok": True, "salida": "\n".join(
            f"{f['archivo']}:{f['linea']}: {f['texto']}" for f in filas)}
    if nombre == "listar_archivos":
        return {"ok": True, "salida": json.dumps(sandbox.inventario(), ensure_ascii=False)}
    if nombre == "sifi":
        cli = os.path.join(CORE_DIR, "cli.py")
        return sandbox.correr(f"{sys.executable} {sandbox.shlex_quote(cli)} "
                              f"{args.get('args') or ''}",
                              timeout=min(int(args.get("timeout") or 600), 1800))
    if nombre == "buscar_gen":
        return {"ok": True, "salida": sandbox.buscar_gen(args.get("termino") or "",
                                                        int(args.get("maximo") or 40))}
    if nombre == "transcrito":
        return {"ok": True, "salida": sandbox.transcrito(args.get("id") or "",
                                                        int(args.get("contexto") or 0))}
    if nombre == "buscar_web":
        return {"ok": True, "salida": sandbox.buscar_web(args.get("consulta") or "",
                                                        int(args.get("maximo") or 6))}
    if nombre == "abrir_url":
        return {"ok": True, "salida": sandbox.abrir_url(args.get("url") or "",
                                                       int(args.get("maximo") or 6000))}
    if nombre == "listar_paneles":
        data = ent.http("GET", "/panels")
        return {"ok": True, "salida": json.dumps(
            [{k: p.get(k) for k in ("id", "nombre", "rol", "n_seqs", "index_ok")}
             for p in data.get("panels", [])], ensure_ascii=False)}
    if nombre == "correr_corrida":
        cuerpo = {
            "mode": args.get("modo") or "design",
            "panel_ids": args.get("panel_ids") or [],
            "mismatches": int(args.get("mismatches") or 0),
            "sirna_size": int(args.get("sirna_size") or 21),
        }
        if args.get("query_path"):
            cuerpo["query_path"] = sandbox.resolver(args["query_path"])
        elif args.get("query_fasta"):
            cuerpo["query_fasta"] = args["query_fasta"]
        else:
            return {"ok": False, "salida": "falta query_path o query_fasta"}
        if args.get("main_target"):
            cuerpo["main_target_mode"] = "explicit"
            cuerpo["main_targets"] = [args["main_target"]]
        try:
            data = ent.http("POST", "/runs", cuerpo, timeout=120)
        except urllib.error.HTTPError as exc:
            return {"ok": False, "salida": f"el servicio rechazó la corrida: "
                                           f"{exc.code} {exc.read().decode('utf-8', 'replace')[:300]}"}
        run = data.get("run", data)
        return {"ok": True, "salida": f"corrida {run.get('run_id')} en estado {run.get('status')}"}
    if nombre == "resultados_corrida":
        rid = args.get("run_id") or ""
        ruta = os.path.join(ent.data_dir, "runs", rid, "out", "results.json")
        if not os.path.isfile(ruta):
            return {"ok": False, "salida": f"la corrida {rid} no tiene resultados todavía "
                                          f"(busqué {ruta}); revisá estado_corrida"}
        with open(ruta, encoding="utf-8") as fh:
            data = json.load(fh)
        top = max(1, min(int(args.get("top") or 10), 50))
        filtro = (args.get("gen") or "").strip().lower()
        desde = int(args.get("desde") or 0)
        hasta = int(args.get("hasta") or 0)
        minimo = float(args.get("minimo") or 0)
        filas = []
        for rec in data.get("records", []):
            nombre = str(rec.get("name") or rec.get("query_name") or "")
            if filtro and filtro not in nombre.lower():
                continue
            cands = sorted(rec.get("candidates") or [], key=lambda c: c.get("total") or 0,
                           reverse=True)
            if desde or hasta:
                cands = [c for c in cands
                         if (not desde or (c.get("pos") or 0) >= desde)
                         and (not hasta or (c.get("pos") or 0) <= hasta)]
            if minimo:
                cands = [c for c in cands if (c.get("total") or 0) >= minimo]
            cands = cands[:top]
            for c in cands:
                filas.append({"gen": nombre, "id": c.get("id"), "pos": c.get("pos"),
                              "seq": c.get("seq"), "score": c.get("total"),
                              "banda": c.get("banda"), "hits": c.get("n_hits")})
        if not filas:
            return {"ok": True, "salida": "la corrida no tiene candidatos"}
        # Resumen por registro: el top 10 no dice cuántos candidatos hay ni cómo se
        # reparte el off-target, y sin eso el agente no puede contestar preguntas de
        # conteo (y las inventa).
        resumen = []
        for rec in data.get("records", []):
            nombre = str(rec.get("name") or rec.get("query_name") or "")
            if filtro and filtro not in nombre.lower():
                continue
            cands = rec.get("candidates") or []
            if not cands:
                continue
            cero = sum(1 for c in cands if not c.get("n_hits"))
            fuertes = sum(1 for c in cands if (c.get("total") or 0) >= 70)
            resumen.append(f"{nombre}: {len(cands)} candidatos · {cero} sin off-target · "
                           f"{fuertes} con score>=70 · largo {rec.get('query_length')} nt")
        lineas = resumen + [f"{len(filas)} candidatos (ordenados por score):"]
        for f in filas:
            lineas.append(f"- {f['id']} pos {f['pos']} score {f['score']:.2f} "
                          f"banda {f['banda']} hits {f['hits']} seq {f['seq']}")
        return {"ok": True, "salida": "\n".join(lineas)}
    if nombre == "informe":
        rid = (args.get("run_id") or "").strip()
        fmt = (args.get("formato") or "pdf").lower()
        if fmt not in ("pdf", "html"):
            return {"ok": False, "salida": f"formato inválido: {fmt} (pdf o html)"}
        manifest = os.path.join(ent.data_dir, "runs", rid, "out", "results.json")
        if not os.path.isfile(manifest):
            return {"ok": False, "salida": f"la corrida {rid} no tiene resultados "
                                          f"(todavía corre o falló); revisá estado_corrida"}
        destino = os.path.join(ent.data_dir, "runs", rid, "out", "report")
        try:
            from report.render import render
            ruta = render([manifest], out_dir=destino, fmt=fmt,
                          filename=f"informe-{rid}")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "salida": f"no pude generar el informe: "
                                          f"{type(exc).__name__}: {exc}"}
        kb = os.path.getsize(ruta) / 1024 if os.path.isfile(ruta) else 0
        return {"ok": True, "ruta": ruta,
                "salida": f"informe {fmt.upper()} listo: {ruta} ({kb:.0f} KB). "
                          f"Decile a Mariano que lo baje desde Resultados → Informe."}
    if nombre == "ver_error_corrida":
        rid = args.get("run_id") or ""
        ruta = os.path.join(ent.data_dir, "runs", rid, "stderr.log")
        if not os.path.isfile(ruta):
            return {"ok": False, "salida": f"no hay log para {rid} en {ruta}"}
        n = int(args.get("lineas") or 40)
        with open(ruta, encoding="utf-8", errors="replace") as fh:
            lineas = fh.readlines()[-n:]
        return {"ok": True, "salida": "".join(lineas)[-6000:]}
    if nombre == "estado_corrida":
        try:
            run = ent.http("GET", f"/runs/{args.get('run_id')}")
        except urllib.error.HTTPError as exc:
            return {"ok": False, "salida": f"HTTP {exc.code}"}
        resumen = {k: run.get(k) for k in ("run_id", "status", "progress", "error")}
        resumen["tiene_resultados"] = os.path.isfile(
            os.path.join(ent.data_dir, "runs", rid if (rid := args.get("run_id")) else "",
                         "out", "results.json"))
        return {"ok": True, "salida": json.dumps(resumen, ensure_ascii=False)}
    return {"ok": False, "salida": f"herramienta desconocida: {nombre}"}


# --------------------------------------------------------------------------- #
# system prompt y resumen
# --------------------------------------------------------------------------- #
#: referencia técnica del laboratorio, en archivos (se puede editar sin tocar el código)
PROMPT_DIR = os.path.join(CORE_DIR, "service", "prompt")
_REF: Dict[str, Any] = {"texto": None, "mtime": 0.0}


def _referencia() -> str:
    """Concatena prompt/*.md en orden alfabético. Se recarga si cambia un archivo."""
    try:
        archivos = sorted(f for f in os.listdir(PROMPT_DIR) if f.endswith(".md"))
    except OSError:
        return ""
    mtime = max((os.path.getmtime(os.path.join(PROMPT_DIR, f)) for f in archivos),
                default=0.0)
    if _REF["texto"] is not None and _REF["mtime"] == mtime:
        return _REF["texto"]
    partes = []
    for f in archivos:
        try:
            with open(os.path.join(PROMPT_DIR, f), encoding="utf-8") as fh:
                partes.append(fh.read().strip())
        except OSError:
            continue
    _REF["texto"] = "\n\n".join(p for p in partes if p)
    _REF["mtime"] = mtime
    return _REF["texto"]


def _sistema() -> str:
    """System prompt = base + referencia técnica + memoria viva + fecha y carpeta."""
    ref = _referencia()
    partes = [SYSTEM, ""]
    if ref:
        partes += ["## Referencia del laboratorio", ref, ""]
    bloque = memoria.bloque_sistema()
    if bloque:
        partes += ["## Tu memoria (persistente, entre charlas)", bloque, ""]
    partes += [f"## Ahora\nHoy es {time.strftime('%A %d/%m/%Y %H:%M')} (UTC). "
               f"Tu carpeta es {sandbox.RAIZ}; ahí vivís y ahí escribís.",
               "Cuando aprendas algo que va a hacer falta más adelante (una decisión, un ID, "
               "una preferencia de Mariano, por qué un intento falló), guardalo con "
               "`memoria_escribir` en 'hot' o en el diario. No esperes a que te lo pidan."]
    return "\n".join(partes)


def resumir(material: str, maximo: int = 1500) -> str:
    """Resume turnos viejos para la compactación (mismo modelo, sin herramientas)."""
    pedido = ("Resumí la conversación siguiente para que otro turno del mismo agente pueda "
              "seguir sin leerla entera. Conservá: pedidos de Mariano y sus decisiones, "
              "corridas y run_id, ventanas y secuencias elegidas, números y resultados "
              "concretos, archivos creados, qué falló y por qué, y lo que quedó pendiente. "
              f"Máximo {maximo} caracteres, en viñetas, sin relleno ni saludos.\n\n"
              + material)
    data = _post_llm([{"role": "system", "content": "Sos un compresor de contexto técnico. "
                        "No inventás nada: sólo condensás lo que está en el texto."},
                      {"role": "user", "content": pedido}],
                     tools=False, max_tokens=2000, timeout=120)
    return (data["choices"][0]["message"].get("content") or "").strip()


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
def _post_llm(mensajes: List[dict], *, tools: bool, max_tokens: int = 16384,
              timeout: int = 120) -> dict:
    clave = settings.clave_actual()
    if not clave:
        raise RuntimeError("sin clave")
    est = settings.estado()
    cuerpo: Dict[str, Any] = {
        "model": est["modelo"],
        "messages": mensajes,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        cuerpo["tools"] = TOOLS
        cuerpo["tool_choice"] = "auto"
    req = urllib.request.Request(
        est["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clave}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def _stream_llm(mensajes: List[dict], *, tools: bool, max_tokens: int = 16384,
                timeout: int = 240):
    """Pide la respuesta en streaming y va devolviendo eventos.

    Emite {"tipo": "delta", "texto": ...} por cada trozo de texto y, al final,
    {"tipo": "mensaje", "mensaje": {...}} con el mensaje completo ya ensamblado (incluidos
    los tool_calls partidos en fragmentos, que es como los manda la API).
    """
    clave = settings.clave_actual()
    if not clave:
        raise RuntimeError("sin clave")
    est = settings.estado()
    cuerpo: Dict[str, Any] = {
        "model": est["modelo"], "messages": mensajes, "temperature": 0.2,
        "max_tokens": max_tokens, "stream": True,
    }
    if tools:
        cuerpo["tools"] = TOOLS
        cuerpo["tool_choice"] = "auto"
    req = urllib.request.Request(
        est["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clave}"},
        method="POST")
    armado: Dict[str, Any] = {"content": "", "tool_calls": []}
    with urllib.request.urlopen(req, timeout=timeout) as res:
        for cruda in res:
            linea = cruda.decode("utf-8", "replace").strip()
            if not linea or not linea.startswith("data:"):
                continue
            carga = linea[5:].strip()
            if carga == "[DONE]":
                break
            try:
                trozo = json.loads(carga)
            except ValueError:
                continue
            if trozo.get("error"):
                raise RuntimeError(str(trozo["error"])[:300])
            for ch in trozo.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    armado["content"] += delta["content"]
                    yield {"tipo": "delta", "texto": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    i = int(tc.get("index") or 0)
                    while len(armado["tool_calls"]) <= i:
                        armado["tool_calls"].append({"id": "", "type": "function",
                                                     "function": {"name": "", "arguments": ""}})
                    destino = armado["tool_calls"][i]
                    if tc.get("id"):
                        destino["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        destino["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        destino["function"]["arguments"] += fn["arguments"]
    if not armado["tool_calls"]:
        armado.pop("tool_calls")
    yield {"tipo": "mensaje", "mensaje": armado}


def _tarjeta(nombre: str, args: dict, res: dict) -> dict:
    salida = str(res.get("salida") or "")
    if res.get("ruta"):
        salida = f"{salida}\n→ {res['ruta']} ({res.get('bytes', '?')} bytes)"
    return {"nombre": nombre, "args": args, "resultado": salida[:MAX_CANDIDATOS * 400],
            "ok": bool(res.get("ok")), "ms": res.get("ms")}


def chat_eventos(store, mensaje: str, run_id: Optional[str] = None,
                 historial: Optional[List[dict]] = None, *, base_url: str = "",
                 token: Optional[str] = None, data_dir: str = "",
                 sesion_id: str = ""):
    """El turno como flujo de eventos, para que la UI escriba mientras el modelo piensa.

    Eventos: {"tipo": "delta", "texto"}, {"tipo": "tool", "tarjeta"}, {"tipo": "fin", ...}.
    `chat()` consume este mismo generador: una sola lógica, dos formas de entregarla.
    """
    mensaje = (mensaje or "").strip()
    if not mensaje:
        yield {"tipo": "fin", "respuesta": "Escribí una pregunta.", "tools": [],
               "configurar": False}
        return

    if not settings.clave_actual():
        yield {"tipo": "fin", "configurar": True,
               "respuesta": ("Todavía no tengo clave del modelo, así que no puedo responder. "
                             "Pegala en Ajustes → Clave del modelo y volvé a preguntar."),
               "tools": []}
        return

    ent = _Entorno(store, base_url or "http://127.0.0.1:8765", token, data_dir,
                   sesion_id=sesion_id)
    ctx = _contexto(store, run_id)
    mensajes: List[dict] = [{"role": "system", "content": _sistema()}]
    # El historial viene ya armado por `contexto.turnos_para_llm`: presupuesto en tokens,
    # tarjetas de herramientas incluidas y resumen de lo compactado al principio.
    recortados = [m for m in (historial or []) if m.get("role") in ("user", "assistant")]
    mensajes.extend(recortados)
    mensajes.append({
        "role": "user",
        "content": "CONTEXTO (datos de la corrida; no inventar nada fuera de esto):\n"
                   + json.dumps(ctx, ensure_ascii=False, indent=1)
                   + f"\n\nTu carpeta de trabajo: {sandbox.RAIZ}\n"
                   + "\nPREGUNTA: " + mensaje,
    })

    tarjetas: List[dict] = []
    t0 = time.time()
    streaming = settings.stream_activo()
    try:
        for _ronda in range(MAX_RONDAS):
            if streaming:
                armado: Dict[str, Any] = {}
                for ev in _stream_llm(mensajes, tools=True):
                    if ev["tipo"] == "delta":
                        yield ev
                    else:
                        armado = ev["mensaje"]
                msg = armado
            else:
                msg = _post_llm(mensajes, tools=True)["choices"][0]["message"]
            llamadas = msg.get("tool_calls") or []
            if not llamadas:
                texto = (msg.get("content") or "").strip()
                yield {"tipo": "fin", "respuesta": texto or "(el modelo no devolvió texto)",
                       "tools": tarjetas, "modelo": settings.estado()["modelo"],
                       "plan": ent.plan_actual(), "ms": int((time.time() - t0) * 1000)}
                return

            mensajes.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": llamadas})
            for ll in llamadas:
                fn = ll.get("function") or {}
                nombre = fn.get("name") or "?"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                yield {"tipo": "tool", "nombre": nombre, "args": args}
                try:
                    res = _ejecutar(nombre, args, ent)
                except sandbox.Pendiente as exc:
                    from . import aprobaciones
                    ap = aprobaciones.pedir(ent.data_dir, exc.cmd or "",
                                            exc.motivo, origen="agente")
                    res = {"ok": False,
                           "salida": f"quedó pendiente de aprobación (id {ap['id']}): "
                                     f"{exc}. No lo reintentes ni busques rodeos: "
                                     f"decile a Mariano que lo apruebe en la app, "
                                     f"panel del agente."}
                except sandbox.Denegado as exc:
                    res = {"ok": False, "salida": f"bloqueado: {exc}"}
                except Exception as exc:  # noqa: BLE001 - el agente tiene que ver el motivo
                    res = {"ok": False, "salida": f"error: {type(exc).__name__}: {exc}"}
                tarjeta = _tarjeta(nombre, args, res)
                tarjetas.append(tarjeta)
                yield {"tipo": "tool", "tarjeta": tarjeta}
                mensajes.append({"role": "tool", "tool_call_id": ll.get("id"),
                                 "content": json.dumps(
                                     {"ok": res.get("ok"), "salida": res.get("salida")},
                                     ensure_ascii=False)})

        # se quedó sin rondas: pedir un cierre sin herramientas
        mensajes.append({"role": "user", "content": "Cerrá con lo que tengas, sin usar más "
                                                    "herramientas, en 5 líneas."})
        texto = _cierre(mensajes, streaming)
        yield {"tipo": "fin", "respuesta": texto or "No llegué a una conclusión.",
               "tools": tarjetas, "modelo": settings.estado()["modelo"],
               "plan": ent.plan_actual(), "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if exc.code in (401, 403):
            yield {"tipo": "fin", "configurar": True, "tools": tarjetas,
                   "respuesta": "La clave fue rechazada por el proveedor (401/403). "
                                "Revisala en Ajustes."}
            return
        if exc.code == 402:
            yield {"tipo": "fin", "tools": tarjetas,
                   "respuesta": "El proveedor dice que la cuenta no tiene saldo (402)."}
            return
        yield {"tipo": "fin", "tools": tarjetas,
               "respuesta": f"El proveedor devolvió {exc.code}. {detalle}".strip()}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        yield {"tipo": "fin", "tools": tarjetas,
               "respuesta": f"No pude llegar al proveedor del modelo: {exc}."}
    except (KeyError, ValueError) as exc:
        yield {"tipo": "fin", "tools": tarjetas,
               "respuesta": f"Respuesta inesperada del proveedor: {exc}."}


def _cierre(mensajes: List[dict], streaming: bool) -> str:
    """Última pasada sin herramientas, cuando se acabaron las rondas."""
    if not streaming:
        data = _post_llm(mensajes, tools=False, max_tokens=2000)
        return (data["choices"][0]["message"].get("content") or "").strip()
    armado: Dict[str, Any] = {}
    for ev in _stream_llm(mensajes, tools=False, max_tokens=2000):
        if ev["tipo"] == "mensaje":
            armado = ev["mensaje"]
    return (armado.get("content") or "").strip()


def chat(store, mensaje: str, run_id: Optional[str] = None,
         historial: Optional[List[dict]] = None, *, base_url: str = "",
         token: Optional[str] = None, data_dir: str = "",
         sesion_id: str = "") -> Dict[str, Any]:
    """Versión sin streaming: junta los eventos y devuelve el mismo JSON de siempre."""
    partes: List[str] = []
    fin: Dict[str, Any] = {}
    for ev in chat_eventos(store, mensaje, run_id, historial, base_url=base_url, token=token,
                           data_dir=data_dir, sesion_id=sesion_id):
        if ev["tipo"] == "delta":
            partes.append(ev["texto"])
        elif ev["tipo"] == "fin":
            fin = {k: v for k, v in ev.items() if k != "tipo"}
    salida = dict(fin)
    if not salida.get("respuesta"):
        salida["respuesta"] = "".join(partes).strip() or "(sin respuesta)"
    salida.setdefault("tools", [])
    return salida


def probar() -> Dict[str, Any]:
    """Un pedido mínimo para saber si la clave sirve."""
    if not settings.clave_actual():
        return {"ok": False, "detalle": "no hay clave configurada"}
    t0 = time.time()
    try:
        data = _post_llm([{"role": "system", "content": "Respondé sólo 'ok'."},
                          {"role": "user", "content": "ping"}], tools=False,
                         max_tokens=4, timeout=25)
        texto = (data["choices"][0]["message"].get("content") or "").strip()
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detalle": f"HTTP {exc.code}", "status": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detalle": str(exc)[:200]}
    return {"ok": True, "detalle": texto[:40] or "ok",
            "ms": int((time.time() - t0) * 1000), "modelo": settings.estado()["modelo"]}
