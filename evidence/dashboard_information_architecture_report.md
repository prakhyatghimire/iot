# Dashboard information-architecture revision report

Report date: 2026-11-25  
Live dashboard preserved: `8626a700-e451-11f1-8c2a-39d8a38c3af6`  
Live fleet alias preserved: `JalSanket Fleet`, current live id
`8ebfa76f-118a-c3c9-3670-92d61b84c911` (an earlier snapshot recorded
`2ea433e1-1bb5-76cd-daee-b4c348e7e6b8`; this change kept the existing live id).

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

## 7A. Water Safety Incident Mode

Incident Mode is a presentation state on the same 13 widgets; it is not a new
alarm engine, dashboard state, entity or RPC method. Normal monitoring remains
the default. A serious Critical/Major condition opens one fixed banner that
names the water source, JalSanket node and severity, then lists the breached
measurements and current values with units, the connectivity state, the other
sources and where the real trend charts continue the history.

The status cards and map markers reuse the existing `safetyStatus`, `active`,
`ph`, `turbidity_ntu`, `tds_ppm` and `flow_lpm` values. They use both the
existing alarm trigger thresholds and their clear bands (for example, a gross
contamination alarm remains active until turbidity is below 150 NTU) to confirm
that a stored unsafe status is still supported by current readings. A stale
`UNSAFE` attribute with normal readings is shown as `STALE / UNCONFIRMED` and
does not open an incident. Supply interruption with zero flow and a connected
node is shown as Major, not as offline. Multiple serious conditions on one node
are grouped into one banner.

The ACTIVE alerts table remains the evidence panel and uses only real
ThingsBoard alarm fields (`severity`, `originatorDisplayName`, type and real
detection time). No fake Customer, User, Asset, relation, alarm, telemetry
sample, timestamp or physical cause is introduced.

## 8. ThingsBoard Cloud limitations

- No Customer, Asset or relation records exist. Tenant users are platform
  accounts, not fabricated municipal roles or Asset hierarchy records.
- Real owner/role hierarchy and duty-officer access control would require a
  provisioning/application change; no fake Customer/User/Asset entity was added.
  A real platform user was separately invited to the **Tenant Users** group.
- The live tenant currently has no alarm-generation path: the Root Rule Chain
  has no create/clear alarm node and the device profile has `alarms: []`. Alarm
  history contains 201 cleared records, but `statusList=ACTIVE` is empty. The
  alarm table is therefore an evidence panel only; no alarm was fabricated.
- `bufferDepth` is absent from all Cloud timeseries and attribute key lists, so
  no buffer-depth or replay count is shown. Exact incident timelines are not
  invented: only the existing trend charts and real alarm fields are used.
- This Cloud tenant disconnects MQTT with `rc=128` and no QoS 1 PUBACK when a
  replay message carries more than about ten data points, or when three nodes
  replay batches together. A stuck replay backlog therefore blocks live
  telemetry and demo RPCs, making contamination appear to have no effect. The
  runtime `.env` uses `MQTT_REPLAY_BATCH_SIZE=1` (documented in `.env.example`
  and the README); no transport or replay code was changed. With that setting
  the RPC reached the generator, Cloud telemetry updated and the dashboard
  opened the grouped Critical incident with real values, then recovered on
  Reset.
- Agent-side WebSocket subscriptions fail in this environment; verification used
  fresh authenticated page loads and REST reads.
- Static device attributes still hold older `27.x` coordinates; the map uses the
  existing telemetry `latitude`/`longitude` (`28.1100`, `28.0920`, `28.1710`).
- CE-shaped `jalsanket_rule_chain.json` / `jalsanket_alarm_config.json` remain
  local regression references only; live behaviour is the six Cloud Alarm Rules.

## 9. Exact files changed

- `jalsanket/dashboard.py` — presentation hierarchy, titles, widget rows, gauge
  settings, colour bands and Water Safety Incident Mode rendering.
