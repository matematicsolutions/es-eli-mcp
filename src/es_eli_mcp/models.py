"""Pydantic v2 models for the Spanish BOE API + es-eli-mcp.

Tolerant models (``extra="allow"``) over the flattened BOE records.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# BOE open-data keyword search (/legislacion-consolidada) currently returns HTTP 500
# server-side, so this connector is grounding + gazette-browse, not keyword search.
DATASET_NOTE = (
    "BOE consolidated legislation is reached by BOE id / ELI (es_get_act, es_get_text) or "
    "by browsing the daily gazette (es_browse_gazette). The BOE open-data keyword-search "
    "endpoint is unavailable (server-side error), so this connector offers no free-text search."
)


class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Act(_Tolerant):
    """A consolidated BOE law (from /metadatos)."""

    id: str | None = None
    titulo: str | None = None
    rango: str | None = None
    departamento: str | None = None
    numero_oficial: str | None = None
    fecha_publicacion: str | None = None
    fecha_disposicion: str | None = None
    estado_consolidacion: str | None = None

    # Citation contract (Art. 4 CONSTITUTION).
    eli_uri: str | None = None
    human_readable_citation: str | None = None
    source_url: str | None = None
    dataset_note: str = DATASET_NOTE


class IndexBlock(_Tolerant):
    """One block in a law's text index."""

    id: str | None = None
    titulo: str | None = None
    url: str | None = None


class IndexResult(_Tolerant):
    """Result of ``es_get_index``."""

    id: str
    blocks: list[IndexBlock] = Field(default_factory=list)
    dataset_note: str = DATASET_NOTE


class LawText(_Tolerant):
    """Result of ``es_get_text`` (consolidated text, XML)."""

    id: str
    block_id: str | None = None
    eli_uri: str | None = None
    human_readable_citation: str | None = None
    source_url: str | None = None
    format: str = "xml"
    content: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    dataset_note: str = DATASET_NOTE


class GazetteItem(_Tolerant):
    """One document published in a daily BOE gazette."""

    id: str
    titulo: str | None = None


class GazetteResult(_Tolerant):
    """Result of ``es_browse_gazette``."""

    date: str
    total: int
    items: list[GazetteItem] = Field(default_factory=list)
    dataset_note: str = DATASET_NOTE
