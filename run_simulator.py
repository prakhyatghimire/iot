#!/usr/bin/env python3
"""Live entry point for one virtual JalSanket node (Phase 3).

Credentials are read from environment variables or a git-ignored .env file.
Example::

    export TB_HOST=your-tenant.thingsboard.cloud
    export TB_DEVICE_TOKEN=...          # never commit this
    python3 run_simulator.py --node-id node-01 --duration 300

Optional demonstration triggers (by tick number at the configured interval)::

    --contaminate-after 30 --outage-after 90 --outage-duration 40
"""

from __future__ import annotations

import argparse
import logging
import sys

from jalsanket import (
    GeneratorConfig,
    MqttConfig,
    StoreConfig,
    TelemetryGenerator,
    TelemetryStore,
    VirtualEdgeNode,
)
from jalsanket.config import ConfigurationError
from jalsanket.mqtt_transport import MqttTransport
from jalsanket.runner import EdgeSimulator


def main() -> int:
    parser = argparse.ArgumentParser(description="JalSanket virtual edge node")
    parser.add_argument("--node-id", default="node-01")
    parser.add_argument("--db", default="data/jalsanket.db")
    parser.add_argument("--duration", type=float, default=None, help="run duration in seconds")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--contaminate-after", type=int, default=None, help="tick to trigger contamination")
    parser.add_argument("--outage-after", type=int, default=None, help="tick to drop the cellular link")
    parser.add_argument("--outage-duration", type=int, default=None, help="ticks before link restoration")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        mqtt_config = MqttConfig.from_env()
    except (ConfigurationError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print("Set TB_HOST and TB_DEVICE_TOKEN (see .env.example).", file=sys.stderr)
        return 2

    generator = TelemetryGenerator(GeneratorConfig(node_id=args.node_id, seed=args.seed))
    store = TelemetryStore(StoreConfig(db_path=args.db))
    transport = MqttTransport(mqtt_config, store, args.node_id)
    node = VirtualEdgeNode(generator, store)

    outage_restore_tick: int | None = None

    def on_tick(count: int, _result) -> None:
        nonlocal outage_restore_tick
        if args.contaminate_after == count:
            logging.getLogger("jalsanket.demo").warning("DEMO TRIGGER: contamination event")
            generator.trigger_contamination()
        if args.outage_after == count:
            transport.simulate_outage()
            if args.outage_duration is not None:
                outage_restore_tick = count + args.outage_duration
        if outage_restore_tick == count:
            logging.getLogger("jalsanket.demo").warning("DEMO TRIGGER: restoring cellular link")
            transport.start()
            outage_restore_tick = None

    simulator = EdgeSimulator(node, transport, on_tick=on_tick)
    simulator.run(duration_s=args.duration)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
