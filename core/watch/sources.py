"""Consultas a las fuentes de novedades científicas.

Fuentes implementadas (todas sin credenciales):

* **Crossref** (`api.crossref.org`) — papers con DOI, filtrable por fecha de publicación.
* **PubMed** (`eutils.ncbi.nlm.nih.gov`) — esearch + esummary.
* **bioRxiv** (`api.biorxiv.org`) — preprints por rango de fechas; la API no busca, así que
  se baja la ventana y se filtra localmente por palabras clave.
* **GitHub releases** — versiones nuevas del upstream siFi (opcional, para el vigilante
  "upstream").

Reglas que se respetan acá:

* `User-Agent` identificable con un mailto de contacto (`sifi-desk/0.1 (mailto:...)`), como
  piden Crossref y NCBI. El contacto se puede pisar con `SIFI_WATCH_CONTACT`.
* Timeout por request y **backoff exponencial** ante 429/5xx/timeouts, respetando
  `Retry-After` cuando viene.
* **Caché en disco** de cada respuesta: una corrida semanal no vuelve a golpear las APIs
  si ya bajó lo mismo, y `--offline` funciona con lo cacheado.
* Un fallo de una fuente **no** tumba la corrida: se anota en `client.warnings` y sigue.

Las funciones devuelven `dict` planos (no dataclasses) para que el JSON de salida sea
directamente el contrato con el agente (`sifi_watch` → `{novedades[]}`).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_CONTACT = "sifi-desk@omnivac.science"
VERSION = "0.1"

CROSSREF_URL = "https://api.crossref.org/works"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
BIORXIV_DETAILS = "https://api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}"
GITHUB_RELEASES = "https://api.github.com/repos/{repo}/releases"

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def user_agent(contact: Optional[str] = None) -> str:
    """User-Agent identificable. Crossref/NCBI rechazan clientes anónimos."""
    who = contact or os.environ.get("SIFI_WATCH_CONTACT") or DEFAULT_CONTACT
    return f"sifi-desk/{VERSION} (mailto:{who})"


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------- #
# normalización de texto (para matching local y dedupe por título)
# --------------------------------------------------------------------------- #

def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, espacios colapsados. Sirve para buscar y comparar."""
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


def normalize_title(title: str) -> str:
    """Sólo [a-z0-9 ]: dos títulos iguales con distinta puntuación colapsan al mismo key."""
    text = normalize_text(title)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _term_pattern(term: str) -> re.Pattern:
    """Phrase match con bordes de palabra.

    Admite plural (`insect` → `insects`, `pest` → `pests`) pero no prefijos/sufijos
    arbitrarios: `RNAi` no matchea `RNAinterference-ish` y `pest` no matchea `pesticide`.
    """
    words = [re.escape(w) for w in normalize_text(term).split() if w]
    if not words:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(words) + r"(?:s|es)?(?![a-z0-9])")


def matched_terms(text: str, keywords: Sequence[str]) -> List[str]:
    hay = normalize_text(text)
    hits = []
    for kw in keywords or ():
        if kw and _term_pattern(kw).search(hay):
            hits.append(kw)
    return hits


# --------------------------------------------------------------------------- #
# caché en disco
# --------------------------------------------------------------------------- #

