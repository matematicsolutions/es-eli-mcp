"""Smoke tests - require internet, hit the live BOE API.

Run manually:

    pytest tests/test_smoke.py -v
"""

from __future__ import annotations

import pytest

from es_eli_mcp.server import (
    es_browse_gazette,
    es_get_act,
    es_get_constitutional_ruling,
    es_get_index,
    es_get_text,
    es_search_constitutional,
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
