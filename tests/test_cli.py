"""CLI tests. These patch the client, so they never touch the network."""

from __future__ import annotations

import json
import runpy
from typing import Any

import pytest

import observatorio.cli as cli


def _snapshot(hash_: str = "abc123", incidents: int = 1) -> dict[str, Any]:
    normal = {
        "sistema": "Metro",
        "linea": "1",
        "estado": "Servicio Regular",
        "estaciones_afectadas": "Ninguna",
        "informacion_adicional": "",
        "normal": True,
    }
    incident = {
        "sistema": "Metrobus",
        "linea": "2",
        "estado": "Avance lento",
        "estaciones_afectadas": "Linea completa",
        "informacion_adicional": "Lluvia",
        "normal": False,
    }
    lineas = [normal, incident] if incidents else [normal]
    return {
        "fetched_at": "2026-08-06T00:00:00+00:00",
        "hash": hash_,
        "lineas": lineas,
        "incidencias": [row for row in lineas if not row["normal"]],
    }


class _FakeClient:
    def __init__(self, snapshots: list[dict[str, Any] | Exception]) -> None:
        self.snapshots = snapshots

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        pass

    async def snapshot(self) -> dict[str, Any]:
        snap = self.snapshots.pop(0)
        if isinstance(snap, Exception):
            raise snap
        return snap


class _StopWatch(Exception):
    pass


def test_render_marks_incidents_and_summarizes_counts():
    rendered = cli.render(_snapshot())
    summary = rendered.splitlines()[-1]

    assert "   Metro" in rendered
    assert "!! Metrobus" in rendered
    assert summary.startswith("2 ")
    assert "1 con incidencia" in summary
    assert "hash abc123" in summary


def test_emit_prints_table(capsys):
    cli._emit(_snapshot(), as_json=False)

    assert "!! Metrobus" in capsys.readouterr().out


@pytest.mark.parametrize("compact", [False, True])
def test_emit_prints_json(capsys, compact):
    snap = _snapshot()

    cli._emit(snap, as_json=True, compact=compact)

    assert json.loads(capsys.readouterr().out) == snap


@pytest.mark.asyncio
async def test_once_uses_status_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "StatusClient", lambda: _FakeClient([_snapshot()]))

    assert await cli._once(as_json=True) == 0
    assert json.loads(capsys.readouterr().out)["hash"] == "abc123"


def test_main_runs_once_by_default(monkeypatch):
    calls = []

    async def once(as_json: bool) -> int:
        calls.append(("once", as_json))
        return 7

    async def watch(interval: int, as_json: bool) -> int:
        calls.append(("watch", interval, as_json))
        return 8

    monkeypatch.setattr(cli, "_once", once)
    monkeypatch.setattr(cli, "_watch", watch)

    assert cli.main([]) == 7
    assert calls == [("once", False)]


def test_main_passes_json_to_once(monkeypatch):
    calls = []

    async def once(as_json: bool) -> int:
        calls.append(as_json)
        return 7

    monkeypatch.setattr(cli, "_once", once)

    assert cli.main(["--json"]) == 7
    assert calls == [True]


def test_main_runs_watch_when_requested(monkeypatch):
    calls = []

    async def watch(interval: int, as_json: bool) -> int:
        calls.append((interval, as_json))
        return 9

    monkeypatch.setattr(cli, "_watch", watch)

    assert cli.main(["--watch", "5", "--json"]) == 9
    assert calls == [(5, True)]


def test_main_turns_keyboard_interrupt_into_exit_130(monkeypatch):
    async def once(as_json: bool) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_once", once)

    assert cli.main([]) == 130


@pytest.mark.asyncio
async def test_watch_emits_only_when_hash_changes(monkeypatch, capsys):
    client = _FakeClient([_snapshot("same"), _snapshot("same"), _snapshot("different")])
    sleeps = []
    monkeypatch.setattr(cli, "StatusClient", lambda: client)

    async def sleep(interval: int) -> None:
        sleeps.append(interval)
        if len(sleeps) == 3:
            raise _StopWatch

    monkeypatch.setattr(cli.asyncio, "sleep", sleep)

    with pytest.raises(_StopWatch):
        await cli._watch(5, as_json=False)

    captured = capsys.readouterr()
    assert captured.out.count("===") == 2
    assert captured.err == ""
    assert sleeps == [5, 5, 5]


@pytest.mark.asyncio
async def test_watch_logs_transient_errors_and_keeps_polling(monkeypatch, capsys):
    client = _FakeClient([RuntimeError("temporary failure"), _snapshot("recovered")])
    sleeps = []
    monkeypatch.setattr(cli, "StatusClient", lambda: client)

    async def sleep(interval: int) -> None:
        sleeps.append(interval)
        if len(sleeps) == 2:
            raise _StopWatch

    monkeypatch.setattr(cli.asyncio, "sleep", sleep)

    with pytest.raises(_StopWatch):
        await cli._watch(1, as_json=False)

    captured = capsys.readouterr()
    assert "temporary failure" in captured.err
    assert captured.err.startswith("!! ")
    assert "=== 2026-08-06T00:00:00+00:00" in captured.out
    assert sleeps == [1, 1]


def test_python_m_entrypoint_uses_cli_main(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda: 37)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("observatorio", run_name="__main__")

    assert exc.value.code == 37
