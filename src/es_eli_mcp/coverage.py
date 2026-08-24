"""Element 9 of the MateMatic MCP canon: this connector declares its own coverage.

Knowledge about what a corpus does NOT hold is useless while it lives only as prose
in the server instructions - the model has to remember it and choose to relay it, and
an agent has no way to ask. Here it is callable.

Every gap below is grounded in this connector's own source and tool surface. The list
is deliberately never empty: no legal corpus is complete, so an empty gap list would
mean "nobody checked", not "there are no gaps".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _CoverageBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CoverageFamily(_CoverageBase):
    """One data family this connector exposes."""

    name: str = Field(description="Data family, e.g. 'Federal legislation'.")
    tool: str = Field(description="Tool or tools that reach this family.")
    source: str = Field(description="Official source the data comes from.")
    captured_at: str | None = Field(
        default=None,
        description="Date this family was last captured (ISO). None when queried live.",
    )
    live: bool = Field(default=True, description="True when queried live instead of from a snapshot.")


class CoverageGap(_CoverageBase):
    """A known, named hole in this connector's coverage - plus the way around it."""

    id: str = Field(description="Stable gap identifier.")
    family: str = Field(description="Which family the gap belongs to.")
    missing: str = Field(description="What is NOT available through this connector.")
    fallback: str = Field(description="Where to go instead.")


class Coverage(_CoverageBase):
    """What this connector covers, how it is sourced, and what it does not cover."""

    status: Literal["ok", "degraded", "failed"] = "ok"
    as_of_note: str = Field(description="States what the dates mean, and what they do not promise.")
    families: list[CoverageFamily] = Field(default_factory=list)
    known_gaps: list[CoverageGap] = Field(
        default_factory=list,
        description="Never empty. An empty list would mean 'not checked', not 'no gaps'.",
    )


SOURCE = 'boe.es, tribunalconstitucional.es, AEAT/TEAC and AEPD'

AS_OF_NOTE = (
    "Data is queried live against the source, so there is no local snapshot date. Any date "
    "on a record states when the source published it - not that this connector verified the "
    "text is still in force today."
)

_FAMILIES: list[dict] = [{'name': 'BOE consolidated legislation', 'tool': 'es_get_act / es_get_text / es_browse_gazette'}, {'name': 'Constitutional Court rulings', 'tool': 'es_get_constitutional_ruling / es_search_constitutional'}, {'name': 'Tax doctrine (DGT, TEAC)', 'tool': 'es_search_tax_rulings / es_search_teac_doctrine'}, {'name': 'AEPD data-protection resolutions', 'tool': 'es_search_aepd_resolutions / es_get_aepd_resolution'}]

_GAPS: list[dict] = [{'id': 'ES-001', 'family': 'BOE consolidated legislation', 'missing': 'No free-text search - the BOE open-data keyword-search endpoint returns a server-side error, so this connector offers none.', 'fallback': 'Use the BOE website search to obtain a BOE id or ELI, then query here.'}, {'id': 'ES-002', 'family': 'BOE consolidated legislation', 'missing': 'Autonomous-community legislation is out of scope; the BOE consolidated corpus is state law.', 'fallback': "Use the relevant comunidad autonoma's official gazette."}, {'id': 'ES-003', 'family': 'BOE consolidated legislation', 'missing': 'Legal force on a given date is not evaluated. Text is returned as the source publishes it; this connector does not decide whether a provision is in force.', 'fallback': 'Check the validity or consolidation dates on the source record itself.'}]


def build_coverage() -> Coverage:
    """Assemble the declared coverage for this connector."""
    return Coverage(
        status="ok",
        as_of_note=AS_OF_NOTE,
        families=[CoverageFamily(source=SOURCE, live=True, **f) for f in _FAMILIES],
        known_gaps=[CoverageGap(**g) for g in _GAPS],
    )
