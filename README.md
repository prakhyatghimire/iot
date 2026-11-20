# JalSanket – ITS67404 Assessment Task 3

Post-flood smart water-quality monitoring system for Nepal. This repository
contains **Phases 1–4** plus the live ThingsBoard Cloud integration: the Python
virtual ESP32-S3 telemetry generator, its SQLite store-and-forward buffer,
MQTT/TLS transport with confirmed QoS 1 delivery and buffered replay, and the
three-node fleet with Cloud provisioning, dashboard and alarm rules.

Architecture decision (fixed for the project): direct cellular path
`Python virtual edge node → SQLite → MQTT/TLS → ThingsBoard`. There is no
LoRaWAN gateway and no Node-RED.

## Phase 1 – Telemetry generator

### Layout

| Path | Purpose |
| --- | --- |
| `jalsanket/telemetry.py` | Physical model, `GeneratorConfig`, `Reading`, `TelemetryGenerator` |
| `jalsanket/storage.py` | SQLite WAL buffer, `StoreConfig`, `TelemetryStore` |
| `jalsanket/node.py` | `VirtualEdgeNode`: enforces generate → persist → publish ordering |
| `jalsanket/config.py` | Env-var/`.env` configuration, `MqttConfig` (no hardcoded secrets) |
| `jalsanket/mqtt_transport.py` | paho MQTT/TLS, QoS 1 confirmation, backoff, batched replay |
| `jalsanket/runner.py` | Non-blocking simulator main loop |
| `jalsanket/alarms.py` | Local evaluator with exact thresholds, hysteresis, sustained/inactive logic |
| `jalsanket/fleet.py` | Three independent nodes, tokens, coordinates, buffers and RPC control |
| `jalsanket/provisioning.py` | ThingsBoard Cloud device/profile/token/alarm REST provisioning client |
| `jalsanket/alarm_rules.py` | Generated Cloud Alarm Rules 2.0 and local reference rule-chain JSON |
| `jalsanket/dashboard.py` | Generated Cloud duty-officer dashboard JSON |
| `run_simulator.py` | Live entry point for one node (Phase 3) |
| `run_fleet.py` | Live entry point for the three-node fleet (Phase 4) |
| `jalsanket/__init__.py` | Public imports |
| `verify_phase1.py` | Repeatable demonstration and assertions for all Phase 1 requirements |
| `verify_phase2.py` | Persistence, ordering, sync-state, restart and buffer-capacity tests |
| `verify_phase3.py` | MQTT/TLS, QoS 1 confirmation, outage, reconnect and replay tests (fake client) |
| `verify_phase4.py` | Three-node separation, alarms, dashboard/rule-chain artifacts, RPC and provisioning (fake clients/REST) |

