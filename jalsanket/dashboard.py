"""Dashboard definitions for the municipal duty officer.

``build_dashboard()`` keeps the original CE-shaped artifact used by the local
regression suite. ``build_cloud_dashboard()`` emits the ThingsBoard Cloud
dashboard with a demonstration information hierarchy: owner → area → water
source → JalSanket node → measurements/alarms. Both answer the same question:
"Which water source is unsafe right now?" Every Cloud widget is bound to the
existing fleet alias and reads existing telemetry/attributes only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .alarm_rules import device_profile_alarm_config, rule_chain_document
from .alarms import (
    GROSS_CONTAMINATION_CLEAR,
    GROSS_CONTAMINATION_TRIGGER,
    HIGH_TDS_CLEAR,
    HIGH_TDS_TRIGGER,
    HIGH_TURBIDITY_CLEAR,
    HIGH_TURBIDITY_TRIGGER,
    PH_HIGH_CLEAR,
    PH_HIGH_TRIGGER,
    PH_LOW_CLEAR,
    PH_LOW_TRIGGER,
)
from .fleet import DEFAULT_NODE_SPECS, FleetConfig
from .provisioning import TELEMETRY_KEYS, device_document

DASHBOARD_TITLE = "JalSanket Water Safety — Rasuwa Monitoring Area"
DEMO_CONTROLS_TITLE = "JalSanket - Demo Controls"
FLEET_ALIAS = "fleet"

# Demonstration-only organizational model. These strings describe the intended
# information hierarchy; they do not claim real municipal ownership or a real
# sensor deployment. No Cloud Customer/Asset entities are created.
HIERARCHY_OWNER = "Municipal Water Monitoring Authority"
HIERARCHY_AREA = "Rasuwa Monitoring Area"
HIERARCHY_NOTE = "Demonstration hierarchy — no real municipal ownership or sensor deployment is claimed."
HIERARCHY_CHAIN = (
    f"{HIERARCHY_OWNER} → {HIERARCHY_AREA} → water source / location → "
    "JalSanket IoT node → sensors / telemetry → alarms / events."
)

# Duty-officer labels for the three existing devices. These are presentation
# names only: device names, IDs, tokens and telemetry keys are never changed.
NODE_LOCATIONS: dict[str, str] = {
    "node-01": "Dhunche",
    "node-02": "Syafrubesi",
    "node-03": "Rasuwagadhi",
}

# Live tenant dashboard IDs used by the cross-dashboard navigation buttons.
MONITORING_DASHBOARD_ID = "8626a700-e451-11f1-8c2a-39d8a38c3af6"
DEMO_CONTROLS_DASHBOARD_ID = "19cf5c70-e69d-11f1-855e-4d781d6baffc"


def _data_keys(names: tuple[str, ...] | list[str], key_type: str = "timeseries") -> list[dict]:
    return [
        {"name": name, "type": key_type, "label": f"{name} - ${{deviceName}}"}
        for name in names
    ]


def _widget(
    title: str,
    widget_type: str,
    data_keys: list[dict],
    widget_config: dict,
    data_type: str = "timeseries",
    alarm_source: bool = False,
) -> dict:
    datasource: dict = {
        "type": "entity",
        "entityAliasId": FLEET_ALIAS,
        "dataKeys": data_keys,
    }
    if alarm_source:
        datasource = {"type": "entity", "entityAliasId": FLEET_ALIAS, "dataKeys": []}
    return {
        "type": data_type,
        "title": title,
        "widget": {"type": widget_type, "config": widget_config},
        "datasources": [datasource],
    }


def build_dashboard() -> dict:
    widget_configs: dict[str, dict] = {}
    grid: list[dict] = []

    def add(widget_id: str, x: int, y: int, w: int, h: int, config: dict) -> None:
        widget_configs[widget_id] = config
        grid.append({"x": x, "y": y, "w": w, "h": h, "content": widget_id})

    add("summary", 0, 0, 12, 2, {
        "type": "static",
        "title": "Which water source is unsafe right now?",
        "widget": {
            "type": "Markdown",
            "config": {
                "md": (
                    "**Read the Fleet Health table below.** A source marked `UNSAFE` has an "
                    "active CRITICAL or MAJOR alarm; `WARNING` means the High Turbidity "
                    "Warning is active. Use the gauges and time series to confirm the cause."
                )
            },
        },
        "datasources": [],
    })
    add("fleet_health", 0, 2, 12, 4, _widget(
        "Fleet Health / Safety Status",
        "Entities Table",
        _data_keys(("safetyStatus", "deviceName", "bufferDepth"), "attribute"),
        {"showHeader": True, "enableSelection": False},
        data_type="latest",
    ))
    add("ph_gauge", 0, 6, 4, 5, _widget(
        "pH (Node-01)",
        "Analog Gauge",
        _data_keys(("ph",)),
        {"minValue": 0, "maxValue": 14, "units": "pH", "decimals": 2},
        data_type="latest",
    ))
    add("turbidity_gauge", 4, 6, 4, 5, _widget(
        "Turbidity (Node-01)",
        "Analog Gauge",
        _data_keys(("turbidity_ntu",)),
        {"minValue": 0, "maxValue": 300, "units": "NTU", "decimals": 1},
        data_type="latest",
    ))
    add("tds_gauge", 8, 6, 4, 5, _widget(
        "TDS (Node-01)",
        "Digital Gauge",
        _data_keys(("tds_ppm",)),
        {"units": "ppm", "decimals": 1},
        data_type="latest",
    ))
    add("multi_series", 0, 11, 12, 6, _widget(
        "Turbidity / pH / TDS time series",
        "Timeseries Chart",
        _data_keys(("turbidity_ntu", "ph", "tds_ppm")),
        {"showLegend": True, "yAxisTitle": "value", "stacked": False},
    ))
    add("temp_flow", 0, 17, 12, 5, _widget(
        "Water temperature and flow",
        "Timeseries Chart",
        _data_keys(("water_temp_c", "flow_lpm")),
        {"showLegend": True, "yAxisTitle": "C / L/min", "stacked": False},
    ))
    add("node_map", 0, 22, 8, 7, _widget(
        "Source locations (OpenStreetMap)",
        "OpenStreetMap",
        _data_keys(("latitude", "longitude")),
        {"mapProvider": "OpenStreetMap", "defaultZoomLevel": 11, "showMarkers": True},
        data_type="latest",
    ))
    add("alarms", 8, 22, 4, 7, _widget(
        "Active alarms",
        "Alarms Table",
        [],
        {"showSearch": True, "alarmsPollingInterval": 5000},
        data_type="alarm",
        alarm_source=True,
    ))

    return {
        "title": DASHBOARD_TITLE,
        "configuration": {
            "description": (
                "Municipal water-safety overview for three JalSanket virtual nodes. "
                "Telemetry keys: " + ", ".join(TELEMETRY_KEYS) + "."
            ),
            "entityAliases": {
                FLEET_ALIAS: {
                    "id": FLEET_ALIAS,
                    "alias": "JalSanket Fleet",
                    "type": "ENTITY_LIST",
                    "filter": {"type": "DEVICE_TYPE", "value": "JalSanket Virtual Sensor"},
                }
            },
            "widgets": {"grid": grid},
            "widgetConfigs": widget_configs,
        },
    }


RPC_BUTTON_FQN: tuple[str, str] = ("control_widgets.rpcbutton", "rpc")

# Live demo controls. Each ThingsBoard RPC Button targets exactly one device,
# so every command is emitted once per node rather than injecting readings.
RPC_BUTTON_COMMANDS: tuple[tuple[str, str, str, str], ...] = (
    ("Flood Contamination", "Trigger Contamination", "trigger_contamination", "{}"),
    ("Supply Interruption ON", "Supply Interruption ON", "set_supply_interrupted",
     '{"interrupted": true}'),
    ("Supply Interruption OFF", "Supply Interruption OFF", "set_supply_interrupted",
     '{"interrupted": false}'),
    ("Reset", "Reset", "reset", "{}"),
)

# Consistent action colors across all three nodes in the demo-controls dashboard.
RPC_BUTTON_COLORS: tuple[str, ...] = ("#d32f2f", "#f57c00", "#1976d2", "#616161")

# Incident Mode is presentation-only. It reads the same device attributes and
# telemetry keys as the existing status cards and uses the existing alarm
# thresholds, including their clear bands, solely to explain which measurements
# are outside their safe range. It never creates, clears, acknowledges or
# redefines a ThingsBoard alarm.
INCIDENT_THRESHOLDS = {
    "phLow": PH_LOW_TRIGGER,
    "phHigh": PH_HIGH_TRIGGER,
    "phLowClear": PH_LOW_CLEAR,
    "phHighClear": PH_HIGH_CLEAR,
    "turbidityWarning": HIGH_TURBIDITY_TRIGGER,
    "turbidityClear": HIGH_TURBIDITY_CLEAR,
    "turbidityCritical": GROSS_CONTAMINATION_TRIGGER,
    "grossClear": GROSS_CONTAMINATION_CLEAR,
    "tdsCritical": HIGH_TDS_TRIGGER,
    "tdsClear": HIGH_TDS_CLEAR,
}
INCIDENT_THRESHOLDS_JS = "const T = " + json.dumps(INCIDENT_THRESHOLDS) + ";\n"

CLOUD_WIDGET_FQNS: dict[str, tuple[str, str]] = {
    "system_status": ("cards.markdown_card", "latest"),
    "node_status": ("cards.markdown_card", "latest"),
    "measurements_header": ("cards.markdown_card", "latest"),
    "ph_gauge": ("digital_gauges.gauge_justgage", "latest"),
    "turbidity_gauge": ("digital_gauges.gauge_justgage", "latest"),
    "tds_gauge": ("digital_gauges.gauge_justgage", "latest"),
    "turbidity_series": ("time_series_chart", "timeseries"),
    "ph_series": ("time_series_chart", "timeseries"),
    "tds_series": ("time_series_chart", "timeseries"),
    "temp_flow": ("time_series_chart", "timeseries"),
    "node_map": ("maps_v2.openstreetmap", "latest"),
    "active_alerts": ("alarm_widgets.alarms_table", "alarm"),
}

# A markdown card receives one row per resolved fleet device. ThingsBoard
# exposes each value under its configured label ("Connectivity", "Water
# status", ...), not the raw attribute name, so the helper below accepts both.
# Status labels are derived from existing safetyStatus, active and measurement
# values. A stale safetyStatus is never promoted to an incident without current
# measurements that still fall inside the existing alarm hysteresis band.
_STATUS_COMMON_JS = r"""
const places = {"JalSanket-Node-01": "Dhunche", "JalSanket-Node-02": "Syafrubesi", "JalSanket-Node-03": "Rasuwagadhi"};
const nodes = {"Dhunche": "JalSanket Node 01", "Syafrubesi": "JalSanket Node 02", "Rasuwagadhi": "JalSanket Node 03"};
const order = ["Dhunche", "Syafrubesi", "Rasuwagadhi"];
const val = function (d, label, name) {
  return d[label] !== undefined ? d[label] : d[name];
};
const numberOrNull = function (v) {
  const n = Number(v);
  return isFinite(n) ? n : null;
};
const evidenceFor = function (ph, turbidity, tds, flow) {
  return {
    gross: turbidity !== null && turbidity > T.grossClear,
    tdsHigh: tds !== null && tds > T.tdsClear,
    phBad: ph !== null && (ph < T.phLowClear || ph > T.phHighClear),
    warningTurbidity: turbidity !== null && turbidity > T.turbidityClear,
    interrupted: flow === 0
  };
};
const statusFor = function (active, safety, evidence) {
  if (!active) return "OFFLINE";
  const critical = evidence.gross || evidence.tdsHigh || evidence.phBad || evidence.interrupted;
  if (safety === "UNSAFE" || safety === "CRITICAL") {
    return critical ? "CRITICAL" : "STALE";
  }
  if (safety === "WARNING") {
    if (critical) return "CRITICAL";
    return evidence.warningTurbidity ? "WARNING" : "STALE";
  }
  return "SAFE";
};
const rows = data.map(function (d) {
  const location = places[val(d, "Location", "deviceName") || d.entityName] || d.entityName || "Unknown location";
  const rawActive = val(d, "Connectivity", "active");
  const active = rawActive === true || String(rawActive).toLowerCase() === "true";
  const safety = String(val(d, "Water status", "safetyStatus") || "").toUpperCase();
  const ph = numberOrNull(val(d, "pH reading", "ph"));
  const turbidity = numberOrNull(val(d, "Turbidity reading", "turbidity_ntu"));
  const tds = numberOrNull(val(d, "TDS reading", "tds_ppm"));
  const flow = numberOrNull(val(d, "Flow", "flow_lpm"));
  const evidence = evidenceFor(ph, turbidity, tds, flow);
  return {location: location, node: nodes[location] || "JalSanket node",
          status: statusFor(active, safety, evidence), safety: safety, active: active,
          ph: ph, turbidity: turbidity, tds: tds, flow: flow, evidence: evidence};
}).sort(function (a, b) { return order.indexOf(a.location) - order.indexOf(b.location); });
const count = function (s) { return rows.filter(function (r) { return r.status === s; }).length; };
const critical = rows.filter(function (r) { return r.status === "CRITICAL"; });
const warning = rows.filter(function (r) { return r.status === "WARNING"; });
const stale = rows.filter(function (r) { return r.status === "STALE"; });
const offline = rows.filter(function (r) { return r.status === "OFFLINE"; });
const clsFor = function (s) {
  if (s === "CRITICAL") return "crit";
  if (s === "WARNING") return "warn";
  if (s === "OFFLINE") return "off";
  if (s === "STALE") return "stale";
  return "safe";
};
"""

_INCIDENT_STATUS_JS_BODY = r"""
const incidentRows = rows.map(function (r) {
  return {
    location: r.location, node: r.node, status: r.status, safety: r.safety,
    active: r.active, flow: r.flow, ph: r.ph, turbidity: r.turbidity,
    tds: r.tds, evidence: r.evidence
  };
});
const serious = incidentRows.filter(function (r) {
  return r.status === "CRITICAL" || r.status === "OFFLINE";
});
let incidentHtml = "";
if (serious.length) {
  const primary = serious[0];
  const flowNumber = Number(primary.flow);
  const flowText = isFinite(flowNumber) ? flowNumber.toFixed(1) + " L/min" : "no reading";
  const offline = primary.status === "OFFLINE";
  const interrupted = !offline && primary.active && flowNumber === 0;
  const severity = offline ? "CRITICAL" : interrupted ? "MAJOR" : "CRITICAL";
  const title = offline ? "NODE INACTIVE WATER SAFETY INCIDENT" :
    severity + " WATER SAFETY INCIDENT";
  const concerns = [];
  if (offline) {
    concerns.push("No recent data from the node");
  } else {
    const evidence = primary.evidence || {};
    if (evidence.gross) concerns.push("severe turbidity");
    else if (evidence.warningTurbidity) concerns.push("high turbidity");
    if (evidence.tdsHigh) concerns.push("high dissolved solids");
    if (evidence.phBad) concerns.push("pH outside safe range");
    if (evidence.interrupted) concerns.push("water supply interrupted");
  }
  const primaryConcern = concerns.length ? concerns[0] : "unsafe water status reported";
  const explanation = offline
    ? "No recent data is available from this node; water-quality values cannot be confirmed."
    : concerns.length > 1
      ? "Multiple water-quality thresholds are currently exceeded. Observed: " +
        concerns.join(", ") + "."
      : "Primary concern: " + primaryConcern + ".";
  const others = incidentRows.filter(function (r) {
    return r.location !== primary.location;
  }).map(function (r) {
    return r.location + " — " + r.status;
  }).join(" · ");
  const measurement = function (label, value, unit, state, digits) {
    const n = Number(value);
    const shown = isFinite(n) ? n.toFixed(digits) : "No reading";
    const cls = state === "CRITICAL" ? "crit" :
      state === "WARNING" || state === "ALARM BAND" ? "warn" :
      state === "SAFE" || state === "INTERRUPTED" ? "safe" : "off";
    return '<span class="js-incident-measure ' + cls + '">' + label + " " + shown +
      (unit ? " " + unit : "") + " · " + state + "</span>";
  };
  const bandState = function (value, highTrigger, clearThreshold, lowTrigger, lowClear) {
    const n = Number(value);
    if (!isFinite(n)) return "NO READING";
    if (lowTrigger !== undefined) {
      if (n < lowTrigger || n > highTrigger) return "CRITICAL";
      if (n < lowClear || n > clearThreshold) return "ALARM BAND";
      return "SAFE";
    }
    if (n > highTrigger) return "CRITICAL";
    if (n > clearThreshold) return "ALARM BAND";
    return "SAFE";
  };
  const readings = offline
    ? '<span class="js-incident-measure off">No current readings while the node has no recent data</span>'
    : measurement("Turbidity", primary.turbidity, "NTU",
                  bandState(primary.turbidity, T.turbidityCritical, T.grossClear), 1) +
      measurement("TDS", primary.tds, "ppm",
                  bandState(primary.tds, T.tdsCritical, T.tdsClear), 1) +
      measurement("pH", primary.ph, "",
                  bandState(primary.ph, T.phHigh, T.phHighClear, T.phLow, T.phLowClear), 2) +
      measurement("Flow", primary.flow, "L/min",
                  interrupted ? "INTERRUPTED" : "SAFE", 1);
  let situation = "Current values use the existing safe ranges shown by the gauges.";
  if (offline) {
    situation = "The node has no recent data. Check connectivity before relying on water-quality values.";
  } else if (interrupted) {
    situation = "Water supply is interrupted at this source; the node is connected. This is not a connection loss.";
  }
  let scenarioNote = "";
  const evidence = primary.evidence || {};
  if (!offline && (evidence.gross || evidence.warningTurbidity) &&
      (evidence.tdsHigh || evidence.phBad)) {
    scenarioNote = '<div class="js-incident-note">Simulated scenario note: this pattern is ' +
      'consistent with the scripted contamination demonstration. It does not identify a physical cause.</div>';
  }
  incidentHtml = '<div class="js-critical-alert js-incident" role="alert">' +
    '<div class="js-incident-kicker"><span class="js-critical-alert-title">CRITICAL ALERT</span> · ' +
    title + '</div>' +
    '<div class="js-incident-place">' + primary.location + ' Water Source · ' +
    primary.node + '</div>' +
    '<div class="js-incident-meta">' + severity + ' · CURRENT DASHBOARD TELEMETRY' +
    ' · detection time is shown in ACTIVE ALERTS below when an alarm is present</div>' +
    '<div class="js-incident-summary"><b>What happened:</b> ' + explanation + '</div>' +
    '<div class="js-incident-readings">' + readings + '</div>' +
    '<div class="js-incident-summary"><b>Current flow:</b> ' + flowText +
    ' · <b>Node:</b> ' + (primary.active ? "connected" : "no recent data") + '</div>' +
    '<div class="js-incident-note">' + situation + '</div>' +
    '<div class="js-incident-others"><b>Other sources:</b> ' + others + '</div>' +
    '<div class="js-incident-note">Progression: the trend charts below show actual measurement ' +
    'history. No timestamps or values are invented.</div>' + scenarioNote +
    '</div>';
}

