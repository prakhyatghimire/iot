"""Pure, deterministic calculations for the JalSanket metrics experiment.

No module here contacts ThingsBoard or reads credentials. Keeping the maths
separate makes every reported number reproducible with synthetic data in
``verify_metrics.py``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable, Sequence

JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{20,}")


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolation percentile (the common 'type 7' definition)."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if not 0.0 <= p <= 1.0:
        raise ValueError("p must be between 0 and 1")
    if len(data) == 1:
        return data[0]
    rank = p * (len(data) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return data[low]
    return data[low] + (rank - low) * (data[high] - data[low])


def summarize(values: Sequence[float]) -> dict[str, float | int | None]:
    """Return count, mean, median, p95, min and max for a sample."""
    data = [float(v) for v in values]
    if not data:
        return {"n": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None}
    return {
        "n": len(data),
        "mean": sum(data) / len(data),
        "median": percentile(data, 0.5),
        "p95": percentile(data, 0.95),
        "min": min(data),
        "max": max(data),
    }


def delivery_metrics(generated: int, delivered_cloud: int, buffered: int, lost: int) -> dict[str, float]:
    """Delivery/buffering/loss percentages. Buffered rows are NOT lost."""
    if generated < 0 or delivered_cloud < 0 or buffered < 0 or lost < 0:
        raise ValueError("counts must be non-negative")
    if generated == 0:
        return {
            "generated": 0,
            "delivered_cloud": 0,
            "buffered": 0,
            "lost": 0,
            "delivery_ratio_pct": 0.0,
            "buffered_pct": 0.0,
            "loss_pct": 0.0,
        }
    return {
        "generated": generated,
        "delivered_cloud": delivered_cloud,
        "buffered": buffered,
        "lost": lost,
        "delivery_ratio_pct": 100.0 * delivered_cloud / generated,
        "buffered_pct": 100.0 * buffered / generated,
        "loss_pct": 100.0 * lost / generated,
    }


def alarm_delay_stats(records: Iterable[dict]) -> dict:
    """Mean/median activation delay from alarm records with ``delay_ms``."""
    rows = [r for r in records if isinstance(r.get("delay_ms"), (int, float))]
    stats = summarize([r["delay_ms"] for r in rows])
    return {"alarms": len(rows), **stats}


def group_replay_episodes(events: Sequence[dict], gap_s: float = 30.0) -> list[list[dict]]:
    """Group replay PUBACK events into recovery episodes per node.

    ``events`` items need ``node_id`` and ``publish_started_ms``. A gap larger
    than ``gap_s`` starts a new episode for that node.
    """
    by_node: dict[str, list[dict]] = {}
    for event in events:
        if not event.get("is_replay"):
            continue
        by_node.setdefault(str(event["node_id"]), []).append(dict(event))

    episodes: list[list[dict]] = []
    for node_id in sorted(by_node):
        current: list[dict] = []
        last_ms: float | None = None
        for event in sorted(by_node[node_id], key=lambda e: e["publish_started_ms"]):
            start_ms = float(event["publish_started_ms"])
            if current and last_ms is not None and (start_ms - last_ms) > gap_s * 1000.0:
                episodes.append(current)
                current = []
            current.append(event)
            last_ms = max(start_ms, float(event.get("ack_ms", start_ms)))
        if current:
            episodes.append(current)
    return episodes


def throughput_rows_per_s(rows: int, start_ms: float, end_ms: float) -> float | None:
    """Rows successfully replayed per second over an exact measured window."""
    duration_s = (float(end_ms) - float(start_ms)) / 1000.0
    if duration_s <= 0:
        return None
    return float(rows) / duration_s


def recovery_summary(episodes: Sequence[dict]) -> dict:
    """Mean/per-node summary of recovery and flush measurements."""
    delays = [float(e["recovery_ms"]) for e in episodes if e.get("recovery_ms") is not None]
    rates = [float(e["flush_rows_per_s"]) for e in episodes if e.get("flush_rows_per_s") is not None]
    return {
        "events": len(episodes),
        "recovery_ms": summarize(delays),
        "flush_rows_per_s": summarize(rates),
        "per_node": list(episodes),
    }


def scan_for_secrets(paths: Iterable[Path], secret_values: Iterable[str] = ()) -> list[dict]:
    """Return non-secret descriptions of any credential-like strings found."""
    secrets = [s for s in secret_values if s and len(s) >= 8]
    findings: list[dict] = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if JWT_PATTERN.search(text):
            findings.append({"file": str(path), "kind": "JWT-like string"})
        for index, secret in enumerate(secrets):
            if secret in text:
                findings.append({"file": str(path), "kind": f"configured secret #{index + 1}"})
    return findings
