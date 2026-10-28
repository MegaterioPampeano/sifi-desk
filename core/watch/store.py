"""Inventario de lo ya visto y `diff()` para que un paper viejo no vuelva a aparecer.

El inventario es un JSON chico y legible (a propósito: el usuario tiene que poder auditarlo):

    {
      "schema": "sifi.watch.inventory/1",
      "created_at": "2026-10-28T19:30:00Z",
      "updated_at": "2026-10-28T19:30:00Z",
      "entries": {
        "doi:10.1127/entomologia/4935": {
          "id": "doi:10.1127/entomologia/4935",
          "keys": ["doi:10.1127/entomologia/4935", "title:rnaibased control of spider mites ..."],
          "first_seen": "...", "last_seen": "...", "seen_count": 1,
          "title": "...", "date": "...", "source": "crossref"
        }
      }
    }

Un ítem se identifica por **cualquiera** de sus claves: DOI, PMID o título normalizado
(`entries` guarda un registro por paper; todas sus claves viven en `keys` y se indexan en
memoria al cargar). Eso cubre los tres casos que duelen en la práctica:

* el mismo paper sale de Crossref y de PubMed (DOI o título coinciden),
* el mismo preprint sale en bioRxiv con y sin versión nueva (mismo DOI),
* la misma noticia aparece con puntuación distinta (título normalizado).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .sources import normalize_title

SCHEMA = "sifi.watch.inventory/1"


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def item_keys(item: Mapping[str, Any]) -> List[str]:
    """Todas las claves de identidad de un ítem (las que existan)."""
    keys: List[str] = []
    doi = (item.get("doi") or "").strip().lower()
    if doi:
        keys.append("doi:" + doi)
    pmid = str(item.get("pmid") or "").strip()
    if pmid:
        keys.append("pmid:" + pmid)
    title = normalize_title(item.get("title") or "")
    if len(title) >= 12:  # títulos muy cortos dan falsos positivos
        keys.append("title:" + title[:160])
    return keys


def _merge_into(target: Dict[str, Any], extra: Mapping[str, Any]) -> None:
    """Fusiona dos ítems que son el mismo paper (distintas query o distinta fuente)."""
    for q in extra.get("matched_by") or []:
        if q not in target.setdefault("matched_by", []):
            target["matched_by"].append(q)
    if not target.get("abstract") and extra.get("abstract"):
        target["abstract"] = extra["abstract"]
    if not target.get("doi") and extra.get("doi"):
        target["doi"] = extra["doi"]
    if not target.get("pmid") and extra.get("pmid"):
        target["pmid"] = extra["pmid"]
    if not target.get("url") and extra.get("url"):
        target["url"] = extra["url"]
    if not target.get("date") and extra.get("date"):
        target["date"] = extra["date"]
    terms = list(target.get("matched_terms") or [])
    for t in extra.get("matched_terms") or []:
        if t not in terms:
            terms.append(t)
    if terms:
        target["matched_terms"] = terms


def dedupe(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Colapsa duplicados dentro de una misma corrida, preservando el orden."""
    out: List[Dict[str, Any]] = []
    index: Dict[str, Dict[str, Any]] = {}
    for item in items:
        keys = item_keys(item)
        hit = next((index[k] for k in keys if k in index), None)
        if hit is not None:
            _merge_into(hit, item)
            for k in keys:
                index.setdefault(k, hit)
            continue
        index.update({k: item for k in keys})
        out.append(item)
    return out


class Inventory:
    """`inventory.json`: ids vistos + diff contra lo nuevo."""

    def __init__(self, path: Optional[str | os.PathLike] = None, data: Optional[Dict[str, Any]] = None):
        self.path = Path(path) if path else None
        if data is not None:
            self.data: Dict[str, Any] = dict(data)
        else:
            self.data = {"schema": SCHEMA, "created_at": utcnow(), "updated_at": utcnow(),
                         "entries": {}}
        self.data.setdefault("schema", SCHEMA)
        self.data.setdefault("entries", {})
        self._index: Dict[str, str] = {}
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index.clear()
        for canonical, entry in self.entries.items():
            for key in (entry or {}).get("keys") or []:
                self._index.setdefault(key, canonical)
            self._index.setdefault(canonical, canonical)

    # -- persistencia ------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | os.PathLike) -> "Inventory":
        path = Path(path)
        if not path.is_file():
            return cls(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), dict):
            raise ValueError(f"inventario inválido: {path}")
        if raw.get("schema") not in (None, SCHEMA):
            raise ValueError(f"inventario de otro schema: {raw.get('schema')}")
        return cls(path, raw)

    def save(self, path: Optional[str | os.PathLike] = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("inventario sin ruta: pasá --inventory")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = utcnow()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(target)
        self.path = target
        return target

    # -- consultas --------------------------------------------------------- #
    @property
    def entries(self) -> Dict[str, Any]:
        return self.data["entries"]

    def has(self, key: str) -> bool:
        return key in self._index

    def known(self, item: Mapping[str, Any]) -> bool:
        return any(self.has(k) for k in item_keys(item))

    def __len__(self) -> int:
        """Cantidad de papers vistos (no de claves)."""
        return len(self.entries)

    @property
    def n_keys(self) -> int:
        return len(self._index)

    # -- mutaciones -------------------------------------------------------- #
    def mark(self, items: Iterable[Mapping[str, Any]]) -> int:
        """Anota los ítems como vistos. Idempotente: si ya estaba, suma aliases y `seen_count`."""
        now = utcnow()
        added = 0
        for item in items:
            keys = item_keys(item)
            if not keys:
                continue
            canonical = next((self._index[k] for k in keys if k in self._index), None)
            if canonical is not None:
                entry = self.entries[canonical]
                entry["last_seen"] = now
                entry["seen_count"] = int(entry.get("seen_count", 1)) + 1
                entry["keys"] = sorted(set(entry.get("keys") or []) | set(keys))
                for k in keys:
                    self._index.setdefault(k, canonical)
                continue
            canonical = keys[0]
            self.entries[canonical] = {
                "id": canonical,
                "keys": keys,
                "first_seen": now,
                "last_seen": now,
                "seen_count": 1,
                "title": item.get("title", ""),
                "date": item.get("date", ""),
                "source": item.get("source", ""),
                "doi": item.get("doi", ""),
                "pmid": str(item.get("pmid") or ""),
            }
            for k in keys:
                self._index[k] = canonical
            added += 1
        return added

    def diff(self, items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """Sólo lo nuevo: no está en el inventario ni repetido dentro del mismo lote.

        No modifica el inventario; el llamador decide cuándo hacer `mark()` (así una
        corrida con `--dry-run` no ensucia el estado).
        """
        out: List[Dict[str, Any]] = []
        batch: Dict[str, Dict[str, Any]] = {}
        for item in dedupe([dict(i) for i in items]):
            keys = item_keys(item)
            if any(self.has(k) for k in keys):
                continue
            hit = next((batch[k] for k in keys if k in batch), None)
            if hit is not None:
                _merge_into(hit, item)
                for k in keys:
                    batch.setdefault(k, hit)
                continue
            batch.update({k: item for k in keys})
            out.append(item)
        return out

    def unseen_count(self, items: Iterable[Mapping[str, Any]]) -> int:
        return len(self.diff(items))
