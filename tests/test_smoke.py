"""Smoke tests - require internet, hit the live BOE API.

Run manually:

    pytest tests/test_smoke.py -v
"""

from __future__ import annotations

import pytest

from es_eli_mcp.server import (
    es_browse_gazette,
    es_get_act,
    es_get_aepd_resolution,
    es_get_constitutional_ruling,
    es_get_index,
    es_get_tax_ruling,
    es_get_teac_criterio,
    es_get_text,
    es_search_aepd_resolutions,
    es_search_constitutional,
    es_search_tax_rulings,
    es_search_teac_doctrine,
)

# Ley Organica 3/2018 (LOPDGDD) - Spanish data protection law - stable consolidated act.
LOPDGDD = "BOE-A-2018-16673"

# STC 31/2010, de 28 de junio - landmark ruling on the Catalan Statute of Autonomy.
# Stable historical citation, internal Sistema HJ id 6670 (verified 2026-07-07).
STC_31_2010_ID = "6670"


@pytest.mark.asyncio
async def test_smoke_get_act() -> None:
    act = await es_get_act(LOPDGDD)
    assert act.id == LOPDGDD
    assert act.eli_uri is not None and "boe.es/eli" in act.eli_uri, f"bad eli: {act.eli_uri!r}"
    assert act.human_readable_citation is not None and "3/2018" in act.human_readable_citation
    assert act.source_url is not None and act.source_url.startswith("https://")


@pytest.mark.asyncio
async def test_smoke_get_index() -> None:
    idx = await es_get_index(LOPDGDD)
    assert len(idx.blocks) > 0
    ids = {b.id for b in idx.blocks}
    assert "a1" in ids, f"expected block 'a1', got a sample of {list(ids)[:5]}"


@pytest.mark.asyncio
async def test_smoke_get_text_block() -> None:
    text = await es_get_text(LOPDGDD, block_id="a1")
    assert text.format == "xml"
    assert text.content is not None and len(text.content) > 0
    assert "bloque" in text.content
    assert text.eli_uri is not None and "boe.es/eli" in text.eli_uri
    assert text.byte_size and text.byte_size > 0


@pytest.mark.asyncio
async def test_smoke_browse_gazette() -> None:
    result = await es_browse_gazette("20181206")
    assert result.total > 0, "expected documents in the 2018-12-06 gazette"
    ids = {i.id for i in result.items}
    assert LOPDGDD in ids, f"expected {LOPDGDD} in the gazette of its publication date"


@pytest.mark.asyncio
async def test_smoke_get_constitutional_ruling() -> None:
    ruling = await es_get_constitutional_ruling(STC_31_2010_ID)
    assert ruling.id == STC_31_2010_ID
    assert ruling.ecli == "ECLI:ES:TC:2010:31"
    citation = ruling.human_readable_citation
    assert citation is not None and "31/2010" in citation
    assert citation.startswith("STC ")
    assert ruling.source_url is not None and ruling.source_url.startswith("https://")
    assert ruling.fallo is not None and len(ruling.fallo) > 0


@pytest.mark.asyncio
async def test_smoke_search_constitutional() -> None:
    ruling = await es_search_constitutional(numero="31", anno="2010")
    assert ruling.id == STC_31_2010_ID
    assert ruling.ecli == "ECLI:ES:TC:2010:31"
    assert ruling.human_readable_citation == "STC 31/2010, de 28 de junio"


# ----- feature-003: DGT / TEAC / AEPD ---------------------------------------

# Consulta Vinculante V0001-25 - first binding tax ruling of 2025 (verified 2026-07-08).
DGT_V0001_25 = "V0001-25"

# TEAC criterio on IRPF deductible life-insurance premiums (verified 2026-07-08).
TEAC_CRITERIO = "00/07082/2025/00/0/1"

# AEPD sanctioning-procedure resolution (verified 2026-07-08).
AEPD_PS = "PS-00615-2025"


@pytest.mark.asyncio
async def test_smoke_search_tax_rulings() -> None:
    result = await es_search_tax_rulings(texto="aerotermia")
    assert result.total > 0
    assert result.items and result.items[0].num_consulta


@pytest.mark.asyncio
async def test_smoke_get_tax_ruling() -> None:
    ruling = await es_get_tax_ruling(DGT_V0001_25)
    assert ruling.num_consulta == DGT_V0001_25
    assert ruling.fecha_salida == "02/01/2025"
    assert ruling.contestacion is not None and len(ruling.contestacion) > 5000
    citation = ruling.human_readable_citation
    assert citation is not None and citation.startswith("Consulta Vinculante V0001-25")
    assert ruling.source_url is not None and "num_consulta=V0001-25" in ruling.source_url


@pytest.mark.asyncio
async def test_smoke_search_teac_doctrine() -> None:
    result = await es_search_teac_doctrine(sede="00", numero="07082", anno="2025")
    assert result.total == 1
    assert result.items[0].criterio_id == TEAC_CRITERIO


@pytest.mark.asyncio
async def test_smoke_get_teac_criterio() -> None:
    criterio = await es_get_teac_criterio(TEAC_CRITERIO)
    assert criterio.rg == "00/07082/2025/00/00"
    assert criterio.fecha_resolucion == "24/06/2026"
    assert criterio.texto_resolucion is not None and len(criterio.texto_resolucion) > 5000
    citation = criterio.human_readable_citation
    assert citation is not None and "RG 00/07082/2025" in citation


@pytest.mark.asyncio
async def test_smoke_search_aepd_resolutions() -> None:
    result = await es_search_aepd_resolutions(texto="videovigilancia")
    assert result.total > 100
    assert result.items and result.items[0].expediente


@pytest.mark.asyncio
async def test_smoke_get_aepd_resolution() -> None:
    hit = await es_get_aepd_resolution(AEPD_PS)
    assert hit.expediente == AEPD_PS
    assert hit.pdf_url == "https://www.aepd.es/documento/ps-00615-2025.pdf"
    # fecha_firma is None when the search endpoint is load-shedding and the client
    # verified the deterministic PDF permalink instead (HEAD fallback).
    assert hit.fecha_firma is None or len(hit.fecha_firma) == 10
    citation = hit.human_readable_citation
    assert citation is not None and "PS-00615-2025" in citation
