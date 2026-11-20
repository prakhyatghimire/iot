"""Local alarm evaluator with the exact assignment thresholds and hysteresis.

This is the reference implementation used for automated verification. The
Cloud Alarm Rules 2.0 definitions generated in ``alarm_rules.py`` mirror these
same conditions, and live alarm behaviour is verified against ThingsBoard
Cloud.

Hysteresis rule: an alarm stays active after it triggers until its own, wider
clear condition is met. A warning therefore does not flicker when a value
merely dips just below its trigger threshold.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from .telemetry import Reading

# Exact thresholds from the assignment brief. Do not change these values.
HIGH_TURBIDITY_TRIGGER = 50.0
HIGH_TURBIDITY_CLEAR = 40.0
GROSS_CONTAMINATION_TRIGGER = 200.0
GROSS_CONTAMINATION_CLEAR = 150.0
PH_LOW_TRIGGER = 6.5
PH_HIGH_TRIGGER = 8.5
PH_LOW_CLEAR = 6.7
PH_HIGH_CLEAR = 8.3
HIGH_TDS_TRIGGER = 500.0
HIGH_TDS_CLEAR = 450.0
INTERRUPTION_SUSTAINED_S = 30.0
INACTIVITY_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class AlarmEvent:
    node_id: str
    alarm_type: str
    severity: str
    action: str  # "ACTIVATED" or "CLEARED"
    value: float
    timestamp_ms: int

    def to_dict(self) -> dict:
        return {
            "nodeId": self.node_id,
            "alarmType": self.alarm_type,
            "severity": self.severity,
            "action": self.action,
            "value": self.value,
            "timestampMs": self.timestamp_ms,
        }


@dataclass(frozen=True)
class AlarmDefinition:
    alarm_type: str
    severity: str
    trigger: str
    clear: str


ALARM_DEFINITIONS: tuple[AlarmDefinition, ...] = (
    AlarmDefinition(
        "High Turbidity Warning",
        "WARNING",
        "turbidity_ntu > 50",
        "turbidity_ntu < 40",
    ),
    AlarmDefinition(
        "Gross Contamination Critical",
        "CRITICAL",
        "turbidity_ntu > 200",
        "turbidity_ntu < 150",
    ),
    AlarmDefinition(
        "pH Out of Range Critical",
        "CRITICAL",
        "ph < 6.5 OR ph > 8.5",
        "6.7 <= ph <= 8.3",
    ),
    AlarmDefinition(
        "High TDS Critical",
        "CRITICAL",
        "tds_ppm > 500",
        "tds_ppm < 450",
    ),
    AlarmDefinition(
        "Supply Interruption Major",
        "MAJOR",
        "flow_lpm == 0 sustained for 30 s",
        "flow_lpm > 0",
    ),
    AlarmDefinition(
        "Node Inactive Critical",
        "CRITICAL",
        "no telemetry for 60 s",
        "telemetry resumes",
    ),
)


class AlarmEvaluator:
    """Stateful per-node evaluator with hysteresis and sustained conditions."""

    def __init__(
        self,
        sample_interval_s: float = 2.0,
        inactivity_timeout_s: float = INACTIVITY_TIMEOUT_S,
        interruption_sustained_s: float = INTERRUPTION_SUSTAINED_S,
    ) -> None:
        self.sample_interval_s = sample_interval_s
        self.inactivity_timeout_s = inactivity_timeout_s
        self.interruption_sustained_s = interruption_sustained_s
        self.required_zero_samples = max(1, math.ceil(interruption_sustained_s / sample_interval_s))
        self._active: dict[str, set[str]] = {}
        self._zero_samples: dict[str, int] = {}
        self._last_telemetry_ms: dict[str, int] = {}

    # ------------------------------------------------------------------ state
    def _active_set(self, node_id: str) -> set[str]:
        return self._active.setdefault(node_id, set())

    def active_alarms(self, node_id: str) -> list[dict]:
        active = self._active_set(node_id)
        return [
            {"alarmType": d.alarm_type, "severity": d.severity}
            for d in ALARM_DEFINITIONS
            if d.alarm_type in active
        ]

    def safety_status(self, node_id: str) -> str:
        """Answer the duty officer's question for one source."""
        active = self._active_set(node_id)
        severities = {d.severity for d in ALARM_DEFINITIONS if d.alarm_type in active}
        if severities & {"CRITICAL", "MAJOR"}:
            return "UNSAFE"
        if "WARNING" in severities:
            return "WARNING"
        return "SAFE"

    def fleet_status(self) -> list[dict]:
        return [
            {
                "nodeId": node_id,
                "safetyStatus": self.safety_status(node_id),
                "activeAlarms": self.active_alarms(node_id),
                "lastTelemetryMs": self._last_telemetry_ms.get(node_id),
            }
            for node_id in sorted(self._active)
        ]

    # -------------------------------------------------------------- transition
    def _transition(
        self,
        node_id: str,
        alarm_type: str,
        severity: str,
        triggered: bool,
        cleared: bool,
        value: float,
        now_ms: int,
        events: list[AlarmEvent],
    ) -> None:
        active = self._active_set(node_id)
        if alarm_type not in active and triggered:
            active.add(alarm_type)
            events.append(AlarmEvent(node_id, alarm_type, severity, "ACTIVATED", value, now_ms))
        elif alarm_type in active and cleared:
            active.discard(alarm_type)
            events.append(AlarmEvent(node_id, alarm_type, severity, "CLEARED", value, now_ms))

    # --------------------------------------------------------------- evaluation
    def evaluate(self, reading: Reading, now_ms: Optional[int] = None) -> list[AlarmEvent]:
        """Evaluate one reading; returns only transitions, not steady state."""
        node_id = reading.node_id
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        self._last_telemetry_ms[node_id] = now
        events: list[AlarmEvent] = []

        self._transition(
            node_id, "High Turbidity Warning", "WARNING",
            reading.turbidity_ntu > HIGH_TURBIDITY_TRIGGER,
            reading.turbidity_ntu < HIGH_TURBIDITY_CLEAR,
            reading.turbidity_ntu, now, events,
        )
        self._transition(
            node_id, "Gross Contamination Critical", "CRITICAL",
            reading.turbidity_ntu > GROSS_CONTAMINATION_TRIGGER,
            reading.turbidity_ntu < GROSS_CONTAMINATION_CLEAR,
            reading.turbidity_ntu, now, events,
        )
        self._transition(
            node_id, "pH Out of Range Critical", "CRITICAL",
            reading.ph < PH_LOW_TRIGGER or reading.ph > PH_HIGH_TRIGGER,
            PH_LOW_CLEAR <= reading.ph <= PH_HIGH_CLEAR,
            reading.ph, now, events,
        )
        self._transition(
            node_id, "High TDS Critical", "CRITICAL",
            reading.tds_ppm > HIGH_TDS_TRIGGER,
            reading.tds_ppm < HIGH_TDS_CLEAR,
            reading.tds_ppm, now, events,
        )

        # Supply interruption requires sustained zero flow, not one sample.
        if reading.flow_lpm == 0.0:
            self._zero_samples[node_id] = self._zero_samples.get(node_id, 0) + 1
        else:
            self._zero_samples[node_id] = 0
        self._transition(
            node_id, "Supply Interruption Major", "MAJOR",
            self._zero_samples[node_id] >= self.required_zero_samples,
            reading.flow_lpm > 0.0,
            reading.flow_lpm, now, events,
        )

        # Telemetry resuming clears the inactivity alarm immediately.
        self._transition(
            node_id, "Node Inactive Critical", "CRITICAL",
            False, True, 0.0, now, events,
        )
        return events

    def check_inactivity(self, node_id: str, now_ms: Optional[int] = None) -> list[AlarmEvent]:
        """Call periodically even when no telemetry arrives (network outage)."""
        last = self._last_telemetry_ms.get(node_id)
        if last is None:
            return []
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        events: list[AlarmEvent] = []
        elapsed_s = (now - last) / 1000.0
        self._transition(
            node_id, "Node Inactive Critical", "CRITICAL",
            elapsed_s > self.inactivity_timeout_s,
            False, elapsed_s, now, events,
        )
        return events
