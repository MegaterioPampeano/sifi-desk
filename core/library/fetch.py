"""Resolución y descarga del PDF **real** de un paper de acceso abierto.

Orden de resolución (el primero que dé un PDF válido gana):

1. **Europe PMC** — `search` (da `fullTextUrlList` y licencia) y `fullTextXML` del PMCID
   (da el nombre exacto del PDF y la licencia del artículo).
2. **Unpaywall** — `api.unpaywall.org/v2/{doi}`: `oa_status`, licencia y `url_for_pdf`.
3. **PMC OA** — `idconv` (DOI/PMID → PMCID) + `oa.fcgi` y la ruta `/articles/{pmcid}/pdf/`.
4. **Portada del editor** — `https://doi.org/{doi}` y su `<meta name="citation_pdf_url">`.
5. **Patrones del editor** — sólo cuando el XML de PMC dio el nombre del archivo (MDPI) o
   el DOI es de bioRxiv/medRxiv.

Reglas:

* `User-Agent: sifi-desk/0.1 (mailto:sifi-desk@omnivac.science)`, timeout, backoff con
  `Retry-After`, y caché en disco de **las respuestas de resolución** (no de los PDFs).
* Sólo se baja lo que es abierto: licencia CC/CC0/dominio público, o `oa_status`
  gold/hybrid/green sin licencia declarada. `bronze` (gratis pero sin licencia) y `closed`
  quedan `sin_pdf` con el motivo.
* El archivo se guarda **tal cual** lo entregó el servidor. Si no pasa la verificación de
  `extract.verify_pdf`, se descarta: nunca se rellena con texto propio.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin

from . import extract

VERSION = "0.1"
CONTACT = os.environ.get("SIFI_LIBRARY_CONTACT", "sifi-desk@omnivac.science")
USER_AGENT = f"sifi-desk/{VERSION} (mailto:{CONTACT})"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")

CROSSREF_URL = "https://api.crossref.org/works/{doi}"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPMC_XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
IDCONV_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
PMC_PDF_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
MDPI_CDN = "https://mdpi-res.com/d_attachment/{journal}/{base}/article_deploy/{base}.pdf"
UNPAYWALL_EMAIL = os.environ.get("SIFI_UNPAYWALL_EMAIL", CONTACT)

DEFAULT_CACHE_DIR = os.environ.get("SIFI_LIBRARY_CACHE",
                                   os.path.expanduser("~/.cache/sifi-desk/library"))
CACHE_TTL_HOURS = float(os.environ.get("SIFI_LIBRARY_CACHE_TTL", "720"))
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_CANDIDATES = 12

OPEN_LICENSE_RE = re.compile(
    r"(creativecommons\.org/(licenses|publicdomain)/"
    r"(by|by-sa|by-nc|by-nc-sa|by-nd|by-nc-nd|zero|mark)"
    r"|creativecommons\.org/publicdomain/zero"
    r"|\bcc[- _]?by\b|\bcc0\b|public domain|open access)",
    re.I)
OPEN_OA_STATUS = ("gold", "hybrid", "green")


# --------------------------------------------------------------------------- #
# HTTP con caché y backoff
# --------------------------------------------------------------------------- #
class FetchError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


class OfflineCacheMiss(FetchError):
    pass


@dataclass
class Response:
    status: int
    headers: Dict[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        return (self.body or b"").decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.text)


Transport = Callable[[str, Dict[str, str], float], Tuple[int, Dict[str, str], bytes]]


def requests_transport(url: str, headers: Dict[str, str], timeout: float):
    import requests  # import perezoso: los tests no lo necesitan

    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.content


class DiskCache:
    """Una respuesta por archivo, con edad. Sobrevive a reinicios; se puede borrar."""

    def __init__(self, root: str | os.PathLike | None = None, ttl_hours: float = CACHE_TTL_HOURS):
        self.root = Path(root or DEFAULT_CACHE_DIR)
        self.ttl_hours = float(ttl_hours)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str, max_age_hours: Optional[float] = "default") -> Optional[Dict[str, Any]]:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if max_age_hours == "default":
            max_age_hours = self.ttl_hours
        if max_age_hours is not None:
            try:
                age = (time.time() - float(record.get("fetched_at") or 0)) / 3600.0
            except (TypeError, ValueError):
                return None
            if age > float(max_age_hours):
                return None
        return record

    def put(self, key: str, url: str, status: int, headers: Dict[str, str], body: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "fetched_at": time.time(),
            "url": url,
            "status": status,
            "headers": headers,
            "body_b64": base64.b64encode(body).decode("ascii"),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)


class Http:
    """GET con UA identificable, timeout, reintentos con `Retry-After` y caché de resolución."""

    def __init__(self, cache_dir: str | os.PathLike | None = None, offline: bool = False,
                 timeout: float = 30.0, retries: int = 3, backoff: float = 1.5,
                 transport: Optional[Transport] = None, sleep: Callable[[float], None] = time.sleep,
                 max_cache_bytes: int = 2 * 1024 * 1024):
        self.cache = DiskCache(cache_dir)
        self.offline = bool(offline)
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self.backoff = float(backoff)
        self.transport = transport or requests_transport
        self.sleep = sleep
        self.max_cache_bytes = int(max_cache_bytes)
        self.notes: List[str] = []

    def note(self, msg: str) -> None:
        if msg and msg not in self.notes:
            self.notes.append(msg)

    def get(self, url: str, accept: str = "*/*", use_cache: bool = True,
            cache_age: Optional[float] = "default") -> Response:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cached = self.cache.get(key, max_age_hours=None if self.offline else cache_age) \
            if use_cache else None
        if self.offline:
            if cached is None:
                raise OfflineCacheMiss(f"sin caché para {url}", url=url)
            return Response(int(cached["status"]), cached.get("headers") or {},
                            base64.b64decode(cached["body_b64"]), cached.get("url") or url)
        if cached is not None:
            return Response(int(cached["status"]), cached.get("headers") or {},
                            base64.b64decode(cached["body_b64"]), cached.get("url") or url)

        headers = {"User-Agent": USER_AGENT, "Accept": accept,
                   "Accept-Language": "en-US,en;q=0.9"}
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                status, resp_headers, body = self.transport(url, headers, self.timeout)
            except Exception as exc:  # red, DNS, timeout del cliente
                last = exc
                self.note(f"{url}: {type(exc).__name__}: {exc}")
                if attempt + 1 < self.retries:
                    self.sleep(self._wait(attempt, None))
                continue
            if status in RETRY_STATUS and attempt + 1 < self.retries:
                self.note(f"{url}: HTTP {status}, reintento")
                self.sleep(self._wait(attempt, resp_headers.get("retry-after")))
                continue
            if 200 <= status < 300 and use_cache and len(body) <= self.max_cache_bytes:
                try:
                    self.cache.put(key, url, status, resp_headers, body)
                except OSError:
                    pass
            return Response(status, resp_headers, body, url)
        raise FetchError(str(last) if last else "sin respuesta", url=url)

    def _wait(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(60.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return self.backoff * (2 ** attempt)

    def get_json(self, url: str, accept: str = "application/json") -> Any:
        resp = self.get(url, accept=accept)
        if resp.status >= 400:
            raise FetchError(f"HTTP {resp.status}", status=resp.status, url=url)
        try:
            return resp.json()
        except ValueError as exc:
            raise FetchError(f"respuesta no-JSON ({exc})", status=resp.status, url=url)


# --------------------------------------------------------------------------- #
# acceso abierto
# --------------------------------------------------------------------------- #
def license_is_open(value: Optional[str]) -> bool:
    return bool(value) and bool(OPEN_LICENSE_RE.search(str(value)))


def oa_is_open(licenses: Sequence[str], oa_status: Optional[str]) -> bool:
    """Abierto = licencia CC/CC0/PD, o gold/hybrid/green sin licencia restrictiva."""
    clean = [x for x in (licenses or []) if x]
    if any(license_is_open(x) for x in clean):
        return True
    if not clean and (oa_status or "").lower() in OPEN_OA_STATUS:
        return True
    return False


# --------------------------------------------------------------------------- #
# helpers de metadatos
# --------------------------------------------------------------------------- #
_JATS = re.compile(r"<[^>]+>")


def clean_text(text: Optional[str]) -> str:
    value = _JATS.sub(" ", text or "")
    value = (value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#x2010;", "-"))
    return re.sub(r"\s+", " ", value).strip()


def clean_doi(value: Optional[str]) -> str:
    doi = (value or "").strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.strip().rstrip(".")


def year_from(value: Any) -> Optional[int]:
    match = re.search(r"(1[5-9]\d{2}|20\d{2}|21\d{2})", str(value or ""))
    return int(match.group(1)) if match else None


def format_authors(crossref_message: Dict[str, Any]) -> str:
    names: List[str] = []
    for author in crossref_message.get("author") or []:
        family = (author.get("family") or "").strip()
        given = (author.get("given") or "").strip()
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
        elif author.get("name"):
            names.append(str(author["name"]).strip())
    return "; ".join(names)[:600]


def crossref_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    message = payload.get("message") if isinstance(payload, dict) else None
    if not message:
        return {}
    issued = (((message.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
    if not issued:
        for key in ("published-print", "published-online", "created"):
            parts = ((message.get(key) or {}).get("date-parts") or [[None]])[0] or [None]
            if parts[0]:
                issued = parts[0]
                break
    licenses = [lic.get("URL") for lic in (message.get("license") or []) if lic.get("URL")]
    links = [{"content_type": (lk.get("content-type") or ""), "url": lk.get("URL") or ""}
             for lk in (message.get("link") or []) if lk.get("URL")]
    title = (message.get("title") or [""])[0] if message.get("title") else ""
    journal = (message.get("container-title") or [""])[0] if message.get("container-title") else ""
    return {
        "doi": clean_doi(message.get("DOI")),
        "title": clean_text(title),
        "authors": format_authors(message),
        "journal": clean_text(journal),
        "year": year_from(issued),
        "abstract": clean_text(message.get("abstract")),
        "license": licenses[0] if licenses else "",
        "licenses": licenses,
        "links": links,
        "publisher": clean_text(message.get("publisher")),
        "source": "crossref",
    }


def unpaywall_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("error"):
        return {}
    locations = list(payload.get("oa_locations") or [])
    best = payload.get("best_oa_location") or {}
    if best and best not in locations:
        locations.insert(0, best)
    pdfs: List[Dict[str, str]] = []
    for loc in locations:
        url = loc.get("url_for_pdf") or ""
        if not url:
            continue
        pdfs.append({"url": url, "license": loc.get("license") or "",
                     "host": loc.get("host_type") or "", "version": loc.get("version") or ""})
    licenses = [str(loc.get("license")) for loc in locations if loc.get("license")]
    return {
        "oa_status": (payload.get("oa_status") or "").lower(),
        "licenses": licenses,
        "pdfs": pdfs,
        "title": clean_text(payload.get("title")),
        "year": year_from(payload.get("year")),
        "journal": clean_text(payload.get("journal_name")),
        "doi": clean_doi(payload.get("doi")),
        "source": "unpaywall",
    }


def epmc_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    results = ((payload or {}).get("resultList") or {}).get("result") or []
    if not results:
        return {}
    hit = results[0]
    urls = []
    for item in ((hit.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
        url = item.get("url") or ""
        if url:
            urls.append({"url": url,
                         "style": (item.get("documentStyle") or "").lower(),
                         "availability": (item.get("availability") or "").lower(),
                         "site": item.get("site") or ""})
    return {
        "pmid": str(hit.get("pmid") or ""),
        "pmcid": str(hit.get("pmcid") or ""),
        "doi": clean_doi(hit.get("doi")),
        "title": clean_text(hit.get("title")),
        "journal": clean_text(((hit.get("journalInfo") or {}).get("journal") or {}).get("title")),
        "year": year_from(hit.get("pubYear")),
        "abstract": clean_text(hit.get("abstractText")),
        "is_oa": str(hit.get("isOpenAccess") or "").upper() == "Y",
        "license": hit.get("license") or "",
        "urls": urls,
        "source": "europepmc",
    }


def _xml_text(root, path: str) -> str:
    found = root.find(path) if root is not None else None
    if found is None or found.text is None:
        return ""
    return re.sub(r"\s+", " ", found.text).strip()


def epmc_xml_meta(xml_text: str) -> Dict[str, Any]:
    """Saca del JATS de Europe PMC el nombre del PDF, la licencia y el journal-id.

    Tolera XML truncado o con entidades raras: lo esencial (hrefs) se saca por regex y
    el resto con ElementTree sólo si el documento parsea.
    """
    import xml.etree.ElementTree as ET

    text = xml_text or ""
    hrefs = re.findall(r'xlink:href="([^"]+)"', text)
    pdfs = [h for h in hrefs if h.lower().endswith(".pdf")]
    license_hrefs = [h for h in hrefs if "creativecommons.org" in h.lower()
                     or "publicdomain" in h.lower()]
    journal_id = ""
    title = ""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None
    if root is not None:
        node = root.find(".//journal-id")
        if node is not None and node.text:
            journal_id = node.text.strip()
        title = _xml_text(root, ".//article-title")
    return {
        "pdf_names": list(dict.fromkeys(pdfs)),
        "license_urls": list(dict.fromkeys(license_hrefs)),
        "journal_id": journal_id,
        "title": title,
        "source": "europepmc-xml",
    }


def pmc_oa_pdfs(xml_text: str) -> List[str]:
    """`oa.fcgi` devuelve `<link format="pdf" href="ftp://...">`."""
    found = re.findall(r'<link[^>]+format="pdf"[^>]+href="([^"]+)"', xml_text or "")
    out = []
    for url in found:
        if url.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
            url = "https://" + url[len("ftp://"):]
        out.append(url)
    return out


def landing_pdf_url(html: str, base_url: str) -> str:
    for pattern in (
        r'<meta[^>]+name="citation_pdf_url"[^>]+content="([^"]+)"',
        r'<meta[^>]+content="([^"]+)"[^>]+name="citation_pdf_url"',
        r'<meta[^>]+property="citation_pdf_url"[^>]+content="([^"]+)"',
    ):
        match = re.search(pattern, html or "", re.I)
        if match:
            return urljoin(base_url, match.group(1).strip())
    return ""


# --------------------------------------------------------------------------- #
# resolución
# --------------------------------------------------------------------------- #
def _candidate(url: str, source: str, license_: str = "", oa_status: str = "") -> Dict[str, str]:
    return {"url": url, "source": source, "license": license_ or "", "oa_status": oa_status or ""}


def _dedupe(items: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    seen, out = set(), []
    for item in items:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        item["url"] = url
        out.append(item)
    return out


def publisher_candidates(doi: str, xml_meta: Dict[str, Any],
                         unpaywall: Dict[str, Any]) -> List[Dict[str, str]]:
    """Patrones de editor que se pueden armar sin adivinar (MDPI, bioRxiv/medRxiv)."""
    out: List[Dict[str, str]] = []
    names = xml_meta.get("pdf_names") or []
    journal = (xml_meta.get("journal_id") or "").lower()
    if names and doi.startswith("10.3390/"):
        for name in names:
            base = re.sub(r"\.pdf$", "", name)
            if not base or "/" in base:
                continue
            # `plants-15-03237` → journal `plants` (el path del CDN no lleva el volumen)
            slug = re.match(r"^([a-z0-9]+)-\d+-\d+$", base.lower())
            jrn = slug.group(1) if slug else re.sub(r"[^a-z0-9]", "", journal.split()[0] if journal else "")
            if jrn:
                out.append(_candidate(MDPI_CDN.format(journal=jrn, base=base), "mdpi-cdn"))
    if doi.startswith("10.1101/"):
        out.append(_candidate(f"https://www.biorxiv.org/content/{doi}v1.full.pdf",
                              "biorxiv"))
    if doi.startswith("10.64898/") or doi.startswith("10.1102/"):
        out.append(_candidate(f"https://www.biorxiv.org/content/{doi}v1.full.pdf",
                              "biorxiv"))
    # nature: el `url_for_pdf` de Unpaywall (`..._reference.pdf`) es el PDF del artículo
    # en prensa; ya viene en la lista de Unpaywall, no hace falta patrón.
    return out


@dataclass
class Resolution:
    meta: Dict[str, Any] = field(default_factory=dict)
    candidates: List[Dict[str, str]] = field(default_factory=list)
    oa_status: str = ""
    licenses: List[str] = field(default_factory=list)
    open_access: bool = False
    motivo: str = ""
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "meta": self.meta, "candidates": self.candidates,
            "oa_status": self.oa_status, "licenses": self.licenses,
            "open_access": self.open_access, "motivo": self.motivo, "notes": self.notes,
        }


def resolve(doi: Optional[str] = None, pmid: Optional[str] = None,
            url: Optional[str] = None, http: Optional[Http] = None) -> Resolution:
    """Junta metadatos y candidatos de PDF. No descarga nada."""
    http = http or Http()
    res = Resolution()
    doi = clean_doi(doi)
    pmid = re.sub(r"[^0-9]", "", str(pmid or ""))

    # -- Crossref (metadatos canónicos) ---------------------------------- #
    if doi:
        try:
            payload = http.get_json(CROSSREF_URL.format(doi=quote(doi, safe="")))
            meta = crossref_meta(payload)
            if meta:
                res.meta.update({k: v for k, v in meta.items() if v not in ("", None, [])})
                res.licenses.extend(meta.get("licenses") or [])
                for link in meta.get("links") or []:
                    if link["content_type"] in ("application/pdf", "unspecified", ""):
                        res.candidates.append(_candidate(link["url"], "crossref"))
        except FetchError as exc:
            res.notes.append(f"crossref: {exc}")

    # -- Unpaywall -------------------------------------------------------- #
    up: Dict[str, Any] = {}
    if doi:
        try:
            up = unpaywall_meta(http.get_json(
                UNPAYWALL_URL.format(doi=quote(doi, safe="")) +
                f"?email={quote(UNPAYWALL_EMAIL)}"))
            res.licenses.extend(up.get("licenses") or [])
            res.oa_status = up.get("oa_status") or res.oa_status
            for item in up.get("pdfs") or []:
                res.candidates.append(_candidate(item["url"], "unpaywall",
                                                 item.get("license") or "",
                                                 res.oa_status))
        except FetchError as exc:
            res.notes.append(f"unpaywall: {exc}")

    # -- PMCID (DOI/PMID → PMC) ------------------------------------------ #
    pmcid = ""
    ids = doi or pmid
    if ids:
        try:
            params = f"?ids={quote(ids, safe='')}&format=json&tool=sifi-desk&email={quote(CONTACT)}"
            conv = http.get_json(IDCONV_URL + params)
            for record in ((conv or {}).get("records") or []):
                if record.get("pmcid"):
                    pmcid = str(record["pmcid"])
                    res.meta.setdefault("pmcid", pmcid)
                if record.get("doi") and not doi:
                    res.meta.setdefault("doi", clean_doi(record["doi"]))
                if record.get("pmid") and not pmid:
                    res.meta.setdefault("pmid", str(record["pmid"]))
        except FetchError as exc:
            res.notes.append(f"idconv: {exc}")
    if not pmcid:
        pmcid = str(res.meta.get("pmcid") or "")

    # -- Europe PMC search (fullTextUrlList) ----------------------------- #
    if doi or pmid:
        query = f"DOI:\"{doi}\"" if doi else f"EXT_ID:{pmid} AND SRC:MED"
        try:
            payload = http.get_json(
                EPMC_SEARCH + "?query=" + quote(query) +
                "&format=json&resultType=core&pageSize=3")
            epmc = epmc_meta(payload)
            if epmc:
                if epmc.get("pmcid") and not pmcid:
                    pmcid = epmc["pmcid"]
                    res.meta.setdefault("pmcid", pmcid)
                for key in ("pmid", "title", "journal", "year", "abstract"):
                    if epmc.get(key) and not res.meta.get(key):
                        res.meta[key] = epmc[key]
                if epmc.get("license"):
                    res.licenses.append(epmc["license"])
                if epmc.get("is_oa") and not res.oa_status:
                    res.oa_status = "gold"
                for item in epmc.get("urls") or []:
                    if item["style"] == "pdf" or item["url"].lower().endswith(".pdf"):
                        res.candidates.append(_candidate(item["url"], "europepmc",
                                                         epmc.get("license") or "",
                                                         res.oa_status))
        except FetchError as exc:
            res.notes.append(f"europepmc: {exc}")

    # -- Europe PMC fullTextXML (nombre exacto del PDF + licencia) ------- #
    xml_meta: Dict[str, Any] = {}
    if pmcid:
        try:
            xml = http.get(EPMC_XML.format(pmcid=pmcid), accept="application/xml").text
            xml_meta = epmc_xml_meta(xml)
            res.licenses.extend(xml_meta.get("license_urls") or [])
        except FetchError as exc:
            res.notes.append(f"epmc-xml: {exc}")
        # PMC OA (puede estar retirado; si contesta, se usa)
        try:
            oa = http.get(PMC_OA_URL + "?id=" + quote(pmcid)).text
            for url in pmc_oa_pdfs(oa):
                res.candidates.append(_candidate(url, "pmc-oa"))
        except FetchError as exc:
            res.notes.append(f"pmc-oa: {exc}")
        res.candidates.append(_candidate(PMC_PDF_URL.format(pmcid=pmcid), "pmc"))

    # -- Portada del editor ---------------------------------------------- #
    if doi and len(res.candidates) < 3:
        try:
            page = http.get("https://doi.org/" + quote(doi, safe="/"),
                            accept="text/html", use_cache=False)
            pdf_url = landing_pdf_url(page.text, page.url) if page.status < 400 else ""
            if pdf_url:
                res.candidates.append(_candidate(pdf_url, "landing"))
        except FetchError as exc:
            res.notes.append(f"landing: {exc}")

    # -- Patrones de editor ---------------------------------------------- #
    res.candidates.extend(publisher_candidates(doi, xml_meta, up))

    # -- metadatos que faltan -------------------------------------------- #
    if xml_meta.get("title") and not res.meta.get("title"):
        res.meta["title"] = xml_meta["title"]
    if not res.meta.get("pmcid") and pmcid:
        res.meta["pmcid"] = pmcid
    res.meta["doi"] = clean_doi(res.meta.get("doi") or doi)
    res.meta["pmid"] = str(res.meta.get("pmid") or pmid or "")
    res.meta["source"] = res.meta.get("source") or ("doi" if doi else ("pmid" if pmid else "url"))

    # -- decisión de acceso abierto -------------------------------------- #
    res.licenses = list(dict.fromkeys([x for x in res.licenses if x]))
    if res.licenses:
        res.meta["license"] = min(res.licenses, key=len)
    if not res.oa_status and res.licenses:
        res.oa_status = "open-license"
    res.open_access = oa_is_open(res.licenses, res.oa_status)

    if url:
        res.candidates.insert(0, _candidate(url, "url"))

    res.candidates = _dedupe(res.candidates)[:MAX_CANDIDATES]
    if not res.open_access and not (url and not res.licenses):
        res.motivo = ("sin versión de acceso abierto"
                      f" (oa_status={res.oa_status or 'desconocido'}"
                      f"{'; licencia=' + res.licenses[0] if res.licenses else ''})")
    elif not res.candidates:
        fallen = ", ".join(sorted({n.split(":")[0].strip() for n in res.notes})) or "sin fuentes"
        res.motivo = (f"acceso abierto ({res.oa_status or 's/d'}"
                      + (f", {res.meta.get('license')}" if res.meta.get("license") else "")
                      + f") pero ninguna fuente dio URL de PDF ({fallen})")
    return res


# --------------------------------------------------------------------------- #
# descarga + guardado
# --------------------------------------------------------------------------- #
def download(http: Http, url: str) -> bytes:
    resp = http.get(url, accept="application/pdf", use_cache=False)
    if resp.status >= 400:
        raise FetchError(f"HTTP {resp.status}", status=resp.status, url=url)
    return resp.body


def _store_pdf(lib, paper_id: int, data: bytes, source: str) -> Dict[str, Any]:
    """Verifica y guarda el archivo **tal cual**. Devuelve el resultado."""
    tmp = lib.pdf_dir / f".tmp-{paper_id}.pdf"
    tmp.write_bytes(data)
    try:
        ok, motivo, info = extract.verify_pdf(tmp)
        if not ok:
            return {"ok": False, "motivo": motivo}
        try:
            text = extract.normalize_text(extract.pdf_text(tmp, layout=True))
        except extract.ExtractError as exc:
            return {"ok": False, "motivo": f"no se pudo extraer texto: {exc}"}
        if not text:
            return {"ok": False, "motivo": "el PDF no tiene texto extraíble (¿escaneado?)"}
        sha = extract.sha256_file(tmp)
        final = lib.pdf_dir / f"{paper_id}-{sha[:12]}.pdf"
        shutil.move(str(tmp), str(final))
        rel = str(final.relative_to(lib.data_dir))
        lib.set_pdf(paper_id, rel, sha, len(data), int(info.get("pages") or 0), text)
        return {"ok": True, "path": str(final), "sha256": sha, "bytes": len(data),
                "pages": int(info.get("pages") or 0), "text_chars": len(text),
                "source": source}
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def ingest(lib, doi: Optional[str] = None, pmid: Optional[str] = None,
           url: Optional[str] = None, tags: Sequence[str] = (),
           http: Optional[Http] = None, source: str = "",
           author: str = "", force: bool = False) -> Dict[str, Any]:
    """Resuelve, baja y guarda un paper. Nunca inventa un PDF.

    Devuelve `{id, created, status, motivo, pdf={...}|None, resolution}`.
    """
    http = http or Http()
    res = resolve(doi=doi, pmid=pmid, url=url, http=http)
    meta = dict(res.meta)
    if not meta.get("title") and url:
        meta["title"] = url.rstrip("/").rsplit("/", 1)[-1]
    meta["oa_status"] = res.oa_status
    meta["license"] = res.meta.get("license") or (
        min(res.licenses, key=len) if res.licenses else "")
    if source:
        meta["source"] = source

    added = lib.add_paper(meta)
    paper_id = int(added["id"])
    for tag in tags or ():
        lib.add_tag(paper_id, tag)

    current = added["paper"]
    if current and current.get("status") == "ok" and current.get("pdf_path") and not force:
        return {"id": paper_id, "created": added["created"], "status": "ok",
                "motivo": "ya estaba", "pdf": None, "resolution": res.as_dict()}

    if not res.open_access and not url:
        # puerta de acceso abierto: sin licencia/estado abierto no se toca la red
        motivo = res.motivo or "sin versión de acceso abierto"
        lib.clear_pdf(paper_id, "sin_pdf", motivo)
        return {"id": paper_id, "created": added["created"], "status": "sin_pdf",
                "motivo": motivo, "pdf": None, "resolution": res.as_dict()}

    attempts: List[str] = []
    for cand in res.candidates:
        try:
            data = download(http, cand["url"])
        except FetchError as exc:
            attempts.append(f"{cand['source']}: {exc}")
            continue
        reason = extract.describe_rejection(data)
        if reason:
            attempts.append(f"{cand['source']}: {reason}")
            continue
        stored = _store_pdf(lib, paper_id, data, cand["source"])
        if stored.get("ok"):
            return {"id": paper_id, "created": added["created"], "status": "ok",
                    "motivo": "", "pdf": stored, "resolution": res.as_dict()}
        attempts.append(f"{cand['source']}: {stored.get('motivo')}")

    motivo = res.motivo or "ninguna fuente entregó un PDF válido"
    if attempts:
        motivo = f"{motivo}; intentos: " + " | ".join(attempts[:4])
    if res.notes:
        motivo += "; resolución: " + " | ".join(res.notes[:3])
    lib.clear_pdf(paper_id, "sin_pdf", motivo)
    return {"id": paper_id, "created": added["created"], "status": "sin_pdf",
            "motivo": motivo, "pdf": None, "resolution": res.as_dict()}


def import_items(lib, items: Sequence[Dict[str, Any]], limit: Optional[int] = None,
                 tags: Sequence[str] = (), tag_from_query: bool = False,
                 http: Optional[Http] = None, force: bool = False) -> Dict[str, Any]:
    """Importa un digest del vigilante (`sifi.watch.digest/1`)."""
    http = http or Http()
    selected = list(items)[:int(limit)] if limit else list(items)
    results = []
    for item in selected:
        doi = clean_doi(item.get("doi") or "")
        pmid = re.sub(r"[^0-9]", "", str(item.get("pmid") or ""))
        item_tags = list(tags or ())
        if tag_from_query and item.get("query_id"):
            item_tags.append(str(item["query_id"]))
        existing = lib.get(doi) if doi else (lib.get(pmid) if pmid else None)
        if existing and existing.get("status") == "ok" and not force:
            results.append({"id": existing["id"], "created": False, "status": "ok",
                            "motivo": "ya estaba", "pdf": None, "title": existing["title"]})
            for tag in item_tags:
                lib.add_tag(existing["id"], tag)
            continue
        out = ingest(lib, doi=doi or None, pmid=pmid or None, tags=item_tags,
                     http=http, source=item.get("source") or "watch", force=force)
        out["title"] = (out.get("resolution", {}).get("meta") or {}).get("title") \
            or item.get("title") or ""
        results.append(out)
    return {
        "total": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "sin_pdf": sum(1 for r in results if r["status"] != "ok"),
        "items": results,
        "notes": http.notes,
    }
