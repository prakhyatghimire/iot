# Dashboard information-architecture revision report

Report date: 2026-11-25  
Live dashboard preserved: `8626a700-e451-11f1-8c2a-39d8a38c3af6`  
Live fleet alias preserved: `JalSanket Fleet`, id `2ea433e1-1bb5-76cd-daee-b4c348e7e6b8`

## 1. Current hierarchy before the change

Inspected live Cloud REST and local artifacts:

- Tenant `6ff10c20-e2f1-11f1-a2b8-99b86090d117` owns three devices directly:
  - `JalSanket-Node-01` (`737cbce0-e44f-11f1-8c2a-39d8a38c3af6`)
  - `JalSanket-Node-02` (`8090ab30-e44f-11f1-b835-cf86ca25bc9f`)
  - `JalSanket-Node-03` (`81265b80-e44f-11f1-b835-cf86ca25bc9f`)
- One device profile: `JalSanket Water Quality Node`.
- Six Cloud Alarm Rules 2.0 are attached to the device profile, not to a location.
- Dashboard alias `JalSanket Fleet` is a flat `entityList` of the three device IDs.
- `GET /api/customers`, `/api/tenant/assets` and relation queries returned no
  Customer, Asset or relation entities.
- Dhunche / Syafrubesi / Rasuwagadhi existed only as labels in dashboard JS and
  as timeseries latitude/longitude values; they were not ThingsBoard entities.

## 2. Problems found

- Device names and IDs were the only Cloud-level structure; a user had to infer
  which water source a device belonged to.
- No area or owner context was visible, so "who is responsible" and "which area"
  were unanswered.
- Alarms were device-profile events, not location/area events.
- The dashboard alias treated the nodes as an unrelated fleet list.
- Detailed measurements competed with status information rather than sitting
  clearly below it.
- There was no duty-officer role; only the tenant administrator exists.

## 3. New hierarchy

Demonstration hierarchy shown in the dashboard:

```text
Municipal Water Monitoring Authority (demonstration)
        ↓
Rasuwa Monitoring Area
        ├── Dhunche water source → JalSanket Node 01 → ph, turbidity_ntu,
        │                                           tds_ppm, water_temp_c,
        │                                           flow_lpm, latitude, longitude
        │                                           → alarms/events
        ├── Syafrubesi water source → JalSanket Node 02 → same keys → alarms
        └── Rasuwagadhi water source → JalSanket Node 03 → same keys → alarms
```

The authority/area are explicitly labelled `demonstration hierarchy`; no real
municipal ownership or sensor deployment is claimed.

## 4. How ownership / role is represented

- Dashboard title and status banner name the authority model and area.
- Tenant ownership remains the real Cloud ownership; no Customer/User entities
  were invented and no credentials or tokens were created.
- The interface is written for one municipal duty-officer / monitoring-operator
  view: status → location → node → alarm → detail.
- Tenant limits report `maxAssets: 0`, `maxCustomers: 0`, `maxUsers: 0`, so a
  real multi-role Customer/Asset tree is not available on this plan.

## 5. How area → location → node relationships are represented

- Area: dashboard title, banner, alert table title, map title and map tooltip.
- Location ↔ node: explicit subtitle on each status card, e.g.
  `Water source · JalSanket Node 02`.
- Location is primary text; `JalSanket-Node-02` is secondary context, never the
  main label.
- Existing fleet alias still resolves to the three exact devices; its internal
  name/id were preserved.
- Per-location chart datasources and map/tooltip functions repeat the human
  location name, so the mental model is consistent across widgets.
- No ThingsBoard relation entities were fabricated.

## 6. Dashboard information hierarchy

| Level | Widget area | Row | Question answered |
| --- | --- | --- | --- |
| 1 | `JalSanket Water Safety · Rasuwa Monitoring Area` | 0 | Is the area safe? |
| 2 | `Monitoring locations / water sources → JalSanket nodes` | 4 | Which source has a problem? |
| 3 | Active alerts + area map | 9 | Severity, cause and where? |
| 4 | `Selected location / node details → measurements → trends` + pH / turbidity / TDS gauges | 16–17 | Current sensor values and safe/out-of-range state? |
| 5 | Trends and temperature/flow | 22–27 | Historical/technical detail |
| — | Navigation to demo controls | 32 | Separate RPC scenario controls |

The first viewport shows owner/area context, system status, all three location
cards, ACTIVE alerts and the map.

## 7. Widgets removed / rearranged / renamed

- Removed: **none**. All 13 widgets and all required functionality remain.
- Restored all three current readings as real JustGage dials after the assignment
  requirement. Each gauge shows the live value, unit, min/max numbers and tick
  marks at the existing alarm thresholds. Its arc is green inside the safe range
  and red outside it; turbidity uses dark red for the critical band above 200
  NTU. No widget was added and no telemetry or alarm threshold was derived.
- Renamed:
  - `system_status` → `JalSanket Water Safety · Rasuwa Monitoring Area`
  - `node_status` → `Monitoring locations / water sources → JalSanket nodes`
  - `active_alerts` → `Active alerts requiring attention · Rasuwa area`
  - `node_map` → `Rasuwa area — water sources (OpenStreetMap)`
  - `measurements_header` → `Selected location / node details → measurements → trends`
  - pH / turbidity / TDS gauges → `pH/Turbidity/TDS — Dhunche (Node 01)`
