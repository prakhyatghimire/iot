"""Alarm artifacts generated from the exact brief thresholds.

Two local artifacts are retained for the CE-style regression suite:

* ``device_profile_alarm_config()`` - CE device-profile alarm rules with a
  ``time`` (duration) field for 30 s of zero flow and 60 s inactivity.
* ``rule_chain_document()`` - an importable rule chain with a trigger and a
  clear filter per alarm. Clear conditions are deliberately wider than trigger
  conditions, giving hysteresis and preventing alarm flapping.

``cloud_alarm_rules()`` emits the ThingsBoard Cloud Alarm Rules 2.0 payloads
that were applied to the JalSanket device profile. Local behaviour is verified
with ``AlarmEvaluator`` in ``alarms.py``; no live instance is contacted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .alarms import (
    GROSS_CONTAMINATION_CLEAR,
    GROSS_CONTAMINATION_TRIGGER,
    HIGH_TDS_CLEAR,
    HIGH_TDS_TRIGGER,
    HIGH_TURBIDITY_CLEAR,
    HIGH_TURBIDITY_TRIGGER,
    INTERRUPTION_SUSTAINED_S,
    INACTIVITY_TIMEOUT_S,
    PH_HIGH_CLEAR,
    PH_HIGH_TRIGGER,
    PH_LOW_CLEAR,
    PH_LOW_TRIGGER,
)


@dataclass(frozen=True)
class RuleSpec:
    alarm_type: str
    severity: str
    trigger_script: str
    clear_script: str
    duration_ms: int = 0


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


RULE_SPECS: tuple[RuleSpec, ...] = (
    RuleSpec(
        "High Turbidity Warning",
        "WARNING",
        f"return msg.turbidity_ntu !== undefined && msg.turbidity_ntu > {_num(HIGH_TURBIDITY_TRIGGER)};",
        f"return msg.turbidity_ntu !== undefined && msg.turbidity_ntu < {_num(HIGH_TURBIDITY_CLEAR)};",
    ),
    RuleSpec(
        "Gross Contamination Critical",
        "CRITICAL",
        f"return msg.turbidity_ntu !== undefined && msg.turbidity_ntu > {_num(GROSS_CONTAMINATION_TRIGGER)};",
        f"return msg.turbidity_ntu !== undefined && msg.turbidity_ntu < {_num(GROSS_CONTAMINATION_CLEAR)};",
    ),
    RuleSpec(
        "pH Out of Range Critical",
        "CRITICAL",
        "return msg.ph !== undefined && "
        f"(msg.ph < {_num(PH_LOW_TRIGGER)} || msg.ph > {_num(PH_HIGH_TRIGGER)});",
        "return msg.ph !== undefined && "
        f"(msg.ph >= {_num(PH_LOW_CLEAR)} && msg.ph <= {_num(PH_HIGH_CLEAR)});",
    ),
    RuleSpec(
        "High TDS Critical",
        "CRITICAL",
        f"return msg.tds_ppm !== undefined && msg.tds_ppm > {_num(HIGH_TDS_TRIGGER)};",
        f"return msg.tds_ppm !== undefined && msg.tds_ppm < {_num(HIGH_TDS_CLEAR)};",
    ),
    RuleSpec(
        "Supply Interruption Major",
        "MAJOR",
        "return msg.flow_lpm !== undefined && msg.flow_lpm === 0;",
        "return msg.flow_lpm !== undefined && msg.flow_lpm > 0;",
        duration_ms=int(INTERRUPTION_SUSTAINED_S * 1000),
    ),
    RuleSpec(
        "Node Inactive Critical",
        "CRITICAL",
        "return metadata.inactive === true;",
        "return metadata.inactive === false;",
        duration_ms=int(INACTIVITY_TIMEOUT_S * 1000),
    ),
)

FILTER_NODE_TYPE = "org.thingsboard.rule.engine.filter.TbJsFilterNode"
CREATE_ALARM_NODE_TYPE = "org.thingsboard.rule.engine.action.TbCreateAlarmNode"
CLEAR_ALARM_NODE_TYPE = "org.thingsboard.rule.engine.action.TbClearAlarmNode"


def device_profile_alarm_config() -> dict:
    """CE device-profile alarm config with durations and hysteresis."""
    rules = []
    for spec in RULE_SPECS:
        rule: dict = {
            "alarmType": spec.alarm_type,
            "severity": spec.severity,
            "condition": {
                "type": "SCRIPT",
                "script": spec.trigger_script,
            },
            "clearCondition": {
                "type": "SCRIPT",
                "script": spec.clear_script,
            },
            "propagate": False,
        }
        if spec.duration_ms:
            rule["time"] = spec.duration_ms
        rules.append(rule)
    return {"rules": rules}


def rule_chain_document() -> dict:
    """Importable CE rule chain with trigger/clear filters per alarm."""
    nodes: list[dict] = []
    index = 0
    for spec in RULE_SPECS:
        trigger_index = index
        create_index = index + 1
        clear_index = index + 2
        clear_filter_index = index + 3

        nodes.append({
            "index": trigger_index,
            "type": FILTER_NODE_TYPE,
            "name": f"{spec.alarm_type} - TRIGGER",
            "configuration": {"jsScript": spec.trigger_script},
            "connections": {"True": [create_index], "False": []},
            "x": 100 + index * 40,
            "y": 100,
        })
        nodes.append({
            "index": create_index,
            "type": CREATE_ALARM_NODE_TYPE,
            "name": f"Create {spec.alarm_type}",
            "configuration": {
                "alarmType": spec.alarm_type,
                "alarmSeverity": spec.severity,
                "checkExistingAlarm": True,
                "propagate": False,
            },
            "connections": {},
            "x": 300 + index * 40,
            "y": 100,
        })
        nodes.append({
            "index": clear_filter_index,
            "type": FILTER_NODE_TYPE,
            "name": f"{spec.alarm_type} - CLEAR",
            "configuration": {"jsScript": spec.clear_script},
            "connections": {"True": [clear_index], "False": []},
            "x": 100 + index * 40,
            "y": 300,
        })
        nodes.append({
            "index": clear_index,
            "type": CLEAR_ALARM_NODE_TYPE,
            "name": f"Clear {spec.alarm_type}",
            "configuration": {"alarmType": spec.alarm_type, "propagate": False},
            "connections": {},
            "x": 300 + index * 40,
            "y": 300,
        })
        index += 4

    return {
        "ruleChain": {
            "name": "JalSanket Water Quality Alarms",
            "type": "CORE",
            "description": "Assignment thresholds with hysteresis; 30 s flow and 60 s inactivity durations",
            "debugMode": False,
        },
        "metadata": {
            "firstNodeIndex": 0,
            "nodes": nodes,
            "connections": [],
            "ruleChainConnections": [],
        },
    }


def _cloud_argument(name: str, ref_key: Optional[str] = None,
                    argument_type: str = "TS_LATEST",
                    scope: Optional[str] = None) -> dict:
    ref_entity_key = {"key": ref_key or name, "type": argument_type}
    if scope:
        ref_entity_key["scope"] = scope
    return {"refEntityKey": ref_entity_key, "defaultValue": ""}


def _simple_condition(expression: str) -> dict:
    return {
        "type": "SIMPLE",
        "expression": {"type": "TBEL", "expression": expression},
        "schedule": None,
    }


def _duration_condition(expression: str, seconds: int) -> dict:
    return {
        "type": "DURATION",
        "expression": {"type": "TBEL", "expression": expression},
        "value": {"staticValue": seconds},
        "unit": "SECONDS",
        "schedule": None,
    }


def cloud_alarm_rules(profile_id: str) -> list[dict]:
    """Six Alarm Rules 2.0 definitions bound to a Cloud device profile.

    The trigger/clear expressions use the same constants as
    ``AlarmEvaluator``; ``Supply Interruption Major`` additionally uses a
    Cloud DURATION condition for the exact 30 s sustained-zero-flow rule.
    ``Node Inactive Critical`` reads the Device State service ``active``
    server attribute; the 60 s timeout itself is the per-device
    ``inactivityTimeout`` server attribute.
    """
    if not profile_id:
        raise ValueError("profile_id is required for Cloud alarm rules")

    definitions = (
        ("High Turbidity Warning", "WARNING", "turbidity",
         _cloud_argument("turbidity", "turbidity_ntu"),
         f"return turbidity > {_num(HIGH_TURBIDITY_TRIGGER)};",
         f"return turbidity < {_num(HIGH_TURBIDITY_CLEAR)};",
         None),
        ("Gross Contamination Critical", "CRITICAL", "turbidity",
         _cloud_argument("turbidity", "turbidity_ntu"),
         f"return turbidity > {_num(GROSS_CONTAMINATION_TRIGGER)};",
         f"return turbidity < {_num(GROSS_CONTAMINATION_CLEAR)};",
         None),
        ("pH Out of Range Critical", "CRITICAL", "ph",
         _cloud_argument("ph"),
         f"return ph < {_num(PH_LOW_TRIGGER)} || ph > {_num(PH_HIGH_TRIGGER)};",
         f"return ph >= {_num(PH_LOW_CLEAR)} && ph <= {_num(PH_HIGH_CLEAR)};",
         None),
        ("High TDS Critical", "CRITICAL", "tds",
         _cloud_argument("tds", "tds_ppm"),
         f"return tds > {_num(HIGH_TDS_TRIGGER)};",
         f"return tds < {_num(HIGH_TDS_CLEAR)};",
         None),
        ("Supply Interruption Major", "MAJOR", "flow",
         _cloud_argument("flow", "flow_lpm"),
         "return flow === 0;",
         "return flow > 0;",
         int(INTERRUPTION_SUSTAINED_S)),
        ("Node Inactive Critical", "CRITICAL", "active",
         _cloud_argument("active", argument_type="ATTRIBUTE", scope="SERVER_SCOPE"),
         "return active == false;",
         "return active == true;",
         None),
    )

    rules: list[dict] = []
    for name, severity, argument_name, argument, create_expression, clear_expression, duration_s in definitions:
        create = (_simple_condition(create_expression) if duration_s is None
                  else _duration_condition(create_expression, duration_s))
        rules.append({
            "name": name,
            "type": "ALARM",
            "configurationVersion": 0,
            "debugSettings": {
                "failuresEnabled": True,
                "allEnabled": False,
                "allEnabledUntil": 0,
            },
            "entityId": {"entityType": "DEVICE_PROFILE", "id": profile_id},
            "configuration": {
                "type": "ALARM",
                "arguments": {argument_name: argument},
                "createRules": {
                    severity: {
                        "condition": create,
                        "alarmDetails": None,
                        "dashboardId": None,
                    }
                },
                "clearRule": {
                    "condition": _simple_condition(clear_expression),
                    "alarmDetails": None,
                    "dashboardId": None,
                },
                "propagate": False,
                "propagateToOwner": False,
                "propagateToOwnerHierarchy": False,
                "propagateToTenant": False,
                "propagateRelationTypes": None,
                "output": None,
            },
        })
    return rules