### Run it

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python verify_phase1.py
.venv/bin/python verify_phase2.py
.venv/bin/python verify_phase3.py
.venv/bin/python verify_phase4.py
```

Phases 1–2 use only the standard library. Phases 3–4 require `paho-mqtt` (2.x).

### Generated fields

`ph`, `turbidity_ntu`, `tds_ppm`, `water_temp_c`, `flow_lpm`, `latitude`,
`longitude`, plus `node_id` and an acquisition timestamp (`acquired_at`, UTC).

### Physical model

The generator keeps two clocks:

* **Simulation clock** in physical seconds – all physical constants are in
  real units.
* **Acquisition timestamp** in UTC – supplied by the caller (or the system
  clock) and recorded on every `Reading`.

`time_scale` (default `20`) maps physical seconds to wall-clock seconds so a
40-minute washout is observable in roughly two minutes of demonstration time.
It does not alter any physical constant.

**Correlation instead of independent randomness.** Three mean-reverting
Ornstein–Uhlenbeck latent drivers are shared across parameters:

* `runoff` (τ = 300 s) raises turbidity and TDS and slightly lowers pH;
* `flow_state` (τ = 120 s) drives normal flow variation;
* `temp_state` (τ = 900 s) adds smooth deviation around the diurnal cycle.

**Temperature.** `20 + 4·sin(2π(t − 6h)/86400) + smooth_noise`, clamped to
16–24 °C. It cannot jump between unrelated values.

**Contamination event** (triggered by `trigger_contamination()`):

A two-timescale pulse with rise τ = 120 s and washout τ = 2400 s:

```
envelope(u) = [e^(−u/τ_wash) − e^(−u/τ_rise)] / normalisation
```

The single envelope drives all four affected parameters:

* turbidity: rises from its baseline to ≈260 NTU;
* TDS: rises to ≈535 ppm;
* pH: falls via a Hill-type response toward a hard floor of 6.0 (non-linear,
  physically bounded);
* flow: a short +4 L/min inflow pressure surge followed by a mild sustained
  reduction.

The event peaks around 6 minutes after onset and washes out over tens of
minutes. These peaks are plausible for flood/runoff-impacted water and cross
the specified warning/critical alarm thresholds without fabricating values.

**Supply interruption.** `set_supply_interrupted(True)` forces flow to exactly
`0.0` L/min; clearing it restores normal flow.

**Repeatability.** `reset()` restores the seeded RNG and simulation clock.
`trigger_contamination()` and `set_supply_interrupted()` are explicit commands
so a scenario can be replayed identically. The remote MQTT RPC command
mechanism that calls these methods is implemented in Phase 4; it never
fabricates telemetry values.

### Configuration

All tunables live in `GeneratorConfig` in `jalsanket/telemetry.py`. Defaults
follow the assignment ranges:

| Parameter | Default |
| --- | --- |
| pH | 7.2 baseline, clamped 6.8–7.6 |
| Turbidity | 5.0 baseline, clamped 2–8 NTU |
| TDS | 185 baseline, clamped 120–250 ppm |
| Water temperature | 20 ± 4 °C (16–24) |
| Flow | 13 baseline, clamped 8–18 L/min |
| Sample interval | 2 s wall clock |
| Time scale | 20 physical s per wall s |
| Initial sim time | 21 600 s (06:00, temperature rising) |
| Seed | 42 |

### Decisions made in Phase 1 (please review)

These were not specified in the brief, so they were implemented as configurable
defaults rather than hard-coded assumptions:

1. **Demo time compression** via `time_scale = 20` while keeping the physical
   constants in real seconds.
2. **Peak contamination values** (260 NTU, 535 ppm) and a **pH floor of 6.0**,
   chosen to be physically plausible while crossing the alarm thresholds.
3. **Seed = 42** and explicit command methods for repeatability; remote
   triggering added in Phase 4 as MQTT RPC commands over the real generator.
4. **Static GPS coordinates** per node (jitter not required by the brief);
   three distinct Rasuwa water-source sites assigned in Phase 4.

## Phase 2 – SQLite store-and-forward

### Decisions approved by the project owner

| Setting | Value | Reason |
| --- | --- | --- |
| Maximum buffer capacity | **10,800 unsynchronised rows** (6 h at 2 s sampling) | Covers a realistic cellular outage; small on disk; configurable for the demo |
| Eviction policy | **drop-newest** | Never deletes already-buffered unsynchronised rows, so it honours "do not delete unsynchronised data". The rejected reading is recorded as a durable loss event |

Capacity applies to the *unsynchronised backlog*. Synchronised rows are retained
for audit and future metrics; they are never silently deleted.

### How it works

`VirtualEdgeNode.tick()` performs, in this exact order:

1. `TelemetryGenerator.tick()` generates a reading.
2. `TelemetryStore.persist()` writes it to SQLite inside a transaction.
3. Only afterwards does transport publish it (Phase 3).

Transport reads rows via `get_unsynced_batch()` and calls `mark_synced()`
**only after confirmed QoS 1 delivery**.

### Time semantics

The database deliberately separates clocks so later latency measurements stay
valid:

| Column | Source | Meaning |
| --- | --- | --- |
| `acquisition_ms` | `Reading.acquired_at` | Original acquisition time (real UTC in live operation); preserved on replay |
| `stored_at_ms` | `time.time()` at INSERT | Real wall-clock time the row reached SQLite |
| `synced_at_ms` | `time.time()` at confirmation | Real wall-clock time the row was confirmed delivered |

The generator's simulated/scenario clock is intentionally **not** stored in the
database, so it cannot be mistaken for measurement time.

### Schema and durability

* `readings` table with sync flag, retry counters and last error.
* `loss_events` table records every eviction with a reason and timestamp.
* WAL journal mode with `synchronous=FULL`.
* Indexes on `(synced, acquisition_ms, id)` and
  `(node_id, synced, acquisition_ms, id)` for chronological replay.
* Default database path `data/jalsanket.db` (git-ignored).

Console logs report every store with `buffer_depth` and `capacity`, every
eviction as a `BUFFER FULL - DROPPING NEWEST` warning, and every sync with
`rows_flushed` and `remaining_rows`.

## Phase 3 – MQTT/TLS transport, confirmation and replay

### Credentials (never committed)

Supply these as exported environment variables or in a git-ignored `.env` file
at the project root. Copy `.env.example` to `.env` and fill in real values.

| Variable | Required | Purpose |
| --- | --- | --- |
| `TB_HOST` | yes | ThingsBoard Cloud MQTT hostname (HTTPS REST defaults to it) |
| `TB_MQTT_PORT` | no (8883) | Assignment mandates TLS on 8883; other values are rejected |
| `TB_REST_HOST` | no (`TB_HOST`) | Cloud REST hostname; HTTPS uses 443 |
| `TB_HTTP_SCHEME` / `TB_HTTP_PORT` | no (`https` / `443`) | Cloud REST URI settings |
| `TB_DEVICE_TOKEN` | yes for single-node use | Access token for one device; the fleet uses the three variables in Phase 4 |
| `TB_NODE_01_TOKEN` / `TB_NODE_02_TOKEN` / `TB_NODE_03_TOKEN` | yes for fleet | Distinct Cloud access tokens; never committed |
| `TB_REST_JWT` | no | Optional tenant REST JWT for `--provision`; Cloud UI session may be used instead |
| `TB_CA_CERT` | no | CA PEM path; defaults to the OS trust store |
| `MQTT_CLIENT_ID` | no | Derived from the node ID if omitted |
| `MQTT_RECONNECT_MIN_DELAY_S` | no (2) | Backoff floor |
| `MQTT_RECONNECT_MAX_DELAY_S` | no (60) | Backoff ceiling |
| `MQTT_REPLAY_BATCH_SIZE` | no (20) | Rows per replay publish |
| `MQTT_PUBLISH_TIMEOUT_S` | no (30) | Time without PUBACK before retrying |

TLS uses `ssl.create_default_context()` and certificate verification is never
disabled. Logs use `MqttConfig.safe_summary()`, which never contains the token.

### Confirmed delivery guarantee

`publish()` alone changes no database state. The **only** call to
`mark_synced()` is inside `_on_publish()`, which paho invokes after the broker's
QoS 1 PUBACK. All live and replay messages use QoS 1 on
`v1/devices/me/telemetry`.

### Reliability behaviour

* Blocking `connect()` plus explicit `loop_read()`/`loop_write()`/`loop_misc()`
  on the simulator thread — no background thread, so generation never blocks or
  crashes on network errors. These explicit network-loop calls are required for
  live paho 2.x TLS connections to ThingsBoard Cloud.
* Distinct log messages for successful connection/reconnect, authentication
  failure (CONNACK 5/135/137), network/connect failure, outage, reconnect
  attempt, publish confirmation, replay batch, and final buffer depth.
* Backoff doubles from 2 s to a 60 s ceiling with small jitter; authentication
  failures go straight to the maximum delay. The first eligible pump schedules
  the delay and a later pump makes the attempt, so `connect()` is never called
  on a socket that is still live.
* After reconnect, unsynchronized rows are replayed chronologically in
  configurable batches using their original `acquisition_ms`. Replay continues
  until the buffer is empty or a publish fails.
* During an outage the simulator keeps generating and persisting; buffered
  depth and capacity are logged on every row.

### Verification

`verify_phase3.py` uses an injectable fake MQTT client — no real credentials
are needed and no token is invented. Verified: 50/50 checks including no-early-
sync-before-PUBACK, auth vs network distinction, backoff sequence
2,4,8,16,32,60,60,60, outage buffering, automatic reconnect, 3 chronological
replay batches preserving original timestamps, and local publish failure.

## Phase 4 – Three nodes and ThingsBoard Cloud

### Three independent nodes

`Fleet` builds `node-01`, `node-02` and `node-03`, each with its own device
identity, access token, coordinates, SQLite database and MQTT client. One node
going offline or replaying does not affect the others. All three share one
non-blocking main loop (`FleetRunner.step()`).

| Node | Device name | Area | Coordinates | Token variable |
| --- | --- | --- | --- | --- |
| `node-01` | JalSanket-Node-01 | Dhunche | 28.1100, 85.2900 | `TB_NODE_01_TOKEN` |
| `node-02` | JalSanket-Node-02 | Syafrubesi | 28.0920, 85.3610 | `TB_NODE_02_TOKEN` |
| `node-03` | JalSanket-Node-03 | Rasuwagadhi area | 28.1710, 85.3870 | `TB_NODE_03_TOKEN` |

These are demonstration positions around different Rasuwa water-source sites,
chosen to match the post-flood Rasuwa/Nuwakot scenario; they are not survey data
or a claim that sensors are installed at these exact points. The coordinates
are defined once in `DEFAULT_NODE_SPECS` in `jalsanket/fleet.py`, flow through
`GeneratorConfig` into every SQLite reading and telemetry payload (and the
client-side attribute publication), and therefore drive the dashboard's
OpenStreetMap markers without any manual ThingsBoard edits. After a fleet run,
the Cloud values can be confirmed with `evidence/live_cloud_coordinates.json`,
which records the latest latitude/longitude timeseries per device (no JWT).
The older `evidence/live_cloud_attributes.json` and `live_fleet_*.log` files are
historical snapshots from before this coordinate change; they are kept as-is as
a record and are not the current source of truth.

Coordinates can be overridden with `NODE_01_LAT/LON`, etc. Tokens are never
hard-coded: they are read from environment variables or a git-ignored `.env`,
and all three must be distinct.

### ThingsBoard Cloud configuration

`run_fleet.py` always writes four artifacts to `thingsboard/`:

* `jalsanket_dashboard.json` – importable Cloud dashboard
* `jalsanket_rule_chain.json` – local reference rule chain (CE-shaped)
* `jalsanket_alarm_config.json` – local reference alarm rules (CE-shaped)
* `jalsanket_devices.json` – desired Cloud device documents

The live tenant was configured in the logged-in Cloud browser session: device
profile `JalSanket Water Quality Node`, devices `JalSanket-Node-01/02/03`,
three distinct access tokens, a `60000` ms `inactivityTimeout` SERVER_SCOPE
attribute on each device, six Alarm Rules 2.0 definitions bound to the profile,
and the nine-widget duty-officer dashboard. REST uses HTTPS/443 via
`TB_REST_HOST`, `TB_HTTP_SCHEME` and `TB_HTTP_PORT`; MQTT remains TLS/8883 via
`TB_HOST`. `--provision` accepts `TB_REST_JWT` (or self-hosted admin credentials)
and applies the Cloud-shaped profile, credentials, attributes, alarm rules and
dashboard. No admin password is invented or required for the Cloud tenant.

The dashboard answers "Which water source is unsafe right now?" with: a
fleet-health/safety table, pH and turbidity gauges, a TDS digital gauge,
turbidity/pH/TDS and temperature/flow time-series charts, an
OpenStreetMap node map, and an alarms table. Every widget is bound to a single
fleet alias, so each measurement is labelled with its device/source name.

### Alarm thresholds and hysteresis (exact values from the brief)

| Alarm | Trigger | Clear | Extra |
| --- | --- | --- | --- |
| High Turbidity Warning | > 50 | < 40 | — |
| Gross Contamination Critical | > 200 | < 150 | — |
| pH Out of Range Critical | < 6.5 or > 8.5 | 6.7–8.3 | — |
| High TDS Critical | > 500 | < 450 | — |
| Supply Interruption Major | flow == 0 | flow > 0 | sustained 30 s (15 samples) |
| Node Inactive Critical | no telemetry | telemetry resumes | 60 s timeout |

`jalsanket/alarms.py` is the reference implementation used by the automated
tests. It also publishes `safetyStatus` as a device attribute for the dashboard.

### Scenario control

Local `trigger_contamination()` / `set_supply_interrupted()` / `reset()` remain
unchanged. As an additional mechanism, each node subscribes to
`v1/devices/me/rpc/request/+` and accepts RPC methods `trigger_contamination`,
`set_supply_interrupted`, and `reset`, replying on
`v1/devices/me/rpc/response/<id>`. RPC only calls the real generator methods;
it never writes abnormal values directly into telemetry.

### Verification

`verify_phase4.py` uses injected fake MQTT clients and a fake REST transport —
no ThingsBoard host, device token or REST JWT is required. Verified locally:
93/93 checks covering three-node identity/token/coordinate/database separation,
exact telemetry schema, all six threshold and hysteresis transitions, the
30 s sustained-flow and 60 s inactivity timing, repeatable contamination on
all three nodes, RPC command handling, all required dashboard widgets and rule
artifacts, and provisioning payloads with no secret leakage.

### Live verification status

The architecture is unchanged: each node keeps SQLite as its **local edge
store-and-forward buffer**, and **ThingsBoard Cloud** (`eu.thingsboard.cloud`)
is the cloud platform that receives MQTT/TLS telemetry, raises alarms and hosts
the dashboard. There is no local ThingsBoard server.

Live ThingsBoard Cloud checks are recorded under `evidence/`:
`live_preflight.json`, `live_mqtt_probe.json`, `live_cloud_config.json`,
`live_rpc_probe.json`, `live_cloud_alarms.json`, `live_cloud_attributes.json`,
`live_fleet_run7.log`, `live_cloud_verification.json` and the dashboard
screenshots. The measured metrics and publication plots are documented in
"Final metrics / evidence" below.

Commands used for live verification (run from the repository root). Credentials
come only from the git-ignored `.env` or exported environment variables; do not
paste tokens, passwords or JWTs into commands or commit them.

```bash
.venv/bin/python live_preflight.py

