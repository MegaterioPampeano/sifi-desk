"""SQLite de la biblioteca: papers, etiquetas, anotaciones y búsqueda FTS5.

Decisiones:

* una sola base (`library.db`) con WAL, sin servidor;
* `papers` guarda los metadatos y el **texto extraído** del PDF real (`body`);
* `papers_fts` es una tabla FTS5 *external content* sobre `papers(title, abstract, body)`,
  sincronizada con triggers: no hay que acordarse de reindexar a mano;
* `tags` y `annotations` cuelgan de `papers` con `ON DELETE CASCADE`;
* `pdf_path` se guarda **relativo** al directorio de datos, para que la biblioteca se
  pueda mover de máquina sin romper los links.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
DB_FILENAME = "library.db"
ANNOTATION_KINDS = ("idea_test", "mejora_plataforma", "riesgo", "nota")
STATUSES = ("ok", "sin_pdf", "error")

DEFAULT_DATA_DIR = os.environ.get("SIFI_LIBRARY_DIR",
                                  os.path.expanduser("~/.sifidesk/library"))

# Pesos de bm25 por columna (title, abstract, body). Menor = mejor.
BM25_TITLE, BM25_ABSTRACT, BM25_BODY = 8.0, 3.0, 1.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doi         TEXT NOT NULL DEFAULT '',
    pmid        TEXT NOT NULL DEFAULT '',
    pmcid       TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    authors     TEXT NOT NULL DEFAULT '',
    journal     TEXT NOT NULL DEFAULT '',
    year        INTEGER,
    abstract    TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    oa_status   TEXT NOT NULL DEFAULT '',
    license     TEXT NOT NULL DEFAULT '',
    pdf_path    TEXT NOT NULL DEFAULT '',
    pdf_sha256  TEXT NOT NULL DEFAULT '',
    pdf_bytes   INTEGER NOT NULL DEFAULT 0,
    pages       INTEGER NOT NULL DEFAULT 0,
    text_chars  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'sin_pdf',
    motivo      TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS papers_doi_uq ON papers(doi) WHERE doi <> '';
CREATE INDEX IF NOT EXISTS papers_pmid_ix ON papers(pmid);
CREATE INDEX IF NOT EXISTS papers_pmcid_ix ON papers(pmcid);
CREATE INDEX IF NOT EXISTS papers_status_ix ON papers(status);

CREATE TABLE IF NOT EXISTS tags (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (paper_id, tag)
);
CREATE INDEX IF NOT EXISTS tags_tag_ix ON tags(tag);

CREATE TABLE IF NOT EXISTS annotations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id   INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    author     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS annotations_paper_ix ON annotations(paper_id);
CREATE INDEX IF NOT EXISTS annotations_kind_ix ON annotations(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title, abstract, body,
    content='papers',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, title, abstract, body)
    VALUES (new.id, new.title, new.abstract, new.body);
END;

CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, body)
    VALUES ('delete', old.id, old.title, old.abstract, old.body);
END;

CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, body)
    VALUES ('delete', old.id, old.title, old.abstract, old.body);
    INSERT INTO papers_fts(rowid, title, abstract, body)
    VALUES (new.id, new.title, new.abstract, new.body);
END;
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_title(title: str) -> str:
    """Clave de dedupe: minúsculas sin acentos ni puntuación."""
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def clean_doi(doi: Optional[str]) -> str:
    """Normaliza `https://doi.org/10.1/x`, `doi:10.1/x` y `10.1/x` al mismo valor."""
    value = (doi or "").strip()
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.strip().rstrip(".").lower()


def clean_pmid(pmid: Optional[str]) -> str:
    value = re.sub(r"[^0-9]", "", str(pmid or ""))
    return value


def clean_pmcid(pmcid: Optional[str]) -> str:
    value = re.sub(r"[^0-9A-Za-z]", "", str(pmcid or "")).upper()
    if value and not value.startswith("PMC") and value.isdigit():
        value = "PMC" + value
    return value


class Library:
    """Acceso a la base. Es un wrapper fino: SQL explícito y filas como dicts."""

    def __init__(self, data_dir: str | os.PathLike | None = None,
                 path: str | os.PathLike | None = None):
        if path is None:
            self.data_dir = Path(data_dir or DEFAULT_DATA_DIR).expanduser()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.data_dir / DB_FILENAME
        else:
            path = Path(path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.data_dir = path.parent
        self.path = Path(path)
        self.pdf_dir = self.data_dir / "pdfs"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    # ------------------------------------------------------------------ #
    # papers
    # ------------------------------------------------------------------ #
    def add_paper(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Inserta o completa un paper. Devuelve `{id, created, paper}`.

        Dedupe por DOI, PMID, PMCID o título normalizado. Los campos vacíos no pisan
        datos ya guardados: importar primero desde el vigilante y después enriquecer
        desde Crossref no borra nada.
        """
        doi = clean_doi(meta.get("doi"))
        pmid = clean_pmid(meta.get("pmid"))
        pmcid = clean_pmcid(meta.get("pmcid"))
        title = (meta.get("title") or "").strip()
        title_key = normalize_title(title)

        row = None
        if doi:
            row = self.db.execute("SELECT * FROM papers WHERE doi = ?", (doi,)).fetchone()
        if row is None and pmid:
            row = self.db.execute("SELECT * FROM papers WHERE pmid = ?", (pmid,)).fetchone()
        if row is None and pmcid:
            row = self.db.execute("SELECT * FROM papers WHERE pmcid = ?", (pmcid,)).fetchone()
        if row is None and title_key:
            for cand in self.db.execute("SELECT * FROM papers WHERE title <> ''"):
                if normalize_title(cand["title"]) == title_key:
                    row = cand
                    break

        fields = {
            "doi": doi,
            "pmid": pmid,
            "pmcid": pmcid,
            "title": title,
            "authors": (meta.get("authors") or "").strip(),
            "journal": (meta.get("journal") or "").strip(),
            "year": _as_year(meta.get("year")),
            "abstract": (meta.get("abstract") or "").strip(),
            "oa_status": (meta.get("oa_status") or "").strip().lower(),
            "license": (meta.get("license") or "").strip(),
            "source": (meta.get("source") or "").strip(),
        }

        if row is None:
            cols = ", ".join(fields)
            marks = ", ".join("?" for _ in fields)
            values = [fields[k] for k in fields] + [utcnow()]
            cur = self.db.execute(
                f"INSERT INTO papers ({cols}, added_at) VALUES ({marks}, ?)", values)
            self.db.commit()
            paper_id = int(cur.lastrowid)
            return {"id": paper_id, "created": True, "paper": self.get(paper_id)}

        updates = {k: v for k, v in fields.items() if v not in ("", None)}
        # `year` puede ser 0/None: sólo actualizar si hay valor real
        updates.pop("year", None)
        if fields["year"]:
            updates["year"] = fields["year"]
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            self.db.execute(f"UPDATE papers SET {sets} WHERE id = ?",
                            list(updates.values()) + [row["id"]])
            self.db.commit()
        return {"id": int(row["id"]), "created": False, "paper": self.get(int(row["id"]))}

    def get(self, ref: int | str) -> Optional[Dict[str, Any]]:
        """Busca por id numérico, DOI, PMID o PMCID."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            row = self.db.execute("SELECT * FROM papers WHERE id = ?", (int(ref),)).fetchone()
        else:
            text = str(ref).strip()
            doi = clean_doi(text)
            row = self.db.execute("SELECT * FROM papers WHERE doi = ?", (doi,)).fetchone() if doi else None
            if row is None:
                row = self.db.execute("SELECT * FROM papers WHERE pmcid = ?",
                                      (clean_pmcid(text),)).fetchone()
            if row is None:
                row = self.db.execute("SELECT * FROM papers WHERE pmid = ?",
                                      (clean_pmid(text),)).fetchone()
            if row is None:
                slug = normalize_title(text)
                for cand in self.db.execute("SELECT * FROM papers WHERE title <> ''"):
                    if normalize_title(cand["title"]) == slug:
                        row = cand
                        break
        return self._decorate(row) if row else None

    def list_papers(self, status: Optional[str] = None, tag: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
        sql = "SELECT p.* FROM papers p"
        where, params = [], []
        if tag:
            sql += " JOIN tags t ON t.paper_id = p.id"
            where.append("t.tag = ?")
            params.append(tag.strip().lower())
        if status:
            where.append("p.status = ?")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.added_at DESC, p.id DESC LIMIT ?"
        params.append(int(limit))
        return [self._decorate(r) for r in self.db.execute(sql, params)]

    def set_status(self, paper_id: int, status: str, motivo: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"status inválido: {status}")
        self.db.execute("UPDATE papers SET status = ?, motivo = ? WHERE id = ?",
                        (status, motivo or "", int(paper_id)))
        self.db.commit()

    def set_text(self, paper_id: int, body: str, pages: int = 0,
                 text_chars: Optional[int] = None) -> None:
        chars = len(body or "") if text_chars is None else int(text_chars)
        self.db.execute(
            "UPDATE papers SET body = ?, pages = ?, text_chars = ? WHERE id = ?",
            (body or "", int(pages or 0), chars, int(paper_id)))
        self.db.commit()

    def set_pdf(self, paper_id: int, pdf_path: str, sha256: str, pdf_bytes: int,
                pages: int, body: str) -> None:
        self.db.execute(
            """UPDATE papers SET pdf_path = ?, pdf_sha256 = ?, pdf_bytes = ?, pages = ?,
                   body = ?, text_chars = ?, status = 'ok', motivo = ''
               WHERE id = ?""",
            (pdf_path, sha256, int(pdf_bytes), int(pages), body or "", len(body or ""),
             int(paper_id)))
        self.db.commit()

    def clear_pdf(self, paper_id: int, status: str, motivo: str) -> None:
        self.db.execute(
            """UPDATE papers SET pdf_path = '', pdf_sha256 = '', pdf_bytes = 0, pages = 0,
                   body = '', text_chars = 0, status = ?, motivo = ? WHERE id = ?""",
            (status, motivo or "", int(paper_id)))
        self.db.commit()

    def _decorate(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["tags"] = self.tags(int(row["id"]))
        data["n_annotations"] = int(self.db.execute(
            "SELECT COUNT(*) c FROM annotations WHERE paper_id = ?", (row["id"],)).fetchone()["c"])
        return data

    # ------------------------------------------------------------------ #
    # etiquetas
    # ------------------------------------------------------------------ #
    def add_tag(self, paper_id: int, tag: str) -> bool:
        value = (tag or "").strip().lower()
        if not value:
            return False
        before = self.db.total_changes
        self.db.execute("INSERT OR IGNORE INTO tags(paper_id, tag) VALUES (?, ?)",
                        (int(paper_id), value))
        self.db.commit()
        return self.db.total_changes > before

    def remove_tag(self, paper_id: int, tag: str) -> bool:
        cur = self.db.execute("DELETE FROM tags WHERE paper_id = ? AND tag = ?",
                              (int(paper_id), (tag or "").strip().lower()))
        self.db.commit()
        return cur.rowcount > 0

    def tags(self, paper_id: int) -> List[str]:
        return [r["tag"] for r in self.db.execute(
            "SELECT tag FROM tags WHERE paper_id = ? ORDER BY tag", (int(paper_id),))]

    def tag_counts(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            """SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag""")]

    # ------------------------------------------------------------------ #
    # anotaciones
    # ------------------------------------------------------------------ #
    def add_annotation(self, paper_id: int, kind: str, text: str,
                       author: str = "") -> Dict[str, Any] | None:
        kind = (kind or "").strip().lower()
        body = (text or "").strip()
        if kind not in ANNOTATION_KINDS:
            raise ValueError(f"kind inválido: {kind} (usar {', '.join(ANNOTATION_KINDS)})")
        if not body:
            raise ValueError("la anotación está vacía")
        created = utcnow()
        cur = self.db.execute(
            "INSERT INTO annotations(paper_id, kind, text, author, created_at) VALUES (?,?,?,?,?)",
            (int(paper_id), kind, body, (author or "").strip(), created))
        self.db.commit()
        return self.get_annotation(int(cur.lastrowid))

    def get_annotation(self, annotation_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.execute("SELECT * FROM annotations WHERE id = ?",
                              (int(annotation_id),)).fetchone()
        return dict(row) if row else None

    def annotations(self, paper_id: int, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM annotations WHERE paper_id = ?"
        params: List[Any] = [int(paper_id)]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at, id"
        return [dict(r) for r in self.db.execute(sql, params)]

    def delete_annotation(self, annotation_id: int) -> bool:
        cur = self.db.execute("DELETE FROM annotations WHERE id = ?", (int(annotation_id),))
        self.db.commit()
        return cur.rowcount > 0

    def annotations_by_kind(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT kind, COUNT(*) AS n FROM annotations GROUP BY kind ORDER BY n DESC")]

    # ------------------------------------------------------------------ #
    # stats / export
    # ------------------------------------------------------------------ #
    def stats(self) -> Dict[str, Any]:
        one = lambda sql, params=(): self.db.execute(sql, params).fetchone()[0]  # noqa: E731
        by_status = {r["status"]: r["n"] for r in self.db.execute(
            "SELECT status, COUNT(*) n FROM papers GROUP BY status")}
        years = [dict(r) for r in self.db.execute(
            """SELECT year, COUNT(*) n FROM papers WHERE year IS NOT NULL
               GROUP BY year ORDER BY year DESC LIMIT 10""")]
        return {
            "papers": int(one("SELECT COUNT(*) FROM papers")),
            "with_pdf": int(one("SELECT COUNT(*) FROM papers WHERE status = 'ok'")),
            "without_pdf": int(one("SELECT COUNT(*) FROM papers WHERE status <> 'ok'")),
            "by_status": by_status,
            "pdf_bytes": int(one("SELECT COALESCE(SUM(pdf_bytes), 0) FROM papers")),
            "pages": int(one("SELECT COALESCE(SUM(pages), 0) FROM papers")),
            "text_chars": int(one("SELECT COALESCE(SUM(text_chars), 0) FROM papers")),
            "tags": self.tag_counts(),
            "annotations": self.annotations_by_kind(),
            "years": years,
            "db_path": str(self.path),
            "pdf_dir": str(self.pdf_dir),
        }

    def export(self, out_dir: str | os.PathLike, tag: Optional[str] = None) -> Dict[str, Any]:
        """Copia los PDFs y escribe `index.json` + `notas.md` en `out_dir`."""
        import shutil

        out = Path(out_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        (out / "pdfs").mkdir(exist_ok=True)
        rows = self.list_papers(tag=tag, limit=100000)
        index = []
        notes = ["# Biblioteca siFi — export", ""]
        if tag:
            notes.append(f"Etiqueta: `{tag}`")
        notes.append("")
        for paper in rows:
            entry = {k: paper[k] for k in (
                "id", "doi", "pmid", "pmcid", "title", "authors", "journal", "year",
                "abstract", "oa_status", "license", "pdf_sha256", "pdf_bytes", "pages",
                "text_chars", "status", "motivo", "source", "added_at", "tags")}
            if paper["pdf_path"]:
                src = self.data_dir / paper["pdf_path"]
                if src.is_file():
                    dst = out / "pdfs" / src.name
                    shutil.copy2(src, dst)
                    entry["pdf_file"] = f"pdfs/{src.name}"
            entry["annotations"] = self.annotations(paper["id"])
            index.append(entry)

            notes.append(f"## [{paper['id']}] {paper['title']}")
            notes.append("")
            meta = " · ".join(str(x) for x in [paper["authors"], paper["journal"],
                                               paper["year"], paper["doi"]] if x)
            if meta:
                notes.append(meta)
            if paper["tags"]:
                notes.append(f"Etiquetas: {', '.join(paper['tags'])}")
            if paper["status"] != "ok":
                notes.append(f"_Sin PDF_: {paper['motivo']}")
            notes += ["", "### Qué se puede extraer"]
            if entry["annotations"]:
                for ann in entry["annotations"]:
                    notes.append(f"- **{ann['kind']}** ({ann['author'] or 's/a'}, "
                                 f"{ann['created_at'][:10]}): {ann['text']}")
            else:
                notes.append("- _(sin anotaciones)_")
            notes.append("")

        (out / "index.json").write_text(
            json.dumps({"schema": "sifi.library.export/1", "tag": tag, "count": len(index),
                        "papers": index}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (out / "notas.md").write_text("\n".join(notes), encoding="utf-8")
        return {"out": str(out), "count": len(index), "tag": tag}

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _as_year(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    match = re.search(r"(1[5-9]\d{2}|20\d{2}|21\d{2})", str(value))
    return int(match.group(1)) if match else None


def open_library(data_dir: str | os.PathLike | None = None,
                 path: str | os.PathLike | None = None) -> Library:
    return Library(data_dir=data_dir, path=path)