let cls = "safe", level = "SAFE", headline = "No active water-safety incident";
let detail = "No active warning or critical condition is reported.";
if (critical.length) {
  cls = "crit"; level = "CRITICAL"; headline = "Immediate attention required";
  detail = critical.map(function (r) { return r.location; }).join(", ") +
    " has an unsafe water status. Incident details are shown in the fixed banner.";
} else if (warning.length) {
  cls = "warn"; level = "WARNING"; headline = "Attention required";
  detail = warning.map(function (r) { return r.location; }).join(", ") +
    " has an active warning condition.";
} else if (offline.length === rows.length) {
  cls = "off"; level = "OFFLINE"; headline = "No recent data from any location";
  detail = "All three monitoring locations are offline. Confirm connectivity before relying on this view.";
} else if (offline.length) {
  cls = "warn"; level = "ATTENTION"; headline = offline.length + " monitoring location(s) offline";
  detail = offline.map(function (r) { return r.location; }).join(", ") +
    " has no recent data. The remaining locations report normal water status.";
} else if (stale.length) {
  cls = "warn"; level = "ATTENTION"; headline = "No active water-safety incident";
  detail = stale.map(function (r) { return r.location; }).join(", ") +
    " has a stored water status that current readings do not confirm. It is not shown as an incident.";
}
const summary = rows.length + " monitoring locations · " + count("SAFE") + " safe · " +
  count("WARNING") + " warning · " + count("CRITICAL") + " critical · " +
  count("STALE") + " unconfirmed · " + count("OFFLINE") + " offline";