# Live three-node fleet with a simulated cellular outage and buffered replay.
# This run owns the MQTT session for each of the three device tokens.
.venv/bin/python run_fleet.py --duration 90 --outage-after 15 \
    --outage-duration 20 --verbose > evidence/live_fleet_final.log 2>&1

# REST two-way RPC can be checked while the fleet is running. The probe reads
# the tenant JWT from the clipboard and never writes it to disk.
.venv/bin/python evidence/live_rpc_probe.py

# These two probes open their own MQTT session with a device token, so run them
# only after the fleet has stopped; otherwise they take over the fleet session.
.venv/bin/python evidence/live_mqtt_probe.py
.venv/bin/python evidence/live_cloud_alarms.py
```

`live_rpc_probe.py` and `live_cloud_alarms.py` read the tenant JWT from the
clipboard (copied from the logged-in ThingsBoard Cloud browser tab). Keep it out
of shell history and version control.

### Secrets

No credentials are committed. Real host, device tokens, REST JWT and any admin
credentials come only from exported environment variables or a git-ignored
`.env` (see `.env.example`). Logs and evidence use safe summaries that omit
tokens and passwords.

## Final metrics / evidence

`collect_metrics.py` is a dedicated, reproducible metrics experiment. It runs
the **existing** three-node fleet unchanged, uses only the built-in scenario
controls (`trigger_contamination`, `set_supply_interrupted`, `reset`) and one
normal 20 s simulated cellular outage, then correlates four independent
evidence sources:

1. SQLite `readings` (`acquisition_ms`, `stored_at_ms`, `synced_at_ms`, `synced`)
2. Instrumented QoS 1 PUBACK and CONNACK events captured in the collector process
3. ThingsBoard Cloud timeseries REST responses (device name + device-supplied `ts`)
4. ThingsBoard Cloud alarm REST records (`startTs`, `createdTime`)

The only addition to the runtime path is callback wrapping inside the collector;
no telemetry physics, SQLite schema, store-and-forward, MQTT/TLS settings, QoS
level, replay logic, alarm thresholds or dashboard widget was changed. No fake
high telemetry value is injected: every alarm comes from a real scenario control
driving the unchanged generator.

### Exact command

```bash
# Copy the logged-in Cloud tenant JWT (localStorage jwt_token) to the clipboard.
.venv/bin/python collect_metrics.py --duration 240
```

The JWT is read from the clipboard, used in memory only, and the clipboard is
cleared when the fleet run ends. It is never written to evidence or logs.

### Metric definitions and measurement boundaries

| Metric | Start | End | Notes |
| --- | --- | --- | --- |
| End-to-end latency (reported honestly) | SQLite `acquisition_ms` (edge acquisition) | QoS 1 PUBACK callback in the fleet process | n ≥ 200 live messages; reported as **edge→broker** only, *not* Cloud ingestion |
| Cloud ingestion latency | — | — | **Not measurable**: Cloud timeseries REST returns only the device-supplied `ts` (equal to `acquisition_ms`), with no server ingestion timestamp. No number is reported. |
| Delivery ratio with outage | rows generated in the window | Cloud REST timeseries keyed by `(device, acquisition_ms)` | Buffered rows that later replay count as delivered |
| Alarm activation delay | Cloud alarm `startTs` (triggering telemetry event) | Cloud alarm `createdTime` (activation) | ≥ 10 Cloud alarm events; correlated to a local reading where possible |
| Buffer flush throughput | first replay publish | last replay PUBACK | replayed rows ÷ measured window; per node and fleet summary |
| Recovery time | simulated outage onset | buffer empty (last replay PUBACK) | Reconnect delay and flush time reported separately |
| Actual data loss | SQLite `loss_events` (drop-newest evictions only) | — | Temporarily buffered rows are **not** loss |

Because SQLite autoincrement IDs are unique per node database only, puback→row
correlation is keyed by `(node_id, id)`. The collector does not treat reconnect
delay as recovery: the transport auto-reconnects with backoff, often before the
scripted "restore" tick, so wall-clock restoration is not a valid anchor.

### Evidence and results

Machine-readable result: `evidence/metrics/metrics_results.json`.
Terminal summary: `evidence/metrics_experiment.log`.
Raw evidence (all under `evidence/metrics/`): `raw_puback_events.csv`,
`raw_latency_samples.csv`, `raw_db_rows.csv`, `raw_loss_events.csv`,
`raw_local_alarm_events.csv`, `raw_scenario_events.csv`,
`raw_link_and_connect_events.csv`, `raw_recovery_events.csv`,
`raw_cloud_alarms.csv`, `raw_cloud_telemetry.json`, `experiment_config.json`.
Publication plots: `latency_distribution.png` and `buffer_depth_timeline.png`.
`manifest.json` lists SHA-256 hashes and the credential scan result (empty).

Latest measured snapshot (240 s, three nodes, one 20 s outage):

| Metric | Value |
| --- | --- |
| Messages generated / Cloud-visible / lost | 362 / 362 / 0 |
| Live edge→PUBACK latency (n) | mean 196.9 ms, median 194.0 ms, p95 203.4 ms, max 629.0 ms (353) |
| Alarm activation delay (n) | mean 544.8 ms, median 189.0 ms (15) |
| Recovery time (n) | mean 3302.7 ms, median 3203.0 ms (3) |
| Buffer flush throughput (n) | mean 5.50 rows/s, median 5.51 rows/s (3) |

### Limitations

* PUBACK confirms broker receipt at QoS 1, not dashboard/Cloud ingestion time.
  The Cloud exposes no ingestion timestamp, so true end-to-end Cloud latency
  cannot be honestly quantified here.
* The buffer outage used here is the normal 20 s scenario; the SQLite buffer was
  never deliberately filled to capacity, so no capacity-exhaustion result is
  claimed. The observed replay batches were small (2 rows per node).
* Alarm `startTs` is the triggering telemetry timestamp. For the duration-based
  Supply Interruption rule, `createdTime − startTs` also includes the sustained
  condition window; these events are retained but should be interpreted per type.
* Results are from one controlled run against the shared ThingsBoard Cloud
  tenant; network conditions and shared-tenant load can affect latency values.

### Metrics verification

Deterministic synthetic-data tests (no network, no credentials) for the
percentile, delivery, alarm, recovery and collector correlation functions:

```bash
.venv/bin/python verify_metrics.py     # 29/29 checks
```
