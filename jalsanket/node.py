"""Virtual edge node orchestration (Phase 2).

This is the single place where the mandatory ordering is enforced:

    generate reading -> persist to SQLite -> (later) attempt MQTT publish

MQTT is deliberately absent in Phase 2. It will consume rows from the store's
unsynchronized queue in a later phase, never a freshly generated reading that
has bypassed SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .storage import InsertOutcome, TelemetryStore
from .telemetry import Reading, TelemetryGenerator


@dataclass(frozen=True)
class TickResult:
    reading: Reading
    persistence: InsertOutcome


class VirtualEdgeNode:
    """Owns one telemetry generator and one durable buffer."""

    def __init__(self, generator: TelemetryGenerator, store: TelemetryStore) -> None:
        self.generator = generator
        self.store = store

    def tick(self, at: Optional[datetime] = None) -> TickResult:
        """Generate one reading and persist it before any transport step."""
        reading = self.generator.tick(at=at)
        persistence = self.store.persist(reading)
        return TickResult(reading=reading, persistence=persistence)

    def generate_and_store(self, count: int, start_at: Optional[datetime] = None) -> list[TickResult]:
        """Generate and persist ``count`` consecutive readings."""
        base = start_at or datetime.now(timezone.utc)
        return [
            self.tick(at=base + timedelta(seconds=i * self.generator.config.sample_interval_s))
            for i in range(count)
        ]

    def status(self) -> dict:
        return {
            "node_id": self.generator.config.node_id,
            "buffer_depth": self.store.get_buffer_depth(),
            "capacity": self.store.config.max_buffer_rows,
            "eviction_policy": self.store.config.eviction_policy,
            "data_loss_count": self.store.data_loss_count(),
            "simulation_time_s": self.generator.simulation_time_s,
        }