- `thingsboard/jalsanket_dashboard.json` — regenerated Cloud import artifact.
- `verify_phase4.py` — hierarchy, demonstration-label and node-pairing assertions.
- `verify_incident_mode.py` — normal, contamination, supply, grouped alarms,
  stale-state, resolution, unaffected-node and preserved-widget checks.
- `README.md` — updated dashboard hierarchy and Incident Mode description.
- `evidence/dashboard_ux_revision_report.md` — pointer to this authoritative report.
- This report and the screenshots below.

No provisioning, telemetry, storage, MQTT, alarm or RPC source file was changed.

## 10. Verification results

- `python3 -m compileall -q jalsanket *.py` — passed.
- `verify_phase1.py` — 31/31 passed.
- `verify_phase2.py` — 45/45 passed.
- `verify_phase3.py` — 63/63 passed.
- `verify_metrics.py` — 29/29 passed.
- `verify_phase4.py` — 127/127 passed (including all three threshold-gauge checks).
- `verify_incident_mode.py` — 43/43 passed (normal, stale status, hysteresis
  bands, contamination, supply interruption, grouped alarms, unaffected sources
  and resolution, using the exact functions in the generated Cloud artifact).
- Live REST after the final save: title `JalSanket Water Safety — Rasuwa
  Monitoring Area`, 13 widgets, alias id
  `8ebfa76f-118a-c3c9-3670-92d61b84c911`, three unchanged device IDs, and the
  status/map datasources carry the existing measurement keys used by the guard.
- All seven existing telemetry keys returned values for all three devices, with
  coordinates `28.11/85.29`, `28.092/85.361`, `28.171/85.387`; no stale
  Kathmandu coordinates remain in the map datasource.
- Node cards showed `Dhunche · JalSanket Node 01`, `Syafrubesi · JalSanket Node 02`
  and `Rasuwagadhi · JalSanket Node 03` on a fresh page load with no console errors.
- Each live gauge config kept `showValue`, `showMinMax`, `showTitle`,
  `showUnitTitle` and `showTicks` enabled. Tick values are `0/6.5/8.5/14` for
  pH, `0/50/200/300` for turbidity and `0/500/1000` for TDS; the in-gauge labels
  are `SAFE 6.5-8.5 pH`, `SAFE 0-50 NTU` and `SAFE 0-500 ppm`.
- Colour bands verified live: pH red below 6.5 and above 8.5 with green between;
  turbidity green to 50 NTU, red to 200 and dark red above 200; TDS green to
  500 ppm and red above. These only mirror existing alarm thresholds.
- Incident Mode live exercise with the existing demo controls: normal state
  (`SYSTEM STATUS: SAFE`, no overlay), scripted contamination at Node 01
  (one grouped `CRITICAL WATER SAFETY INCIDENT`, real turbidity/TDS/pH values,
  `INCIDENT · Dhunche — CRITICAL` on the map), supply interruption at Node 02
  (`MAJOR WATER SAFETY INCIDENT`, zero flow with the node connected), then
  recovery (`No active water-safety incident` again). Each state was confirmed
  against REST telemetry/attributes and fresh page loads had no console errors.

## 11. Screenshot paths

Existing hierarchy/gauge evidence:

- `evidence/screenshots/dashboard_ia_first_viewport.png`
- `evidence/screenshots/dashboard_ia_alerts_map.png`
- `evidence/screenshots/dashboard_ia_details.png`
- `evidence/screenshots/dashboard_ph_led.png`
- `evidence/screenshots/dashboard_all_led_panels.png`
- `evidence/screenshots/dashboard_threshold_gauges.png`

Water Safety Incident Mode evidence:

- `evidence/screenshots/incident_normal.png`
- `evidence/screenshots/incident_contamination.png`
- `evidence/screenshots/incident_map.png`
- `evidence/screenshots/incident_supply.png`
- `evidence/screenshots/incident_resolved.png`

## 12. Backend untouched

Yes. No change to telemetry generation, SQLite buffering, MQTT/TLS, QoS 1,
replay logic, alarm thresholds, RPC methods, fleet architecture, device tokens,
device identities or existing telemetry keys. Only the ThingsBoard dashboard
presentation layer, its generated JSON and verification/docs were changed.
