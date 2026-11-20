"""Three independent virtual nodes and their fleet runner (Phase 4).

Each node owns a distinct device identity, access token, coordinates and
SQLite database. They share no transport state: each has its own MQTT client,
outage detection, backoff and replay loop.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .alarms import AlarmEvaluator
from .config import ConfigurationError, MqttConfig, load_dotenv
from .mqtt_transport import MqttTransport
from .node import VirtualEdgeNode
from .runner import EdgeSimulator
from .storage import StoreConfig, TelemetryStore
from .telemetry import GeneratorConfig, TelemetryGenerator

logger = logging.getLogger("jalsanket.fleet")


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    device_name: str
    token_env_var: str
    latitude: float
    longitude: float
    seed: int
    db_path: str
    token: Optional[str] = None  # test injection only; never committed

    def resolve_token(self) -> str:
        if self.token:
            return self.token
        value = os.environ.get(self.token_env_var, "")
        if not value:
            raise ConfigurationError(
                f"{self.token_env_var} is required for {self.node_id}; "
                "see .env.example (never commit tokens)"
            )
        return value


# Three distinct post-flood water-source sites in Rasuwa district:
# Dhunche, Syafrubesi and the Rasuwagadhi area. Demonstration coordinates
# only - not a claim that sensors are installed at these exact points.
DEFAULT_NODE_SPECS: tuple[NodeConfig, ...] = (
    NodeConfig("node-01", "JalSanket-Node-01", "TB_NODE_01_TOKEN",
               28.1100, 85.2900, 42, "data/node-01.db"),
    NodeConfig("node-02", "JalSanket-Node-02", "TB_NODE_02_TOKEN",
               28.0920, 85.3610, 43, "data/node-02.db"),
    NodeConfig("node-03", "JalSanket-Node-03", "TB_NODE_03_TOKEN",
               28.1710, 85.3870, 44, "data/node-03.db"),
)


@dataclass(frozen=True)
class FleetConfig:
    host: str
    nodes: tuple[NodeConfig, ...]
    replay_batch_size: int = 20
    reconnect_min_delay_s: float = 2.0
    reconnect_max_delay_s: float = 60.0

    @classmethod
    def from_env(cls, token_overrides: Optional[dict[str, str]] = None) -> "FleetConfig":
        load_dotenv()
        host = os.environ.get("TB_HOST", "")
        if not host:
            raise ConfigurationError("TB_HOST is required for the fleet")
        overrides = token_overrides or {}
        nodes = []
        for spec in DEFAULT_NODE_SPECS:
            lat = float(os.environ.get(f"{spec.node_id.upper().replace('-', '_')}_LAT", spec.latitude))
            lon = float(os.environ.get(f"{spec.node_id.upper().replace('-', '_')}_LON", spec.longitude))
            nodes.append(NodeConfig(
                node_id=spec.node_id,
                device_name=spec.device_name,
                token_env_var=spec.token_env_var,
                latitude=lat,
                longitude=lon,
                seed=spec.seed,
                db_path=spec.db_path,
                token=overrides.get(spec.node_id),
            ))
        return cls(
            host=host,
            nodes=tuple(nodes),
            replay_batch_size=int(os.environ.get("MQTT_REPLAY_BATCH_SIZE", "20")),
            reconnect_min_delay_s=float(os.environ.get("MQTT_RECONNECT_MIN_DELAY_S", "2")),
            reconnect_max_delay_s=float(os.environ.get("MQTT_RECONNECT_MAX_DELAY_S", "60")),
        )


@dataclass
class FleetNode:
    config: NodeConfig
    generator: TelemetryGenerator
    store: TelemetryStore
    transport: MqttTransport
    node: VirtualEdgeNode
    simulator: EdgeSimulator


class Fleet:
    """Builds and owns three fully independent edge nodes."""

    def __init__(
        self,
        config: FleetConfig,
        client_factories: Optional[dict[str, Callable]] = None,
    ) -> None:
        self.config = config
        self.evaluator = AlarmEvaluator()
        self.nodes: list[FleetNode] = []
        factories = client_factories or {}

        for nc in config.nodes:
            generator = TelemetryGenerator(GeneratorConfig(
                node_id=nc.node_id,
                seed=nc.seed,
                latitude=nc.latitude,
                longitude=nc.longitude,
            ))
            store = TelemetryStore(StoreConfig(db_path=nc.db_path))
            mqtt_config = MqttConfig(
                host=config.host,
                token=nc.resolve_token(),
                client_id=f"jalsanket-{nc.node_id}",
                replay_batch_size=config.replay_batch_size,
                reconnect_min_delay_s=config.reconnect_min_delay_s,
                reconnect_max_delay_s=config.reconnect_max_delay_s,
            )
            factory = factories.get(nc.node_id)

            def handle_command(method: str, params: dict, gen: TelemetryGenerator = generator) -> dict:
                """Remote scenario control - commands only, never fake readings."""
                if method == "trigger_contamination":
                    gen.trigger_contamination()
                    return {"ok": True, "method": method}
                if method == "set_supply_interrupted":
                    gen.set_supply_interrupted(bool(params.get("interrupted", True)))
                    return {"ok": True, "method": method}
                if method == "reset":
                    gen.reset()
                    return {"ok": True, "method": method}
                return {"ok": False, "error": f"unknown method: {method}"}

            transport = MqttTransport(
                mqtt_config, store, nc.node_id,
                client_factory=factory, command_handler=handle_command,
            )
            node = VirtualEdgeNode(generator, store)
            evaluator = self.evaluator
            simulator = EdgeSimulator(
                node,
                transport,
                on_tick=lambda _count, result, ev=evaluator: ev.evaluate(result.reading),
            )
            self.nodes.append(FleetNode(nc, generator, store, transport, node, simulator))

    def by_id(self, node_id: str) -> FleetNode:
        for fleet_node in self.nodes:
            if fleet_node.config.node_id == node_id:
                return fleet_node
        raise KeyError(node_id)

    def status(self) -> list[dict]:
        return [
            {
                **fn.simulator.node.status(),
                "deviceName": fn.config.device_name,
                "latitude": fn.config.latitude,
                "longitude": fn.config.longitude,
                "connected": fn.transport.is_connected,
                "safetyStatus": self.evaluator.safety_status(fn.config.node_id),
                "activeAlarms": self.evaluator.active_alarms(fn.config.node_id),
            }
            for fn in self.nodes
        ]

    def shutdown(self) -> None:
        """Drain in-flight QoS 1 publishes before any client is disconnected."""
        for fn in self.nodes:
            fn.transport.shutdown()

    def close(self) -> None:
        self.shutdown()
        for fn in self.nodes:
            fn.store.close()


class FleetRunner:
    """Steps all three nodes in one loop and checks inactivity alarms."""

    def __init__(self, fleet: Fleet, loop_sleep_s: float = 0.02) -> None:
        self.fleet = fleet
        self.loop_sleep_s = loop_sleep_s
        self._stop = False
        self._published_status: dict[str, str] = {}

    def start(self) -> None:
        for fn in self.fleet.nodes:
            fn.simulator.start()

    def step(self, now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else now
        for fn in self.fleet.nodes:
            fn.simulator.step(current)
        now_ms = int(time.time() * 1000)
        for fn in self.fleet.nodes:
            for event in self.fleet.evaluator.check_inactivity(fn.config.node_id, now_ms):
                logger.warning("INACTIVITY ALARM %s", event.to_dict())
            status = self.fleet.evaluator.safety_status(fn.config.node_id)
            if self._published_status.get(fn.config.node_id) != status:
                published = fn.transport.publish_attributes({
                    "safetyStatus": status,
                    "deviceName": fn.config.device_name,
                })
                if published:
                    self._published_status[fn.config.node_id] = status

    def run(self, duration_s: Optional[float] = None) -> None:
        self.start()
        started = time.monotonic()
        logger.info("FLEET STARTED nodes=%d", len(self.fleet.nodes))
        try:
            while not self._stop:
                now = time.monotonic()
                if duration_s is not None and now - started >= duration_s:
                    break
                self.step(now)
                time.sleep(self.loop_sleep_s)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received - stopping fleet")
        finally:
            # No more ticks run here: drain confirmations/replay first so the
            # final status reflects the real SQLite state after a clean stop.
            self.fleet.shutdown()
            logger.info("FLEET STOPPED status=%s", self.fleet.status())
            self.fleet.close()

    def stop(self) -> None:
        self._stop = True
