"""Simulator main loop and fleet stepping (Phase 3 + Phase 4).

Reading generation is never gated by connectivity: each step generates and
persists a reading, attempts a live publish if connected, and pumps the MQTT
event loop. ``step()`` lets several independent nodes share one main loop
without sharing any token, device identity or SQLite buffer.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable, Optional

from .mqtt_transport import MqttTransport
from .node import TickResult, VirtualEdgeNode

logger = logging.getLogger("jalsanket.runner")


class EdgeSimulator:
    """Drives one virtual node and its MQTT transport."""

    def __init__(
        self,
        node: VirtualEdgeNode,
        transport: MqttTransport,
        tick_interval_s: Optional[float] = None,
        loop_sleep_s: float = 0.02,
        on_tick: Optional[Callable[[int, TickResult], None]] = None,
    ) -> None:
        self.node = node
        self.transport = transport
        self.tick_interval_s = tick_interval_s or node.generator.config.sample_interval_s
        self.loop_sleep_s = loop_sleep_s
        self.on_tick = on_tick
        self.tick_count = 0
        self._next_tick: Optional[float] = None
        self._stop = False

    def start(self) -> None:
        self.transport.start()
        self._next_tick = time.monotonic()
        logger.info(
            "SIMULATOR STARTED node=%s interval=%.1fs",
            self.node.generator.config.node_id,
            self.tick_interval_s,
        )

    def run_once(self, at: Optional[datetime] = None) -> TickResult:
        """One generate -> persist -> publish attempt cycle."""
        result = self.node.tick(at=at)
        self.tick_count += 1
        self.transport.publish_live(result.reading, result.persistence.row_id)
        self.transport.pump()
        if self.on_tick is not None:
            self.on_tick(self.tick_count, result)
        return result

    def step(self, now: Optional[float] = None) -> None:
        """Advance this node by at most one reading plus network processing."""
        if self._next_tick is None:
            self.start()
        current = time.monotonic() if now is None else now
        if current >= self._next_tick:
            self.run_once()
            self._next_tick += self.tick_interval_s
        self.transport.pump()

    def run(self, duration_s: Optional[float] = None) -> None:
        """Run continuously until stopped or until ``duration_s`` elapses."""
        self.start()
        started = time.monotonic()
        logger.info("SIMULATOR RUN duration=%s", duration_s if duration_s is not None else "unlimited")
        try:
            while not self._stop:
                now = time.monotonic()
                if duration_s is not None and now - started >= duration_s:
                    break
                self.step(now)
                time.sleep(self.loop_sleep_s)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received - stopping")
        finally:
            self.transport.shutdown()
            logger.info(
                "SIMULATOR STOPPED node=%s buffer_depth=%d/%d stats=%s",
                self.node.generator.config.node_id,
                self.transport.buffer_depth,
                self.node.store.config.max_buffer_rows,
                self.transport.stats,
            )

    def stop(self) -> None:
        self._stop = True
