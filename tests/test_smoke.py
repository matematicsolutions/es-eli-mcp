"""Smoke tests - require internet, hit the live BOE API.

Run manually:

    pytest tests/test_smoke.py -v
"""

from __future__ import annotations

import pytest

from es_eli_mcp.server import es_browse_gazette, es_get_act, es_get_index, es_get_text

# Ley Organica 3/2018 (LOPDGDD) - Spanish data protection law - stable consolidated act.
LOPDGDD = "BOE-A-2018-16673"


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
