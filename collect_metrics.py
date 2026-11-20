#!/usr/bin/env python3
"""Controlled three-node ThingsBoard Cloud metrics experiment.

This command runs the existing fleet unchanged, injects only the legitimate
scenario controls (contamination / supply interruption / reset) and one
simulated cellular outage, then correlates four independent evidence sources:

  1. SQLite readings (acquisition_ms, stored_at_ms, synced_at_ms, sync flag)
  2. Instrumented QoS 1 PUBACK events captured from the existing transport
  3. ThingsBoard Cloud timeseries REST responses (device + ts)
  4. ThingsBoard Cloud alarm REST records (startTs + createdTime)

Measurement boundaries are explicit in ``metrics_results.json``. The tenant JWT
is read from the clipboard, kept in memory only, and the clipboard is cleared
at exit. No token, password or JWT is ever written to evidence.

Run from the repository root after copying the Cloud JWT to the clipboard::

    .venv/bin/python collect_metrics.py --duration 240
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from jalsanket import AlarmEvaluator, FleetConfig, load_dotenv  # noqa: E402
from jalsanket.fleet import Fleet, FleetNode, FleetRunner  # noqa: E402
from jalsanket.provisioning import TELEMETRY_KEYS  # noqa: E402
from metricslib import (  # noqa: E402
    alarm_delay_stats,
    delivery_metrics,
    group_replay_episodes,
    recovery_summary,
    scan_for_secrets,
    summarize,
    throughput_rows_per_s,
)

EVIDENCE = Path("evidence/metrics")
DEVICE_BY_NODE = {
    "node-01": "JalSanket-Node-01",
    "node-02": "JalSanket-Node-02",
    "node-03": "JalSanket-Node-03",
}
ALARM_TYPES = {
    "High Turbidity Warning",
    "Gross Contamination Critical",
    "pH Out of Range Critical",
    "High TDS Critical",
    "Supply Interruption Major",
    "Node Inactive Critical",
}


def now_ms() -> int:
    return int(time.time() * 1000)


class CloudClient:
    """Minimal authenticated REST client; never logs or stores the JWT."""

    def __init__(self, jwt: str, rest_host: str) -> None:
        self._jwt = jwt
        self.base = f"https://{rest_host}:443"

    def get(self, path: str) -> tuple[int, object]:
        request = urllib.request.Request(
            self.base + path,
            headers={"X-Authorization": f"Bearer {self._jwt}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return exc.code, (json.loads(raw) if raw else {})

    def post(self, path: str, body: dict) -> tuple[int, object]:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "X-Authorization": f"Bearer {self._jwt}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return exc.code, (json.loads(raw) if raw else {})

    def device_ids(self) -> dict[str, str]:
        status, payload = self.get("/api/tenant/devices?pageSize=100&page=0")
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"Cloud device query failed: HTTP {status}")
        found: dict[str, str] = {}
        for device in payload.get("data", []):
            name = device.get("name")
            device_id = (device.get("id") or {}).get("id")
            if name in DEVICE_BY_NODE.values() and device_id:
                found[name] = device_id
        missing = set(DEVICE_BY_NODE.values()) - set(found)
        if missing:
            raise RuntimeError(f"Cloud devices missing: {sorted(missing)}")
        return found

    def clear_active_alarms(self) -> int:
        status, payload = self.get("/api/alarms?searchStatus=ACTIVE&pageSize=100&page=0")
        if status != 200:
            raise RuntimeError(f"Cloud active-alarm query failed: HTTP {status}")
        cleared = 0
        for alarm in payload.get("data", []):
            alarm_id = (alarm.get("id") or {}).get("id")
            if alarm_id and self.post(f"/api/alarm/{alarm_id}/clear", {})[0] == 200:
                cleared += 1
        return cleared

    def timeseries(self, device_id: str, start_ms: int, end_ms: int) -> tuple[int, dict]:
        keys = ",".join(TELEMETRY_KEYS)
        path = (
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
            f"?keys={keys}&startTs={start_ms}&endTs={end_ms}&limit=10000&agg=NONE"
        )
        return self.get(path)

    def alarms(self) -> tuple[int, dict]:
        return self.get("/api/alarms?pageSize=1000&page=0")


class Experiment:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.start_ms = 0
        self.end_ms = 0
        self.puback_events: list[dict] = []
        self.connect_events: list[dict] = []
        self.link_events: list[dict] = []
        self.local_alarms: list[dict] = []
        self.scenario_events: list[dict] = []

    def scenario_control(self, count: int, node_id: str, fn: FleetNode) -> None:
        cfg = self.config
        at = now_ms()

        def record(kind: str) -> None:
            self.scenario_events.append(
                {"node_id": node_id, "tick": count, "at_ms": at, "control": kind}
            )

        if count == cfg["contamination_tick"][node_id]:
            fn.generator.trigger_contamination()
            record("trigger_contamination")
        if count == cfg["contamination_reset_tick"]:
            # reset() restores the seeded generator and clears the event.
            fn.generator.reset()
            record("reset")
        if count == cfg["interrupt_tick"][node_id]:
            fn.generator.set_supply_interrupted(True)
            record("set_supply_interrupted(True)")
        if count == cfg["interrupt_clear_tick"]:
            fn.generator.set_supply_interrupted(False)
            record("set_supply_interrupted(False)")
        if count == cfg["outage_tick"]:
            fn.transport.simulate_outage()
            self.link_events.append(
                {"node_id": node_id, "event": "link_dropped", "at_ms": at, "tick": count}
            )
        if count == cfg["restore_tick"]:
            fn.transport.start()
            self.link_events.append(
                {"node_id": node_id, "event": "link_restored", "at_ms": at, "tick": count}
            )


def attach_instrumentation(fleet: Fleet, exp: Experiment) -> None:
    """Wrap callbacks in the collector process only; core code is untouched."""
    metrics_evaluators = {fn.config.node_id: AlarmEvaluator() for fn in fleet.nodes}

    for fn in fleet.nodes:
        node_id = fn.config.node_id
        transport = fn.transport
        simulator = fn.simulator
        original_tick = simulator.on_tick
        original_publish = transport._on_publish
        original_connect = transport._on_connect

        def on_tick(
            count: int,
            result,
            _orig: Callable | None = original_tick,
            _nid: str = node_id,
            _fn: FleetNode = fn,
            _evaluator: AlarmEvaluator = metrics_evaluators[node_id],
        ) -> None:
            if _orig is not None:
                _orig(count, result)
            # A second evaluator records the local trigger time without
            # changing the fleet's own evaluator/attribute state.
            for event in _evaluator.evaluate(result.reading, now_ms=result.reading.acquisition_ms()):
                if event.action == "ACTIVATED":
                    exp.local_alarms.append(
                        {
                            "node_id": _nid,
                            "alarm_type": event.alarm_type,
                            "severity": event.severity,
                            "trigger_reading_acq_ms": result.reading.acquisition_ms(),
                            "value": event.value,
                            "local_event_ms": event.timestamp_ms,
                        }
                    )
            exp.scenario_control(count, _nid, _fn)

        def on_publish(
            client,
            userdata,
            mid,
            reason_code,
            properties,
            _transport=transport,
            _nid: str = node_id,
            _orig: Callable = original_publish,
        ) -> None:
            entry = _transport._pending.get(int(mid))
            ack_ms = now_ms()
            row_ids: list[int] = []
            started_ms: int | None = None
            is_replay = False
            if entry is not None:
                row_ids, started_ms, is_replay = entry
            _orig(client, userdata, mid, reason_code, properties)
            if entry is not None:
                exp.puback_events.append(
                    {
                        "node_id": _nid,
                        "device": DEVICE_BY_NODE[_nid],
                        "mid": int(mid),
                        "type": "replay" if is_replay else "live",
                        "is_replay": bool(is_replay),
                        "row_ids": list(row_ids),
                        "publish_started_ms": int(started_ms),
                        "ack_ms": ack_ms,
                    }
                )

        def on_connect(
            client,
            userdata,
            flags,
            reason_code,
            properties,
            _transport=transport,
            _nid: str = node_id,
            _orig: Callable = original_connect,
        ) -> None:
            first = not _transport._ever_connected
            _orig(client, userdata, flags, reason_code, properties)
            code = int(getattr(reason_code, "value", reason_code))
            if code == 0:
                exp.connect_events.append(
                    {"node_id": _nid, "connected_ms": now_ms(), "first": bool(first)}
                )

        simulator.on_tick = on_tick
        # paho binds callbacks on the client at construction time. Replace them
        # there (not on the transport object) so the wrappers actually fire.
        transport._client.on_publish = on_publish
        transport._client.on_connect = on_connect


def read_sqlite(window_start_ms: int, window_end_ms: int) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    losses: list[dict] = []
    for node_id, device in DEVICE_BY_NODE.items():
        db_path = f"data/{node_id}.db"
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        for row in connection.execute(
            "SELECT id, node_id, acquisition_ms, stored_at_ms, synced_at_ms, synced, "
            "publish_attempts, last_error, ph, turbidity_ntu, tds_ppm, water_temp_c, "
            "flow_lpm, latitude, longitude "
            "FROM readings WHERE acquisition_ms BETWEEN ? AND ? ORDER BY acquisition_ms, id",
            (window_start_ms, window_end_ms),
        ):
            item = dict(row)
            item["device"] = device
            rows.append(item)
        for event in connection.execute(
            "SELECT id, occurred_at_ms, node_id, reason, acquisition_ms, detail "
            "FROM loss_events WHERE occurred_at_ms BETWEEN ? AND ? ORDER BY occurred_at_ms",
            (window_start_ms, window_end_ms),
        ):
            losses.append(dict(event))
        connection.close()
    return rows, losses


def fetch_cloud(
    client: CloudClient, device_ids: dict[str, str], start_ms: int, end_ms: int
) -> tuple[dict, list[dict]]:
    telemetry: dict[str, dict] = {}
    telemetry_raw: dict[str, dict] = {}
    for device, device_id in device_ids.items():
        status, payload = client.timeseries(device_id, start_ms, end_ms)
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"Cloud telemetry query failed for {device}: HTTP {status}")
        telemetry_raw[device] = payload
        by_ts: dict[int, dict] = {}
        for key, points in payload.items():
            for point in points or []:
                ts = int(point["ts"])
                by_ts.setdefault(ts, {"ts": ts})[key] = point.get("value")
        telemetry[device] = by_ts

    status, payload = client.alarms()
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"Cloud alarm query failed: HTTP {status}")
    alarms: list[dict] = []
    for alarm in payload.get("data", []):
        created = alarm.get("createdTime")
        if not isinstance(created, int) or not (start_ms <= created <= end_ms):
            continue
        if alarm.get("type") not in ALARM_TYPES:
            continue
        if alarm.get("originatorName") not in DEVICE_BY_NODE.values():
            continue
        start_ts = alarm.get("startTs")
        alarms.append(
            {
                "id": (alarm.get("id") or {}).get("id"),
                "alarm_type": alarm.get("type"),
                "severity": alarm.get("severity"),
                "status": alarm.get("status"),
                "device": alarm.get("originatorName"),
                "startTs": start_ts,
                "createdTime": created,
                "endTs": alarm.get("endTs"),
                "cleared": alarm.get("cleared"),
                "acknowledged": alarm.get("acknowledged"),
                "details": alarm.get("details"),
                "delay_ms": (created - start_ts) if isinstance(start_ts, int) else None,
            }
        )
    alarms.sort(key=lambda a: (a["createdTime"], a["device"], a["alarm_type"]))
    return telemetry, alarms


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if not fieldnames:
        fieldnames = sorted({key for row in rows for key in row}) or ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def compute_latency(exp: Experiment, db_rows: list[dict]) -> dict:
    # SQLite autoincrement ids are unique per node database, not globally.
    # Key by (node_id, id) so identical ids on different nodes cannot collide.
    timing = {
        (row["node_id"], row["id"]): (row["acquisition_ms"], row["stored_at_ms"])
        for row in db_rows
    }
    samples: list[dict] = []
    for event in exp.puback_events:
        for row_id in event["row_ids"]:
            pair = timing.get((event["node_id"], row_id))
            if pair is None:
                continue
            acq, stored = pair
            samples.append(
                {
                    "node_id": event["node_id"],
                    "device": event["device"],
                    "row_id": row_id,
                    "type": event["type"],
                    "acquisition_ms": acq,
                    "stored_at_ms": stored,
                    "publish_started_ms": event["publish_started_ms"],
                    "ack_ms": event["ack_ms"],
                    "edge_to_puback_ms": event["ack_ms"] - acq,
                    "puback_latency_ms": event["ack_ms"] - event["publish_started_ms"],
                    "stored_to_puback_ms": (
                        event["ack_ms"] - stored if stored is not None else None
                    ),
                }
            )
    live = [s["edge_to_puback_ms"] for s in samples if s["type"] == "live"]
    replay = [s["edge_to_puback_ms"] for s in samples if s["type"] == "replay"]
    return {
        "samples": samples,
        "live": summarize(live),
        "replay": summarize(replay),
        "puback_only_live": summarize(
            [s["puback_latency_ms"] for s in samples if s["type"] == "live"]
        ),
    }


def compute_recovery(exp: Experiment) -> list[dict]:
    results: list[dict] = []
    replay_events = [e for e in exp.puback_events if e["is_replay"]]
    for node_id, device in DEVICE_BY_NODE.items():
        links = [e for e in exp.link_events if e["node_id"] == node_id]
        dropped = [e["at_ms"] for e in links if e["event"] == "link_dropped"]
        restored = [e["at_ms"] for e in links if e["event"] == "link_restored"]
        if not dropped or not restored:
            continue
        outage_ms = min(dropped)
        restore_ms = max(restored)
        # The transport auto-reconnects with exponential backoff, so the first
        # successful reconnect can precede the demo "restore" tick. Anchor the
        # measurement at the real outage onset and the real reconnect instead.
        reconnects = sorted(
            e["connected_ms"]
            for e in exp.connect_events
            if e["node_id"] == node_id and not e["first"] and e["connected_ms"] >= outage_ms
        )
        reconnect_ms = reconnects[0] if reconnects else None
        episodes = [
            ep
            for ep in group_replay_episodes(replay_events, gap_s=30.0)
            if ep and ep[0]["node_id"] == node_id
            and max(e["ack_ms"] for e in ep) >= outage_ms
        ]
        if not episodes or reconnect_ms is None:
            results.append(
                {
                    "node_id": node_id,
                    "device": device,
                    "outage_ms": outage_ms,
                    "demo_restore_ms": restore_ms,
                    "reconnect_ms": reconnect_ms,
                    "rows_replayed": 0,
                    "replay_start_ms": None,
                    "buffer_empty_ms": None,
                    "recovery_ms": None,
                    "reconnect_delay_ms": None,
                    "flush_ms": None,
                    "flush_rows_per_s": None,
                }
            )
            continue
        episode = max(episodes, key=lambda ep: max(e["ack_ms"] for e in ep))
        rows = sum(len(e["row_ids"]) for e in episode)
        replay_start_ms = min(e["publish_started_ms"] for e in episode)
        buffer_empty_ms = max(e["ack_ms"] for e in episode)
        results.append(
            {
                "node_id": node_id,
                "device": device,
                "outage_ms": outage_ms,
                "demo_restore_ms": restore_ms,
                "reconnect_ms": reconnect_ms,
                "rows_replayed": rows,
                "replay_start_ms": replay_start_ms,
                "buffer_empty_ms": buffer_empty_ms,
                "recovery_ms": buffer_empty_ms - outage_ms,
                "reconnect_delay_ms": reconnect_ms - outage_ms,
                "flush_ms": buffer_empty_ms - reconnect_ms,
                "flush_rows_per_s": throughput_rows_per_s(rows, replay_start_ms, buffer_empty_ms),
            }
        )
    return results


def buffer_depth_samples(db_rows: list[dict], outage_ms: int, restore_ms: int) -> list[dict]:
    events: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in db_rows:
        events[row["device"]].append((row["stored_at_ms"], 1))
        if row["synced_at_ms"] is not None:
            events[row["device"]].append((row["synced_at_ms"], -1))
    samples: list[dict] = []
    for device, series in events.items():
        depth = 0
        for timestamp, delta in sorted(series):
            depth += delta
            samples.append(
                {
                    "device": device,
                    "at_ms": timestamp,
                    "buffer_depth": depth,
                    "in_outage": bool(outage_ms <= timestamp <= restore_ms),
                }
            )
    return samples


def make_plots(latency_samples: list[dict], depth_samples: list[dict], outage_ms: int, link_up_ms: int) -> None:
    live = [s["edge_to_puback_ms"] for s in latency_samples if s["type"] == "live"]
    if live:
        stats = summarize(live)
        fig, ax = plt.subplots(figsize=(8, 5), dpi=200)
        ax.hist(live, bins=40, color="#2c7fb8", edgecolor="white", linewidth=0.5)
        for value, color, label in (
            (stats["mean"], "#d95f0e", f"mean {stats['mean']:.0f} ms"),
            (stats["median"], "#31a354", f"median {stats['median']:.0f} ms"),
            (stats["p95"], "#c51b7d", f"p95 {stats['p95']:.0f} ms"),
        ):
            ax.axvline(value, color=color, linestyle="--", linewidth=1.4, label=label)
        ax.set_xlabel("Edge acquisition → QoS 1 PUBACK (ms)")
        ax.set_ylabel("Messages")
        ax.set_title("JalSanket: edge-to-broker latency (not Cloud ingestion time)")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(EVIDENCE / "latency_distribution.png", dpi=200)
        plt.close(fig)

    if depth_samples:
        fig, ax = plt.subplots(figsize=(9, 4.5), dpi=200)
        colors = {"node-01": "#1b9e77", "node-02": "#d95f02", "node-03": "#7570b3"}
        device_by_node = {v: k for k, v in DEVICE_BY_NODE.items()}
        for device in sorted({s["device"] for s in depth_samples}):
            points = sorted((s["at_ms"], s["buffer_depth"]) for s in depth_samples if s["device"] == device)
            xs = [t / 1000.0 for t, _ in points]
            ys = [d for _, d in points]
            ax.step(xs, ys, where="post", linewidth=1.3,
                    color=colors.get(device_by_node.get(device, ""), "#333333"), label=device)
        ax.axvspan(outage_ms / 1000.0, link_up_ms / 1000.0, color="#999999", alpha=0.25,
                   label="link down (until first reconnect)")
        ax.set_xlabel("Wall-clock time (epoch seconds)")
        ax.set_ylabel("Unsynchronised SQLite rows")
        ax.set_title("JalSanket: buffer depth through outage and recovery")
        ax.legend(frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(EVIDENCE / "buffer_depth_timeline.png", dpi=200)
        plt.close(fig)


def manifest(paths: list[Path]) -> list[dict]:
    items = []
    for path in paths:
        if path.is_file():
            items.append(
                {
                    "file": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return items


def run(args: argparse.Namespace) -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    load_jwt = subprocess.check_output(["pbpaste"]).decode("utf-8", errors="replace").strip()
    if not load_jwt.startswith("eyJ") or len(load_jwt) < 100:
        raise SystemExit("Copy the ThingsBoard Cloud JWT to the clipboard first")
    jwt_fingerprint = hashlib.sha256(load_jwt.encode()).hexdigest()[:8]

    load_dotenv()
    rest_host = os.environ.get("TB_REST_HOST") or os.environ.get("TB_HOST", "")
    if not rest_host:
        raise SystemExit("TB_REST_HOST or TB_HOST is required")
    cloud = CloudClient(load_jwt, rest_host)

    config = {
        "duration_s": args.duration,
        "outage_tick": args.outage_after_tick,
        "restore_tick": args.outage_after_tick + args.outage_duration_ticks,
        "contamination_tick": {"node-01": 4, "node-02": 6, "node-03": 8},
        "contamination_reset_tick": 28,
        "interrupt_tick": {"node-01": 60, "node-02": 62, "node-03": 64},
        "interrupt_clear_tick": 90,
        "sample_interval_s": 2.0,
        "note": "All scenario controls are the existing generator/RPC controls; no telemetry values are injected.",
    }
    exp = Experiment(config)

    try:
        device_ids = cloud.device_ids()
        cleared = cloud.clear_active_alarms()
        fleet_config = FleetConfig.from_env()
        fleet = Fleet(fleet_config)
        attach_instrumentation(fleet, exp)

        exp.start_ms = now_ms()
        runner = FleetRunner(fleet)
        print(f"Running {args.duration}s Cloud metrics experiment (JWT fingerprint {jwt_fingerprint})")
        runner.run(duration_s=args.duration)
        exp.end_ms = now_ms() + 5000  # allow final REST-visible writes to settle
    finally:
        subprocess.run(["pbcopy"], input=b"", check=False)

    if not exp.puback_events:
        raise RuntimeError(
            "No QoS 1 PUBACK events captured - paho callback instrumentation failed"
        )
    if not any(event["is_replay"] for event in exp.puback_events):
        raise RuntimeError("No replay PUBACK events captured - outage/recovery did not run")

    db_rows, loss_events = read_sqlite(exp.start_ms, exp.end_ms)
    cloud_telemetry, cloud_alarms = fetch_cloud(cloud, device_ids, exp.start_ms, exp.end_ms)

    acquisition_by_key = {(r["device"], r["acquisition_ms"]): r for r in db_rows}
    cloud_keys = {(device, ts) for device, points in cloud_telemetry.items() for ts in points}
    matched_alarms = []
    for alarm in cloud_alarms:
        alarm["matched_local_reading"] = (
            alarm["device"], alarm["startTs"]
        ) in acquisition_by_key
        matched_alarms.append(alarm)

    latency = compute_latency(exp, db_rows)
    generated = len(db_rows)
    delivered_cloud = sum(
        1 for row in db_rows if (row["device"], row["acquisition_ms"]) in cloud_keys
    )
    synced_puback = sum(1 for row in db_rows if row["synced"] == 1)
    buffered = sum(1 for row in db_rows if row["synced"] == 0)
    loss_rows = len(loss_events)
    delivery = delivery_metrics(generated, delivered_cloud, buffered, loss_rows)
    delivery["puback_synced_rows"] = synced_puback
    delivery["puback_synced_pct"] = (
        100.0 * synced_puback / generated if generated else 0.0
    )

    alarm_stats = alarm_delay_stats(matched_alarms)
    recovery_events = compute_recovery(exp)
    recovery = recovery_summary(recovery_events)

    definitions = {
        "latency_primary": {
            "name": "edge acquisition → MQTT QoS 1 PUBACK",
            "start": "SQLite readings.acquisition_ms (device wall-clock acquisition time)",
            "end": "PUBACK callback time captured in the fleet process",
            "sample": "one value per generated row, separated into live and replay paths",
            "limitation": "This is edge-to-broker confirmation. It is NOT ThingsBoard Cloud dashboard ingestion latency.",
        },
        "cloud_ingestion_latency": {
            "available": False,
            "reason": "Cloud timeseries REST exposes only the device-supplied ts equal to acquisition_ms; no server ingestion timestamp is returned. Any Cloud-ingestion latency number would be fabricated.",
        },
        "cloud_delivery": {
            "method": "Post-run REST timeseries query keyed by (device name, acquisition_ms); presence confirms Cloud-visible storage, not ingestion time.",
        },
        "alarm_activation_delay": {
            "name": "Cloud alarm createdTime − Cloud alarm startTs",
            "start": "Cloud alarm startTs (the triggering telemetry event timestamp)",
            "end": "Cloud alarm createdTime (actual alarm activation)",
            "correlation": "startTs is matched to a local SQLite acquisition_ms for the same device where possible.",
        },
        "buffer_flush_throughput": {
            "name": "replayed rows / (last replay PUBACK − first replay publish)",
            "source": "instrumented PUBACK events from the existing transport",
        },
        "recovery_time": {
            "name": "buffer empty after replay − simulated outage onset",
            "note": (
                "reconnect_delay_ms and flush_ms are reported separately. The transport "
                "auto-reconnects with backoff, often before the demo restore tick, so "
                "wall-clock restoration is not a valid measurement anchor."
            ),
        },
        "data_loss": {
            "source": "SQLite loss_events table",
            "note": "Temporarily buffered rows are not loss; only drop-newest evictions count.",
        },
    }

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": "ThingsBoard Cloud",
        "jwt_fingerprint_not_secret": jwt_fingerprint,
        "experiment": config,
        "window_ms": {"start": exp.start_ms, "end": exp.end_ms},
        "evidence": {
            "devices": device_ids,
            "active_alarms_cleared_at_start": cleared,
            "local_alarm_events": len(exp.local_alarms),
            "puback_events": len(exp.puback_events),
            "connect_events": len(exp.connect_events),
            "link_events": len(exp.link_events),
            "cloud_timeseries_devices": sorted(cloud_telemetry),
            "cloud_alarms_in_window": len(cloud_alarms),
        },
        "definitions": definitions,
        "metrics": {
            "latency_edge_to_puback_live_ms": latency["live"],
            "latency_edge_to_puback_replay_ms": latency["replay"],
            "puback_only_live_ms": latency["puback_only_live"],
            "delivery": delivery,
            "alarm_activation_delay_ms": alarm_stats,
            "buffer_flush": recovery,
            "data_loss": {
                "lost_rows": loss_rows,
                "generated_rows": generated,
                "loss_pct": delivery["loss_pct"],
            },
        },
    }

    # ------------------------------------------------------------ raw evidence
    write_csv(EVIDENCE / "raw_puback_events.csv", exp.puback_events)
    write_csv(EVIDENCE / "raw_latency_samples.csv", latency["samples"])
    write_csv(EVIDENCE / "raw_db_rows.csv", db_rows)
    write_csv(EVIDENCE / "raw_loss_events.csv", loss_events)
    write_csv(EVIDENCE / "raw_local_alarm_events.csv", exp.local_alarms)
    write_csv(EVIDENCE / "raw_scenario_events.csv", exp.scenario_events)
    write_csv(EVIDENCE / "raw_link_and_connect_events.csv",
              exp.link_events + exp.connect_events)
    write_csv(EVIDENCE / "raw_recovery_events.csv", recovery_events)
    write_csv(EVIDENCE / "raw_cloud_alarms.csv", matched_alarms)
    (EVIDENCE / "raw_cloud_telemetry.json").write_text(
        json.dumps(cloud_telemetry, indent=2), encoding="utf-8"
    )
    (EVIDENCE / "experiment_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    (EVIDENCE / "metrics_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )

    outage_ms = min(e["at_ms"] for e in exp.link_events if e["event"] == "link_dropped")
    reconnect_times = [
        e["connected_ms"] for e in exp.connect_events
        if not e["first"] and e["connected_ms"] >= outage_ms
    ]
    link_up_ms = (
        max(reconnect_times) if reconnect_times
        else max(e["at_ms"] for e in exp.link_events if e["event"] == "link_restored")
    )
    depth_samples = buffer_depth_samples(db_rows, outage_ms, link_up_ms)
    write_csv(EVIDENCE / "raw_buffer_depth_samples.csv", depth_samples)
    make_plots(latency["samples"], depth_samples, outage_ms, link_up_ms)

    secret_values = [
        load_jwt,
        os.environ.get("TB_REST_JWT", ""),
        os.environ.get("TB_DEVICE_TOKEN", ""),
        *(os.environ.get(f"TB_NODE_0{i}_TOKEN", "") for i in (1, 2, 3)),
    ]
    generated_files = sorted(EVIDENCE.iterdir())
    findings = scan_for_secrets(generated_files, secret_values)
    manifest_items = manifest(generated_files)
    (EVIDENCE / "manifest.json").write_text(
        json.dumps({"files": manifest_items, "secret_scan_findings": findings}, indent=2),
        encoding="utf-8",
    )

    live = latency["live"]
    if live["n"] < 200:
        raise RuntimeError(
            f"only {live['n']} live latency samples; need at least 200 (increase --duration)"
        )
    if len(cloud_alarms) < 10:
        raise RuntimeError(
            f"only {len(cloud_alarms)} Cloud alarm events; need at least 10"
        )
    if findings:
        raise RuntimeError(f"credential-like strings found in evidence: {findings}")

    print("\n=== Metrics summary ===")
    print(f"messages generated:        {generated}")
    print(f"Cloud-visible delivered:    {delivered_cloud} ({delivery['delivery_ratio_pct']:.2f}%)")
    print(f"still buffered at end:     {buffered}")
    print(f"permanently lost rows:     {loss_rows} ({delivery['loss_pct']:.2f}%)")
    print(f"live edge→PUBACK latency:  n={live['n']} mean={live['mean']:.1f} ms "
          f"median={live['median']:.1f} ms p95={live['p95']:.1f} ms max={live['max']:.1f} ms")
    delay_mean = alarm_stats["mean"]
    print(f"Cloud alarm events:        {len(cloud_alarms)} "
          f"mean delay={f'{delay_mean:.1f}' if delay_mean is not None else 'n/a'} ms")
    print(f"recovery events:           {len(recovery_events)}")
    for event in recovery_events:
        rate = event["flush_rows_per_s"]
        print(f"  {event['device']}: recovery={event['recovery_ms']} ms "
              f"rows={event['rows_replayed']} "
              f"flush={f'{rate:.2f}' if rate is not None else 'n/a'} rows/s "
              f"reconnect={event['reconnect_delay_ms']} ms")
    print("Cloud ingestion latency:   NOT MEASURABLE (no Cloud ingestion timestamp exposed)")
    print(f"raw evidence:              {EVIDENCE}/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=240.0)
    parser.add_argument("--outage-after-tick", type=int, default=40)
    parser.add_argument("--outage-duration-ticks", type=int, default=10)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
