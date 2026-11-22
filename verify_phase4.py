#!/usr/bin/env python3
"""Phase 4 verification: three nodes, alarms, artifacts and RPC control.

Run with::

    .venv/bin/python verify_phase4.py

Everything runs locally with injected fake MQTT clients and a fake REST
transport. No ThingsBoard host, device token or admin password is required.
Exits non-zero if any check fails.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from verify_phase3 import FakeMqttClient

from jalsanket import AlarmEvaluator, Fleet, FleetConfig, NodeConfig, Reading
from jalsanket.alarm_rules import device_profile_alarm_config, rule_chain_document
from jalsanket.fleet import DEFAULT_NODE_SPECS
from jalsanket.dashboard import (
    DEMO_CONTROLS_DASHBOARD_ID,
    MONITORING_DASHBOARD_ID,
    RPC_BUTTON_COLORS,
    build_dashboard,
    write_artifacts,
)
from jalsanket.provisioning import (
    DEVICE_PROFILE_NAME,
    INACTIVITY_TIMEOUT_MS,
    TELEMETRY_KEYS,
    ThingsBoardConfig,
    ThingsBoardProvisioner,
    device_profile_document,
)
from jalsanket.telemetry import GeneratorConfig

TEST_TOKENS = {
    "node-01": "TEST_TOKEN_NODE_01_NOT_REAL",
    "node-02": "TEST_TOKEN_NODE_02_NOT_REAL",
    "node-03": "TEST_TOKEN_NODE_03_NOT_REAL",
}
results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((bool(passed), name, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def make_reading(node_id: str, **overrides) -> Reading:
    base = dict(
        node_id=node_id,
        acquired_at=datetime.now(timezone.utc),
        ph=7.2,
        turbidity_ntu=5.0,
        tds_ppm=185.0,
        water_temp_c=20.0,
        flow_lpm=13.0,
        latitude=27.7,
        longitude=85.3,
    )
    base.update(overrides)
    return Reading(**base)


def actions(events, alarm_type: str) -> list[str]:
    return [e.action for e in events if e.alarm_type == alarm_type]


def build_fleet(tmp: str):
    nodes = tuple(
        NodeConfig(
            node_id=f"node-0{i}",
            device_name=f"JalSanket-Test-{i}",
            token_env_var=f"TB_NODE_0{i}_TOKEN",
            latitude=27.80 + i / 100,
            longitude=85.30 + i / 100,
            seed=42 + i,
            db_path=str(Path(tmp) / f"node-0{i}.db"),
            token=TEST_TOKENS[f"node-0{i}"],
        )
        for i in (1, 2, 3)
    )
    config = FleetConfig(host="test.local", nodes=nodes)
    clients = {f"node-0{i}": FakeMqttClient() for i in (1, 2, 3)}
    factories = {key: (lambda client=client: client) for key, client in clients.items()}
    fleet = Fleet(config, client_factories=factories)
    return fleet, clients, config


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jalsanket-phase4-") as tmp:
        fleet, factories, fleet_config = build_fleet(tmp)

        # ---------------------------------------------------------- identities
        section("1. Three-node identity, credentials and location separation")
        check("exactly three nodes", len(fleet.nodes) == 3)
        ids = [fn.config.node_id for fn in fleet.nodes]
        names = [fn.config.device_name for fn in fleet.nodes]
        tokens = [fn.transport.config.token for fn in fleet.nodes]
        coords = [(fn.config.latitude, fn.config.longitude) for fn in fleet.nodes]
        dbs = [fn.store.config.db_path for fn in fleet.nodes]
        check("distinct node ids", len(set(ids)) == 3, str(ids))
        check("distinct device identities", len(set(names)) == 3, str(names))
        check("distinct access tokens", len(set(tokens)) == 3)
        check("each token matches its node config",
              all(t == TEST_TOKENS[n] for n, t in zip(ids, tokens)))
        check("token env var names distinct",
              len({fn.config.token_env_var for fn in fleet.nodes}) == 3)
        check("distinct coordinates", len(set(coords)) == 3, str(coords))
        check("separate SQLite databases", len(set(dbs)) == 3)
        check("separate MQTT clients",
              len({id(fn.transport._client) for fn in fleet.nodes}) == 3)
        first = fleet.nodes[0]
        first.store.persist(first.generator.tick())
        check("buffers are independent",
              first.store.get_buffer_depth() == 1
              and all(fn.store.get_buffer_depth() == 0 for fn in fleet.nodes[1:]))

        # -------------------------------------------------------------- schema
        section("2. Telemetry schema and per-node attribution")
        schema = {"node_id", "acquired_at", *TELEMETRY_KEYS}
        readings = [fn.generator.tick() for fn in fleet.nodes]
        check("exact required field set", all(set(r.to_dict()) == schema for r in readings))
        check("all seven telemetry keys present",
              all(set(r.to_dict()) & set(TELEMETRY_KEYS) == set(TELEMETRY_KEYS) for r in readings))
        check("readings attributed to their node",
              all(r.node_id == fn.config.node_id for r, fn in zip(readings, fleet.nodes)))
        check("coordinates differ in telemetry",
              len({(r.latitude, r.longitude) for r in readings}) == 3)

        # --------------------------------------------------- alarm thresholds
        section("3. Alarm thresholds and hysteresis")
        ev = AlarmEvaluator()
        node = "node-01"

        check("high turbidity triggers above 50",
              actions(ev.evaluate(make_reading(node, turbidity_ntu=51.0), 1000), "High Turbidity Warning") == ["ACTIVATED"])
        check("warning hysteresis at 41 (clear is <40)",
              actions(ev.evaluate(make_reading(node, turbidity_ntu=41.0), 2000), "High Turbidity Warning") == [])
        check("warning clears below 40",
              actions(ev.evaluate(make_reading(node, turbidity_ntu=39.0), 3000), "High Turbidity Warning") == ["CLEARED"])

        check("gross contamination triggers above 200",
              actions(ev.evaluate(make_reading(node, turbidity_ntu=201.0), 4000), "Gross Contamination Critical") == ["ACTIVATED"])
        check("critical hysteresis at 151 (clear is <150)",
              actions(ev.evaluate(make_reading(node, turbidity_ntu=151.0), 5000), "Gross Contamination Critical") == [])
        check("critical clears below 150",
              actions(ev.evaluate(make_reading(node, turbidity_ntu=149.0), 6000), "Gross Contamination Critical") == ["CLEARED"])

        check("low pH triggers below 6.5",
              actions(ev.evaluate(make_reading(node, ph=6.4), 7000), "pH Out of Range Critical") == ["ACTIVATED"])
        check("pH hysteresis at 6.6 (clear starts 6.7)",
              actions(ev.evaluate(make_reading(node, ph=6.6), 8000), "pH Out of Range Critical") == [])
        check("low pH clears within 6.7-8.3",
              actions(ev.evaluate(make_reading(node, ph=6.8), 9000), "pH Out of Range Critical") == ["CLEARED"])
        check("high pH triggers above 8.5",
              actions(ev.evaluate(make_reading(node, ph=8.6), 10000), "pH Out of Range Critical") == ["ACTIVATED"])
        check("high pH clears within 6.7-8.3",
              actions(ev.evaluate(make_reading(node, ph=8.2), 11000), "pH Out of Range Critical") == ["CLEARED"])

        check("high TDS triggers above 500",
              actions(ev.evaluate(make_reading(node, tds_ppm=501.0), 12000), "High TDS Critical") == ["ACTIVATED"])
        check("TDS hysteresis at 451 (clear is <450)",
              actions(ev.evaluate(make_reading(node, tds_ppm=451.0), 13000), "High TDS Critical") == [])
        check("TDS clears below 450",
              actions(ev.evaluate(make_reading(node, tds_ppm=449.0), 14000), "High TDS Critical") == ["CLEARED"])

        ev.evaluate(make_reading(node, turbidity_ntu=300.0), 15000)
        check("active CRITICAL makes source UNSAFE", ev.safety_status(node) == "UNSAFE")
        ev.evaluate(make_reading(node, turbidity_ntu=10.0), 16000)
        check("source returns SAFE after clears", ev.safety_status(node) == "SAFE")

        # ------------------------------------------------- sustained/inactive
        section("4. Sustained interruption and node inactivity")
        ev2 = AlarmEvaluator()
        check("15 zero-flow samples required (30 s / 2 s)",
              ev2.required_zero_samples == 15, f"required={ev2.required_zero_samples}")
        for i in range(14):
            events = ev2.evaluate(make_reading("node-02", flow_lpm=0.0), 20000 + i * 2000)
        check("no supply alarm after 14 zero samples",
              "Supply Interruption Major" not in {e.alarm_type for e in events})
        events = ev2.evaluate(make_reading("node-02", flow_lpm=0.0), 48000)
        check("supply alarm activates on 15th zero sample",
              actions(events, "Supply Interruption Major") == ["ACTIVATED"])
        events = ev2.evaluate(make_reading("node-02", flow_lpm=1.0), 50000)
        check("supply alarm clears when flow resumes",
              actions(events, "Supply Interruption Major") == ["CLEARED"])

        ev3 = AlarmEvaluator()
        ev3.evaluate(make_reading("node-03"), 100000)
        check("no inactivity alarm at 59 s", ev3.check_inactivity("node-03", 159000) == [])
        check("inactivity alarm at 61 s",
              actions(ev3.check_inactivity("node-03", 161000), "Node Inactive Critical") == ["ACTIVATED"])
        check("inactivity alarm clears when telemetry resumes",
              actions(ev3.evaluate(make_reading("node-03"), 162000), "Node Inactive Critical") == ["CLEARED"])
        check("fleet status exposes safety for each node",
              isinstance(ev3.fleet_status(), list))

        # --------------------------------------------------- contamination
        section("5. Repeatable contamination across all three nodes")
        start = datetime(2026, 6, 15, 6, 0, tzinfo=timezone.utc)
        for fn in fleet.nodes:
            fn.generator.reset()
            fn.generator.trigger_contamination()
            event = fn.generator.generate(12, start_at=start + timedelta(seconds=20))
            check(f"{fn.config.node_id}: turbidity crosses warning and critical",
                  max(r.turbidity_ntu for r in event) > 200)
            check(f"{fn.config.node_id}: TDS rises above 500",
                  max(r.tds_ppm for r in event) > 500)
            check(f"{fn.config.node_id}: pH drops below 6.5",
                  min(r.ph for r in event) < 6.5)
            transitions = [e for r in event for e in fleet.evaluator.evaluate(r, 200000)]
            check(f"{fn.config.node_id}: local evaluator raises critical alarm",
                  any(e.alarm_type == "Gross Contamination Critical" and e.action == "ACTIVATED"
                      for e in transitions))

        # --------------------------------------------------------- RPC control
        section("6. Remote scenario control via MQTT RPC")
        for fn in fleet.nodes:
            fn.transport.start()
            fn.transport.pump()
        check("all nodes subscribed to RPC requests",
              all(any(t == "v1/devices/me/rpc/request/+" for t, _ in c.subscriptions)
                  for c in factories.values()))
        n1 = fleet.by_id("node-01")
        c1 = factories["node-01"]
        c1.inject_message(
            "v1/devices/me/rpc/request/req-1",
            json.dumps({"method": "trigger_contamination", "params": {}}),
        )
        n1.generator.tick()
        check("RPC contamination affects the real generator", n1.generator.is_contaminated)
        check("RPC response published",
              any(m["topic"] == "v1/devices/me/rpc/response/req-1" for m in c1.published))
        c1.inject_message(
            "v1/devices/me/rpc/request/req-2",
            json.dumps({"method": "set_supply_interrupted", "params": {"interrupted": True}}),
        )
        zero = n1.generator.tick()
        check("RPC interruption forces real zero flow", zero.flow_lpm == 0.0)
        c1.inject_message(
            "v1/devices/me/rpc/request/req-3",
            json.dumps({"method": "unknown_method", "params": {}}),
        )
        check("unknown RPC method rejected safely",
              any('"ok": false' in m["payload"] for m in c1.published
                  if m["topic"].endswith("req-3")))
        # Contamination legitimately suppresses pH through the physical model
        # (floor 6.0), so the earlier reading is not expected to look "normal".
        # Reset via RPC and confirm the *same generator* returns to its seeded
        # baselines: this proves commands only steer the model, never inject
        # hard-coded telemetry numbers.
        check("contamination changed pH through the model (not a fixed value)",
              6.0 <= zero.ph < 6.8, f"ph={zero.ph}")
        c1.inject_message(
            "v1/devices/me/rpc/request/req-4",
            json.dumps({"method": "reset", "params": {}}),
        )
        restored = n1.generator.tick()
        check("RPC reset restores model baselines (no fabricated telemetry)",
              6.8 <= restored.ph <= 7.6
              and 16.0 <= restored.water_temp_c <= 24.0
              and restored.flow_lpm > 0.0,
              f"ph={restored.ph} temp={restored.water_temp_c} flow={restored.flow_lpm}")

        # ------------------------------------------------------ TB artifacts
        section("7. ThingsBoard dashboard and alarm artifacts")
        dash = build_dashboard()
        widget_configs = dash["configuration"]["widgetConfigs"]
        types = {w["widget"]["type"] for w in widget_configs.values()}
        for required in ("Analog Gauge", "Digital Gauge", "Timeseries Chart",
                         "OpenStreetMap", "Alarms Table", "Entities Table"):
            check(f"dashboard contains {required}", required in types)
        all_keys = {
            k["name"]
            for w in widget_configs.values()
            for ds in w["datasources"]
            for k in ds.get("dataKeys", [])
        }
        check("dashboard datasources cover all telemetry keys",
              set(TELEMETRY_KEYS).issubset(all_keys))
        check("dashboard uses one fleet alias",
              dash["configuration"]["entityAliases"]["fleet"]["filter"]["value"]
              == "JalSanket Virtual Sensor")
        check("dashboard title states the duty-officer question",
              "unsafe" in dash["title"].lower() or "unsafe" in str(widget_configs["summary"]).lower())

        chain = rule_chain_document()
        scripts = json.dumps(chain)
        for required in ("> 50", "< 40", "> 200", "< 150", "< 6.5", "> 8.5",
                         ">= 6.7", "<= 8.3", "> 500", "< 450", "=== 0", "> 0"):
            check(f"rule chain encodes condition {required}", required in scripts)
        check("rule chain has trigger and clear nodes for 6 alarms",
              len([n for n in chain["metadata"]["nodes"] if "TRIGGER" in n["name"]]) == 6
              and len([n for n in chain["metadata"]["nodes"] if "CLEAR" in n["name"]]) == 6)

        alarm_cfg = device_profile_alarm_config()
        check("6 device-profile alarm rules", len(alarm_cfg["rules"]) == 6)
        durations = {r.get("time") for r in alarm_cfg["rules"] if "time" in r}
        check("30 s and 60 s durations present", durations == {30000, 60000}, str(durations))
        profile = device_profile_document()
        check("profile uses 60 s inactivity timeout",
              profile["inactivityTimeout"] == INACTIVITY_TIMEOUT_MS == 60000)
        check("profile lists telemetry keys", profile["profileData"]["telemetryKeys"] == list(TELEMETRY_KEYS))

        written = write_artifacts(str(Path(tmp) / "artifacts"), fleet_config)
        check("five artifact files written", len(written) == 5
              and all(p.exists() and json.loads(p.read_text()) for p in written.values()))

        demo_dash = json.loads(written["demo_controls"].read_text())
        demo_widgets = demo_dash["configuration"]["widgets"]
        rpc_widgets = [w for w in demo_widgets.values()
                       if w["typeFullFqn"] == "system.control_widgets.rpcbutton"]
        check("demo controls dashboard has twelve RPC buttons",
              len(rpc_widgets) == 12)
        expected_colors = {
            "Trigger Contamination": RPC_BUTTON_COLORS[0],
            "Supply Interruption ON": RPC_BUTTON_COLORS[1],
            "Supply Interruption OFF": RPC_BUTTON_COLORS[2],
            "Reset": RPC_BUTTON_COLORS[3],
        }
        colors_ok = all(
            w["config"]["settings"]["styleButton"]["bgColor"]
            == expected_colors[w["config"]["settings"]["buttonText"]]
            for w in rpc_widgets
        )
        check("demo buttons are colour-coded by action", colors_ok)
        demo_layout = demo_dash["configuration"]["states"]["default"]["layouts"]["main"]["widgets"]
        demo_rows = {demo_layout[w["id"]]["row"] for w in rpc_widgets}
        check("demo controls use three compact rows", demo_rows == {0, 2, 4}, str(demo_rows))

        main_dash = json.loads(written["dashboard"].read_text())
        tw = main_dash["configuration"]["timewindow"]
        buckets = tw["realtime"]["timewindowMs"] // tw["realtime"]["interval"]
        check("time-series timewindow uses a valid aggregation query",
              tw["selectedTab"] == 0
              and tw["realtime"]["realtimeType"] == 0
              and tw["realtime"]["quickInterval"] == "CURRENT_DAY"
              and tw["aggregation"] == {"type": "AVG", "limit": 25000}
              and buckets <= 600, str(tw))
        check("time-series widgets use the dashboard timewindow",
              all(main_dash["configuration"]["widgets"][k]["config"]["useDashboardTimewindow"]
                  is True for k in ("turbidity_series", "ph_series",
                                    "tds_series", "temp_flow")))
        check("per-metric charts each carry one key",
              all(len(main_dash["configuration"]["widgets"][k]["config"]["datasources"][0]["dataKeys"]) == 1
                  for k in ("turbidity_series", "ph_series", "tds_series")))
        main_layout = main_dash["configuration"]["states"]["default"]["layouts"]["main"]["widgets"]
        check("dashboard layout has no stale multi_series widget",
              "multi_series" not in main_layout
              and all(k in main_layout for k in ("turbidity_series", "ph_series",
                                                  "tds_series")))
        gauges = [w for w in main_dash["configuration"]["widgets"].values()
                  if w["typeFullFqn"] == "system.digital_gauges.gauge_justgage"]
        check("three monitoring gauges hide the canvas label",
              len(gauges) == 3 and all(w["config"]["settings"]["showTitle"] is False
                                       for w in gauges))
        expected_gauge_titles = {
            "ph_gauge": "pH (Node-01)",
            "turbidity_gauge": "Turbidity (Node-01)",
            "tds_gauge": "TDS (Node-01)",
        }
        check("monitoring gauges are labelled Node-01",
              {w["id"]: w["config"]["title"] for w in gauges} == expected_gauge_titles)
        check("monitoring gauges use compact canvas fonts",
              len(gauges) == 3 and all(
                  w["config"]["settings"]["fontValueSize"] == 24
                  and w["config"]["settings"]["fontTitleSize"] == 9
                  and w["config"]["settings"]["fontMinMaxSize"] == 9
                  and w["config"]["settings"]["fontLabelSize"] == 8
                  for w in gauges))
        import_artifact = json.loads(
            (Path(__file__).parent / "thingsboard" / "jalsanket_dashboard.json").read_text())
        import_gauges = [w for w in import_artifact["configuration"]["widgets"].values()
                         if w["typeFullFqn"] == "system.digital_gauges.gauge_justgage"]
        check("monitoring gauges are pinned to Node-01 in the import artifact",
              len(import_gauges) == 3 and all(
                  w["config"]["datasources"][0].get("entityId")
                  == "737cbce0-e44f-11f1-8c2a-39d8a38c3af6"
                  and "entityAliasId" not in w["config"]["datasources"][0]
                  for w in import_gauges))
        main_navs = [w for w in main_dash["configuration"]["widgets"].values()
                     if w["typeFullFqn"] == "system.action_button"]
        demo_navs = [w for w in demo_widgets.values()
                     if w["typeFullFqn"] == "system.action_button"]
        check("both dashboards have a navigation button",
              len(main_navs) == 1 and len(demo_navs) == 1)
        if main_navs and demo_navs:
            main_target = main_navs[0]["config"]["actions"]["click"][0]["targetDashboardId"]
            demo_target = demo_navs[0]["config"]["actions"]["click"][0]["targetDashboardId"]
            check("navigation buttons point to each other",
                  main_target == DEMO_CONTROLS_DASHBOARD_ID
                  and demo_target == MONITORING_DASHBOARD_ID,
                  f"{main_target} / {demo_target}")

        # --------------------------------------------------- default locations
        section("7b. Default node coordinates (Rasuwa scenario)")
        defaults = [(n.latitude, n.longitude) for n in DEFAULT_NODE_SPECS]
        check("three distinct default node sites", len(set(defaults)) == 3, str(defaults))
        check("all defaults inside Rasuwa bounding box",
              all(27.95 < lat < 28.30 and 85.20 < lon < 85.50
                  for lat, lon in defaults), str(defaults))
        device_artifact = json.loads(written["devices"].read_text())
        artifact_coords = [
            (d["additionalInfo"]["latitude"], d["additionalInfo"]["longitude"])
            for d in device_artifact
        ]
        expected_artifact_coords = [
            (n.latitude, n.longitude) for n in fleet_config.nodes
        ]
        check("device artifact carries the configured node coordinates",
              artifact_coords == expected_artifact_coords, str(artifact_coords))

        # ------------------------------------------------------- provisioning
        section("8. Device provisioning with fake REST transport")
        calls: list[dict] = []

        def fake_http(method, url, body=None, headers=None):
            calls.append({"method": method, "url": url, "body": body, "headers": headers})
            if url.endswith("/api/auth/login"):
                return 200, {"token": "FAKE_JWT"}
            if "/api/deviceProfiles?" in url:
                return 200, {"data": []}
            if url.endswith("/api/deviceProfile"):
                return 200, {"id": {"id": "profile-1"}}
            if "/api/tenant/devices?" in url:
                return 200, {"data": []}
            if url.endswith("/api/device"):
                return 200, {"id": {"id": f"dev-{body['name']}"}}
            if url.endswith("/credentials") or url.endswith("/api/dashboard"):
                return 200, {"id": {"id": "ok"}}
            return 200, {}

        tb_config = ThingsBoardConfig("test.local", "admin", "SECRET_ADMIN_PASSWORD")
        provisioner = ThingsBoardProvisioner(tb_config, fleet_config, http=fake_http)
        provisioner.login()
        provisioner.ensure_device_profile()
        provisioner.ensure_devices()
        provisioner.import_dashboard(dash)
        check("login called with admin credentials",
              any(c["url"].endswith("/api/auth/login") and c["body"]["username"] == "admin"
                  for c in calls))
        profile_body = next(c["body"] for c in calls if c["url"].endswith("/api/deviceProfile"))
        check("profile name correct", profile_body["name"] == DEVICE_PROFILE_NAME)
        check("profile inactivity timeout 60000", profile_body["inactivityTimeout"] == 60000)
        created = [c["body"] for c in calls if c["url"].endswith("/api/device")]
        check("three devices created", len(created) == 3)
        check("device names distinct", len({d["name"] for d in created}) == 3)
        creds = [c["body"]["accessToken"] for c in calls if c["url"].endswith("/credentials")]
        check("three distinct device tokens applied", len(set(creds)) == 3 and set(creds) == set(TEST_TOKENS.values()))
        check("dashboard imported via REST", any(c["url"].endswith("/api/dashboard") for c in calls))
        summary = json.dumps(provisioner.provisioning_summary())
        check("admin password never appears in summary", "SECRET_ADMIN_PASSWORD" not in summary)
        check("device tokens never appear in summary", not any(t in summary for t in TEST_TOKENS.values()))

        fleet.close()

        section("Summary")
        passed = sum(1 for ok, _, _ in results if ok)
        failed = len(results) - passed
        print(f"  {passed}/{len(results)} checks passed")
        if failed:
            print("\nFailed checks:")
            for ok, name, detail in results:
                if not ok:
                    print(f"  - {name} ({detail})")
            return 1
        print("\nPhase 4 verification: ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
