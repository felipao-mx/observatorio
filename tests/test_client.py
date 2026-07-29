"""Network-level tests, replayed from VCR cassettes."""

from __future__ import annotations

import pytest

from cdmx_status import SYSTEMS, StatusClient


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_snapshot_covers_every_system():
    async with StatusClient() as client:
        snap = await client.snapshot()

    assert {row["sistema_id"] for row in snap["lineas"]} == set(SYSTEMS)
    assert snap["hash"]
    assert snap["fetched_at"]


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_metro_includes_paginated_letter_lines():
    """Regression guard for the whole reason this library exists.

    Metro has 12 rows over two pages. An unpaginated read returns 10 and drops
    Líneas A and B with no visible error.
    """
    async with StatusClient() as client:
        rows = await client.fetch("stc")

    lines = {row["linea"] for row in rows}
    assert len(rows) == 12
    assert {"A", "B"} <= lines, f"paginated lines missing: {sorted(lines)}"


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_ste_pagination_is_followed():
    """STE has 11 rows, so it also spills onto a second page."""
    async with StatusClient() as client:
        rows = await client.fetch("ste")
    assert len(rows) == 11


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_single_page_systems_need_no_pagination():
    async with StatusClient() as client:
        assert len(await client.fetch("mb")) == 7
        assert len(await client.fetch("cb")) == 3


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_incidencias_are_the_non_normal_subset():
    async with StatusClient() as client:
        snap = await client.snapshot()

    assert all(not row["normal"] for row in snap["incidencias"])
    assert all(row in snap["lineas"] for row in snap["incidencias"])


@pytest.mark.asyncio
async def test_unknown_system_rejected():
    async with StatusClient() as client:
        with pytest.raises(ValueError, match="unknown system"):
            await client.fetch("nope")


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_fila_disambiguates_the_unnumbered_ste_rows():
    """STE ends with two rows carrying only the plain system logo.

    The published page is equally ambiguous -- a reader cannot tell them apart
    either -- so `linea` alone is not a unique key. `fila`, the server's own
    row index, is the only stable handle, and it must stay correct across the
    pagination boundary (the last row comes from page 2).
    """
    async with StatusClient() as client:
        rows = await client.fetch("ste")

    filas = [row["fila"] for row in rows]
    assert filas == list(range(len(rows))), "fila must be dense and ordered"

    unnumbered = [row for row in rows if row["icono"] == "ste.png"]
    assert len(unnumbered) == 2
    assert unnumbered[0]["fila"] != unnumbered[1]["fila"]
