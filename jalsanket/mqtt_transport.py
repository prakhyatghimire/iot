"""MQTT/TLS transport with QoS 1 confirmation and buffered replay (Phase 3).

Mandatory ordering, enforced here and in ``VirtualEdgeNode``:

    generate -> persist to SQLite -> publish -> PUBACK -> mark synced

A row is marked synchronized ONLY in ``_on_publish``, which paho invokes after
the broker's QoS 1 PUBACK. A successful local ``publish()`` call changes no
database state by itself.

The client is driven by a blocking ``connect()`` plus explicit
``loop_read()``/``loop_write()``/``loop_misc()`` calls from the simulator's main
loop. paho-mqtt 2.x does not complete ``connect_async()`` without its own
background loop, so the explicit network-loop calls are required for live TLS
connections. No background thread is used, so callbacks and database updates
run on one thread and no locking is required. This also means an outage never
blocks or crashes reading generation.
"""

from __future__ import annotations

import json
import logging
import random
import ssl
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from .config import MqttConfig
from .storage import StoredReading, TelemetryStore
from .telemetry import Reading

logger = logging.getLogger("jalsanket.mqtt")

# MQTT 3.1.1 code 5 and MQTT 5 codes 135/137 all mean "not authorized".
AUTH_FAILURE_CODES = {5, 135, 137}

# Bounded grace period for a stop request: enough for an in-flight QoS 1 PUBACK
# and any safe replay, but never an unbounded wait. Expiry leaves every
# unconfirmed row durable and unsynchronized, exactly as on an outage.
DEFAULT_SHUTDOWN_DRAIN_TIMEOUT_S = 10.0
_SHUTDOWN_POLL_S = 0.02


def _reason_code_value(reason_code) -> int:
    """Normalize paho 2.x ReasonCode and legacy integer callbacks."""
    return int(getattr(reason_code, "value", reason_code))