- Rearranged: system banner grew from 3 to 4 rows; node status moved from row 3
  to 4, alerts/map 8→9, measurements header 15→16, gauges 16→17, trends
  21→22, temperature/flow 26→27 and navigation 31→32. Ordering is unchanged.
- No charts or decorative widgets were added.

## 8. ThingsBoard Cloud limitations

- No Customer, Asset, User or relation records exist; tenant limits are zero.
- Real owner/role hierarchy and duty-officer access control cannot be created
  without a provisioning/application change, so it was not attempted.
- Alarm quota remains exhausted (`201 / 200`, billing period ends 2026-12-18),
  so ACTIVE alarm rows are empty in screenshots; no alarms were fabricated.
- Agent-side WebSocket subscriptions fail in this environment; verification used
  fresh authenticated page loads and REST reads.
- Static device attributes still hold older `27.x` coordinates; the map uses the
  existing telemetry `latitude`/`longitude` (`28.1100`, `28.0920`, `28.1710`).
- CE-shaped `jalsanket_rule_chain.json` / `jalsanket_alarm_config.json` remain
  local regression references only; live behaviour is the six Cloud Alarm Rules.

## 9. Exact files changed

- `jalsanket/dashboard.py` — presentation hierarchy, titles, widget rows, gauge
  settings and colour bands.
- `thingsboard/jalsanket_dashboard.json` — regenerated Cloud import artifact.
- `verify_phase4.py` — hierarchy, demonstration-label and node-pairing assertions.
- `README.md` — updated dashboard hierarchy description.
- `evidence/dashboard_ux_revision_report.md` — pointer to this authoritative report.
- This report and six screenshots below.

No provisioning, telemetry, storage, MQTT, alarm or RPC source file was changed.

## 10. Verification results

- `python3 -m compileall -q jalsanket *.py` — passed.
- `verify_phase1.py` — 31/31 passed.
- `verify_phase2.py` — 45/45 passed.
- `verify_phase3.py` — 63/63 passed.
- `verify_metrics.py` — 29/29 passed.
- `verify_phase4.py` — 127/127 passed (including all three threshold-gauge checks).
- Live REST after save: title `JalSanket Water Safety — Rasuwa Monitoring Area`,
  13 widgets, alias id `2ea433e1-1bb5-76cd-daee-b4c348e7e6b8`, six alarm rules,
  three unchanged device IDs.
- All seven existing telemetry keys returned values for all three devices, with
  coordinates `28.11/85.29`, `28.092/85.361`, `28.171/85.387`; no stale
  Kathmandu coordinates remain in the map datasource.
- Fresh Cloud page load: no console errors; banner showed owner/area context,
  `SYSTEM STATUS: CRITICAL`, and the overlay
  `CRITICAL ALERT — Rasuwa Monitoring Area / Syafrubesi (JalSanket Node 02) has unsafe water status. Immediate attention required.`
- Node cards showed `Dhunche · JalSanket Node 01`, `Syafrubesi · JalSanket Node 02`
  and `Rasuwagadhi · JalSanket Node 03`.
- Live REST after the gauge save returned 13 widgets and three
  `system.digital_gauges.gauge_justgage` widgets (`ph_gauge`, `turbidity_gauge`,
  `tds_gauge`) with the same alias id `2ea433e1-1bb5-76cd-daee-b4c348e7e6b8`.
- Each live gauge config kept `showValue`, `showMinMax`, `showTitle`,
  `showUnitTitle` and `showTicks` enabled. Tick values are `0/6.5/8.5/14` for
  pH, `0/50/200/300` for turbidity and `0/500/1000` for TDS; the in-gauge labels
  are `SAFE 6.5-8.5 pH`, `SAFE 0-50 NTU` and `SAFE 0-500 ppm`.
- Colour bands verified live: pH red below 6.5 and above 8.5 with green between;
  turbidity green to 50 NTU, red to 200 and dark red above 200; TDS green to
  500 ppm and red above. These only mirror existing alarm thresholds.
- Current Node-01 REST telemetry was pH `7.168` (shown as `7.17`), turbidity
  `6.07` (`6.1 NTU`) and TDS `195.0` (`195.0 ppm`), all inside the green bands.
  Three gauge canvases rendered with no console errors; pixel sampling confirmed
  green arcs for the safe readings. A red state was not forced live because that
  would require changing live telemetry or thresholds; the red bands are covered
  by `verify_phase4.py` and the saved Cloud configuration.

## 11. Screenshot paths

- `evidence/screenshots/dashboard_ia_first_viewport.png`
- `evidence/screenshots/dashboard_ia_alerts_map.png`
- `evidence/screenshots/dashboard_ia_details.png`
- `evidence/screenshots/dashboard_ph_led.png`
- `evidence/screenshots/dashboard_all_led_panels.png`
- `evidence/screenshots/dashboard_threshold_gauges.png`

## 12. Backend untouched

Yes. No change to telemetry generation, SQLite buffering, MQTT/TLS, QoS 1,
replay logic, alarm thresholds, RPC methods, fleet architecture, device tokens,
device identities or existing telemetry keys. Only the ThingsBoard dashboard
presentation layer, its generated JSON and verification/docs were changed.