return incidentHtml + '<div class="js-system ' + cls + '">' +
  '<div class="js-system-context">Municipal Water Monitoring Authority · demonstration hierarchy</div>' +
  '<div class="js-system-area">Rasuwa Monitoring Area</div>' +
  '<div class="js-system-level">SYSTEM STATUS: ' + level + '</div>' +
  '<div class="js-system-headline">' + headline + '</div>' +
  '<div class="js-system-detail">' + detail + '</div>' +
  '<div class="js-system-summary">' + summary + '</div>' +
  '</div>';
"""

SYSTEM_STATUS_JS = INCIDENT_THRESHOLDS_JS + _STATUS_COMMON_JS + _INCIDENT_STATUS_JS_BODY

NODE_STATUS_JS = INCIDENT_THRESHOLDS_JS + _STATUS_COMMON_JS + r"""
const cards = rows.map(function (r) {
  const overall = r.status === "STALE" ? "UNCONFIRMED" :
    r.status === "OFFLINE" ? "OFFLINE" : (r.safety || "UNKNOWN");
  const alarm = r.status === "CRITICAL" ? "Critical — see alert below" :
    r.status === "WARNING" ? "Warning — see alert below" :
    r.status === "OFFLINE" ? "Not available while offline" :
    r.status === "STALE" ? "Not confirmed by current readings" : "None";
  const flowNumber = Number(r.flow);
  let flow;
  if (!r.active) {
    flow = "No recent reading";
  } else if (r.active && isFinite(flowNumber) && flowNumber > 0) {
    flow = "Flowing · " + flowNumber.toFixed(1) + " L/min";
  } else if (r.active && flowNumber === 0) {
    flow = "No flow reported";
  } else {
    flow = "No recent reading";
  }
  const connectivity = r.active ? "Connected" : "No recent data";
  return '<div class="js-node ' + clsFor(r.status) + '">' +
    '<div class="js-node-head"><div>' +
    '<div class="js-node-name">' + r.location + '</div>' +
    '<div class="js-node-sub">Water source · ' + r.node + '</div></div>' +
    '<span class="js-node-status ' + clsFor(r.status) + '">' + r.status + '</span></div>' +
    '<div class="js-node-row"><span>Overall water status</span><b>' + overall + '</b></div>' +
    '<div class="js-node-row"><span>Active alarm</span><b>' + alarm + '</b></div>' +
    '<div class="js-node-row"><span>Flow status</span><b>' + flow + '</b></div>' +
    '<div class="js-node-row"><span>Connectivity</span><b>' + connectivity + '</b></div>' +
    '</div>';
}).join("");
const seriousRows = rows.filter(function (r) {
  return r.status === "CRITICAL" || r.status === "OFFLINE";
});
let scope = "Incident scope: no active critical or major incident";
let scopeCls = "safe";
if (seriousRows.length > 1) {
  scope = "Incident scope: multiple locations affected";
  scopeCls = "crit";
} else if (seriousRows.length === 1) {
  scope = "Incident scope: isolated to " + seriousRows[0].location;
  scopeCls = "crit";
}
return '<div class="js-node-scope ' + scopeCls + '">' + scope + '</div>' +
  '<div class="js-node-grid">' + cards + '</div>';