class DiskCache:
    """Un archivo JSON por request, con timestamp. Simple, inspeccionable, sin dependencias."""

    def __init__(self, root: str | os.PathLike, ttl_hours: float = 24.0):
        self.root = Path(root)
        self.ttl_hours = float(ttl_hours)

    def key_for(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        raw = url + "?" + json.dumps(params or {}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str, max_age_hours: Optional[float] = "default") -> Optional[Dict[str, Any]]:
        """Devuelve el registro cacheado o None. `max_age_hours=None` ignora la edad."""
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        age_hours = "default"
        if max_age_hours == "default":
            max_age_hours = self.ttl_hours
        if max_age_hours is not None:
            ts = record.get("fetched_at")
            try:
                age_hours = (time.time() - float(ts)) / 3600.0
            except (TypeError, ValueError):
                return None
            if age_hours > float(max_age_hours):
                return None
        return record

    def put(self, key: str, url: str, payload: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record = {"fetched_at": time.time(), "url": url, "payload": payload}
        tmp = self.path_for(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path_for(key))


# --------------------------------------------------------------------------- #
# cliente HTTP
# --------------------------------------------------------------------------- #

class FetchError(RuntimeError):
    """La fuente falló después de reintentar."""

    def __init__(self, message: str, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


class OfflineCacheMiss(FetchError):
    """Modo offline y no hay nada cacheado para ese request."""


Transport = Callable[[str, Dict[str, Any], Dict[str, str], float], Tuple[int, Dict[str, str], str]]


def requests_transport(url: str, params: Dict[str, Any], headers: Dict[str, str],
                       timeout: float) -> Tuple[int, Dict[str, str], str]:
    import requests  # import perezoso: los tests no lo necesitan

    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    return resp.status_code, dict(resp.headers), resp.text


class HttpClient:
    """GET JSON con caché, timeout, rate-limit suave y backoff exponencial."""

    def __init__(
        self,
        cache: Optional[DiskCache] = None,
        offline: bool = False,
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 1.0,
        transport: Optional[Transport] = None,
        contact: Optional[str] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cache = cache
        self.offline = bool(offline)
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self.backoff = float(backoff)
        self.transport = transport or requests_transport
        self.sleep = sleep
        self.headers = {"User-Agent": user_agent(contact), "Accept": "application/json"}
        self.warnings: List[str] = []
        self._last_request: Dict[str, float] = {}

    # -- helpers ---------------------------------------------------------- #
    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def _throttle(self, url: str, min_interval: float) -> None:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        last = self._last_request.get(host)
        if min_interval > 0 and last is not None:
            wait = min_interval - (time.monotonic() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = time.monotonic()

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        cache_key: Optional[str] = None,
        min_interval: float = 0.0,
    ) -> Any:
        """Devuelve el payload JSON. Usa caché fresca; en error, cae a caché vieja."""
        params = dict(params or {})
        key = cache_key or (self.cache.key_for(url, params) if self.cache else None)
        # offline ignora la edad de la caché: si está, se usa
        cached = (self.cache.get(key, max_age_hours=None if self.offline else "default")
                  if (self.cache and key) else None)

        if self.offline:
            if cached is None:
                raise OfflineCacheMiss(f"sin caché para {url}", url=url)
            return cached["payload"]

        if cached is not None:
            return cached["payload"]

        last_error: Optional[Exception] = None
        headers = dict(self.headers)
        for attempt in range(1, self.retries + 1):
            self._throttle(url, min_interval)
            try:
                status, resp_headers, body = self.transport(url, params, headers, self.timeout)
            except Exception as exc:  # red caída, timeout, DNS…
                last_error = exc
                if attempt < self.retries:
                    self._backoff(attempt, None)
                continue

            if status == 200:
                try:
                    payload = json.loads(body)
                except ValueError as exc:
                    last_error = FetchError(f"respuesta no-JSON de {url}", status, url)
                    break
                if self.cache is not None and key:
                    try:
                        self.cache.put(key, url, payload)
                    except OSError as exc:  # caché de sólo lectura: no es fatal
                        self.warn(f"no se pudo escribir la caché: {exc}")
                return payload

            last_error = FetchError(
                f"HTTP {status} en {url}" + (f": {body[:200]}" if body else ""), status, url
            )
            if status not in RETRY_STATUS:
                break  # 400/403/404: reintentar no arregla nada
            if attempt < self.retries:
                self._backoff(attempt, resp_headers)

        stale = self.cache.get(key, max_age_hours=None) if (self.cache and key) else None
        if stale is not None:
            self.warn(f"se usa caché vencida para {url} ({last_error})")
            return stale["payload"]
        raise FetchError(
            str(last_error) if last_error else f"fallo desconocido en {url}",
            getattr(last_error, "status", None),
            url,
        )

    def _backoff(self, attempt: int, headers: Optional[Dict[str, str]]) -> None:
        delay = None
        if headers:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after:
                try:
                    delay = min(float(retry_after), 30.0)
                except (TypeError, ValueError):
                    delay = None
        if delay is None:
            delay = self.backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
        self.sleep(delay)


# --------------------------------------------------------------------------- #
# ítems
# --------------------------------------------------------------------------- #

def make_item(
    *,
    source: str,
    title: str,
    date: str = "",
    doi: str = "",
    pmid: str = "",
    url: str = "",
    authors: str = "",
    venue: str = "",
    abstract: str = "",
    query_id: str = "",
    query_text: str = "",
    why: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ítem canónico del digest. Fechas ISO `YYYY-MM-DD` (o `YYYY-MM` / `YYYY`)."""
    item: Dict[str, Any] = {
        "title": (title or "").strip(),
        "source": source,
        "date": (date or "").strip(),
        "doi": (doi or "").strip().lower(),
        "pmid": str(pmid or "").strip(),
        "url": url or "",
        "authors": authors or "",
        "venue": venue or "",
        "abstract": (abstract or "").strip(),
        "query_id": query_id,
        "query": query_text,
        "why": why,
        "matched_by": [{"query_id": query_id, "query": query_text, "why": why}],
    }
    if extra:
        item.update(extra)
    item["id"] = item_id(item)
    return item


def item_id(item: Dict[str, Any]) -> str:
    if item.get("doi"):
        return "doi:" + str(item["doi"]).strip().lower()
    if item.get("pmid"):
        return "pmid:" + str(item["pmid"])
    return "title:" + normalize_title(item.get("title", ""))[:120]


def _iso_from_parts(parts: Any) -> str:
    """Crossref date-parts → ISO parcial.

    Crossref manda `[[2026, 10, 27]]` (lista de listas) pero también aceptamos la lista
    plana `[2026, 10, 27]` para no depender de la forma exacta.
    """
    if isinstance(parts, (list, tuple)) and parts and isinstance(parts[0], (list, tuple)):
        parts = parts[0]
    try:
        nums = [int(x) for x in (parts or []) if x is not None]
    except (TypeError, ValueError):
        return ""
    if not nums:
        return ""
    if len(nums) == 1:
        return f"{nums[0]:04d}"
    if len(nums) == 2:
        return f"{nums[0]:04d}-{nums[1]:02d}"
    return f"{nums[0]:04d}-{nums[1]:02d}-{nums[2]:02d}"


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return value[0] if value else ""
    return value


def _authors_crossref(author_list: Any, limit: int = 3) -> str:
    names = []
    for a in author_list or []:
        if not isinstance(a, dict):
            continue
        name = a.get("family") or a.get("name") or ""
        given = a.get("given") or ""
        names.append((name + (", " + given if given else "")).strip())
        if len(names) >= limit:
            break
    return "; ".join([n for n in names if n])


# --------------------------------------------------------------------------- #
# Crossref
# --------------------------------------------------------------------------- #

def fetch_crossref(
    query: Dict[str, Any],
    since: date,
    limit: int,
    client: HttpClient,
    until: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Crossref ordenado por **relevancia** dentro de la ventana.

    Ojo: `sort=published&order=desc` trae basura (Crossref tiene metadatos con años 2107,
    2117…) y encima desordena el resultado por fecha en vez de por tema. Por eso no se
    ordena: se deja el ranking de relevancia de Crossref y se acota con `until-pub-date`.
    """
    until = until or today_utc()
    params = {
        "query.bibliographic": query["text"],
        "filter": (f"from-pub-date:{since.isoformat()},"
                   f"until-pub-date:{until.isoformat()},type:journal-article"),
        "rows": str(max(1, int(limit))),
        "select": "DOI,title,issued,published-online,published-print,container-title,author,URL,abstract,type,score",
        "mailto": os.environ.get("SIFI_WATCH_CONTACT") or DEFAULT_CONTACT,
    }
    data = client.get_json(CROSSREF_URL, params, min_interval=0.2)
    items = []
    for rec in ((data or {}).get("message") or {}).get("items") or []:
        title = _first(rec.get("title"))
        if not isinstance(title, str) or not title.strip():
            continue
        doi = (rec.get("DOI") or "").lower()
        when = (_iso_from_parts((rec.get("issued") or {}).get("date-parts"))
                or _iso_from_parts((rec.get("published-online") or {}).get("date-parts"))
                or _iso_from_parts((rec.get("published-print") or {}).get("date-parts")))
        items.append(make_item(
            source="crossref",
            title=re.sub(r"<[^>]+>", "", title),
            date=when,
            doi=doi,
            url=rec.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            authors=_authors_crossref(rec.get("author")),
            venue=_first(rec.get("container-title")) or "",
            abstract=re.sub(r"<[^>]+>", " ", rec.get("abstract") or ""),
            query_id=query.get("id", ""),
            query_text=query.get("text", ""),
            why=query.get("why", ""),
            extra={"matched_by": [{"query_id": query.get("id", ""), "query": query.get("text", ""),
                                   "why": query.get("why", "")}],
                   "matched_terms": matched_terms(title + " " + (rec.get("abstract") or ""),
                                                  query.get("keywords") or []),
                   "score": rec.get("score")},
        ))
    return items


# --------------------------------------------------------------------------- #
# PubMed (E-utilities)
# --------------------------------------------------------------------------- #

def _pubmed_term(query: Dict[str, Any], since: date, until: date) -> str:
    if query.get("pubmed_term"):
        return str(query["pubmed_term"])
    base = query["text"]
    if not re.search(r"\b(AND|OR|NOT)\b", base):
        base = f"({base})"
    return f'{base} AND ("{since.isoformat()}"[PDAT] : "{until.isoformat()}"[PDAT])'


def fetch_pubmed(
    query: Dict[str, Any],
    since: date,
    limit: int,
    client: HttpClient,
    until: Optional[date] = None,
) -> List[Dict[str, Any]]:
    until = until or today_utc()
    search = client.get_json(
        PUBMED_ESEARCH,
        {
            "db": "pubmed",
            "term": _pubmed_term(query, since, until),
            "retmax": str(max(1, int(limit))),
            "retmode": "json",
            "sort": "date",
        },
        min_interval=0.4,  # 3 req/s sin API key
    )
    ids = ((search or {}).get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []
    summary = client.get_json(
        PUBMED_ESUMMARY,
        {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        min_interval=0.4,
    )
    result = (summary or {}).get("result") or {}
    items = []
    for pmid in ids:
        rec = result.get(str(pmid)) or {}
        if not rec or rec.get("error"):
            continue
        doi = ""
        for aid in rec.get("articleids") or []:
            if aid.get("idtype") == "doi":
                doi = (aid.get("value") or "").strip()
                break
        title = (rec.get("title") or "").strip().rstrip(".")
        if not title:
            continue
        pubdate = (rec.get("pubdate") or "").strip()
        items.append(make_item(
            source="pubmed",
            title=title,
            date=_pubmed_date(pubdate, rec.get("sortpubdate") or ""),
            doi=doi,
            pmid=str(pmid),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            authors="; ".join(a.get("name", "") for a in (rec.get("authors") or [])[:3]),
            venue=rec.get("fulljournalname") or rec.get("source") or "",
            query_id=query.get("id", ""),
            query_text=query.get("text", ""),
            why=query.get("why", ""),
            extra={"matched_by": [{"query_id": query.get("id", ""), "query": query.get("text", ""),
                                   "why": query.get("why", "")}],
                   "matched_terms": matched_terms(title, query.get("keywords") or [])},
        ))
    return items


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _pubmed_date(pubdate: str, sortpubdate: str = "") -> str:
    """`2026 Oct 20`, `2026 Oct`, `2026` o `2026/10/20 00:00` → ISO parcial."""
    m = re.match(r"^\s*(\d{4})/(\d{1,2})/(\d{1,2})", sortpubdate or "")
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^\s*(\d{4})\s+([A-Za-z]{3})[a-z]*\s+(\d{1,2})", pubdate or "")
    if m:
        return f"{int(m.group(1)):04d}-{_MONTHS.get(m.group(2).lower(), 1):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^\s*(\d{4})\s+([A-Za-z]{3})", pubdate or "")
    if m:
        return f"{int(m.group(1)):04d}-{_MONTHS.get(m.group(2).lower(), 1):02d}"
    m = re.match(r"^\s*(\d{4})", pubdate or "")
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# bioRxiv
# --------------------------------------------------------------------------- #

def fetch_biorxiv(
    query: Dict[str, Any],
    since: date,
    limit: int,
    client: HttpClient,
    until: Optional[date] = None,
    max_pages: int = 8,
    server: str = "biorxiv",
) -> List[Dict[str, Any]]:
    """La API de bioRxiv no busca: baja la ventana (100 por página) y filtra localmente."""
    until = until or today_utc()
    keywords = query.get("keywords") or [query.get("text", "")]
    found: List[Dict[str, Any]] = []
    cursor = 0
    total = None
    pages = 0
    while pages < max_pages:
        url = BIORXIV_DETAILS.format(start=since.isoformat(), end=until.isoformat(), cursor=cursor)
        data = client.get_json(url, {}, min_interval=0.2)
        collection = (data or {}).get("collection") or []
        messages = (data or {}).get("messages") or [{}]
        total = int((messages[0] or {}).get("total") or len(collection))
        pages += 1
        for rec in collection:
            title = (rec.get("title") or "").strip()
            abstract = (rec.get("abstract") or "").strip()
            hits = matched_terms(title + " " + abstract, keywords)
            if not hits:
                continue
            doi = (rec.get("doi") or "").lower()
            version = str(rec.get("version") or "1")
            found.append(make_item(
                source=server,
                title=title,
                date=(rec.get("date") or "").strip(),
                doi=doi,
                url=(f"https://www.{server}.org/content/{doi}v{version}" if doi else ""),
                authors=(rec.get("authors") or "").replace(";", "; "),
                venue=(rec.get("category") or "").replace("_", " "),
                abstract=abstract,
                query_id=query.get("id", ""),
                query_text=query.get("text", ""),
                why=query.get("why", ""),
                extra={"matched_by": [{"query_id": query.get("id", ""), "query": query.get("text", ""),
                                       "why": query.get("why", "")}],
                       "matched_terms": hits,
                       "preprint": True},
            ))
        cursor += len(collection) or 100
        if not collection or cursor >= total:
            break
    found.sort(key=lambda it: it.get("date") or "", reverse=True)
    return found[:limit]


# --------------------------------------------------------------------------- #
# GitHub releases (upstream siFi)
# --------------------------------------------------------------------------- #

def fetch_github_releases(
    query: Dict[str, Any],
    since: date,
    limit: int,
    client: HttpClient,
    repo: str = "snowformatics/siFi21-",
) -> List[Dict[str, Any]]:
    repo = query.get("repo") or repo
    url = GITHUB_RELEASES.format(repo=repo)
    data = client.get_json(url, {"per_page": str(max(1, min(int(limit), 30)))}, min_interval=0.2)
    items = []
    for rec in data or []:
        published = (rec.get("published_at") or rec.get("created_at") or "")[:10]
        if published and published < since.isoformat():
            continue
        tag = rec.get("tag_name") or rec.get("name") or ""
        items.append(make_item(
            source="github",
            title=f"siFi upstream {tag}".strip() + (f" — {rec['name']}" if rec.get("name") and rec.get("name") != tag else ""),
            date=published,
            url=rec.get("html_url") or f"https://github.com/{repo}/releases",
            venue=repo,
            abstract=(rec.get("body") or "")[:1500],
            query_id=query.get("id", ""),
            query_text=query.get("text", ""),
            why=query.get("why", ""),
            extra={"matched_by": [{"query_id": query.get("id", ""), "query": query.get("text", ""),
                                   "why": query.get("why", "")}],
                   "matched_terms": [], "release": True},
        ))
    return items[:limit]


# --------------------------------------------------------------------------- #
# despacho
# --------------------------------------------------------------------------- #

SOURCES: Dict[str, Callable[..., List[Dict[str, Any]]]] = {
    "crossref": fetch_crossref,
    "pubmed": fetch_pubmed,
    "biorxiv": fetch_biorxiv,
    "github": fetch_github_releases,
}


def fetch_query(
    query: Dict[str, Any],
    since: date,
    limit: int,
    client: HttpClient,
    until: Optional[date] = None,
    max_pages: int = 8,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Corre todas las fuentes pedidas por una query. Devuelve (ítems, errores)."""
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    for source in query.get("sources") or ["crossref", "pubmed"]:
        fn = SOURCES.get(source)
        if fn is None:
            errors.append(f"{source}: fuente desconocida")
            continue
        where = f"{source}/{query.get('id', '?')}"
        try:
            if source == "biorxiv":
                got = fn(query, since, limit, client, until=until, max_pages=max_pages)
            elif source == "github":
                got = fn(query, since, limit, client)
            elif source == "crossref":
                got = fn(query, since, limit, client, until=until)
            else:
                got = fn(query, since, limit, client)
            items.extend(got)
        except OfflineCacheMiss as exc:
            errors.append(f"{where}: offline sin caché ({exc})")
        except FetchError as exc:
            errors.append(f"{where}: {exc}")
        except Exception as exc:  # una fuente rota no debe tumbar el digest
            errors.append(f"{where}: {type(exc).__name__}: {exc}")
    return items, errors
