#!/usr/bin/env python3
"""Live MQTT/TLS token-authentication probe for the three Cloud devices.

Prints only booleans and counts; device tokens are never echoed.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jalsanket.config import load_dotenv

TOKEN_VARS = ("TB_NODE_01_TOKEN", "TB_NODE_02_TOKEN", "TB_NODE_03_TOKEN")
DEVICE_NAMES = ("JalSanket-Node-01", "JalSanket-Node-02", "JalSanket-Node-03")
LATLON = ((28.1100, 85.2900), (28.0920, 85.3610), (28.1710, 85.3870))


def probe(index: int, host: str, token: str) -> dict:
    state = {"connected": False, "reason": None, "published": False, "rpc_subscribed": False}
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"jalsanket-live-probe-{index + 1}",
    )
    client.username_pw_set(token, "")
    client.tls_set_context(ssl.create_default_context())

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        code = getattr(reason_code, "value", reason_code)
        state["connected"] = code == 0
        state["reason"] = code
        if state["connected"]:
            result, _ = client.subscribe("v1/devices/me/rpc/request/+", qos=1)
            state["rpc_subscribed"] = result == mqtt.MQTT_ERR_SUCCESS

    def on_publish(_client, _userdata, _mid, _reason_code, _properties):
        state["published"] = True

    client.on_connect = on_connect
    client.on_publish = on_publish
    client.connect_async(host, 8883, keepalive=60)
    client.loop_start()
    deadline = time.time() + 20
    while not state["connected"] and time.time() < deadline:
        time.sleep(0.1)
    if not state["connected"]:
        client.loop_stop()
        return state

    now_ms = int(time.time() * 1000)
    lat, lon = LATLON[index]
    telemetry = {
        "ts": now_ms,
        "values": {
            "ph": 7.1 + index * 0.05,
            "turbidity_ntu": 4.8 + index,
            "tds_ppm": 180.0 + index * 10,
            "water_temp_c": 20.2,
            "flow_lpm": 12.5 + index,
            "latitude": lat,
            "longitude": lon,
        },
    }
    info = client.publish("v1/devices/me/telemetry", json.dumps(telemetry), qos=1)
    state["publish_queued"] = info.rc == mqtt.MQTT_ERR_SUCCESS
    client.publish(
        "v1/devices/me/attributes",
        json.dumps({"deviceName": DEVICE_NAMES[index],
                    "latitude": lat, "longitude": lon}),
        qos=1,
    )
    deadline = time.time() + 20
    while not state["published"] and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)
    client.disconnect()
    client.loop_stop()
    state["telemetry_ts"] = now_ms
    return state


def main() -> int:
    load_dotenv()
    host = os.environ.get("TB_HOST", "")
    if not host:
        raise SystemExit("TB_HOST is required")
    results = {}
    for index, var in enumerate(TOKEN_VARS):
        token = os.environ.get(var, "")
        if not token:
            raise SystemExit(f"{var} is required")
        results[DEVICE_NAMES[index]] = probe(index, host, token)
        print(f"{DEVICE_NAMES[index]}: connected={results[DEVICE_NAMES[index]]['connected']} "
              f"qos1_puback={results[DEVICE_NAMES[index]]['published']} "
              f"rpc_subscribed={results[DEVICE_NAMES[index]]['rpc_subscribed']}")
    output = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "port": 8883,
        "tls": True,
        "devices": results,
        "all_connected": all(r["connected"] for r in results.values()),
        "all_qos1_confirmed": all(r["published"] for r in results.values()),
    }
    Path("evidence/live_mqtt_probe.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0 if output["all_connected"] and output["all_qos1_confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
