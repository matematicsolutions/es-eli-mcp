"""Offline tests for the AEPD HTML parsers - no network calls.

Uses saved fixtures (real pages fetched during discovery, 2026-07-08) and
monkeypatches ``AepdClient._request`` to serve them.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from es_eli_mcp.aepd_client import AepdClient, AepdNotFoundError
from es_eli_mcp.cache import HttpCache
from es_eli_mcp.citations import aepd_human_citation

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_response(html: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=html, request=httpx.Request("GET", "https://example.test"))


@pytest.mark.asyncio
async def test_parses_search_page(tmp_path: Path) -> None:
    html = (FIXTURES / "aepd_search_ps_00598_2025.html").read_text(encoding="utf-8")

    async with AepdClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        page = await client.search(texto="PS-00598-2025")  # pubgate:allow

    assert page.total == 1
    assert len(page.hits) == 1
    hit = page.hits[0]
    assert hit.expediente == "PS-00598-2025"  # pubgate:allow
    assert hit.pdf_url == "https://www.aepd.es/documento/ps-00598-2025.pdf"  # pubgate:allow
    assert hit.fecha_firma == "2026-04-28"
    assert hit.snippet is not None and "EXP202506061" in hit.snippet


@pytest.mark.asyncio
async def test_get_resolution_exact_match(tmp_path: Path) -> None:
    html = (FIXTURES / "aepd_search_ps_00598_2025.html").read_text(encoding="utf-8")

    async with AepdClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        hit = await client.get_resolution("ps-00598-2025")  # pubgate:allow

    assert hit.expediente == "PS-00598-2025"  # pubgate:allow
    assert hit.pdf_url is not None and hit.pdf_url.endswith(".pdf")


@pytest.mark.asyncio
async def test_no_results_page(tmp_path: Path) -> None:
    html = (FIXTURES / "aepd_search_noresults.html").read_text(encoding="utf-8")

    async with AepdClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response(html)

        client._request = fake_request  # type: ignore[method-assign]
        page = await client.search(texto="ZZZZ-99999-2099")
        assert page.total == 0

        with pytest.raises(AepdNotFoundError):
            await client.get_resolution("ZZZZ-99999-2099")


@pytest.mark.asyncio
async def test_get_resolution_pdf_head_fallback(tmp_path: Path) -> None:
    """When search 503s persistently, the deterministic PDF permalink is HEAD-verified."""

    async with AepdClient(cache=HttpCache(cache_dir=tmp_path)) as client:
        async def fake_request(url: str) -> httpx.Response:
            return _fake_response("Service Unavailable", status=503)

        async def fake_head(url: str) -> httpx.Response:
            assert url.endswith("/documento/ps-00598-2025.pdf")  # pubgate:allow
            return httpx.Response(200, request=httpx.Request("HEAD", url))

        client._request = fake_request  # type: ignore[method-assign]
        client._http.head = fake_head  # type: ignore[method-assign]
        hit = await client.get_resolution("PS-00598-2025")  # pubgate:allow

    assert hit.expediente == "PS-00598-2025"  # pubgate:allow
    assert hit.pdf_url == "https://www.aepd.es/documento/ps-00598-2025.pdf"  # pubgate:allow
    assert hit.fecha_firma is None


def test_aepd_human_citation() -> None:
    exp = "PS-00598-2025"  # pubgate:allow
    assert aepd_human_citation(exp, "2026-04-28") == (
        f"Resolución de la AEPD en el procedimiento {exp}, de 28 de abril de 2026"
    )
    assert aepd_human_citation(None, None) is None
