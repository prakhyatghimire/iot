# Dashboard UX revision report

Scope: dashboard UX/information architecture only. No Python simulator, SQLite
buffer, MQTT/TLS transport, alarm logic, telemetry generation, RPC code, device
identity, token or Cloud alarm-rule behaviour was changed.

Live dashboard kept: `8626a700-e451-11f1-8c2a-39d8a38c3af6`
Fleet alias preserved: `JalSanket Fleet`, id `2ea433e1-1bb5-76cd-daee-b4c348e7e6b8`
Generated artifact: `thingsboard/jalsanket_dashboard.json`
Report date: 2026-11-23

## 1. Exact dashboard changes

- Replaced the old text prompt (`summary`) and entities table (`fleet_health`)
  with two dynamic markdown cards:
  - `system_status` — overall SAFE / WARNING / CRITICAL / OFFLINE banner with a
    one-line count of safe, warning, critical and offline locations.
  - `node_status` — one card each for Dhunche, Syafrubesi and Rasuwagadhi showing
    only overall water status, active alarm, flow status and connectivity.
- Replaced `alarms` with `active_alerts`: ACTIVE-only alarm table, severity-first
  sort (`-severity`), five rows per page, custom one-line human-readable cell
  (`CRITICAL — Syafrubesi — Turbidity critically high (time)`), and a widget
  timewindow so the Cloud alarm subscription initialises correctly.
- Added `measurements_header`, a short section label separating operational
  detail from the first-screen status area.
- Reworked `node_map`: OpenStreetMap retained, with latitude/longitude still
  taken from existing timeseries keys; added label, colour and tooltip functions
  that show human location names plus explicit status words.
- Kept the three gauges pinned to Node-01 but changed their visible titles to
  `pH — Dhunche`, `Turbidity — Dhunche` and `TDS — Dhunche`. Their JustGage
  settings were restored to the descriptor's nested font objects and required
  `levelColors: []`, eliminating live `Widget Error` failures.
- Kept the four separate time-series widgets, but gave the turbidity/pH/TDS
  charts one datasource per location with legend names Dhunche, Syafrubesi and
  Rasuwagadhi. The mixed-scale `multi_series` widget remains removed.
- Kept the dashboard timewindow at 10 s aggregation over one hour (360 buckets).
- Kept the stock `system.action_button` navigation to the separate
  demo-controls dashboard (`19cf5c70-e69d-11f1-855e-4d781d6baffc`); that
  dashboard still has its twelve RPC buttons and was not repurposed.

## 2. Hierarchy used

1. `JalSanket Water Safety System` (dashboard title)
2. `Overall system status` — one banner, row 0
3. `Monitoring locations / node status` — three location cards, row 3
4. `Active alerts requiring attention` and `Location overview (OpenStreetMap)` —
   side by side, row 8
5. `Water-quality and operational measurements` — section label, row 15
6. Gauges (row 16), per-metric trends (row 21), temperature/flow (row 26)
7. Navigation button (row 31)

The first viewport therefore answers: is the system safe, which location has the
problem, how serious is it, and what needs attention. History and raw values
are lower on the page.

## 3. Widgets added, removed and rearranged

| Change | Widget ids | Placement |
| --- | --- | --- |
| Added | `system_status` | 24 × 3 at row 0, col 0 |
| Added | `node_status` | 24 × 5 at row 3, col 0 |
| Added | `active_alerts` | 12 × 7 at row 8, col 0 |
| Added | `measurements_header` | 24 × 1 at row 15, col 0 |
| Removed | `summary`, `fleet_health`, `alarms` | old rows 0–2 and 22 |
| Reworked | `node_map` | 12 × 7 at row 8, col 12 |
| Reworked | `ph_gauge`, `turbidity_gauge`, `tds_gauge` | 8 × 5 at row 16 |
| Reworked | `turbidity_series`, `ph_series`, `tds_series` | 8 × 5 at row 21 |
| Moved | `temp_flow` | 24 × 5 at row 26 |
| Moved | `nav_to_demo_controls` | 6 × 1 at row 31, col 9 |

The final layout contains 13 widgets and no stale `summary`, `fleet_health`,
`alarms` or `multi_series` entries.

## 4. Usability improvements

- Duty officers see a status word, never colour alone: SAFE, WARNING, CRITICAL
  and OFFLINE appear in the banner, node cards and map labels.
- Primary labels are Dhunche, Syafrubesi and Rasuwagadhi; device IDs, MQTT
  topics, database terms and raw telemetry keys are not used as primary UI text.
