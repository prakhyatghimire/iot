#!/usr/bin/env python3
"""Live two-way RPC verification against JalSanket-Node-01.

The request is sent through ThingsBoard Cloud REST while the real fleet is
connected over MQTT/TLS. Using REST avoids a second MQTT session with the same
device token (which would take over the fleet's session). The tenant JWT is read
from the clipboard, used in memory only, and the clipboard is cleared at exit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jalsanket.config import load_dotenv  # noqa: E402

DEVICE = "JalSanket-Node-01"
METHODS = (
    ("trigger_contamination", {}),
    ("set_supply_interrupted", {"interrupted": True}),
    ("reset", {}),
)


def rest(method: str, url: str, jwt: str, body: dict | None = None) -> tuple[int, object]:
    headers = {"X-Authorization": f"Bearer {jwt}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:200]}
        return exc.code, parsed


def main() -> int:
    load_dotenv()
    jwt = subprocess.check_output(["pbpaste"]).decode().strip()
    if not jwt or len(jwt) < 100:
        raise SystemExit("Copy the ThingsBoard browser JWT to the clipboard first")
    host = os.environ.get("TB_HOST", "")
    rest_host = os.environ.get("TB_REST_HOST", host)
    if not rest_host:
        raise SystemExit("TB_REST_HOST or TB_HOST is required")
    base_url = f"https://{rest_host}:443"

    try:
        status, devices = rest("GET", base_url + "/api/tenant/devices?pageSize=100&page=0", jwt)
        if status != 200 or not isinstance(devices, dict):
            raise SystemExit(f"device query failed: {status}")
        device_id = next(
            d["id"]["id"] for d in devices.get("data", []) if d.get("name") == DEVICE
        )

        responses: dict[str, dict] = {}
        for method, params in METHODS:
            status, payload = rest(
                "POST",
                base_url + f"/api/rpc/twoway/{device_id}",
                jwt,
                {"method": method, "params": params, "timeout": 10000},
            )
            responses[method] = {
                "http_status": status,
                "response": payload,
                "ok": status == 200 and isinstance(payload, dict) and payload.get("ok") is True,
            }
            print(f"{method}: http={status} ok={responses[method]['ok']}")
    finally:
        subprocess.run(["pbcopy"], input=b"", check=False)

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "device": DEVICE,
        "target": "ThingsBoard Cloud",
        "transport": "REST two-way RPC delivered to device MQTT/TLS session",
        "responses": responses,
        "all_ok": all(r["ok"] for r in responses.values()),
    }
    Path("evidence/live_rpc_probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
