"""JalSanket virtual ESP32-S3 edge node.

Phase 1: telemetry generator.
Phase 2: SQLite store-and-forward buffer.

Later phases add MQTT/TLS transport, multi-node operation and measurement
logging.
"""

from .alarms import ALARM_DEFINITIONS, AlarmEvaluator, AlarmEvent
from .config import ConfigurationError, MqttConfig, RestConfig, load_dotenv
from .fleet import Fleet, FleetConfig, FleetNode, FleetRunner, NodeConfig
from .node import TickResult, VirtualEdgeNode
from .storage import (
    InsertOutcome,
    StoreConfig,
    StoredReading,
    TelemetryStore,
)
from .telemetry import GeneratorConfig, Reading, TelemetryGenerator

__all__ = [
    "AlarmEvaluator",
    "AlarmEvent",
    "ALARM_DEFINITIONS",
    "ConfigurationError",
    "MqttConfig",
    "RestConfig",
    "load_dotenv",
    "Fleet",
    "FleetConfig",
    "FleetNode",
    "FleetRunner",
    "NodeConfig",
    "GeneratorConfig",
    "Reading",
    "TelemetryGenerator",
    "StoreConfig",
    "InsertOutcome",
    "StoredReading",
    "TelemetryStore",
    "TickResult",
    "VirtualEdgeNode",
]
