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


# Tribunal Constitucional (hj.tribunalconstitucional.es) is a separate open-data source
# (no JSON API - server-rendered HTML), hence its own dataset note.
TC_DATASET_NOTE = (
    "Tribunal Constitucional rulings are reached by internal resolution id "
    "(es_get_constitutional_ruling) or by human citation number+year "
    "(es_search_constitutional, e.g. numero=31, anno=2010 for 'STC 31/2010'). Source: "
    "hj.tribunalconstitucional.es (Sistema HJ / Buscador de jurisprudencia constitucional), "
    "server-rendered HTML, no free-text full-content search."
)


# DGT tax rulings (petete.tributos.hacienda.gob.es) - server-rendered HTML fragments
# behind the public search form; no JSON API.
DGT_DATASET_NOTE = (
    "DGT consultas tributarias are reached by official number (es_get_tax_ruling, e.g. "
    "'V0001-25') or by full-text/date search (es_search_tax_rulings). Source: "
    "petete.tributos.hacienda.gob.es (Doctrina Tributaria, ~69,500 consultas vinculantes "
    "+ ~19,700 consultas generales). Tax rulings have no ELI/ECLI; the official "
    "NUM-CONSULTA is the durable identifier."
)


class TaxRulingHit(_Tolerant):
    """One row of a DGT search result."""

    num_consulta: str | None = None
    descripcion_hechos: str | None = None
    cuestion_planteada: str | None = None


class TaxRulingSearchResult(_Tolerant):
    """Result of ``es_search_tax_rulings``."""

    total: int
    total_pages: int
    page: int
    database: str  # "vinculantes" | "generales"
    items: list[TaxRulingHit] = Field(default_factory=list)
    dataset_note: str = DGT_DATASET_NOTE


class TaxRuling(_Tolerant):
    """A full DGT consulta (result of ``es_get_tax_ruling``)."""

    num_consulta: str | None = None
    organo: str | None = None
    fecha_salida: str | None = None
    normativa: str | None = None
    descripcion_hechos: str | None = None
    cuestion_planteada: str | None = None
    contestacion: str | None = None

    # Citation contract (Art. 4 CONSTITUTION). No ELI for tax rulings; NUM-CONSULTA is
    # the durable identifier and the permalink carries it.
    human_readable_citation: str | None = None
    source_url: str | None = None
    dataset_note: str = DGT_DATASET_NOTE


# TEAC doctrine (DYCTEA) - ASP.NET results page that accepts plain GET filters.
TEAC_DATASET_NOTE = (
    "TEAC doctrine (criterios) is reached by RG claim-number segments and/or a "
    "resolution-date range (es_search_teac_doctrine) and opened by criterio id "
    "(es_get_teac_criterio, e.g. '00/07082/2025/00/0/1'). Source: DYCTEA "
    "(serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA, ~6,500 criterios). The "
    "portal accepts free-text-looking parameters but silently ignores them, so this "
    "connector offers no full-text search on TEAC."
)


class TeacDoctrineHit(_Tolerant):
    """One row of a DYCTEA search result."""

    criterio_id: str
    title: str | None = None
    snippet: str | None = None


class TeacDoctrineSearchResult(_Tolerant):
    """Result of ``es_search_teac_doctrine``."""

    total: int
    page: int
    items: list[TeacDoctrineHit] = Field(default_factory=list)
    dataset_note: str = TEAC_DATASET_NOTE


class TeacCriterioResult(_Tolerant):
    """A full DYCTEA criterio (result of ``es_get_teac_criterio``)."""

    criterio_id: str
    rg: str | None = None
    calificacion: str | None = None
    unidad_resolutoria: str | None = None
    fecha_resolucion: str | None = None
    asunto: str | None = None
    criterio: str | None = None
    referencias_normativas: str | None = None
    texto_resolucion: str | None = None

    human_readable_citation: str | None = None
    source_url: str | None = None
    dataset_note: str = TEAC_DATASET_NOTE


# AEPD resolutions - Drupal/Solr view with GET exposed filters; full text is a PDF
# permalink per resolution.
AEPD_DATASET_NOTE = (
    "AEPD resolutions are reached by full-text/date search (es_search_aepd_resolutions) "
    "or by expediente number (es_get_aepd_resolution, e.g. 'PS-00615-2025'). Source: "
    "www.aepd.es/informes-y-resoluciones/resoluciones (~46,800 resolutions). The full "
    "text is the linked PDF (pdf_url); this connector returns the teaser + permalink, "
    "not the PDF body."
)


class AepdResolutionModel(_Tolerant):
    """One AEPD resolution teaser (search hit or es_get_aepd_resolution result)."""

    expediente: str
    pdf_url: str | None = None
    fecha_firma: str | None = None
    snippet: str | None = None

    human_readable_citation: str | None = None
    source_url: str | None = None
    dataset_note: str = AEPD_DATASET_NOTE


class AepdSearchResult(_Tolerant):
    """Result of ``es_search_aepd_resolutions``."""

    total: int
    page: int
    items: list[AepdResolutionModel] = Field(default_factory=list)
    dataset_note: str = AEPD_DATASET_NOTE


class ConstitutionalRuling(_Tolerant):
    """A Tribunal Constitucional resolution (Sentencia / Auto / Declaracion)."""

    id: str
    tipo: str | None = None  # SENTENCIA | AUTO | DECLARACION
    sala: str | None = None  # Pleno | Sala Primera | Sala Segunda
    ecli: str | None = None  # the identifier for TC case law (no ELI - ELI covers legislation)
    encabezamiento: str | None = None
    fallo: str | None = None

    # Citation contract (Art. 4 CONSTITUTION). TC case law has no ELI; ``ecli`` is the
    # verifiable identifier instead.
    human_readable_citation: str | None = None
    source_url: str | None = None
    dataset_note: str = TC_DATASET_NOTE
