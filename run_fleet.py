#!/usr/bin/env python3
"""Run the three-node JalSanket fleet and provision ThingsBoard Cloud if asked.

Cloud import artifacts (dashboard, rule chain, alarm config, device documents)
are always written locally to ``thingsboard/``. No live ThingsBoard connection
is made unless ``--provision`` is supplied with a REST JWT or admin credentials.
The MQTT/TLS data path is unchanged.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from jalsanket import FleetConfig
from jalsanket.dashboard import write_artifacts
from jalsanket.fleet import Fleet, FleetRunner
from jalsanket.provisioning import ThingsBoardConfig, ThingsBoardProvisioner


def main() -> int:
    parser = argparse.ArgumentParser(description="JalSanket three-node fleet")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--artifacts", default="thingsboard")
    parser.add_argument("--provision", action="store_true", help="apply config to ThingsBoard Cloud via HTTPS REST")
    parser.add_argument("--contaminate-after", type=int, default=None)
    parser.add_argument("--outage-after", type=int, default=None)
    parser.add_argument("--outage-duration", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        fleet_config = FleetConfig.from_env()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print("Set TB_HOST and TB_NODE_01/02/03_TOKEN (see .env.example).", file=sys.stderr)
        return 2

    provisioner = None
    device_ids = None
    if args.provision:
        try:
            tb_config = ThingsBoardConfig.from_env()
        except Exception as exc:
            print(f"Provisioning configuration error: {exc}", file=sys.stderr)
            return 2
        provisioner = ThingsBoardProvisioner(tb_config, fleet_config)
        try:
            provisioner.login()
        except Exception as exc:
            print(f"REST authentication error: {exc}", file=sys.stderr)
            return 2
        provisioner.ensure_device_profile()
        provisioner.ensure_devices()
        provisioner.ensure_alarm_rules()
        device_ids = list(provisioner.device_ids.values())

    artifacts = write_artifacts(args.artifacts, fleet_config, device_ids)
    logging.getLogger("jalsanket.demo").info("Wrote artifacts: %s", list(str(p) for p in artifacts.values()))

    if provisioner is not None:
        for key in ("dashboard", "demo_controls"):
            provisioner.import_dashboard(artifacts_dashboard(artifacts, key))
        logging.getLogger("jalsanket.demo").info(
            "Provisioning summary: %s", provisioner.provisioning_summary()
        )

    fleet = Fleet(fleet_config)
    runner = FleetRunner(fleet)

    restore_at: dict[str, int] = {}

    def on_tick(node_id: str, count: int, fn) -> None:
        if args.contaminate_after == count:
            logging.getLogger("jalsanket.demo").warning("DEMO TRIGGER: contamination on %s", node_id)
            fn.generator.trigger_contamination()
        if args.outage_after == count:
            fn.transport.simulate_outage()
            if args.outage_duration is not None:
                restore_at[node_id] = count + args.outage_duration
        if restore_at.get(node_id) == count:
            logging.getLogger("jalsanket.demo").warning("DEMO TRIGGER: restoring link on %s", node_id)
            fn.transport.start()
            del restore_at[node_id]

    # FleetRunner owns the tick loop; hooks are attached to each simulator.
    for fn in fleet.nodes:
        simulator = fn.simulator
        evaluator_hook = simulator.on_tick
        fleet_node = fn

        def combined_hook(count, result, _eval=evaluator_hook, _fn=fleet_node) -> None:
            if _eval is not None:
                _eval(count, result)
            on_tick(_fn.config.node_id, count, _fn)

        simulator.on_tick = combined_hook

    runner.run(duration_s=args.duration)
    return 0


def artifacts_dashboard(artifacts: dict, key: str = "dashboard") -> dict:
    return json.loads(artifacts[key].read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
