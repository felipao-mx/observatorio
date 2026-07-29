"""Shared pytest/VCR configuration.

Network tests are recorded to cassettes under ``tests/cassettes`` and replayed
offline. To re-record one, delete its cassette file and run the suite again.

Set ``VCR_RECORD_MODE=none`` (as CI should) to make any unrecorded request a
hard failure instead of a silent live call.
"""

from __future__ import annotations

import os
from typing import Any

import pytest


def _scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep upstream session tokens out of committed cassettes.

    ``filter_headers`` only applies to requests, so the response's Set-Cookie
    (which carries a JSESSIONID) has to be stripped separately.
    """
    for key in ("Set-Cookie", "set-cookie"):
        response["headers"].pop(key, None)
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    return {
        # Deliberately NOT matching on body. Both the JSF ViewState and the
        # session cookie rotate on every recording, so body matching would
        # invalidate every cassette the moment it is re-recorded. Method +
        # URL is enough to disambiguate: the only POSTs are the pagination
        # calls, one per system, and each carries its own idMedioTransporte.
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
        "filter_headers": ["cookie", "user-agent"],
        "before_record_response": _scrub_response,
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "once"),
    }