- Status semantics are consistent: `safetyStatus = UNSAFE` becomes CRITICAL,
  `WARNING` stays WARNING, and `active = false` becomes OFFLINE, with the last
  flow reading clearly marked as historical when offline.
- CRITICAL alerts sort above MAJOR/WARNING and get a stronger red badge;
  warnings use orange and informational alerts use blue.
- The map marker for an unsafe location says `Syafrubesi — CRITICAL`, so the
  location needing attention is identifiable without decoding colours.
- Detailed gauges and trends sit below the operational overview; gauges are
  explicitly scoped to Dhunche and the trends keep one y-axis per metric so pH
  is not visually flattened by the NTU/ppm scales.

## 5. Validation results

- `python3 -m compileall -q jalsanket *.py` — passed.
- `verify_phase1.py`, `verify_phase2.py`, `verify_phase3.py`,
  `verify_metrics.py` — all passed; no backend regression.
- `verify_phase4.py` — 117/117 checks passed, including the new UX assertions:
  no stale widgets, hierarchy order, labelled status-card values, explicit
  severity words, ACTIVE/sorted custom alert cell, map label function, nested
  gauge fonts with `levelColors`, preserved fleet alias, valid timewindow,
  per-location chart legends and human-readable gauge titles.
- Live REST verification of dashboard `8626a700-...`: 13 expected widget ids,
  preserved alias id, dashboard timewindow unchanged, alert widget timewindow
  present, three location-named chart datasources, map functions present.
- Fresh Cloud page load: no console errors and no `Widget Error` text; three
  gauge canvases and three map markers rendered.
- Live snapshot after restarting the existing simulator:
  `SYSTEM STATUS: CRITICAL`, `3 locations · 2 safe · 0 warning · 1 critical ·
  0 offline`; Dhunche SAFE, Syafrubesi CRITICAL, Rasuwagadhi SAFE; flows and
  connectivity were read from existing live values. No readings or alarms were
  invented.
- Map coordinates verified from existing telemetry: Dhunche 28.1100/85.2900,
  Syafrubesi 28.0920/85.3610, Rasuwagadhi 28.1710/85.3870.
- Active-alert widget was probed earlier with a real CRITICAL alarm and rendered
  `CRITICAL — Dhunche — Dissolved solids too high (time)`; the live tenant is
  currently out of alarm quota, so the screenshots show the configured empty
  state (`No alarms found`) rather than a fabricated alarm.
- Temporary UX probe dashboard `e103e830-e722-11f1-855e-4d781d6baffc` was
  deleted (subsequent GET returned 404).

## 6. Screenshot paths

- `evidence/screenshots/dashboard_ux_first_viewport.png` — status banner, three
  location cards, active-alert area and map in the first screen.
- `evidence/screenshots/dashboard_ux_alerts_map.png` — active alerts and the
  OpenStreetMap location overview with status-labelled markers.
- `evidence/screenshots/dashboard_ux_measurements_trends.png` — gauges and the
  lower detailed trends/flow section.

## 7. ThingsBoard limitations and notes

- The tenant has hit its Cloud alarm quota (`alarms: 201 / maxAlarms: 200`,
  billing period ending 2026-12-18). Threshold violations are logged in Alarm
  Rules → Events debug rows and `evidence/metrics/raw_cloud_alarms.csv`, but new
  active alarms cannot be created until the quota resets. Clearing old alarms
  does not reset the created-alarms counter. The dashboard's status cards still
  derive CRITICAL from the real `safetyStatus` attribute.
- Agent-side WebSocket subscriptions to
  `wss://eu.thingsboard.cloud/ws/plugins/telemetry?token=...` fail in this
  environment, so agent verification used fresh authenticated page loads and
  REST reads. The user's browser receives realtime updates normally.
- ThingsBoard markdown cards expose data values under each data key's configured
  **label** (for example `Connectivity`, `Water status`, `Flow`), not the raw key
  name; the card functions accept both forms so the widget keeps human-readable
  internal labels.
- The Cloud JustGage descriptor requires `levelColors` and uses nested font
  objects (`titleFont`, `valueFont`, `minMaxFont`, `labelFont`); the previous flat
  font keys caused runtime widget errors and were removed.
- CE-shaped rule-chain/alarm artifacts remain local reference/regression files.
  Live alarm behaviour is defined by the six existing Cloud Alarm Rules 2.0 and
  was not changed.
- The live tenant JWT was read from the authenticated browser's
  `localStorage.jwt_token` only in page memory for REST calls; it was never
  written to a file or command output and the in-page variable was cleared after
  each call.
