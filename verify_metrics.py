#!/usr/bin/env python3
"""Deterministic tests for the metrics calculations.

No credentials, network or live fleet are used. Exits non-zero on any failure.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import collect_metrics
from metricslib import (
    alarm_delay_stats,
    delivery_metrics,
    group_replay_episodes,
    percentile,
    recovery_summary,
    scan_for_secrets,
    summarize,
    throughput_rows_per_s,
)

results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((bool(passed), name, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    print("=== 1. Percentiles and summaries ===")
    data = list(range(1, 11))
    check("p50 of 1..10 is 5.5", percentile(data, 0.5) == 5.5)
    check("p95 of 1..10 is 9.55", abs(percentile(data, 0.95) - 9.55) < 1e-9,
          str(percentile(data, 0.95)))
    stats = summarize(data)
    check("summary count/mean/max",
          stats["n"] == 10 and stats["mean"] == 5.5 and stats["max"] == 10, str(stats))
    empty = summarize([])
    check("empty summary is explicit", empty["n"] == 0 and empty["p95"] is None)

    print("\n=== 2. Delivery, buffering and loss ===")
    dm = delivery_metrics(generated=100, delivered_cloud=97, buffered=3, lost=0)
    check("delivery ratio 97%", dm["delivery_ratio_pct"] == 97.0, str(dm))
    check("temporarily buffered is not loss", dm["buffered_pct"] == 3.0 and dm["loss_pct"] == 0.0)
    dm2 = delivery_metrics(generated=200, delivered_cloud=196, buffered=0, lost=4)
    check("real loss reported separately", dm2["loss_pct"] == 2.0 and dm2["buffered_pct"] == 0.0)

    print("\n=== 3. Alarm activation delay ===")
    alarms = [
        {"alarmType": "High Turbidity Warning", "delay_ms": 100},
        {"alarmType": "Gross Contamination Critical", "delay_ms": 200},
        {"alarmType": "pH Out of Range Critical", "delay_ms": 300},
    ]
    ads = alarm_delay_stats(alarms)
    check("alarm delay mean 200 ms", ads["mean"] == 200.0 and ads["alarms"] == 3, str(ads))

    print("\n=== 4. Replay grouping, throughput and recovery ===")
    events = [
        {"node_id": "node-01", "publish_started_ms": 1000, "ack_ms": 1200, "is_replay": True},
        {"node_id": "node-01", "publish_started_ms": 1500, "ack_ms": 1700, "is_replay": True},
        {"node_id": "node-02", "publish_started_ms": 1100, "ack_ms": 1300, "is_replay": True},
        {"node_id": "node-01", "publish_started_ms": 61000, "ack_ms": 61200, "is_replay": True},
        {"node_id": "node-01", "publish_started_ms": 2000, "ack_ms": 2100, "is_replay": False},
    ]
    episodes = group_replay_episodes(events, gap_s=30.0)
    # node-01 yields two episodes (gap splits it); node-02 yields one; the
    # non-replay event is ignored entirely.
    check("three replay episodes, live ignored", len(episodes) == 3, str(len(episodes)))
    check("episode sizes 2, 1 and 1", sorted(len(e) for e in episodes) == [1, 1, 2],
          str([len(e) for e in episodes]))
    rate = throughput_rows_per_s(20, 1000, 3000)
    check("throughput 10 rows/s", rate == 10.0, str(rate))
    check("zero-length window is not a number", throughput_rows_per_s(5, 1000, 1000) is None)
    summaries = [
        {"node_id": "node-01", "recovery_ms": 400, "flush_rows_per_s": 10.0},
        {"node_id": "node-02", "recovery_ms": 600, "flush_rows_per_s": 8.0},
    ]
    rs = recovery_summary(summaries)
    check("mean recovery 500 ms", rs["recovery_ms"]["mean"] == 500.0, str(rs["recovery_ms"]))

    print("\n=== 5. Collector correlation, recovery and plots (synthetic) ===")
    exp = collect_metrics.Experiment({})
    exp.puback_events = [
        {
            "node_id": "node-01", "device": "JalSanket-Node-01", "mid": 1,
            "type": "live", "is_replay": False, "row_ids": [1],
            "publish_started_ms": 1005, "ack_ms": 1100,
        },
        {
            "node_id": "node-01", "device": "JalSanket-Node-01", "mid": 2,
            "type": "replay", "is_replay": True, "row_ids": [2, 3],
            "publish_started_ms": 5000, "ack_ms": 5400,
        },
        {
            "node_id": "node-02", "device": "JalSanket-Node-02", "mid": 3,
            "type": "live", "is_replay": False, "row_ids": [1],
            "publish_started_ms": 1205, "ack_ms": 1300,
        },
        {
            "node_id": "node-03", "device": "JalSanket-Node-03", "mid": 4,
            "type": "live", "is_replay": False, "row_ids": [1],
            "publish_started_ms": 1405, "ack_ms": 1500,
        },
    ]
    db_rows = [
        {"id": 1, "node_id": "node-01", "acquisition_ms": 1000, "stored_at_ms": 1002,
         "synced_at_ms": 1100, "device": "JalSanket-Node-01", "synced": 1},
        {"id": 2, "node_id": "node-01", "acquisition_ms": 2000, "stored_at_ms": 2002,
         "synced_at_ms": 5400, "device": "JalSanket-Node-01", "synced": 1},
        {"id": 3, "node_id": "node-01", "acquisition_ms": 2100, "stored_at_ms": 2102,
         "synced_at_ms": 5400, "device": "JalSanket-Node-01", "synced": 1},
        {"id": 1, "node_id": "node-02", "acquisition_ms": 1200, "stored_at_ms": 1201,
         "synced_at_ms": 1300, "device": "JalSanket-Node-02", "synced": 1},
        {"id": 1, "node_id": "node-03", "acquisition_ms": 1400, "stored_at_ms": 1401,
         "synced_at_ms": 1500, "device": "JalSanket-Node-03", "synced": 1},
    ]
    latency = collect_metrics.compute_latency(exp, db_rows)
    first = latency["samples"][0]
    check("latency sample counts live=3 replay=2",
          latency["live"]["n"] == 3 and latency["replay"]["n"] == 2,
          str((latency["live"]["n"], latency["replay"]["n"])))
    check("no negative latency from cross-node id collision",
          all(s["edge_to_puback_ms"] >= 0 for s in latency["samples"]))
    same_id = {s["node_id"]: s for s in latency["samples"] if s["row_id"] == 1}
    check("identical row ids map to each node's own acquisition",
          same_id["node-01"]["acquisition_ms"] == 1000
          and same_id["node-02"]["acquisition_ms"] == 1200
          and same_id["node-03"]["acquisition_ms"] == 1400,
          str({k: v["acquisition_ms"] for k, v in same_id.items()}))
    check("edge acquisition to PUBACK = 100 ms", first["edge_to_puback_ms"] == 100)
    check("PUBACK-only = 95 ms (not end-to-end)", first["puback_latency_ms"] == 95)
    check("stored to PUBACK = 98 ms", first["stored_to_puback_ms"] == 98)

    exp.link_events = [
        {"node_id": "node-01", "event": "link_dropped", "at_ms": 3000},
        {"node_id": "node-01", "event": "link_restored", "at_ms": 6000},
    ]
    exp.connect_events = [
        {"node_id": "node-01", "connected_ms": 100, "first": True},
        {"node_id": "node-01", "connected_ms": 4200, "first": False},
    ]
    recovery = collect_metrics.compute_recovery(exp)
    check("one recovery event", len(recovery) == 1, str(len(recovery)))
    check("recovery anchored at outage onset (2400 ms)",
          recovery[0]["recovery_ms"] == 2400, str(recovery[0]))
    check("reconnect delay 1200 ms", recovery[0]["reconnect_delay_ms"] == 1200)
    check("two rows replayed at 5 rows/s",
          recovery[0]["rows_replayed"] == 2
          and recovery[0]["flush_rows_per_s"] == 5.0,
          str(recovery[0]["flush_rows_per_s"]))

    depth = collect_metrics.buffer_depth_samples(db_rows, 3000, 4200)
    check("buffer depth keys are device names",
          all(isinstance(s["device"], str) for s in depth))
    check("max buffered depth = 2", max(s["buffer_depth"] for s in depth) == 2)
    with tempfile.TemporaryDirectory(prefix="jalsanket-metrics-plot-") as tmp:
        original = collect_metrics.EVIDENCE
        collect_metrics.EVIDENCE = Path(tmp)
        try:
            collect_metrics.make_plots(latency["samples"], depth, 3000, 4200)
        finally:
            collect_metrics.EVIDENCE = original
        check("both PNG plots written",
              (Path(tmp) / "latency_distribution.png").is_file()
              and (Path(tmp) / "buffer_depth_timeline.png").is_file())

    print("\n=== 6. Secret scanning ===")
    with tempfile.TemporaryDirectory(prefix="jalsanket-metrics-test-") as tmp:
        clean = Path(tmp) / "clean.json"
        dirty = Path(tmp) / "dirty.json"
        clean.write_text('{"ok": true, "host": "eu.thingsboard.cloud"}')
        dirty.write_text('{"jwt": "eyJabcdefghijklmnopqrstuvwxyz1234567890", "token": "FAKE_SECRET_VALUE"}')
        findings = scan_for_secrets([clean, dirty], ["FAKE_SECRET_VALUE"])
        kinds = {f["kind"] for f in findings}
        check("JWT-like string detected", "JWT-like string" in kinds, str(kinds))
        check("configured secret detected", "configured secret #1" in kinds, str(kinds))
        check("clean file not flagged", all(f["file"] != str(clean) for f in findings))

    passed = sum(1 for ok, _, _ in results if ok)
    failed = len(results) - passed
    print(f"\n  {passed}/{len(results)} checks passed")
    if failed:
        for ok, name, detail in results:
            if not ok:
                print(f"  - {name} ({detail})")
        return 1
    print("\nMetrics verification: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
