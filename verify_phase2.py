#!/usr/bin/env python3
"""Phase 2 verification: SQLite store-and-forward buffer.

Run with::

    python3 verify_phase2.py

Uses temporary databases so repeated runs are independent. Exits non-zero if
any check fails.
"""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jalsanket import (
    GeneratorConfig,
    StoreConfig,
    TelemetryGenerator,
    TelemetryStore,
    VirtualEdgeNode,
)

BASE = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
results: list[tuple[bool, str, str]] = []


class CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((bool(passed), name, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    handler = CaptureHandler()
    log = logging.getLogger("jalsanket.storage")
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    with tempfile.TemporaryDirectory(prefix="jalsanket-phase2-") as tmp:
        db_path = Path(tmp) / "node01.db"

        # ---------------------------------------------------------- setup/WAL
        section("1. Store setup and WAL mode")
        store = TelemetryStore(StoreConfig(db_path=str(db_path)))
        check("journal mode is WAL", store.journal_mode() == "wal", store.journal_mode())
        check("default capacity is 10,800", store.config.max_buffer_rows == 10_800)
        check("eviction policy is drop_newest", store.config.eviction_policy == "drop_newest")
        check("empty buffer depth is zero", store.get_buffer_depth() == 0)
        check("synchronous is FULL", store.config.synchronous == "FULL")
        wal_sidecars = list(Path(tmp).glob("node01.db-wal"))
        check("WAL sidecar file created", len(wal_sidecars) == 1, str(wal_sidecars))

        # ------------------------------------------- persistence + acquisition
        section("2. Persistence before publish, timestamps and values")
        gen = TelemetryGenerator(GeneratorConfig(node_id="node-01", seed=42))
        node = VirtualEdgeNode(gen, store)

        ticked = node.tick(at=BASE)
        check("tick persists reading immediately", ticked.persistence.inserted)
        check("row id assigned", ticked.persistence.row_id is not None)
        check("depth after one tick is one", store.get_buffer_depth() == 1)
        row = store.get_unsynced_batch(1)[0]
        check("original acquisition_ms preserved", row.acquisition_ms == ticked.reading.acquisition_ms())
        check("acquired_at ISO preserved", row.acquired_at == ticked.reading.acquired_at.isoformat())
        check("all telemetry values preserved", row.values() == {
            "ph": ticked.reading.ph,
            "turbidity_ntu": ticked.reading.turbidity_ntu,
            "tds_ppm": ticked.reading.tds_ppm,
            "water_temp_c": ticked.reading.water_temp_c,
            "flow_lpm": ticked.reading.flow_lpm,
            "latitude": ticked.reading.latitude,
            "longitude": ticked.reading.longitude,
        })

        now_ms = int(time.time() * 1000)
        check("stored_at_ms is real wall clock", abs(row.stored_at_ms - now_ms) < 5000,
              f"stored={row.stored_at_ms} now={now_ms}")
        check("stored_at_ms is NOT the acquisition time", row.stored_at_ms != row.acquisition_ms)
        check("simulated clock not stored as measurement time", not hasattr(row, "simulation_time_s"))

        # Insert more readings with deliberately shuffled acquisition times.
        offsets = [10, 2, 8, 0, 5, 12, 4, 6, 1]
        for offset in offsets:
            reading = gen.tick(at=BASE + timedelta(seconds=offset * 2))
            store.persist(reading)
        check("all readings persisted", store.total_rows() == 10, f"rows={store.total_rows()}")
        check("depth tracks unsynced rows", store.get_buffer_depth() == 10)

        # ------------------------------------------------------------ ordering
        section("3. Chronological retrieval of unsynchronized rows")
        batch = store.get_unsynced_batch(100)
        acq = [r.acquisition_ms for r in batch]
        check("unsynced rows sorted by acquisition_ms", acq == sorted(acq), str(acq))
        check("batch respects limit", len(store.get_unsynced_batch(3)) == 3)
        tie_groups: dict[int, list[int]] = {}
        for r in batch:
            tie_groups.setdefault(r.acquisition_ms, []).append(r.id)
        check("id is the tie-breaker for equal acquisition_ms",
              all(ids == sorted(ids) for ids in tie_groups.values()))
        check("oldest row is first", batch[0].acquisition_ms == int(BASE.timestamp() * 1000))

        # -------------------------------------------------------- sync updates
        section("4. Sync-state changes")
        first_four = [r.id for r in batch[:4]]
        changed = store.mark_synced(first_four)
        check("mark_synced changes exactly 4 rows", changed == 4, f"changed={changed}")
        check("buffer depth decreases to 6", store.get_buffer_depth() == 6)
        remaining_ids = {r.id for r in store.get_unsynced_batch(100)}
        check("synced rows excluded from unsynced queue", not (set(first_four) & remaining_ids))
        synced_rows = [r for r in store.get_unsynced_batch(100)]
        check("remaining rows are the newer ones", all(r.id not in first_four for r in synced_rows))
        check("mark_synced is idempotent", store.mark_synced(first_four) == 0)
        check("sync log reports flushed and remaining rows",
              any("rows_flushed=4 remaining_rows=6" in m for m in handler.messages))
        check("depth/capacity logged on storage",
              any("buffer_depth=1 capacity=10800" in m for m in handler.messages))

        # -------------------------------------------------------------- restart
        section("5. Restart survival")
        store.close()
        store2 = TelemetryStore(StoreConfig(db_path=str(db_path)))
        check("WAL mode survives restart", store2.journal_mode() == "wal")
        check("unsynced rows survive restart", store2.get_buffer_depth() == 6)
        check("synced rows remain synced after restart", store2.total_rows() == 10)
        check("acquisition_ms survives restart",
              store2.get_unsynced_batch(1)[0].acquisition_ms == batch[4].acquisition_ms)
        check("no data loss recorded during normal operation", store2.data_loss_count() == 0)

        # ------------------------------------------------------------- eviction
        section("6. Capacity and drop-newest eviction")
        small_path = Path(tmp) / "small.db"
        small = TelemetryStore(StoreConfig(db_path=str(small_path), max_buffer_rows=5))
        small_gen = TelemetryGenerator(GeneratorConfig(node_id="node-small", seed=7))
        outcomes = []
        for i in range(7):
            reading = small_gen.tick(at=BASE + timedelta(seconds=i * 2))
            outcomes.append(small.persist(reading))

        check("first 5 readings inserted", all(o.inserted for o in outcomes[:5]))
        check("next 2 readings rejected", not any(o.inserted for o in outcomes[5:]))
        check("buffer stays at capacity", small.get_buffer_depth() == 5)
        check("total rows equals capacity", small.total_rows() == 5)
        check("data loss count is 2", small.data_loss_count() == 2)
        kept_acq = [r.acquisition_ms for r in small.get_unsynced_batch(100)]
        expected_kept = [int((BASE + timedelta(seconds=i * 2)).timestamp() * 1000) for i in range(5)]
        check("oldest rows kept (newest dropped)", kept_acq == expected_kept, str(kept_acq))
        eviction_logs = [m for m in handler.messages if "BUFFER FULL - DROPPING NEWEST" in m]
        check("eviction events logged", len(eviction_logs) == 2, f"logged={len(eviction_logs)}")
        check("eviction log shows depth and capacity",
              any("buffer_depth=5 capacity=5" in m for m in eviction_logs))
        check("loss events persisted", small.data_loss_count() == 2)
        small.close()
        store2.close()

        # --------------------------------------------------- Phase 1 regression
        section("7. Physical model unchanged (Phase 1 regression)")
        fresh = TelemetryGenerator(GeneratorConfig(node_id="node-01", seed=42))
        first = fresh.generate(1, start_at=datetime(2026, 6, 15, 6, 0, tzinfo=timezone.utc))[0]
        check("first reading identical to Phase 1 baseline",
              (first.ph, first.turbidity_ntu, first.water_temp_c, first.flow_lpm)
              == (7.15, 5.04, 20.05, 12.8),
              f"{first.ph}, {first.turbidity_ntu}, {first.water_temp_c}, {first.flow_lpm}")
        fresh.trigger_contamination()
        event = fresh.generate(15, start_at=datetime(2026, 6, 15, 6, 2, tzinfo=timezone.utc))
        check("contamination still crosses critical threshold",
              max(r.turbidity_ntu for r in event) > 200)
        check("pH suppression still bounded", min(r.ph for r in event) >= 6.0)

        # -------------------------------------------------------------- summary
        section("Summary")
        passed = sum(1 for ok, _, _ in results if ok)
        failed = len(results) - passed
        print(f"  {passed}/{len(results)} checks passed")
        if failed:
            print("\nFailed checks:")
            for ok, name, detail in results:
                if not ok:
                    print(f"  - {name} ({detail})")
            return 1
        print("\nPhase 2 verification: ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
