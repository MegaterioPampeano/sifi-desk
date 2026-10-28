"""`APIRouter` de FastAPI con la biblioteca (edición developer).

No se monta solo: `core/service/app.py` tiene que incluirlo. Las líneas exactas están en
`core/library/NEEDS.md`.

    router = build_router()          # o `api.router`
    app.include_router(api.router)

En `stable` **todos** los endpoints contestan `403` con un detalle legible
("función de la edición developer"), no un traceback.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import edition, fetch, search as search_mod, store

router = APIRouter(prefix="/library", tags=["library"])


# --------------------------------------------------------------------------- #
# dependencias
# --------------------------------------------------------------------------- #
def _guard() -> None:
    if not edition.is_dev():
        raise HTTPException(status_code=403, detail=edition.MESSAGE)


def get_library() -> store.Library:
    """Una conexión por request (SQLite es barato de abrir)."""
    return store.Library(data_dir=os.environ.get("SIFI_LIBRARY_DIR", store.DEFAULT_DATA_DIR))


# --------------------------------------------------------------------------- #
# modelos
# --------------------------------------------------------------------------- #
class AddRequest(BaseModel):
    doi: Optional[str] = None
    pmid: Optional[str] = None
    url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    force: bool = False


class AnnotationIn(BaseModel):
    kind: str = "nota"
    text: str
    author: str = ""


class TagChange(BaseModel):
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


def _paper_or_404(lib: store.Library, ref: str) -> Dict[str, Any]:
    paper = lib.get(ref)
    if not paper:
        raise HTTPException(status_code=404, detail=f"no existe el paper {ref}")
    return paper


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
@router.get("/search", dependencies=[Depends(_guard)])
def search(q: str = "", tag: Optional[List[str]] = Query(default=None),
           year: Optional[int] = None, status: Optional[str] = None,
           limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    lib = get_library()
    try:
        return search_mod.search(lib, q, tags=tag, year=year, status=status,
                                 limit=max(1, min(limit, 200)), offset=max(0, offset))
    finally:
        lib.close()


@router.get("/papers", dependencies=[Depends(_guard)])
def list_papers(tag: Optional[str] = None, status: Optional[str] = None,
                limit: int = 50) -> Dict[str, Any]:
    lib = get_library()
    try:
        papers = lib.list_papers(status=status, tag=tag, limit=max(1, min(limit, 500)))
        return {"count": len(papers), "papers": papers}
    finally:
        lib.close()


@router.post("/papers", dependencies=[Depends(_guard)], status_code=201)
def add_paper(req: AddRequest) -> Dict[str, Any]:
    if not (req.doi or req.pmid or req.url):
        raise HTTPException(status_code=422, detail="indicá doi, pmid o url")
    lib = get_library()
    try:
        result = fetch.ingest(lib, doi=req.doi, pmid=req.pmid, url=req.url,
                              tags=req.tags, http=fetch.Http(), force=req.force)
        return {"id": result["id"], "created": result["created"],
                "status": result["status"], "motivo": result["motivo"],
                "pdf": result.get("pdf")}
    finally:
        lib.close()


@router.get("/papers/{ref}", dependencies=[Depends(_guard)])
def get_paper(ref: str) -> Dict[str, Any]:
    lib = get_library()
    try:
        paper = _paper_or_404(lib, ref)
        return {**paper, "annotations": lib.annotations(paper["id"])}
    finally:
        lib.close()


@router.get("/papers/{ref}/text", dependencies=[Depends(_guard)])
def get_text(ref: str, limit: int = 20000) -> Dict[str, Any]:
    lib = get_library()
    try:
        paper = _paper_or_404(lib, ref)
        body = paper.get("body") or ""
        return {"id": paper["id"], "text_chars": paper.get("text_chars", 0),
                "truncated": len(body) > limit, "text": body[:max(1, limit)]}
    finally:
        lib.close()


@router.get("/papers/{ref}/pdf", dependencies=[Depends(_guard)])
def get_pdf(ref: str):
    lib = get_library()
    try:
        paper = _paper_or_404(lib, ref)
        if not paper.get("pdf_path"):
            raise HTTPException(status_code=404, detail=f"el paper {paper['id']} no tiene PDF")
        path = (lib.data_dir / paper["pdf_path"]).resolve()
        if not path.is_file():
            raise HTTPException(status_code=410, detail="el PDF ya no está en disco")
        return FileResponse(str(path), media_type="application/pdf",
                            filename=path.name)
    finally:
        lib.close()


@router.get("/papers/{ref}/annotations", dependencies=[Depends(_guard)])
def list_annotations(ref: str, kind: Optional[str] = None) -> Dict[str, Any]:
    lib = get_library()
    try:
        paper = _paper_or_404(lib, ref)
        return {"paper_id": paper["id"], "annotations": lib.annotations(paper["id"], kind=kind)}
    finally:
        lib.close()


@router.post("/papers/{ref}/annotations", dependencies=[Depends(_guard)], status_code=201)
def add_annotation(ref: str, body: AnnotationIn) -> Dict[str, Any]:
    lib = get_library()
    try:
        paper = _paper_or_404(lib, ref)
        try:
            return lib.add_annotation(paper["id"], body.kind, body.text, author=body.author)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        lib.close()


@router.delete("/annotations/{annotation_id}", dependencies=[Depends(_guard)])
def delete_annotation(annotation_id: int) -> Dict[str, Any]:
    lib = get_library()
    try:
        if not lib.delete_annotation(annotation_id):
            raise HTTPException(status_code=404, detail="anotación inexistente")
        return {"deleted": annotation_id}
    finally:
        lib.close()


@router.post("/papers/{ref}/tags", dependencies=[Depends(_guard)])
def change_tags(ref: str, body: TagChange) -> Dict[str, Any]:
    lib = get_library()
    try:
        paper = _paper_or_404(lib, ref)
        for tag in body.add:
            lib.add_tag(paper["id"], tag)
        for tag in body.remove:
            lib.remove_tag(paper["id"], tag)
        return {"paper_id": paper["id"], "tags": lib.tags(paper["id"])}
    finally:
        lib.close()


@router.get("/tags", dependencies=[Depends(_guard)])
def tags() -> Dict[str, Any]:
    lib = get_library()
    try:
        return {"tags": lib.tag_counts()}
    finally:
        lib.close()


@router.get("/stats", dependencies=[Depends(_guard)])
def stats() -> Dict[str, Any]:
    lib = get_library()
    try:
        return lib.stats()
    finally:
        lib.close()


def build_router() -> APIRouter:
    return router