"""

SYSTEM_STATUS_CSS = r"""
.js-system{padding:10px 16px;border-radius:6px;border-left:8px solid #2e7d32;background:#e8f5e9;color:#1b5e20;height:100%;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;}
.js-system.crit{border-left-color:#b71c1c;background:#c62828;color:#fff;}
.js-system.warn{border-left-color:#ef6c00;background:#fff3e0;color:#e65100;}
.js-system.off{border-left-color:#607d8b;background:#eceff1;color:#37474f;}
.js-system.stale{border-left-color:#ef6c00;background:#fff8e1;color:#8d4e00;}
.js-system-context{font-size:11px;font-weight:600;letter-spacing:.2px;opacity:.85;}
.js-system-area{font-size:13px;font-weight:700;margin-top:1px;}
.js-system-level{font-size:19px;font-weight:700;letter-spacing:.3px;margin-top:2px;}
.js-system-headline{font-size:14px;font-weight:600;margin-top:1px;}
.js-system-detail{font-size:12px;margin-top:2px;}
.js-system-summary{font-size:11px;opacity:.85;margin-top:3px;}
.js-critical-alert{position:fixed;top:62px;right:24px;z-index:2147483000;max-width:520px;padding:12px 16px;border:2px solid #fff;border-radius:6px;background:#b71c1c;color:#fff;font-size:14px;line-height:1.4;box-shadow:0 6px 18px rgba(0,0,0,.35);pointer-events:none;animation:jsCriticalPulse 1.6s ease-in-out infinite;}
.js-critical-alert-title{font-weight:800;letter-spacing:.4px;}
.js-critical-alert.js-incident{left:50%;right:auto;transform:translateX(-50%);max-width:880px;padding:14px 18px;background:#b71c1c;animation:none;}
.js-incident-kicker{font-size:17px;font-weight:800;letter-spacing:.5px;line-height:1.2;}
.js-incident-place{font-size:16px;font-weight:700;margin-top:3px;}
.js-incident-meta{font-size:12px;margin-top:2px;opacity:.95;}
.js-incident-summary{font-size:13px;line-height:1.35;margin-top:7px;}
.js-incident-readings{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px;}
.js-incident-measure{display:inline-block;padding:4px 7px;border-radius:4px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.38);font-size:12px;font-weight:600;white-space:nowrap;}
.js-incident-measure.crit{background:#7f0000;border-color:#ffcdd2;}
.js-incident-measure.warn{background:#e65100;border-color:#ffe0b2;}
.js-incident-measure.off{background:#37474f;border-color:#b0bec5;}
.js-incident-others{font-size:12px;margin-top:7px;font-weight:600;}
.js-incident-note{font-size:11px;line-height:1.35;margin-top:5px;opacity:.9;}
@keyframes jsCriticalPulse{0%,100%{opacity:1}50%{opacity:.82}}
"""

NODE_STATUS_CSS = r"""
.js-node-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:8px;box-sizing:border-box;}
.js-node{border:1px solid #d9dee3;border-left:6px solid #2e7d32;border-radius:5px;background:#fff;padding:8px 10px;min-width:0;}
.js-node.crit{border:1px solid #b71c1c;border-left:6px solid #b71c1c;background:#c62828;color:#fff;}
.js-node.crit .js-node-name,.js-node.crit .js-node-row,.js-node.crit .js-node-row b{color:#fff;}
.js-node.crit .js-node-row{border-top-color:rgba(255,255,255,.35);}
.js-node.crit .js-node-status{background:#b71c1c;color:#fff;border:1px solid #fff;}
.js-node.warn{border-left-color:#ef6c00;background:#fffaf2;}
.js-node.off{border-left-color:#607d8b;background:#f7f9fa;}
.js-node.stale{border-left-color:#ef6c00;background:#fffdf6;}
.js-node-status.stale{background:#fff8e1;color:#8d4e00;}
.js-node-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:4px;}
.js-node-name{font-size:15px;font-weight:700;color:#263238;line-height:1.2;}
.js-node-sub{font-size:10px;color:#607d8b;line-height:1.2;margin-top:1px;}
.js-node.crit .js-node-name,.js-node.crit .js-node-sub{color:#fff;}
.js-node-status{font-size:11px;font-weight:700;padding:3px 7px;border-radius:10px;background:#e8f5e9;color:#1b5e20;white-space:nowrap;}
.js-node-status.warn{background:#fff3e0;color:#e65100;}
.js-node-status.off{background:#eceff1;color:#37474f;}
.js-node-row{display:grid;grid-template-columns:minmax(110px,42%) minmax(0,1fr);column-gap:8px;font-size:12px;line-height:1.55;color:#546e7a;border-top:1px solid #eef1f3;padding-top:3px;}
.js-node-row span,.js-node-row b{min-width:0;}
.js-node-row b{color:#263238;font-weight:600;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.js-node-scope{padding:6px 10px;margin:8px 8px 0;border-radius:4px;background:#e8f5e9;border-left:5px solid #2e7d32;color:#1b5e20;font-size:12px;font-weight:700;}
.js-node-scope.crit{background:#ffebee;border-left-color:#c62828;color:#b71c1c;}
"""

# The three current-reading widgets stay as real ThingsBoard gauges. Colour
# bands are visual annotations of the existing alarm thresholds; they do not
# create, widen or replace any rule in alarms.py / alarm_rules.py.
GAUGE_SAFE_COLOR = "#2e7d32"
GAUGE_UNSAFE_COLOR = "#d32f2f"
GAUGE_CRITICAL_COLOR = "#8e0000"

# Alarms table cell function: one human-readable line per active alarm. It uses
# only fields already supplied by ThingsBoard's alarm datasource.
ALERT_CELL_FUNCTION = r"""
var places = {"JalSanket-Node-01": "Dhunche", "JalSanket-Node-02": "Syafrubesi", "JalSanket-Node-03": "Rasuwagadhi"};
var nodes = {"Dhunche": "JalSanket Node 01", "Syafrubesi": "JalSanket Node 02", "Rasuwagadhi": "JalSanket Node 03"};
var problems = {
  "High Turbidity Warning": "Turbidity above safe level",
  "Gross Contamination Critical": "Turbidity critically high",
  "pH Out of Range Critical": "pH outside safe range",
  "High TDS Critical": "Dissolved solids too high",
  "Supply Interruption Major": "Water supply interrupted",
  "Node Inactive Critical": "No recent data from node"
};
var sev = String(alarm.severity || "INFO").toUpperCase();
var place = places[alarm.originatorDisplayName] || alarm.originatorDisplayName || "Unknown location";
var node = nodes[place] || "";
var problem = problems[value] || value;
var ts = alarm.createdTime || alarm.startTs || Date.now();
var time = new Date(ts).toLocaleString();
var style = "border-left:5px solid #1976d2;background:#e3f2fd;";
var badge = "padding:2px 6px;border-radius:3px;background:#1976d2;color:#fff;font-size:10px;";
if (sev === "CRITICAL") {
  style = "border-left:5px solid #c62828;background:#ffebee;";
  badge = "padding:3px 8px;border-radius:3px;background:#c62828;color:#fff;font-size:11px;font-weight:700;";
} else if (sev === "MAJOR" || sev === "WARNING") {
  style = "border-left:5px solid #ef6c00;background:#fff3e0;";
  badge = "padding:2px 7px;border-radius:3px;background:#ef6c00;color:#fff;font-size:10px;font-weight:700;";
}
return '<div style="' + style + 'padding:6px 8px;border-radius:4px;min-width:280px;box-sizing:border-box;">' +
  '<span style="' + badge + '">' + sev + '</span> ' +
  '<b style="color:#263238;">' + place + '</b>' +
  (node ? ' <small style="color:#607d8b;">(' + node + ')</small>' : '') +
  ' — <span style="color:#37474f;">' + problem + '</span> ' +
  '<small style="color:#78909c;">(Detected ' + time + ')</small></div>';
"""

# Map functions use the same existing attributes and measurement values. The
# status word is part of every marker label so severity is never communicated
# by colour alone. The same freshness guard prevents a stale safetyStatus from
# marking a safe source as an incident.
MAP_COMMON_JS = INCIDENT_THRESHOLDS_JS + r"""
var mapNumber = function (v) {
  var n = Number(v);
  return isFinite(n) ? n : null;
};
var mapStatus = function (d) {
  var rawActive = d["active"];
  var active = rawActive === true || String(rawActive).toLowerCase() === "true";
  var safety = String(d["safetyStatus"] || "").toUpperCase();
  if (!active) return "OFFLINE";
  var ph = mapNumber(d["ph"]);
  var turbidity = mapNumber(d["turbidity_ntu"]);
  var tds = mapNumber(d["tds_ppm"]);
  var flow = mapNumber(d["flow_lpm"]);
  var critical = (turbidity !== null && turbidity > T.grossClear) ||
    (tds !== null && tds > T.tdsClear) ||
    (ph !== null && (ph < T.phLowClear || ph > T.phHighClear)) || flow === 0;
  if (safety === "UNSAFE" || safety === "CRITICAL") {
    return critical ? "CRITICAL" : "STALE";
  }
  if (safety === "WARNING") {
    if (critical) return "CRITICAL";
    return turbidity !== null && turbidity > T.turbidityClear ? "WARNING" : "STALE";
  }
  return "SAFE";
};
"""

MAP_LABEL_FUNCTION = MAP_COMMON_JS + r"""
var d = dsData[dsIndex];
var name = d["entityName"] || d["deviceName"] || "";
var places = {"JalSanket-Node-01": "Dhunche", "JalSanket-Node-02": "Syafrubesi", "JalSanket-Node-03": "Rasuwagadhi"};
var status = mapStatus(d);
var incident = status === "CRITICAL" || status === "OFFLINE" ? "INCIDENT · " : "";
return incident + (places[name] || name) + " — " + status;
"""

MAP_COLOR_FUNCTION = MAP_COMMON_JS + r"""
var status = mapStatus(dsData[dsIndex]);
if (status === "OFFLINE") return "#607d8b";
if (status === "CRITICAL") return "#c62828";
if (status === "WARNING" || status === "STALE") return "#ef6c00";
return "#2e7d32";
"""

MAP_TOOLTIP_FUNCTION = MAP_COMMON_JS + r"""
var d = dsData[dsIndex];
var name = d["entityName"] || d["deviceName"] || "";
var places = {"JalSanket-Node-01": "Dhunche", "JalSanket-Node-02": "Syafrubesi", "JalSanket-Node-03": "Rasuwagadhi"};
var nodes = {"Dhunche": "JalSanket Node 01", "Syafrubesi": "JalSanket Node 02", "Rasuwagadhi": "JalSanket Node 03"};
var status = mapStatus(d);
var place = places[name] || name;
var lat = Number(d["latitude"]), lng = Number(d["longitude"]);
return "<b>" + place + "</b><br/>Rasuwa Monitoring Area · water source" +
  "<br/>JalSanket node: " + (nodes[place] || name) + "<br/>Status: " + status +
  "<br/>Affected source: " + (status === "CRITICAL" || status === "OFFLINE" ? "Yes" : "No") +
  "<br/>Location: " + (isFinite(lat) ? lat.toFixed(4) : "n/a") + ", " +
  (isFinite(lng) ? lng.toFixed(4) : "n/a");
"""


def _navigation_button(widget_id: str, label: str, icon: str,
                       target_dashboard_id: str, row: int, col: int) -> dict:
    """Build the stock Action button that switches between the two dashboards."""
    return {
        "id": widget_id,
        "col": col,
        "row": row,
        "sizeX": 6,
        "sizeY": 1,
        "type": "latest",
        "typeFullFqn": "system.action_button",
        "config": {
            "actions": {
                "click": [{
                    "icon": "more_horiz",
                    "id": f"action_{widget_id}",
                    "name": "onClick",
                    "openInPopover": False,
                    "openInSeparateDialog": False,
                    "openNewBrowserTab": False,
                    "setEntityId": True,
                    "stateEntityParamName": None,
                    "targetDashboardId": target_dashboard_id,
                    "targetDashboardStateId": "",
                    "type": "openDashboard",
                }]
            },
            "backgroundColor": "#FFFFFF01",
            "borderRadius": "4px",
            "color": "rgba(0, 0, 0, 0.87)",
            "configMode": "basic",
            "datasources": [],
            "dropShadow": False,
            "enableDataExport": False,
            "enableFullscreen": False,
            "iconColor": "rgba(0, 0, 0, 0.87)",
            "iconSize": "24px",
            "noDataDisplayMessage": "",
            "padding": "0px",
            "pageSize": 1024,
            "settings": {
                "activatedState": {
                    "action": "DO_NOTHING",
                    "dataToValue": {"compareToValue": True,
                                    "dataToValueFunction": "/* Should return boolean value */\nreturn data;",
                                    "type": "NONE"},
                    "defaultValue": False,
                    "getAlarmStatus": {"severityList": None, "typeList": None},
                    "getAttribute": {"key": "state", "scope": None},
                    "getTimeSeries": {"key": "state"},
                },
                "appearance": {
                    "autoScale": True,
                    "backgroundColor": "#FFFFFF",
                    "customStyle": {"activated": None, "disabled": None,
                                    "enabled": None, "hovered": None, "pressed": None},
                    "icon": icon,
                    "iconSize": 24,
                    "iconSizeUnit": "px",
                    "label": label,
                    "mainColor": "var(--tb-primary-500)",
                    "showIcon": True,
                    "showLabel": True,
                    "type": "outlined",
                },
                "disabledState": {
                    "action": "DO_NOTHING",
                    "dataToValue": {"compareToValue": True,
                                    "dataToValueFunction": "/* Should return boolean value */\nreturn data;",
                                    "type": "NONE"},
                    "defaultValue": False,
                    "getAlarmStatus": {"severityList": None, "typeList": None},
                    "getAttribute": {"key": "state", "scope": None},
                    "getTimeSeries": {"key": "state"},
                },
            },
            "showLegend": False,
            "showTitle": False,
            "showTitleIcon": False,
            "title": "Action button",
            "titleStyle": {"fontSize": "16px", "fontWeight": 400},
            "titleTooltip": "",
            "widgetCss": "",
            "widgetStyle": {},
        },
    }


def _cloud_key(name: str, key_type: str, label: str, color: str,
               decimals: Optional[int] = None) -> dict:
    key = {
        "name": name,
        "type": key_type,
        "label": label,
        "color": color,
        "settings": {},
        "aggregationType": None,
        "units": None,
    }
    if decimals is not None:
        key["decimals"] = decimals
    return key


def _cloud_datasource(keys: list[dict]) -> list[dict]:
    return [{
        "type": "entity",
        "name": "",
        "entityAliasId": FLEET_ALIAS,
        "filterId": None,
        "dataKeys": keys,
        "alarmFilterConfig": {"statusList": ["ACTIVE"]},
    }]


def _cloud_device_datasource(device_id: Optional[str], keys: list[dict]) -> list[dict]:
    """Single-device datasource for widgets that only accept one entity.

    Each current-reading card is a single-location readout, and the JustGage
    widget declares ``maxDatasources: 1`` / ``singleEntity: true``. Binding it
    to the multi-device fleet alias makes its subscription ambiguous, so these
    Node-01 detail widgets are pinned to that device explicitly.
    """
    ds = _cloud_datasource(keys)[0]
    if device_id:
        ds["entityId"] = device_id
        ds["entityType"] = "DEVICE"
        ds["entityName"] = "JalSanket-Node-01"
        ds["name"] = "JalSanket-Node-01"
        ds.pop("entityAliasId", None)
    return [ds]


def _cloud_markdown_config(title: str, keys: list[dict], *,
                           javascript: Optional[str] = None,
                           markdown: str = "", css: str = "",
                           device_id: Optional[str] = None) -> dict:
    """Build a markdown card config driven by an in-page JS function."""
    settings: dict = {
        "applyDefaultMarkdownStyle": True,
        "markdownTextPattern": markdown,
    }
    if javascript is not None:
        settings["useMarkdownTextFunction"] = True
        settings["markdownTextFunction"] = javascript
        settings["markdownCss"] = css
    if keys and device_id:
        datasources = _cloud_device_datasource(device_id, keys)
    else:
        datasources = _cloud_datasource(keys) if keys else []
    return {
        "datasources": datasources,
        "settings": settings,
        "showTitle": True,
        "title": title,
    }


def _cloud_gauge_range(start: float, end: Optional[float], color: str) -> dict:
    """One supported ThingsBoard advanced colour band for a gauge."""
    return {
        "from": {"type": "constant", "value": start},
        "to": {"type": "constant", "value": end},
        "color": color,
    }


def _cloud_gauge_config(title: str, key_name: str, label: str, unit: str,
                        decimals: int, minimum: float, maximum: float,
                        ticks: tuple[float, ...], safe_range: str,
                        bands: tuple[tuple[float, Optional[float], str], ...],
                        device_id: Optional[str]) -> dict:
    """Build a real gauge with threshold colours, ticks and a live value."""
    key = _cloud_key(key_name, "timeseries", label, GAUGE_SAFE_COLOR, decimals)
    key["units"] = unit
    key["settings"] = {"units": unit, "decimals": decimals}
    ranges = [_cloud_gauge_range(start, end, color) for start, end, color in bands]
    settings = {
        "minValue": minimum,
        "maxValue": maximum,
        "decimals": decimals,
        "units": unit,
        "gaugeType": "arc",
        "donutStartAngle": 90,
        "gaugeWidthScale": 0.75,
        "gaugeColor": "#eceff1",
        "showValue": True,
        "showMinMax": True,
        "showTitle": True,
        "title": safe_range,
        "showUnitTitle": True,
        "unitTitle": unit,
        "showTimestamp": False,
        "showTicks": True,
        "tickWidth": 3,
        "colorTicks": "#546e7a",
        "ticksValue": [{"type": "constant", "value": value} for value in ticks],
        "animation": True,
        "animationDuration": 700,
        "animationRule": "linear",
        "defaultColor": GAUGE_SAFE_COLOR,
        "levelColors": [],
        "useFixedLevelColor": True,
        "fixedLevelColors": [
            {"from": band["from"], "to": band["to"], "color": band["color"]}
            for band in ranges
        ],
        "barColor": {
            "type": "range",
            "color": GAUGE_SAFE_COLOR,
            "rangeList": {
                "advancedMode": True,
                "range": None,
                "rangeAdvanced": ranges,
            },
        },
        "titleFont": {"family": "Roboto", "size": 9, "style": "normal",
                      "weight": "600", "color": "#37474f"},
        "valueFont": {"family": "Roboto", "size": 28, "style": "normal",
                      "weight": "700", "color": "#263238"},
        "minMaxFont": {"family": "Roboto", "size": 10, "style": "normal",
                       "weight": "600", "color": "#37474f"},
        "labelFont": {"family": "Roboto", "size": 9, "style": "normal",
                      "weight": "500", "color": "#546e7a"},
    }
    return {
        "datasources": _cloud_device_datasource(device_id, [key]),
        "settings": settings,
        "showTitle": True,
        "title": title,
        "useDashboardTimewindow": False,
    }


def _cloud_location_datasources(device_ids: Optional[list[str]],
                                key_name: str, color: str,
                                decimals: int = 2) -> list[dict]:
    """Per-location datasources give chart legends human-readable names."""
    nodes = DEFAULT_NODE_SPECS
    if device_ids and len(device_ids) == len(nodes):
        sources = []
        for node, device_id in zip(nodes, device_ids):
            location = NODE_LOCATIONS.get(node.node_id, node.device_name)
            sources.append({
                "type": "entity",
                "name": location,
                "entityId": device_id,
                "entityType": "DEVICE",
                "entityName": node.device_name,
                "filterId": None,
                "dataKeys": [_cloud_key(key_name, "timeseries", location,
                                        color, decimals)],
            })
        return sources
    return _cloud_datasource([_cloud_key(
        key_name, "timeseries", f"{key_name} - ${{deviceName}}", color, decimals
    )])


def build_cloud_dashboard(device_ids: Optional[list[str]] = None,
                          fleet_config: Optional[FleetConfig] = None) -> dict:
    """Build the importable ThingsBoard Cloud dashboard document.

    When ``device_ids`` are known (after provisioning), the fleet alias is an
    explicit entity list. Otherwise it selects the three exact device names so
    the artifact never depends on a mutable device-type filter.
    """
    nodes = fleet_config.nodes if fleet_config else DEFAULT_NODE_SPECS
    if device_ids:
        alias_filter: dict = {
            "type": "entityList",
            "entityType": "DEVICE",
            "entityList": list(device_ids),
        }
    else:
        pattern = "(" + "|".join(re.escape(node.device_name) for node in nodes) + ")"
        alias_filter = {
            "type": "entityName",
            "entityType": "DEVICE",
            "entityNameFilter": pattern,
        }

    widgets: dict[str, dict] = {}
    layout: dict[str, dict] = {}

    def add(widget_id: str, title: str, size_x: int, size_y: int,
            row: int, col: int, config: dict) -> None:
        fqn, widget_type = CLOUD_WIDGET_FQNS[widget_id]
        widgets[widget_id] = {
            "typeFullFqn": f"system.{fqn}",
            "type": widget_type,
            "sizeX": size_x,
            "sizeY": size_y,
            "config": config,
            "row": row,
            "col": col,
            "id": widget_id,
        }
        layout[widget_id] = {
            "sizeX": size_x,
            "sizeY": size_y,
            "row": row,
            "col": col,
        }

    summary_keys = [
        _cloud_key("deviceName", "attribute", "Location", "#607d8b"),
        _cloud_key("safetyStatus", "attribute", "Water status", "#2e7d32"),
        _cloud_key("active", "attribute", "Connectivity", "#607d8b"),
        _cloud_key("flow_lpm", "timeseries", "Flow", "#1976d3", 1),
        _cloud_key("ph", "timeseries", "pH reading", "#f44336", 2),
        _cloud_key("turbidity_ntu", "timeseries", "Turbidity reading", "#2196f3", 1),
        _cloud_key("tds_ppm", "timeseries", "TDS reading", "#4caf50", 1),
    ]
    add("system_status", "JalSanket Water Safety · Rasuwa Monitoring Area", 24, 4, 0, 0,
        _cloud_markdown_config(
            "JalSanket Water Safety · Rasuwa Monitoring Area", summary_keys,
            javascript=SYSTEM_STATUS_JS, css=SYSTEM_STATUS_CSS,
        ))
    add("node_status", "Monitoring locations / water sources → JalSanket nodes", 24, 5, 4, 0,
        _cloud_markdown_config(
            "Monitoring locations / water sources → JalSanket nodes", summary_keys,
            javascript=NODE_STATUS_JS, css=NODE_STATUS_CSS,
        ))

    alert_key = _cloud_key("type", "alarm", "Priority / location / problem", "#c62828")
    alert_key["settings"] = {
        "useCellContentFunction": True,
        "cellContentFunction": ALERT_CELL_FUNCTION,
        "useCellContentFunctionOnExport": True,
    }
    add("active_alerts", "Active alerts requiring attention · Rasuwa area", 12, 7, 9, 0, {
        "alarmSource": {
            "type": "entity",
            "entityAliasId": FLEET_ALIAS,
            "name": "alerts",
            "dataKeys": [alert_key],
        },
        "alarmFilterConfig": {"statusList": ["ACTIVE"]},
        "alarmStatusList": ["ACTIVE"],
        "configMode": "advanced",
        "settings": {
            "alarmsTitle": "Active alerts — Rasuwa Monitoring Area",
            "allowAcknowledgment": False,
            "allowAssign": False,
            "allowClear": False,
            "defaultPageSize": 5,
            "defaultSortOrder": "-severity",
            "displayActivity": False,
            "displayDetails": False,
            "displayPagination": True,
            "enableFilter": False,
            "enableSearch": False,
            "enableSelectColumnDisplay": False,
            "enableSelection": False,
        },
        "showTitle": True,
        "title": "Active alerts requiring attention · Rasuwa area",
        "useDashboardTimewindow": False,
        # Alarm widgets subscribe with their own timewindow. Without this the
        # Cloud renderer passes null to subscribeForAlarms and throws
        # "Cannot read properties of null (reading 'realtimeWindowMs')".
        "timewindow": {
            "selectedTab": 0,
            "realtime": {"realtimeType": 0, "timewindowMs": 2592000000},
        },
    })

    add("node_map", "Rasuwa area — water sources (OpenStreetMap)", 12, 7, 9, 12, {
        "datasources": _cloud_datasource([
            _cloud_key("latitude", "timeseries", "latitude", "#2196f3", 7),
            _cloud_key("longitude", "timeseries", "longitude", "#4caf50", 7),
            _cloud_key("safetyStatus", "attribute", "safetyStatus", "#607d8b"),
            _cloud_key("active", "attribute", "active", "#607d8b"),
            _cloud_key("flow_lpm", "timeseries", "flow_lpm", "#1976d3", 1),
            _cloud_key("ph", "timeseries", "ph", "#f44336", 2),
            _cloud_key("turbidity_ntu", "timeseries", "turbidity_ntu", "#2196f3", 1),
            _cloud_key("tds_ppm", "timeseries", "tds_ppm", "#4caf50", 1),
        ]),
        "settings": {
            "latKeyName": "latitude",
            "lngKeyName": "longitude",
            "label": "${entityName}",
            "mapProvider": "OpenStreetMap.Mapnik",
            "provider": "openstreet-map",
            "fitMapBounds": True,
            "useDefaultCenterPosition": False,
            "showLabel": True,
            "showTooltip": True,
            "useLabelFunction": True,
            "labelFunction": MAP_LABEL_FUNCTION,
            "useColorFunction": True,
            "colorFunction": MAP_COLOR_FUNCTION,
            "useTooltipFunction": True,
            "tooltipFunction": MAP_TOOLTIP_FUNCTION,
        },
        "showTitle": True,
        "title": "Rasuwa area — water sources (OpenStreetMap)",
    })

    add("measurements_header", "Selected location / node details → measurements → trends", 24, 1, 16, 0,
        _cloud_markdown_config(
            "Selected location / node details → measurements → trends", [],
            markdown=(
                "**Dhunche water source · JalSanket Node 01** — current measurements "
                "below belong to this node; the trend charts cover all three locations. "
                "During an incident, the banner above names the affected source and shows "
                "its current values."
            ),
        ))

    node01_id = device_ids[0] if device_ids else None
    for (widget_id, title, key_name, label, unit, decimals, maximum,
         ticks, safe_range, bands, col) in (
        ("ph_gauge", "pH — Dhunche (Node 01)", "ph", "pH", "pH", 2, 14,
         (0, PH_LOW_TRIGGER, PH_HIGH_TRIGGER, 14), "SAFE 6.5-8.5 pH",
         ((0, PH_LOW_TRIGGER, GAUGE_UNSAFE_COLOR),
          (PH_LOW_TRIGGER, PH_HIGH_TRIGGER, GAUGE_SAFE_COLOR),
          (PH_HIGH_TRIGGER, None, GAUGE_UNSAFE_COLOR)), 0),
        ("turbidity_gauge", "Turbidity — Dhunche (Node 01)", "turbidity_ntu",
         "Turbidity", "NTU", 1, 300,
         (0, HIGH_TURBIDITY_TRIGGER, GROSS_CONTAMINATION_TRIGGER, 300),
         "SAFE 0-50 NTU",
         ((0, HIGH_TURBIDITY_TRIGGER, GAUGE_SAFE_COLOR),
          (HIGH_TURBIDITY_TRIGGER, GROSS_CONTAMINATION_TRIGGER,
           GAUGE_UNSAFE_COLOR),
          (GROSS_CONTAMINATION_TRIGGER, None, GAUGE_CRITICAL_COLOR)), 8),
        ("tds_gauge", "TDS — Dhunche (Node 01)", "tds_ppm", "TDS", "ppm", 1,
         1000, (0, HIGH_TDS_TRIGGER, 1000), "SAFE 0-500 ppm",
         ((0, HIGH_TDS_TRIGGER, GAUGE_SAFE_COLOR),
          (HIGH_TDS_TRIGGER, None, GAUGE_UNSAFE_COLOR)), 16),
    ):
        add(widget_id, title, 8, 5, 17, col, _cloud_gauge_config(
            title, key_name, label, unit, decimals, 0, maximum, ticks,
            safe_range, bands, node01_id,
        ))

    # One chart per metric: turbidity (0-300 NTU), pH (0-14) and TDS (0-1000 ppm)
    # have very different scales. Sharing one y-axis made pH look flat even
    # during a contamination event, so each signal gets its own axis now.
    for widget_id, title, key_name, color, col in (
        ("turbidity_series", "Turbidity trend by location (NTU)", "turbidity_ntu",
         "#2196f3", 0),
        ("ph_series", "pH trend by location", "ph", "#f44336", 8),
        ("tds_series", "TDS trend by location (ppm)", "tds_ppm", "#4caf50", 16),
    ):
        add(widget_id, title, 8, 5, 22, col, {
            "datasources": _cloud_location_datasources(
                device_ids, key_name, color, 2,
            ),
            "settings": {"showLegend": True, "legendConfig": {"show": True}},
            "showTitle": True,
            "title": title,
            "useDashboardTimewindow": True,
        })

    for widget_id, title, key_names in (
        ("temp_flow", "Water temperature and flow", ("water_temp_c", "flow_lpm")),
    ):
        add(widget_id, title, 24, 5, 27, 0, {
            "datasources": _cloud_datasource([
                _cloud_key(name, "timeseries", name, color, 2)
                for name, color in zip(key_names, ("#2196f3", "#f44336"))
            ]),
            "settings": {"showLegend": True, "legendConfig": {"show": True}},
            "showTitle": True,
            "title": title,
            "useDashboardTimewindow": True,
        })

    nav = _navigation_button(
        "nav_to_demo_controls", "Go to Demo Controls", "arrow_forward",
        DEMO_CONTROLS_DASHBOARD_ID, 32, 9,
    )
    widgets[nav["id"]] = nav
    layout[nav["id"]] = {"col": nav["col"], "row": nav["row"],
                         "sizeX": nav["sizeX"], "sizeY": nav["sizeY"]}

    return {
        "title": DASHBOARD_TITLE,
        "configuration": {
            "description": (
                HIERARCHY_CHAIN + " " + HIERARCHY_NOTE +
                " Existing Cloud devices, alias and telemetry keys only: " +
                ", ".join(TELEMETRY_KEYS) + "."
            ),
            "widgets": widgets,
            "states": {
                "default": {
                    "name": "Default",
                    "root": True,
                    "layouts": {
                        "main": {
                            "widgets": layout,
                            "gridSettings": {
                                "layoutType": "default",
                                "backgroundColor": "#eeeeee",
                                "columns": 24,
                                "margin": 10,
                                "outerMargin": True,
                                "backgroundSizeMode": "100%",
                            },
                        }
                    },
                }
            },
            "entityAliases": {
                FLEET_ALIAS: {
                    "id": FLEET_ALIAS,
                    "alias": "JalSanket Fleet",
                    "filter": alias_filter,
                }
            },
            "filters": {},
            "timewindow": {
                "selectedTab": 0,
                "realtime": {
                    "realtimeType": 0,
                    # ThingsBoard rejects a query with more than ~600 buckets;
                    # 5 s over a 1 h window is 720 and returned HTTP 400, which
                    # left every time-series chart (and its CSV export) empty.
                    "interval": 10000,
                    "timewindowMs": 3600000,
                    "quickInterval": "CURRENT_DAY",
                },
                "history": {
                    "historyType": 0,
                    "interval": 1000,
                    "timewindowMs": 60000,
                    "fixedTimewindow": None,
                },
                "aggregation": {"type": "AVG", "limit": 25000},
                "timezone": None,
            },
            "settings": {
                "stateControllerId": "entity",
                "showTitle": False,
                "showDashboardsSelect": True,
                "showEntitiesSelect": True,
                "showDashboardTimewindow": True,
                "showDashboardExport": True,
                "toolbarAlwaysOpen": True,
            },
        },
    }


def build_demo_controls_dashboard(device_ids: Optional[list[str]] = None,
                                  fleet_config: Optional[FleetConfig] = None) -> dict:
    """Build a compact button-only dashboard for live scenario demos.

    The main monitoring dashboard stays clean. These twelve controls are laid
    out in a 4 x 3 grid with a smaller margin so every button is easy to click.
    """
    full = build_cloud_dashboard(device_ids, fleet_config)
    source = full["configuration"]
    nodes = fleet_config.nodes if fleet_config else DEFAULT_NODE_SPECS

    widgets: dict[str, dict] = {}
    layout: dict[str, dict] = {}
    index = 0
    for node_index, node in enumerate(nodes):
        target_id = device_ids[node_index] if device_ids and node_index < len(device_ids) else ""
        for command_index, (short_title, button_text, method, params) in enumerate(
            RPC_BUTTON_COMMANDS
        ):
            widget_id = (
                f"ctrl_{node.node_id.replace('-', '')}_{method}_{command_index}"
            )
            title = f"{node.node_id.replace('node-', 'Node-')} - {short_title}"
            col = (index % 4) * 6
            row = (index // 4) * 2
            widgets[widget_id] = {
                "id": widget_id,
                "col": col,
                "row": row,
                "sizeX": 6,
                "sizeY": 2,
                "type": "rpc",
                "typeFullFqn": f"system.{RPC_BUTTON_FQN[0]}",
                "config": {
                    "actions": {},
                    "backgroundColor": "#f5f5f5",
                    "color": "rgba(0, 0, 0, 0.87)",
                    "datasources": [],
                    "dropShadow": False,
                    "enableFullscreen": False,
                    "padding": "0px",
                    "settings": {
                        "buttonText": button_text,
                        "methodName": method,
                        "methodParams": params,
                        "oneWayElseTwoWay": False,
                        "persistentPollingInterval": 5000,
                        "requestPersistent": False,
                        "requestTimeout": 5000,
                        "showError": False,
                        "styleButton": {
                            "bgColor": RPC_BUTTON_COLORS[command_index],
                            "isPrimary": False,
                            "isRaised": True,
                            "textColor": "#ffffff",
                        },
                        "title": title,
                    },
                    "showLegend": False,
                    "showTitle": False,
                    "targetDevice": {"deviceId": target_id, "type": "device"},
                    "targetDeviceAliases": [],
                    "title": "RPC Button",
                    "titleStyle": {"fontSize": "14px", "fontWeight": 400},
                    "widgetStyle": {},
                },
            }
            layout[widget_id] = {"col": col, "row": row, "sizeX": 6, "sizeY": 2}
            index += 1

    nav = _navigation_button(
        "nav_to_monitoring", "Go to Monitoring Dashboard", "home",
        MONITORING_DASHBOARD_ID, 6, 9,
    )
    widgets[nav["id"]] = nav
    layout[nav["id"]] = {"col": nav["col"], "row": nav["row"],
                         "sizeX": nav["sizeX"], "sizeY": nav["sizeY"]}

    states = json.loads(json.dumps(source["states"]))
    main_layout = states["default"]["layouts"]["main"]
    main_layout["widgets"] = layout
    main_layout["gridSettings"]["margin"] = 6
    main_layout["gridSettings"]["columns"] = 24

    return {
        "title": DEMO_CONTROLS_TITLE,
        "configuration": {
            "description": (
                "Compact RPC demo controls: Trigger Contamination, Supply "
                "Interruption ON/OFF and Reset for each JalSanket node."
            ),
            "widgets": widgets,
            "states": states,
            "entityAliases": {},
            "filters": {},
            "timewindow": source["timewindow"],
            "settings": source["settings"],
        },
    }


def build_device_documents(fleet_config: FleetConfig) -> list[dict]:
    return [device_document(node) for node in fleet_config.nodes]


def write_artifacts(output_dir: str | Path, fleet_config: FleetConfig,
                    device_ids: Optional[list[str]] = None) -> dict[str, Path]:
    """Write importable Cloud artifacts to disk.

    The dashboard file is the Cloud import document; the rule-chain and alarm
    files remain as local reference artifacts used by the regression suite.
    """
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "dashboard": directory / "jalsanket_dashboard.json",
        "demo_controls": directory / "jalsanket_demo_controls.json",
        "rule_chain": directory / "jalsanket_rule_chain.json",
        "alarm_config": directory / "jalsanket_alarm_config.json",
        "devices": directory / "jalsanket_devices.json",
    }
    documents = {
        "dashboard": build_cloud_dashboard(device_ids, fleet_config),
        "demo_controls": build_demo_controls_dashboard(device_ids, fleet_config),
        "rule_chain": rule_chain_document(),
        "alarm_config": device_profile_alarm_config(),
        "devices": build_device_documents(fleet_config),
    }
    for key, path in artifacts.items():
        path.write_text(json.dumps(documents[key], indent=2) + "\n", encoding="utf-8")
    return artifacts
