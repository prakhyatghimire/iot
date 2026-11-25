#!/usr/bin/env python3
"""Verify the dashboard-only Water Safety Incident Mode.

Run with::

    .venv/bin/python verify_incident_mode.py

The tests execute the exact markdown/cell/map functions embedded in the generated
ThingsBoard Cloud dashboard against synthetic telemetry snapshots. No ThingsBoard
host, token, password or backend service is needed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jalsanket.alarm_rules import cloud_alarm_rules
from jalsanket.alarms import (
    GROSS_CONTAMINATION_CLEAR,
    GROSS_CONTAMINATION_TRIGGER,
    HIGH_TDS_CLEAR,
    HIGH_TDS_TRIGGER,
    HIGH_TURBIDITY_CLEAR,
    HIGH_TURBIDITY_TRIGGER,
    PH_HIGH_CLEAR,
    PH_HIGH_TRIGGER,
    PH_LOW_CLEAR,
    PH_LOW_TRIGGER,
)
from jalsanket.dashboard import MONITORING_DASHBOARD_ID
from jalsanket.provisioning import TELEMETRY_KEYS

ROOT = Path(__file__).parent
ARTIFACT = ROOT / "thingsboard" / "jalsanket_dashboard.json"

DEVICE_IDS = [
    "737cbce0-e44f-11f1-8c2a-39d8a38c3af6",
    "8090ab30-e44f-11f1-b835-cf86ca25bc9f",
    "81265b80-e44f-11f1-b835-cf86ca25bc9f",
]
PLACES = ["Dhunche", "Syafrubesi", "Rasuwagadhi"]
NODE_NAMES = ["JalSanket Node 01", "JalSanket Node 02", "JalSanket Node 03"]
REQUIRED_WIDGETS = {
    "system_status", "node_status", "active_alerts", "node_map",
    "measurements_header", "ph_gauge", "turbidity_gauge", "tds_gauge",
    "turbidity_series", "ph_series", "tds_series", "temp_flow",
    "nav_to_demo_controls",
}
TS = 1764000000000

results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((bool(passed), name, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def row(index: int, *, safety: str, active: bool, ph: float, turbidity: float,
        tds: float, flow: float) -> dict:
    """One markdown-card row with both raw keys and configured labels."""
    device = f"JalSanket-Node-0{index + 1}"
    return {
        "entityName": device,
        "entityId": {"entityType": "DEVICE", "id": DEVICE_IDS[index]},
        "Location": device,
        "Water status": safety,
        "Connectivity": active,
        "Flow": flow,
        "pH reading": ph,
        "Turbidity reading": turbidity,
        "TDS reading": tds,
        "ts": TS,
    }


def snapshot(statuses: tuple[str, str, str], active: tuple[bool, bool, bool],
             values: tuple[tuple[float, float, float, float], ...]) -> list[dict]:
    return [
        row(i, safety=statuses[i], active=active[i], ph=values[i][0],
            turbidity=values[i][1], tds=values[i][2], flow=values[i][3])
        for i in range(3)
    ]


NORMAL = snapshot(
    ("SAFE", "SAFE", "SAFE"), (True, True, True),
    ((7.17, 6.1, 195.0, 13.8), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
CONTAMINATION = snapshot(
    ("UNSAFE", "SAFE", "SAFE"), (True, True, True),
    ((6.10, 260.4, 535.0, 11.2), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
SUPPLY = snapshot(
    ("SAFE", "UNSAFE", "SAFE"), (True, True, True),
    ((7.17, 6.1, 195.0, 13.8), (7.22, 4.7, 179.8, 0.0),
     (7.14, 5.4, 188.4, 13.8)),
)
MULTIPLE = snapshot(
    ("UNSAFE", "SAFE", "SAFE"), (True, True, True),
    ((6.10, 260.4, 535.0, 0.0), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
OFFLINE = snapshot(
    ("UNSAFE", "SAFE", "SAFE"), (False, True, True),
    ((7.17, 6.1, 195.0, 13.8), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
WARNING = snapshot(
    ("WARNING", "SAFE", "SAFE"), (True, True, True),
    ((7.17, 67.0, 195.0, 13.8), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
RESOLVED = snapshot(
    ("SAFE", "SAFE", "SAFE"), (True, True, True),
    ((7.18, 18.0, 220.0, 13.8), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
# Live Cloud state on 2026-11-25: connectivity was fresh but safetyStatus was
# two days old and the current readings were normal. It must not open an incident.
STALE = snapshot(
    ("SAFE", "UNSAFE", "SAFE"), (True, True, True),
    ((7.17, 6.1, 195.0, 13.8), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)
# Hysteresis band: still inside an active critical alarm's clear threshold.
HYSTERESIS = snapshot(
    ("UNSAFE", "SAFE", "SAFE"), (True, True, True),
    ((7.25, 180.0, 470.0, 12.1), (7.22, 4.7, 179.8, 12.9),
     (7.14, 5.4, 188.4, 13.8)),
)


NODE_SCRIPT = r"""
const chunks = [];
process.stdin.on('data', function (c) { chunks.push(c); });
process.stdin.on('end', function () {
  try {
    const p = JSON.parse(Buffer.concat(chunks).toString());
    const out = {cards: {}, cells: {}, map: {}};
    Object.keys(p.cards).forEach(function (name) {
      out.cards[name] = Function('data', p.cards[name].js)(p.cards[name].data);
    });
    Object.keys(p.cells).forEach(function (name) {
      out.cells[name] = Function('alarm', 'value', p.cells[name].js)(
        p.cells[name].alarm, p.cells[name].value);
    });
    Object.keys(p.map).forEach(function (name) {
      out.map[name] = Function('dsData', 'dsIndex', p.map[name].js)(
        p.map[name].data, p.map[name].index);
    });
    process.stdout.write(JSON.stringify(out));
  } catch (err) {
    process.stderr.write(String(err && err.stack || err));
    process.exitCode = 1;
  }
});
"""


def run_widget_functions(artifact: dict) -> dict:
    widgets = artifact["configuration"]["widgets"]
    system_js = widgets["system_status"]["config"]["settings"]["markdownTextFunction"]
    node_js = widgets["node_status"]["config"]["settings"]["markdownTextFunction"]
    alert_js = widgets["active_alerts"]["config"]["alarmSource"]["dataKeys"][0]["settings"]["cellContentFunction"]
    map_settings = widgets["node_map"]["config"]["settings"]
    alarm = {
        "severity": "CRITICAL",
        "originatorDisplayName": "JalSanket-Node-01",
        "createdTime": TS,
    }
    map_row = {
        "entityName": "JalSanket-Node-01", "active": True,
        "safetyStatus": "UNSAFE", "latitude": 28.11, "longitude": 85.29,
        "ph": 6.10, "turbidity_ntu": 260.4, "tds_ppm": 535.0, "flow_lpm": 11.2,
    }
    map_safe = dict(map_row, safetyStatus="SAFE")
    map_stale = dict(map_row, ph=7.17, turbidity_ntu=6.1, tds_ppm=195.0,
                     flow_lpm=13.8)
    dismissed_js = (
        "const localStorage = {"
        'getItem: function (k) { return k === "__jalsanketIncidentScopeDismissed" ? "Dhunche:CRITICAL" : null; },'
        "setItem: function () {}, removeItem: function () {}"
        "};\n" + system_js
    )
    payload = {
        "cards": {
            "normal": {"js": system_js, "data": NORMAL},
            "contamination": {"js": system_js, "data": CONTAMINATION},
            "contamination_dismissed": {"js": dismissed_js, "data": CONTAMINATION},
            "supply": {"js": system_js, "data": SUPPLY},
            "multiple": {"js": system_js, "data": MULTIPLE},
            "offline": {"js": system_js, "data": OFFLINE},
            "warning": {"js": system_js, "data": WARNING},
            "resolved": {"js": system_js, "data": RESOLVED},
            "stale": {"js": system_js, "data": STALE},
            "hysteresis": {"js": system_js, "data": HYSTERESIS},
            "nodes_contamination": {"js": node_js, "data": CONTAMINATION},
            "nodes_supply": {"js": node_js, "data": SUPPLY},
            "nodes_normal": {"js": node_js, "data": NORMAL},
            "nodes_stale": {"js": node_js, "data": STALE},
        },
        "cells": {
            "alert": {
                "js": alert_js, "alarm": alarm,
                "value": "Gross Contamination Critical",
            }
        },
        "map": {
            "affected_label": {
                "js": map_settings["labelFunction"], "data": [map_row], "index": 0,
            },
            "safe_label": {
                "js": map_settings["labelFunction"], "data": [map_safe], "index": 0,
            },
            "affected_tooltip": {
                "js": map_settings["tooltipFunction"], "data": [map_row], "index": 0,
            },
            "safe_tooltip": {
                "js": map_settings["tooltipFunction"], "data": [map_safe], "index": 0,
            },
            "stale_label": {
                "js": map_settings["labelFunction"], "data": [map_stale], "index": 0,
            },
        },
    }
    proc = subprocess.run(
        ["node", "-e", NODE_SCRIPT], input=json.dumps(payload),
        text=True, capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node widget evaluation failed: {proc.stderr[:2000]}")
    return json.loads(proc.stdout)


def main() -> int:
    artifact = json.loads(ARTIFACT.read_text())
    config = artifact["configuration"]
    widgets = config["widgets"]
    layout = config["states"]["default"]["layouts"]["main"]["widgets"]

    section("1. Generated dashboard keeps the required architecture")
    check("all 13 required widgets remain present",
          REQUIRED_WIDGETS.issubset(widgets) and len(widgets) == 13,
          str(len(widgets)))
    check("layout still matches the generated widgets", set(layout) == set(widgets))
    check("status card reads telemetry needed for incident measurements",
          {"deviceName", "safetyStatus", "active", "flow_lpm", "ph",
           "turbidity_ntu", "tds_ppm"} <= {
              k["name"] for ds in widgets["system_status"]["config"]["datasources"]
              for k in ds["dataKeys"]
          })
    check("old area-status widget title is replaced by the incident panel",
          widgets["system_status"]["config"]["title"] == "Water Safety Incident")
    check("incident panel renders inside the widget, not as a fixed overlay",
          "js-system-incident" in widgets["system_status"]["config"]["settings"]["markdownCss"]
          and "position:fixed" not in widgets["system_status"]["config"]["settings"]["markdownCss"])
    check("fleet alias is unchanged and still resolves the same three devices",
          len(config["entityAliases"]) == 1
          and config["entityAliases"]["fleet"]["alias"] == "JalSanket Fleet"
          and set(config["entityAliases"]["fleet"]["filter"]["entityList"]) == set(DEVICE_IDS))
    check("no fake customer, asset or user entities were added",
          not {"customers", "assets", "users"} & set(config))
    check("no new device identities were introduced",
          {ds.get("entityId") for w in widgets.values()
           for ds in w["config"].get("datasources", [])
           if ds.get("entityId")} <= set(DEVICE_IDS))
    check("navigation still targets the existing demo dashboard",
          widgets["nav_to_demo_controls"]["config"]["actions"]["click"][0]["targetDashboardId"]
          == "19cf5c70-e69d-11f1-855e-4d781d6baffc")

    section("2. No backend or alarm-engine changes")
    check("existing alarm thresholds are unchanged",
          (HIGH_TURBIDITY_TRIGGER, GROSS_CONTAMINATION_TRIGGER,
           PH_LOW_TRIGGER, PH_HIGH_TRIGGER, HIGH_TDS_TRIGGER)
          == (50.0, 200.0, 6.5, 8.5, 500.0))
    check("existing hysteresis clear bands are unchanged",
          (HIGH_TURBIDITY_CLEAR, GROSS_CONTAMINATION_CLEAR,
           PH_LOW_CLEAR, PH_HIGH_CLEAR, HIGH_TDS_CLEAR)
          == (40.0, 150.0, 6.7, 8.3, 450.0))
    check("existing telemetry schema is unchanged",
          TELEMETRY_KEYS == ("ph", "turbidity_ntu", "tds_ppm", "water_temp_c",
                             "flow_lpm", "latitude", "longitude"))
    check("no rule/provisioning definition was embedded in the dashboard",
          all(token not in json.dumps(widgets)
              for token in ("createAlarm", "clearAlarm", "saveAttributes", "saveTimeseries")))
    dashboard_source = (ROOT / "jalsanket" / "dashboard.py").read_text()
    check("dashboard code only renders; it does not issue Cloud writes",
          not any(token in dashboard_source
                  for token in ("fetch(", "requests.post", "createAlarm", "clearAlarm")))
    check("six existing alarm-rule definitions are still generated",
          len(cloud_alarm_rules("profile-1")) == 6)

    out = run_widget_functions(artifact)

    section("3. Normal mode and progressive disclosure")
    normal = out["cards"]["normal"]
    check("normal mode has no incident overlay",
          "js-incident" not in normal and "WATER SAFETY INCIDENT" not in normal)
    check("normal mode states there is no active incident",
          "No active water-safety incident" in normal)
    check("normal mode still shows the all-clear and all locations",
          "No active water-safety incident" in normal
          and all(name in out["cards"]["nodes_normal"]
                  for name in PLACES + NODE_NAMES))
    check("a warning alone does not open Incident Mode",
          "js-incident" not in out["cards"]["warning"]
          and "Attention required" in out["cards"]["warning"])
    check("system status widget hides incident scope in normal mode",
          "Incident scope:" not in out["cards"]["normal"]
          and "js-incident-scope" not in out["cards"]["normal"])
    check("node status widget no longer repeats the incident scope",
          all("Incident scope:" not in out["cards"][key] for key in (
              "nodes_normal", "nodes_contamination", "nodes_supply", "nodes_stale")))
    stale = out["cards"]["stale"]
    check("stale unsafe status is not promoted to an incident",
          "js-incident" not in stale
          and "No active water-safety incident" in stale
          and "1 unconfirmed" in stale)
    check("stale status is labelled unconfirmed on the node card",
          "UNCONFIRMED" in out["cards"]["nodes_stale"]
          and "Not confirmed by current readings" in out["cards"]["nodes_stale"])

    section("4. Critical contamination incident")
    contamination = out["cards"]["contamination"]
    check("one grouped contamination panel is shown",
          contamination.count('class="js-critical-alert js-incident"') == 1)
    hysteresis = out["cards"]["hysteresis"]
    check("a reading inside the active critical clear band is still an incident",
          'class="js-critical-alert js-incident"' in hysteresis
          and "severe turbidity" in hysteresis
          and "ALARM BAND" in hysteresis
          and "Turbidity 180.0 NTU · ALARM BAND" in hysteresis
          and "TDS 470.0 ppm · ALARM BAND" in hysteresis)
    check("header names severity, source, node and telemetry scope",
          all(token in contamination for token in (
              "CRITICAL WATER SAFETY INCIDENT", "Dhunche Water Source",
              "JalSanket Node 01", "CURRENT DASHBOARD TELEMETRY")))
    check("summary is factual and does not claim AI or a physical cause",
          "Multiple water-quality thresholds are currently exceeded." in contamination
          and "AI" not in contamination and "caused by" not in contamination.lower())
    check("relevant measurements and units are shown",
          all(token in contamination for token in (
              "260.4 NTU", "535.0 ppm", "6.10", "11.2 L/min",
              "CRITICAL", "NTU", "ppm")))
    check("affected node is prioritised and other sources stay visible",
          all(token in contamination for token in (
              "Syafrubesi — SAFE", "Rasuwagadhi — SAFE")))
    check("scripted scenario note is clearly labelled as simulated",
          "Simulated scenario note" in contamination
          and "does not identify a physical cause" in contamination)
    check("system status widget says the incident is isolated to one source",
          "Incident scope: isolated to Dhunche" in contamination)
    check("incident scope has a close button inside the status widget",
          'class="js-system-scope crit js-incident-scope"' in contamination
          and 'class="js-scope-close"' in contamination
          and 'aria-label="Close incident scope"' in contamination
          and "localStorage.setItem('__jalsanketIncidentScopeDismissed'" in contamination)
    check("closing the incident scope hides it in the status widget",
          "Incident scope:" not in out["cards"]["contamination_dismissed"]
          and "js-incident-scope" not in out["cards"]["contamination_dismissed"]
          and "js-incident" in out["cards"]["contamination_dismissed"])

    section("5. Supply interruption and node inactivity")
    supply = out["cards"]["supply"]
    check("supply interruption uses MAJOR severity",
          "MAJOR WATER SAFETY INCIDENT" in supply
          and "Syafrubesi Water Source" in supply)
    check("zero flow is not confused with lost connectivity",
          "0.0 L/min" in supply
          and "water supply interrupted" in supply
          and "node is connected" in supply
          and "This is not a connection loss" in supply)
    check("node card shows no flow while connected",
          "No flow reported" in out["cards"]["nodes_supply"]
          and "Connected" in out["cards"]["nodes_supply"])
    offline = out["cards"]["offline"]
    check("node inactivity is a critical incident without water-quality claims",
          "NODE INACTIVE WATER SAFETY INCIDENT" in offline
          and "No current readings" in offline
          and "Check connectivity" in offline
          and "contamination" not in offline.lower())

    section("6. Multiple alarms, resolution and alarm evidence")
    multiple = out["cards"]["multiple"]
    check("multiple alarms on one node produce one grouped view",
          multiple.count('class="js-critical-alert js-incident"') == 1
          and all(token in multiple for token in (
              "severe turbidity", "high dissolved solids", "pH outside safe range",
              "water supply interrupted")))
    check("alarm cell shows a real detection timestamp",
          "Detected" in out["cells"]["alert"]
          and "JalSanket Node 01" in out["cells"]["alert"]
          and "Turbidity critically high" in out["cells"]["alert"])
    resolved = out["cards"]["resolved"]
    check("resolved state returns to normal with no stale critical text",
          "js-incident" not in resolved
          and "No active water-safety incident" in resolved
          and "WATER SAFETY INCIDENT" not in resolved)

    section("7. Incident map identification")
    check("affected marker is labelled INCIDENT with source and status",
          out["map"]["affected_label"] == "INCIDENT · Dhunche — CRITICAL")
    check("unaffected marker remains visible without an incident label",
          out["map"]["safe_label"] == "Dhunche — SAFE")
    check("stale marker is shown as unconfirmed, not as an incident",
          out["map"]["stale_label"] == "Dhunche — STALE")
    check("tooltip identifies the affected source and its node",
          "Affected source: Yes" in out["map"]["affected_tooltip"]
          and "JalSanket Node 01" in out["map"]["affected_tooltip"]
          and "Rasuwa Monitoring Area" in out["map"]["affected_tooltip"])
    check("unaffected tooltip is explicitly not affected",
          "Affected source: No" in out["map"]["safe_tooltip"])

    section("8. Documented Cloud limitations are respected")
    check("no buffer or replay count is shown",
          not any(token in json.dumps(out)
                  for token in ("bufferDepth", "buffered rows", "replay count")))
    check("no invented timeline stages are rendered",
          not any(token in json.dumps(out)
                  for token in ("Normal → Warning", "peak value", "invented timestamp")))
    check("dashboard id and title stay unchanged",
          MONITORING_DASHBOARD_ID == "8626a700-e451-11f1-8c2a-39d8a38c3af6"
          and artifact["title"] == "JalSanket Water Safety — Rasuwa Monitoring Area")

    passed = sum(1 for ok, _, _ in results if ok)
    print("\n=== Summary ===")
    print(f"  {passed}/{len(results)} checks passed")
    if passed == len(results):
        print("\nIncident Mode verification: ALL CHECKS PASSED")
        return 0
    print("\nIncident Mode verification: CHECKS FAILED")
    for ok, name, detail in results:
        if not ok:
            print(f"  - {name} {detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