class MqttTransport:
    """Publishes live telemetry and drains the SQLite buffer after reconnect."""

    def __init__(
        self,
        config: MqttConfig,
        store: TelemetryStore,
        node_id: str,
        client_factory: Optional[Callable[[], mqtt.Client]] = None,
        clock: Optional[Callable[[], float]] = None,
        command_handler: Optional[Callable[[str, dict], dict]] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.node_id = node_id
        self._clock = clock or time.monotonic
        self.command_handler = command_handler

        factory = client_factory or self._default_client
        self._client = factory()
        self._configure_client()

        self._connected = False
        self._ever_connected = False
        self._connect_pending = False  # connect() issued, CONNACK not yet handled
        self._shutting_down = False
        self._shutdown_complete = False
        self._auth_failure = False
        self._last_connect_error = ""
        self._reconnect_attempt = 0
        self._next_connect_at = 0.0
        self._reconnect_scheduled = False

        # mid -> (row_ids, publish_started_ms, is_replay)
        self._pending: dict[int, tuple[list[int], int, bool]] = {}
        self._needs_replay = False
        self._replay_active = False
        self._replay_batch_done = False

        self.stats: dict[str, int] = {
            "publish_attempts": 0,
            "pubacks": 0,
            "publish_failures": 0,
            "confirmation_timeouts": 0,
            "replay_batches": 0,
            "reconnects": 0,
            "auth_failures": 0,
            "network_failures": 0,
        }

    # ------------------------------------------------------------- setup
    def _default_client(self) -> mqtt.Client:
        client_id = self.config.client_id or f"jalsanket-{self.node_id}"
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)

    def _configure_client(self) -> None:
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_publish = self._on_publish
        self._client.on_message = self._on_message

        # ThingsBoard: username = device access token, password = empty.
        self._client.username_pw_set(self.config.token, "")

        context = ssl.create_default_context()
        if self.config.ca_cert:
            context.load_verify_locations(cafile=self.config.ca_cert)
        self._client.tls_set_context(context)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def buffer_depth(self) -> int:
        return self.store.get_buffer_depth()

    # ---------------------------------------------------------- connection
    def start(self) -> None:
        """Connect once. A repeated call while connected/connecting is a no-op.

        Demo link restoration calls this after an outage. By then automatic
        reconnect may already have succeeded, so forcing another connect()
        would create a second MQTT session and double-count recoveries.
        """
        if self._connected or self._connect_pending or self._shutdown_complete:
            logger.debug(
                "MQTT START SKIPPED node=%s connected=%s connect_pending=%s shutdown=%s",
                self.node_id,
                self._connected,
                self._connect_pending,
                self._shutdown_complete,
            )
            return
        logger.info(
            "MQTT CONFIG %s",
            self.config.safe_summary(),
        )
        logger.info("CONNECTING host=%s port=%d tls=enabled", self.config.host, self.config.port)
        self._reconnect_scheduled = False
        self._next_connect_at = self._clock() + self.config.reconnect_min_delay_s
        self._connect_now()

    def _connect_now(self) -> None:
        self._connect_pending = True
        try:
            self._client.connect(self.config.host, self.config.port, keepalive=60)
        except Exception as exc:  # DNS, socket, invalid host - never crash the node
            self._connect_pending = False
            self._connected = False
            self._last_connect_error = f"{type(exc).__name__}: {exc}"
            self.stats["network_failures"] += 1
            logger.error("NETWORK/CONNECTION FAILURE during connect: %s", self._last_connect_error)

    def _backoff_delay(self, force_max: bool = False) -> float:
        if force_max:
            return self.config.reconnect_max_delay_s
        delay = self.config.reconnect_min_delay_s * (2 ** self._reconnect_attempt)
        delay = min(delay, self.config.reconnect_max_delay_s)
        # Small jitter avoids lockstep retries when several nodes recover together.
        return max(self.config.reconnect_min_delay_s, delay * random.uniform(0.9, 1.1))

    # ----------------------------------------------------------- callbacks
    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        self._connect_pending = False
        rc = _reason_code_value(reason_code)
        if rc == 0:
            first_time = not self._ever_connected
            self._connected = True
            self._ever_connected = True
            self._auth_failure = False
            self._last_connect_error = ""
            self._reconnect_attempt = 0
            self._reconnect_scheduled = False
            self._next_connect_at = float("inf")
            self._needs_replay = True
            try:
                self._client.subscribe("v1/devices/me/rpc/request/+", qos=1)
            except Exception as exc:
                logger.error("RPC SUBSCRIBE FAILED: %s", exc)
            if first_time:
                logger.info("SUCCESSFUL CONNECTION to %s:%d", self.config.host, self.config.port)
            else:
                self.stats["reconnects"] += 1
                logger.info(
                    "SUCCESSFUL RECONNECT attempt=%d buffered_rows=%d",
                    self._reconnect_attempt,
                    self.buffer_depth,
                )
            return

        self._connected = False
        self._last_connect_error = f"CONNACK rc={rc}"
        self._reconnect_scheduled = False
        self._next_connect_at = self._clock()
        if rc in AUTH_FAILURE_CODES:
            self._auth_failure = True
            self.stats["auth_failures"] += 1
            logger.error(
                "AUTHENTICATION FAILURE (CONNACK rc=%d) - check TB_DEVICE_TOKEN; "
                "retrying at maximum backoff",
                rc,
            )
        else:
            self.stats["network_failures"] += 1
            logger.error("CONNECTION FAILURE (CONNACK rc=%d) - broker refused connection", rc)

    def _on_connect_fail(self, client, userdata) -> None:
        self._connect_pending = False
        self._connected = False
        self._last_connect_error = "network connect failed"
        self._reconnect_scheduled = False
        self._next_connect_at = self._clock()
        self.stats["network_failures"] += 1
        logger.error("NETWORK/CONNECTION FAILURE - could not reach %s:%d", self.config.host, self.config.port)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self._connect_pending = False
        self._connected = False
        self._last_connect_error = f"disconnected rc={_reason_code_value(reason_code)}"
        self._reconnect_scheduled = False
        self._next_connect_at = self._clock()
        self._clear_pending("connection lost before PUBACK")
        self._needs_replay = True
        self._replay_active = False
        if self._shutting_down:
            logger.info(
                "MQTT DISCONNECTED during shutdown (rc=%s) buffer_depth=%d",
                _reason_code_value(reason_code),
                self.buffer_depth,
            )
        else:
            logger.warning(
                "OFFLINE - CELLULAR/MQTT LINK LOST (rc=%s); generation continues, "
                "rows are buffering. buffer_depth=%d",
                _reason_code_value(reason_code),
                self.buffer_depth,
            )

    def _on_message(self, client, userdata, message) -> None:
        """Handle ThingsBoard RPC commands without faking telemetry values."""
        topic = getattr(message, "topic", "") or ""
        prefix = "v1/devices/me/rpc/request/"
        if not topic.startswith(prefix):
            return
        request_id = topic[len(prefix):]
        try:
            request = json.loads(getattr(message, "payload", b"{}"))
            method = request.get("method", "")
            params = request.get("params", {}) or {}
        except (ValueError, AttributeError) as exc:
            logger.error("RPC MALFORMED REQUEST: %s", exc)
            return
        if self.command_handler is None:
            response = {"error": "no command handler configured"}
        else:
            try:
                response = self.command_handler(method, params)
            except Exception as exc:
                logger.error("RPC HANDLER ERROR method=%s: %s", method, exc)
                response = {"error": str(exc)}
        logger.info("RPC COMMAND node=%s method=%s response=%s", self.node_id, method, response)
        try:
            self._client.publish(
                f"v1/devices/me/rpc/response/{request_id}",
                json.dumps(response),
                qos=1,
            )
        except Exception as exc:
            logger.error("RPC RESPONSE PUBLISH FAILED: %s", exc)

    def _on_publish(self, client, userdata, mid, reason_code, properties) -> None:
        entry = self._pending.pop(mid, None)
        if entry is None:
            return
        row_ids, started_ms, is_replay = entry
        # This is the ONLY place a row becomes synchronized.
        confirmed = self.store.mark_synced(row_ids)
        self.stats["pubacks"] += 1
        logger.info(
            "PUBLISH CONFIRMED (QoS 1 PUBACK) mid=%s type=%s rows_confirmed=%d "
            "publish_latency_ms=%d buffer_depth=%d",
            mid,
            "replay" if is_replay else "live",
            confirmed,
            int(time.time() * 1000) - started_ms,
            self.buffer_depth,
        )
        if is_replay:
            self._replay_batch_done = True

    def _clear_pending(self, reason: str) -> None:
        """Unconfirmed rows stay unsynchronized and will be replayed."""
        for mid, (row_ids, _, is_replay) in list(self._pending.items()):
            self.store.record_publish_attempt(row_ids, reason)
            if is_replay:
                self.stats["publish_failures"] += 1
        self._pending.clear()
        self._replay_batch_done = False

    # ------------------------------------------------------------- publish
    @staticmethod
    def _reading_values(reading: Reading) -> dict[str, float]:
        return {
            "ph": reading.ph,
            "turbidity_ntu": reading.turbidity_ntu,
            "tds_ppm": reading.tds_ppm,
            "water_temp_c": reading.water_temp_c,
            "flow_lpm": reading.flow_lpm,
            "latitude": reading.latitude,
            "longitude": reading.longitude,
        }

    def publish_live(self, reading: Reading, row_id: int) -> bool:
        """Publish one freshly persisted reading; leave it unsynced until PUBACK."""
        if not self._connected:
            self._needs_replay = True
            logger.warning(
                "OFFLINE - BUFFERING node=%s id=%d acquisition_ms=%d buffer_depth=%d/%d",
                reading.node_id,
                row_id,
                reading.acquisition_ms(),
                self.buffer_depth,
                self.store.config.max_buffer_rows,
            )
            return False

        payload = {"ts": reading.acquisition_ms(), "values": self._reading_values(reading)}
        return self._publish_payload(json.dumps(payload), [row_id], is_replay=False)

    def _publish_payload(self, payload: str, row_ids: list[int], is_replay: bool) -> bool:
        try:
            info = self._client.publish(self.config.telemetry_topic, payload, qos=1)
        except Exception as exc:
            self.stats["publish_failures"] += 1
            self._needs_replay = True
            logger.error("PUBLISH FAILED (local error): %s", exc)
            return False
        if info.rc != 0:
            self.stats["publish_failures"] += 1
            self._needs_replay = True
            logger.error("PUBLISH FAILED (rc=%s); rows remain unsynchronized", info.rc)
            return False

        self.stats["publish_attempts"] += 1
        self._pending[int(info.mid)] = (row_ids, int(time.time() * 1000), is_replay)
        return True

    def publish_attributes(self, attributes: dict) -> bool:
        """Publish derived node state (not readings) to the attributes topic."""
        if not self._connected:
            return False
        try:
            info = self._client.publish(
                self.config.attributes_topic, json.dumps(attributes), qos=1
            )
            return info.rc == 0
        except Exception as exc:
            logger.error("ATTRIBUTE PUBLISH FAILED: %s", exc)
            return False

    # --------------------------------------------------------------- replay
    def _start_replay(self) -> None:
        rows: list[StoredReading] = self.store.get_unsynced_batch(self.config.replay_batch_size)
        if not rows:
            self._needs_replay = False
            self._replay_active = False
            logger.info("REPLAY COMPLETE - BUFFER EMPTY remaining_rows=0")
            return

        # Original acquisition_ms is used verbatim; replay time never replaces it.
        payload = [{"ts": row.acquisition_ms, "values": row.values()} for row in rows]
        row_ids = [row.id for row in rows]
        self._replay_active = True
        self._replay_batch_done = False
        self.stats["replay_batches"] += 1
        logger.info(
            "REPLAY BATCH PUBLISHED rows=%d batch_size=%d oldest_acq_ms=%d newest_acq_ms=%d "
            "buffer_depth=%d",
            len(rows),
            self.config.replay_batch_size,
            rows[0].acquisition_ms,
            rows[-1].acquisition_ms,
            self.buffer_depth,
        )
        self._publish_payload(json.dumps(payload), row_ids, is_replay=True)

    # ----------------------------------------------------------------- pump
    def _pump_network(self) -> None:
        """Drive paho's socket only; no telemetry, retry or replay side effects."""
        try:
            # paho 2.x needs the socket drained/flushed explicitly when no
            # network thread is running; loop_misc() alone cannot deliver
            # CONNACK, SUBACK or QoS 1 PUBACK.
            self._client.loop_read()
            self._client.loop_write()
            self._client.loop_misc()
        except Exception as exc:
            self._connected = False
            self._connect_pending = False
            self.stats["network_failures"] += 1
            logger.error("NETWORK FAILURE in MQTT loop: %s", exc)

    def pump(self) -> None:
        """Process network events, retries, confirmations timeouts and replay."""
        self._pump_network()

        now = self._clock()

        # Confirmation timeout: rows are left unsynchronized for replay.
        now_ms = int(time.time() * 1000)
        for mid, (row_ids, started_ms, is_replay) in list(self._pending.items()):
            if now_ms - started_ms > self.config.publish_timeout_s * 1000:
                logger.error(
                    "PUBLISH CONFIRMATION TIMEOUT mid=%s rows=%d - no QoS 1 PUBACK; "
                    "rows will be replayed",
                    mid,
                    len(row_ids),
                )
                self.stats["confirmation_timeouts"] += 1
                del self._pending[mid]
                self.store.record_publish_attempt(row_ids, "puback_timeout")
                if is_replay:
                    self._replay_active = False
                self._needs_replay = True

        # Reconnect with exponential backoff. The first eligible pump only
        # schedules the delay; a later pump makes the attempt. Calling connect()
        # while a previous socket is still live caused repeated session drops.
        if not self._connected and now >= self._next_connect_at:
            if not self._reconnect_scheduled:
                delay = self._backoff_delay(force_max=self._auth_failure)
                self._next_connect_at = now + delay
                self._reconnect_scheduled = True
                if self._ever_connected:
                    logger.info(
                        "RECONNECT SCHEDULED in %.1fs (auth_failure=%s, last_error=%s)",
                        delay,
                        self._auth_failure,
                        self._last_connect_error,
                    )
            else:
                self._reconnect_scheduled = False
                self._next_connect_at = now + self.config.reconnect_min_delay_s
                self._reconnect_attempt += 1
                if self._ever_connected:
                    logger.info(
                        "RECONNECT ATTEMPT #%d after backoff (auth_failure=%s, last_error=%s)",
                        self._reconnect_attempt,
                        self._auth_failure,
                        self._last_connect_error,
                    )
                self._connect_now()

        # Replay runs only while connected, one batch per confirmed cycle.
        if self._connected:
            if self._replay_active and self._replay_batch_done:
                self._replay_batch_done = False
                self._start_replay()
            elif self._needs_replay and not self._replay_active:
                self._start_replay()

    def simulate_outage(self) -> None:
        """Drop the link to exercise store-and-forward during a live demo."""
        logger.warning("SIMULATED CELLULAR OUTAGE - dropping MQTT link")
        try:
            self._client.disconnect()
        except Exception as exc:
            logger.error("Failed to simulate outage: %s", exc)
            self._on_disconnect(self._client, None, 0, 1, None)

    def _drain_complete(self) -> bool:
        """True when nothing can still be confirmed in the current link state."""
        if self._pending:
            return False
        if not self._connected:
            return True  # offline: unconfirmed rows stay durable for the next run
        return self.buffer_depth == 0

    def shutdown(self, timeout_s: float = DEFAULT_SHUTDOWN_DRAIN_TIMEOUT_S) -> None:
        """Graceful stop: never disconnect while a QoS 1 PUBACK may still arrive.

        Generation has already stopped before this is called. Network events are
        pumped (without starting new telemetry or reconnect attempts), in-flight
        publishes are allowed to complete, and unsynced rows are replayed only
        while the link is healthy. The drain is bounded by ``timeout_s``; on
        expiry the row is left unsynchronized and durable exactly as on an
        outage, and is never marked synced just because shutdown happened.
        """
        if self._shutdown_complete:
            return
        self._shutting_down = True
        timeout_s = max(0.0, float(timeout_s))
        deadline = time.monotonic() + timeout_s
        logger.info(
            "SHUTDOWN DRAIN START node=%s timeout_s=%.2f connected=%s pending=%d buffer_depth=%d",
            self.node_id,
            timeout_s,
            self._connected,
            len(self._pending),
            self.buffer_depth,
        )

        while time.monotonic() < deadline:
            self._pump_network()

            if self._connected:
                if self._replay_active and self._replay_batch_done:
                    self._replay_batch_done = False
                    self._start_replay()
                elif self._needs_replay and not self._replay_active:
                    before = len(self._pending)
                    self._start_replay()
                    if len(self._pending) == before and self.buffer_depth > 0:
                        # Local replay publish failed; no PUBACK can arrive.
                        self._replay_active = False
                        break
                elif not self._replay_active and not self._pending and self.buffer_depth > 0:
                    # Persisted but never published (stopped between steps).
                    before = len(self._pending)
                    self._start_replay()
                    if len(self._pending) == before and self.buffer_depth > 0:
                        self._replay_active = False
                        break

            if self._drain_complete():
                break
            time.sleep(_SHUTDOWN_POLL_S)

        if not self._drain_complete():
            logger.warning(
                "SHUTDOWN DRAIN TIMEOUT node=%s pending=%d buffer_depth=%d - "
                "rows remain unsynchronized and durable",
                self.node_id,
                len(self._pending),
                self.buffer_depth,
            )
            # Same accounting as a link loss: record the attempt, never fake a sync.
            self._clear_pending("connection lost before PUBACK")

        try:
            self._client.disconnect()
        except Exception as exc:
            logger.warning("MQTT shutdown error: %s", exc)
        self._connected = False
        self._connect_pending = False
        self._shutdown_complete = True
        logger.info(
            "SHUTDOWN DRAIN COMPLETE node=%s pending=%d buffer_depth=%d",
            self.node_id,
            len(self._pending),
            self.buffer_depth,
        )
