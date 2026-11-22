"""Dashboard definitions for the municipal duty officer.

``build_dashboard()`` keeps the original CE-shaped artifact used by the local
regression suite. ``build_cloud_dashboard()`` emits the ThingsBoard Cloud
dashboard that was imported into the tenant; both answer the same question:
"Which water source is unsafe right now?" Every widget is bound to one fleet
alias, and the fleet-health table highlights ``safetyStatus``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .alarm_rules import device_profile_alarm_config, rule_chain_document
from .fleet import DEFAULT_NODE_SPECS, FleetConfig
from .provisioning import TELEMETRY_KEYS, device_document

DASHBOARD_TITLE = "JalSanket - Municipal Water Safety"
FLEET_ALIAS = "fleet"


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
        "pH (all sources)",
        "Analog Gauge",
        _data_keys(("ph",)),
        {"minValue": 0, "maxValue": 14, "units": "pH", "decimals": 2},
        data_type="latest",
    ))
    add("turbidity_gauge", 4, 6, 4, 5, _widget(
        "Turbidity (all sources)",
        "Analog Gauge",
        _data_keys(("turbidity_ntu",)),
        {"minValue": 0, "maxValue": 300, "units": "NTU", "decimals": 1},
        data_type="latest",
    ))
    add("tds_gauge", 8, 6, 4, 5, _widget(
        "TDS (all sources)",
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

CLOUD_WIDGET_FQNS: dict[str, tuple[str, str]] = {
    "summary": ("cards.markdown_card", "latest"),
    "fleet_health": ("cards.entities_table", "latest"),
    "ph_gauge": ("digital_gauges.gauge_justgage", "latest"),
    "turbidity_gauge": ("digital_gauges.gauge_justgage", "latest"),
    "tds_gauge": ("digital_gauges.gauge_justgage", "latest"),
    "multi_series": ("time_series_chart", "timeseries"),
    "temp_flow": ("time_series_chart", "timeseries"),
    "node_map": ("maps_v2.openstreetmap", "latest"),
    "alarms": ("alarm_widgets.alarms_table", "alarm"),
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
            row: int, col: int, config: dict,
            fqn_override: Optional[tuple[str, str]] = None) -> None:
        fqn, widget_type = fqn_override or CLOUD_WIDGET_FQNS[widget_id]
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

    add("summary", "Which water source is unsafe right now?", 24, 2, 0, 0, {
        "datasources": [],
        "settings": {
            "markdownTextPattern": (
                "**Read the Fleet Health table below.** A source marked UNSAFE has an "
                "active CRITICAL or MAJOR alarm; WARNING means the High Turbidity "
                "Warning is active."
            ),
            "applyDefaultMarkdownStyle": True,
        },
        "showTitle": True,
        "title": "Which water source is unsafe right now?",
    })
    add("fleet_health", "Fleet Health / Safety Status", 24, 4, 2, 0, {
        "datasources": _cloud_datasource([
            _cloud_key("safetyStatus", "attribute", "Safety status", "#4caf50"),
            _cloud_key("deviceName", "attribute", "Source", "#2196f3"),
            _cloud_key("bufferDepth", "attribute", "Buffer depth", "#ffc107", 0),
        ]),
        "settings": {"defaultPageSize": 10, "defaultSortOrder": "displayName",
                     "enableSearch": True, "enableSelectColumnDisplay": True},
        "showTitle": True,
        "title": "Fleet Health / Safety Status",
        "useDashboardTimewindow": False,
    })

    for widget_id, title, key_name, maximum, units, decimals, col in (
        ("ph_gauge", "pH (all sources)", "ph", 14, "pH", 2, 0),
        ("turbidity_gauge", "Turbidity (all sources)", "turbidity_ntu", 300, "NTU", 1, 8),
        ("tds_gauge", "TDS (all sources)", "tds_ppm", 1000, "ppm", 1, 16),
    ):
        add(widget_id, title, 8, 5, 6, col, {
            "datasources": _cloud_datasource([
                _cloud_key(key_name, "timeseries", title, "#2196f3", decimals),
            ]),
            "settings": {
                "minValue": 0,
                "maxValue": maximum,
                "decimals": decimals,
                "units": units,
                "showTitle": True,
                "showMinMax": True,
            },
            "showTitle": True,
            "title": title,
        })

    for widget_id, title, key_names, size_y, row in (
        ("multi_series", "Turbidity / pH / TDS time series",
         ("turbidity_ntu", "ph", "tds_ppm"), 6, 11),
        ("temp_flow", "Water temperature and flow",
         ("water_temp_c", "flow_lpm"), 5, 17),
    ):
        add(widget_id, title, 24, size_y, row, 0, {
            "datasources": _cloud_datasource([
                _cloud_key(name, "timeseries", name, color, 2)
                for name, color in zip(key_names, ("#2196f3", "#f44336", "#4caf50"))
            ]),
            "settings": {"showLegend": True, "legendConfig": {"show": True}},
            "showTitle": True,
            "title": title,
            "useDashboardTimewindow": True,
        })

    add("node_map", "Source locations (OpenStreetMap)", 16, 7, 22, 0, {
        "datasources": _cloud_datasource([
            _cloud_key("latitude", "timeseries", "latitude", "#2196f3", 7),
            _cloud_key("longitude", "timeseries", "longitude", "#4caf50", 7),
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
        },
        "showTitle": True,
        "title": "Source locations (OpenStreetMap)",
    })
    add("alarms", "Active alarms", 8, 7, 22, 16, {
        "alarmSource": {
            "type": "entity",
            "entityAliasId": FLEET_ALIAS,
            "name": "alarms",
            "dataKeys": [
                _cloud_key("createdTime", "alarm", "Created time", "#2196f3"),
                _cloud_key("originatorDisplayName", "alarm", "Originator", "#4caf50"),
                _cloud_key("type", "alarm", "Type", "#f44336"),
                _cloud_key("severity", "alarm", "Severity", "#ffc107"),
                _cloud_key("status", "alarm", "Status", "#607d8b"),
            ],
        },
        "alarmStatusList": ["ACTIVE"],
        "settings": {
            "defaultPageSize": 10,
            "defaultSortOrder": "-createdTime",
            "enableSearch": True,
            "enableSelection": True,
        },
        "showTitle": True,
        "title": "Active alarms",
        "useDashboardTimewindow": False,
    })

    # Four scenario commands per node (12 buttons). A single RPC Button widget
    # resolves one target device, so the fleet-wide action is expressed as three
    # explicit device-targeted controls per command.
    for node_index, node in enumerate(nodes):
        target_id = device_ids[node_index] if device_ids and node_index < len(device_ids) else ""
        for command_index, (short_title, button_text, method, params) in enumerate(
            RPC_BUTTON_COMMANDS
        ):
            widget_id = f"rpc_{node.node_id}_{method}_{command_index}"
            button_title = f"{node.device_name} - {short_title}"
            add(widget_id, button_title, 6, 2, 29 + command_index,
                node_index * 6, {
                    "actions": {},
                    "backgroundColor": "#e6e7e8",
                    "color": "rgba(0, 0, 0, 0.87)",
                    "datasources": [],
                    "dropShadow": True,
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
                            "bgColor": None,
                            "isPrimary": False,
                            "isRaised": True,
                            "textColor": None,
                        },
                        "title": button_title,
                    },
                    "showLegend": False,
                    "showTitle": False,
                    "targetDevice": {"deviceId": target_id, "type": "device"},
                    "targetDeviceAliases": [],
                    "title": "RPC Button",
                    "titleStyle": {"fontSize": "16px", "fontWeight": 400},
                    "widgetStyle": {},
                }, fqn_override=RPC_BUTTON_FQN)

    return {
        "title": DASHBOARD_TITLE,
        "configuration": {
            "description": (
                "Municipal water-safety overview for three JalSanket Cloud nodes. "
                "Telemetry keys: " + ", ".join(TELEMETRY_KEYS) + "."
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
                    "interval": 5000,
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
        "rule_chain": directory / "jalsanket_rule_chain.json",
        "alarm_config": directory / "jalsanket_alarm_config.json",
        "devices": directory / "jalsanket_devices.json",
    }
    documents = {
        "dashboard": build_cloud_dashboard(device_ids, fleet_config),
        "rule_chain": rule_chain_document(),
        "alarm_config": device_profile_alarm_config(),
        "devices": build_device_documents(fleet_config),
    }
    for key, path in artifacts.items():
        path.write_text(json.dumps(documents[key], indent=2), encoding="utf-8")
    return artifacts
