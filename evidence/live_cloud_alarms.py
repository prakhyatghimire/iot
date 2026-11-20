#!/usr/bin/env python3
"""Live ThingsBoard Cloud alarm verification for Node-01.

The tenant JWT is read from the clipboard (copied from the logged-in browser
tab) and is never written to disk. Telemetry is published over real MQTT/TLS.
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jalsanket.config import load_dotenv  # noqa: E402

DEVICE = "JalSanket-Node-01"
BASELINE = {
    "ph": 7.2,
    "turbidity_ntu": 5.0,
    "tds_ppm": 180.0,
    "water_temp_c": 20.2,
    "flow_lpm": 12.0,
    "latitude": 28.1100,
    "longitude": 85.2900,
}


def rest(method: str, url: str, jwt: str, body: dict | None = None) -> tuple[int, dict]:
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
        return exc.code, (json.loads(raw) if raw else {})


def active_types(base_url: str, jwt: str, device_id: str) -> list[str]:
    status, payload = rest(
        "GET",
        base_url + "/api/alarms?searchStatus=ACTIVE&pageSize=100&page=0",
        jwt,
    )
    if status != 200:
        raise RuntimeError(f"alarm query failed: {status}")
    # Cloud REST returns originatorName for active alarms (originatorId is
    # omitted), so match on the exact device name rather than a missing id.
    return [
        a.get("type", "")
        for a in payload.get("data", [])
        if a.get("originatorName") == DEVICE
        or a.get("originatorId", {}).get("id") == device_id
    ]


def clear_all(base_url: str, jwt: str) -> int:
    status, payload = rest(
        "GET", base_url + "/api/alarms?searchStatus=ACTIVE&pageSize=100&page=0", jwt
    )
    if status != 200:
        return 0
    count = 0
    for alarm in payload.get("data", []):
        alarm_id = alarm.get("id", {}).get("id")
        if alarm_id:
            rest("POST", base_url + f"/api/alarm/{alarm_id}/clear", jwt)
            count += 1
    return count


class Publisher:
    def __init__(self, host: str, token: str) -> None:
        self.connected = False
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="jalsanket-live-alarm-probe",
        )
        self.client.username_pw_set(token, "")
        self.client.tls_set_context(ssl.create_default_context())

        def on_connect(_c, _u, _f, rc, _p):
            code = getattr(rc, "value", rc)
            self.connected = code == 0

        self.client.on_connect = on_connect
        self.client.connect_async(host, 8883, 60)
        self.client.loop_start()
        deadline = time.time() + 20
        while not self.connected and time.time() < deadline:
            time.sleep(0.1)
        if not self.connected:
            raise RuntimeError("MQTT authentication failed")

    def publish(self, values: dict) -> None:
        payload = {"ts": int(time.time() * 1000), "values": dict(BASELINE, **values)}
        self.client.publish("v1/devices/me/telemetry", json.dumps(payload), qos=1)

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


def hold(publisher: Publisher, values: dict, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        publisher.publish(values)
        time.sleep(2)


def main() -> int:
    load_dotenv()
    jwt = subprocess.check_output(["pbpaste"]).decode().strip()
    if not jwt or len(jwt) < 20:
        raise SystemExit("Copy the ThingsBoard JWT from the browser tab first")
    host = os.environ.get("TB_HOST", "")
    token = os.environ.get("TB_NODE_01_TOKEN", "")
    rest_host = os.environ.get("TB_REST_HOST", host)
    if not host or not token:
        raise SystemExit("TB_HOST and TB_NODE_01_TOKEN are required")
    base_url = f"https://{rest_host}:443"

    digest = hashlib.sha256(jwt.encode()).hexdigest()[:8]
    print(f"Using browser REST session (fingerprint {digest}, not logged)")

    status, devices = rest("GET", base_url + "/api/tenant/devices?pageSize=100&page=0", jwt)
    if status != 200:
        raise SystemExit(f"device query failed: {status}")
    device_id = next(
        d["id"]["id"] for d in devices.get("data", []) if d.get("name") == DEVICE
    )
    cleared_at_start = clear_all(base_url, jwt)

    publisher = Publisher(host, token)
    results: dict[str, dict] = {}
    try:
        scenarios = (
            ("High Turbidity Warning", {"turbidity_ntu": 60.0}, {"turbidity_ntu": 30.0}, 8, 8),
            ("Gross Contamination Critical", {"turbidity_ntu": 250.0}, {"turbidity_ntu": 100.0}, 8, 8),
            ("pH Out of Range Critical", {"ph": 6.0}, {"ph": 7.2}, 8, 8),
            ("High TDS Critical", {"tds_ppm": 600.0}, {"tds_ppm": 400.0}, 8, 8),
            ("Supply Interruption Major", {"flow_lpm": 0.0}, {"flow_lpm": 12.0}, 36, 8),
        )
        for alarm_type, trigger, clear, trigger_s, clear_s in scenarios:
            hold(publisher, trigger, trigger_s)
            during = active_types(base_url, jwt, device_id)
            hold(publisher, clear, clear_s)
            after = active_types(base_url, jwt, device_id)
            results[alarm_type] = {
                "triggered": alarm_type in during,
                "cleared": alarm_type not in after,
                "active_during": during,
                "active_after_clear": after,
            }
            print(f"{alarm_type}: triggered={results[alarm_type]['triggered']} "
                  f"cleared={results[alarm_type]['cleared']}")

        # Device inactivity is driven by the Device State service attribute.
        status, _ = rest(
            "POST",
            base_url + f"/api/plugins/telemetry/DEVICE/{device_id}/SERVER_SCOPE",
            jwt,
            {"active": False},
        )
        time.sleep(8)
        inactive_during = active_types(base_url, jwt, device_id)
        rest(
            "POST",
            base_url + f"/api/plugins/telemetry/DEVICE/{device_id}/SERVER_SCOPE",
            jwt,
            {"active": True},
        )
        time.sleep(8)
        inactive_after = active_types(base_url, jwt, device_id)
        results["Node Inactive Critical"] = {
            "triggered": "Node Inactive Critical" in inactive_during,
            "cleared": "Node Inactive Critical" not in inactive_after,
            "active_during": inactive_during,
            "active_after_clear": inactive_after,
            "attribute_write_status": status,
        }
        print(f"Node Inactive Critical: triggered={results['Node Inactive Critical']['triggered']} "
              f"cleared={results['Node Inactive Critical']['cleared']}")
    finally:
        publisher.close()
        clear_all(base_url, jwt)
        subprocess.run(["pbcopy"], input=b"", check=False)

    output = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "device": DEVICE,
        "target": "ThingsBoard Cloud",
        "cleared_active_alarms_at_start": cleared_at_start,
        "results": results,
        "all_triggered": all(r["triggered"] for r in results.values()),
        "all_cleared": all(r["cleared"] for r in results.values()),
    }
    Path("evidence/live_cloud_alarms.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    return 0 if output["all_triggered"] and output["all_cleared"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
