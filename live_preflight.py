#!/usr/bin/env python3
"""Live ThingsBoard Cloud preflight for live Cloud verification.

Checks the configured Cloud REST/MQTT endpoints and confirms that three distinct
device tokens are present. It never invents admin credentials, never contacts a
device broker endpoint, and never writes token values to evidence.

Run::

    .venv/bin/python live_preflight.py

Writes ``evidence/live_preflight.json``. Exits non-zero if REST is unreachable
or the three tokens are missing/duplicated.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jalsanket.config import ConfigurationError, RestConfig, load_dotenv


def http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Return status and body for an unauthenticated HTTPS GET."""
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    load_dotenv()
    try:
        rest = RestConfig.from_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        _write({"checked_at": datetime.now(timezone.utc).isoformat(),
                "configuration_error": str(exc)})
        return 2

    token_vars = ("TB_NODE_01_TOKEN", "TB_NODE_02_TOKEN", "TB_NODE_03_TOKEN")
    tokens = {var: bool(os.environ.get(var, "")) for var in token_vars}
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "target": "ThingsBoard Cloud",
        "rest": rest.safe_summary(),
        "mqtt_endpoint": f"{rest.host}:8883",
        "mqtt_transport": "MQTT over TLS, port 8883, QoS 1",
        "tokens_configured": sum(tokens.values()),
        "tokens_distinct": sum(tokens.values()) == 3 and len({
            os.environ.get(var, "") for var in token_vars if os.environ.get(var, "")
        }) == 3,
        "token_variables": tokens,
        "rest_reachable": False,
        "rest_status": None,
    }

    print(f"Checking Cloud REST endpoint {rest.base_url} ...")
    status, _body = http_get(rest.base_url + "/")
    result["rest_status"] = status
    result["rest_reachable"] = status > 0
    print(f"REST status: {status or 'unreachable'}")

    _write(result)

    if not result["rest_reachable"]:
        print("Cloud REST endpoint is unreachable.", file=sys.stderr)
        return 1
    if not result["tokens_distinct"]:
        print("Three distinct tokens are required (see .env.example).", file=sys.stderr)
        return 1

    print("Cloud preflight complete. Evidence: evidence/live_preflight.json")
    return 0


def _write(result: dict) -> None:
    directory = Path("evidence")
    directory.mkdir(exist_ok=True)
    (directory / "live_preflight.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
