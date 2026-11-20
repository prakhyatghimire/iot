#!/usr/bin/env python3
"""Phase 3 verification: MQTT/TLS transport, QoS 1 confirmation and replay.

Run with::

    python3 -m pip install -r requirements.txt   # or use .venv
    python3 verify_phase3.py

Uses an injectable fake MQTT client. No ThingsBoard host or token is needed,
and no credential is invented: test tokens are explicit non-secret placeholders.
Exits non-zero if any check fails.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jalsanket import (
    ConfigurationError,
    GeneratorConfig,
    MqttConfig,
    StoreConfig,
    TelemetryGenerator,
    TelemetryStore,
    VirtualEdgeNode,
)
from jalsanket.mqtt_transport import MqttTransport
from jalsanket.runner import EdgeSimulator

BASE = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
TOKEN = "TEST_TOKEN_NOT_A_REAL_CREDENTIAL"
results: list[tuple[bool, str, str]] = []


class CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class FakeMessageInfo:
    def __init__(self, rc: int, mid: int) -> None:
        self.rc = rc
        self.mid = mid


class FakeMessage:
    def __init__(self, topic: str, payload: str) -> None:
        self.topic = topic
        self.payload = payload.encode("utf-8")


class FakeMqttClient:
    """Minimal paho-v2-shaped client with controllable CONNACK and PUBACK."""

    def __init__(self, client_id: str = "") -> None:
        self.client_id = client_id
        self.on_connect = None
        self.on_disconnect = None
        self.on_connect_fail = None
        self.on_publish = None
        self.on_message = None
        self.connack_rc = 0
        self.fail_next_connect = False
        self.publish_rc = 0
        self.ack_delay = 0
        self.connack_delay = 0
        self.published: list[dict] = []
        self.subscriptions: list[tuple] = []
        self._events: list[tuple] = []
        self._loop_count = 0
        self._mid = 0
        self.username: str | None = None
        self.password: str | None = None
        self.tls_context = None
        self.connected = False
        self.connect_calls = 0

    def _queue(self, delay: int, kind: str, *args) -> None:
        self._events.append((self._loop_count + delay, kind, *args))

    def username_pw_set(self, username: str, password: str | None = None) -> None:
        self.username, self.password = username, password

    def tls_set_context(self, context) -> None:
        self.tls_context = context

    def connect(self, host: str, port: int, *args, **kwargs) -> None:
        self.host, self.port = host, port
        self.connect_calls += 1
        if self.fail_next_connect:
            self.fail_next_connect = False
            self._queue(0, "connect_fail")
            return
        self._queue(self.connack_delay, "connack", self.connack_rc)

    def connect_async(self, host: str, port: int, *args, **kwargs) -> None:
        self.connect(host, port, *args, **kwargs)

    def loop_read(self) -> int:
        return 0

    def loop_write(self) -> int:
        return 0

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        self._mid += 1
        info = FakeMessageInfo(self.publish_rc, self._mid)
        self.published.append(
            {"mid": self._mid, "topic": topic, "payload": payload, "qos": qos}
        )
        if self.publish_rc == 0:
            self._queue(self.ack_delay, "puback", self._mid)
        return info

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscriptions.append((topic, qos))

    def inject_message(self, topic: str, payload: str) -> None:
        if self.on_message:
            self.on_message(self, None, FakeMessage(topic, payload))

    def disconnect(self) -> None:
        self.connected = False
        self._queue(0, "disconnect", 1)

    def loop_misc(self) -> int:
        self._loop_count += 1
        due = [e for e in self._events if e[0] <= self._loop_count]
        self._events = [e for e in self._events if e[0] > self._loop_count]
        for _, kind, *args in due:
            if kind == "connack" and self.on_connect:
                self.connected = args[0] == 0
                self.on_connect(self, None, {}, args[0], None)
            elif kind == "connect_fail" and self.on_connect_fail:
                self.on_connect_fail(self, None)
            elif kind == "puback" and self.on_publish:
                self.on_publish(self, None, args[0], 0, None)
            elif kind == "disconnect" and self.on_disconnect:
                self.on_disconnect(self, None, 0, args[0], None)
        return 0

    def replay_messages(self) -> list[dict]:
        return [m for m in self.published if isinstance(json.loads(m["payload"]), list)]


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((bool(passed), name, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def make_setup(tmp: str, *, replay_batch_size: int = 20, clock=None):
    store = TelemetryStore(StoreConfig(db_path=str(Path(tmp) / "phase3.db")))
    generator = TelemetryGenerator(GeneratorConfig(node_id="node-01", seed=42))
    node = VirtualEdgeNode(generator, store)
    cfg = MqttConfig(
        host="test.local",
        token=TOKEN,
        replay_batch_size=replay_batch_size,
        publish_timeout_s=30.0,
    )
    fake = FakeMqttClient()
    transport = MqttTransport(cfg, store, "node-01", client_factory=lambda: fake, clock=clock)
    simulator = EdgeSimulator(node, transport)
    return store, generator, node, transport, fake, simulator


def main() -> int:
    handler = CaptureHandler()
    for logger_name in ("jalsanket.mqtt", "jalsanket.storage"):
        log = logging.getLogger(logger_name)
        log.addHandler(handler)
        log.setLevel(logging.INFO)

    with tempfile.TemporaryDirectory(prefix="jalsanket-phase3-") as tmp:
        # ------------------------------------------------------- configuration
        section("1. Secure configuration (no invented credentials)")
        # Empty values keep the key present so load_dotenv() does not refill it
        # from a real git-ignored .env during this negative test.
        for key in ("TB_HOST", "TB_DEVICE_TOKEN", "TB_MQTT_PORT", "MQTT_REPLAY_BATCH_SIZE"):
            os.environ[key] = ""
        try:
            MqttConfig.from_env()
            missing_raises = False
        except (ConfigurationError, ValueError):
            missing_raises = True
        check("missing host/token raises configuration error", missing_raises)

        os.environ["TB_HOST"] = "test.local"
        os.environ["TB_DEVICE_TOKEN"] = TOKEN
        env_cfg = MqttConfig.from_env()
        check("env config uses port 8883", env_cfg.port == 8883)
        check("approved reconnect defaults 2/60",
              (env_cfg.reconnect_min_delay_s, env_cfg.reconnect_max_delay_s) == (2.0, 60.0))
        check("approved replay batch default 20", env_cfg.replay_batch_size == 20)
        check("token never appears in loggable summary", TOKEN not in str(env_cfg.safe_summary()))
        try:
            MqttConfig(host="h", token=TOKEN, port=1883)
            wrong_port_rejected = False
        except ConfigurationError:
            wrong_port_rejected = True
        check("non-8883 port rejected", wrong_port_rejected)
        for key in ("TB_HOST", "TB_DEVICE_TOKEN"):
            os.environ.pop(key, None)

        # ------------------------------------------- connect + confirmed publish
        section("2. TLS auth and QoS 1 confirmed delivery")
        store, gen, node, transport, fake, sim = make_setup(tmp)
        transport.start()
        transport.pump()  # delivers CONNACK
        check("successful connection logged", any("SUCCESSFUL CONNECTION" in m for m in handler.messages))
        check("TLS context configured", fake.tls_context is not None)
        check("username is the device token", fake.username == TOKEN)
        check("password is empty", fake.password == "")

        fake.ack_delay = 3  # delay PUBACK to prove no early sync
        result = sim.run_once(at=BASE)
        check("live publish attempted", len(fake.published) == 1)
        check("live publish uses QoS 1", fake.published[0]["qos"] == 1)
        check("live topic is correct", fake.published[0]["topic"] == "v1/devices/me/telemetry")
        live_msg = json.loads(fake.published[0]["payload"])
        check("live payload carries original acquisition_ms", live_msg["ts"] == result.reading.acquisition_ms())
        check("row still unsynced before PUBACK", store.get_buffer_depth() == 1)
        transport.pump()
        check("still unsynced after one more pump", store.get_buffer_depth() == 1)
        transport.pump()
        check("row synced only after QoS 1 PUBACK", store.get_buffer_depth() == 0)
        check("PUBACK confirmation logged", any("PUBLISH CONFIRMED (QoS 1 PUBACK)" in m for m in handler.messages))
        check("puback statistic recorded", transport.stats["pubacks"] == 1)

        # ------------------------------------------------- failure distinction
        section("3. Authentication vs network failure distinction")
        handler.messages.clear()
        fake2_cfg = MqttConfig(host="test.local", token=TOKEN)
        fake2 = FakeMqttClient()
        fake2.connack_rc = 5
        store2 = TelemetryStore(StoreConfig(db_path=str(Path(tmp) / "auth.db")))
        t2 = MqttTransport(fake2_cfg, store2, "node-01", client_factory=lambda: fake2)
        t2.start()
        t2.pump()
        check("auth failure logged distinctly", any("AUTHENTICATION FAILURE" in m for m in handler.messages))
        check("auth failure counted", t2.stats["auth_failures"] == 1)
        check("auth failure not counted as network failure", t2.stats["network_failures"] == 0)
        check("auth failure leaves node offline", not t2.is_connected)

        handler.messages.clear()
        fake3 = FakeMqttClient()
        fake3.fail_next_connect = True
        store3 = TelemetryStore(StoreConfig(db_path=str(Path(tmp) / "net.db")))
        t3 = MqttTransport(fake2_cfg, store3, "node-01", client_factory=lambda: fake3)
        t3.start()
        t3.pump()
        check("network failure logged distinctly",
              any("NETWORK/CONNECTION FAILURE" in m for m in handler.messages))
        check("network failure counted", t3.stats["network_failures"] == 1)
        check("network failure not counted as auth failure", t3.stats["auth_failures"] == 0)
        t2.shutdown(); t3.shutdown(); store2.close(); store3.close()

        # ------------------------------------------------------------ backoff
        section("4. Exponential backoff bounds (2 s / 60 s)")
        original_uniform = random.uniform
        random.uniform = lambda a, b: 1.0
        try:
            delays = []
            for attempt in range(8):
                transport._reconnect_attempt = attempt
                delays.append(transport._backoff_delay())
            check("backoff sequence 2,4,8,16,32,60,60,60",
                  delays == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0], str(delays))
            check("auth failure forces maximum backoff",
                  transport._backoff_delay(force_max=True) == 60.0)
        finally:
            random.uniform = original_uniform
        transport._reconnect_attempt = 0

        # ------------------------------------------------ outage and buffering
        section("5. Outage: generation continues, buffer grows")
        store4 = TelemetryStore(StoreConfig(db_path=str(Path(tmp) / "phase3b.db")))
        gen4 = TelemetryGenerator(GeneratorConfig(node_id="node-01", seed=42))
        node4 = VirtualEdgeNode(gen4, store4)
        clock = [0.0]
        cfg4 = MqttConfig(host="test.local", token=TOKEN, replay_batch_size=2)
        f4 = FakeMqttClient()
        t4b = MqttTransport(cfg4, store4, "node-01", client_factory=lambda: f4, clock=lambda: clock[0])
        s4 = EdgeSimulator(node4, t4b)
        t4b.start(); t4b.pump()
        check("connected before outage", t4b.is_connected)
        for i in range(3):
            s4.run_once(at=BASE + timedelta(seconds=i * 2))
        check("live rows confirmed before outage", store4.get_buffer_depth() == 0)

        f4.connack_rc = 1  # keep reconnect attempts failing during the outage
        t4b.simulate_outage()
        t4b.pump()
        check("outage detected (offline)", not t4b.is_connected)
        for i in range(5):
            s4.run_once(at=BASE + timedelta(seconds=10 + i * 2))
        check("readings still generated while offline", store4.get_buffer_depth() == 5)
        check("offline/buffering logs emitted",
              any("OFFLINE - BUFFERING" in m for m in handler.messages))
        check("outage log emitted", any("OFFLINE - CELLULAR/MQTT LINK LOST" in m for m in handler.messages))
        check("no crash: simulator still advancing", s4.tick_count == 8)
        buffered = store4.get_unsynced_batch(100)
        expected_ts = [r.acquisition_ms for r in buffered]

        # ------------------------------ automatic reconnect + batched replay
        section("6. Automatic reconnect, chronological batched replay")
        handler.messages.clear()
        initial_published = len(f4.published)  # before any replay traffic
        f4.connack_rc = 0
        clock[0] += 120.0  # advance past maximum backoff
        t4b.pump()  # RECONNECT ATTEMPT -> connect
        check("reconnect attempt logged", any("RECONNECT ATTEMPT" in m for m in handler.messages))
        t4b.pump()  # CONNACK delivered (first replay batch may start here)
        check("automatic reconnect succeeded", t4b.is_connected)
        check("successful reconnect logged", any("SUCCESSFUL RECONNECT" in m for m in handler.messages))

        for _ in range(30):
            t4b.pump()
            if store4.get_buffer_depth() == 0:
                break
        check("buffer fully drained", store4.get_buffer_depth() == 0)
        replay_msgs = f4.published[initial_published:]
        check("exactly 3 replay batches for 5 rows at batch size 2", len(replay_msgs) == 3,
              f"batches={len(replay_msgs)}")
        check("replay batch size respected",
              [len(json.loads(m["payload"])) for m in replay_msgs] == [2, 2, 1])
        replayed_ts = [entry["ts"] for m in replay_msgs for entry in json.loads(m["payload"])]
        check("replay preserves ORIGINAL acquisition_ms", replayed_ts == expected_ts)
        check("replay is chronological", replayed_ts == sorted(replayed_ts))
        check("all replay messages use QoS 1", all(m["qos"] == 1 for m in replay_msgs))
        check("replay complete logged", any("REPLAY COMPLETE - BUFFER EMPTY" in m for m in handler.messages))
        check("rows flushed/remaining logged", any("rows_flushed=2 remaining_rows=" in m for m in handler.messages))
        check("replay reuses telemetry topic",
              all(m["topic"] == "v1/devices/me/telemetry" for m in replay_msgs))
        t4b.shutdown(); store4.close()

        # --------------------------------------------------- publish failures
        section("7. Local publish failure leaves rows unsynced")
        store5, gen5, node5, t5, f5, s5 = make_setup(tmp)
        t5.start(); t5.pump()
        f5.publish_rc = 1
        r5 = s5.run_once(at=BASE)
        check("failed publish counted", t5.stats["publish_failures"] >= 1,
              f"count={t5.stats['publish_failures']}")
        check("failed publish leaves row unsynced", store5.get_buffer_depth() == 1)
        check("failed publish logged", any("PUBLISH FAILED" in m for m in handler.messages))
        t5.shutdown(); store5.close()

        # -------------------------------------- idempotent start / graceful stop
        section("8. Idempotent start() and graceful shutdown drain")

        def isolated_setup(db_name: str):
            db_path = Path(tmp) / db_name
            store = TelemetryStore(StoreConfig(db_path=str(db_path)))
            generator = TelemetryGenerator(GeneratorConfig(node_id="node-01", seed=42))
            node = VirtualEdgeNode(generator, store)
            cfg = MqttConfig(host="test.local", token=TOKEN, publish_timeout_s=30.0)
            fake = FakeMqttClient()
            transport = MqttTransport(cfg, store, "node-01", client_factory=lambda: fake)
            simulator = EdgeSimulator(node, transport)
            return store, db_path, fake, transport, simulator

        # 8a: demo restore must not open a second session when already connected.
        store8a, _, fake8a, t8a, _ = isolated_setup("phase3_start_once.db")
        t8a.start(); t8a.pump()
        check("initial start() connects once", fake8a.connect_calls == 1 and t8a.is_connected)
        handler.messages.clear()
        t8a.start()
        check("already-connected start() does not reconnect",
              fake8a.connect_calls == 1
              and not any("CONNECTING host" in m for m in handler.messages))
        t8a.pump()
        check("client stays connected after repeated start()", t8a.is_connected)
        t8a.shutdown(timeout_s=0.0)
        store8a.close()

        # 8b: an in-flight QoS 1 publish must receive its PUBACK before disconnect.
        store8b, db8b, fake8b, t8b, sim8b = isolated_setup("phase3_shutdown_puback.db")
        fake8b.ack_delay = 6
        t8b.start(); t8b.pump()
        sim8b.run_once(at=BASE)
        check("row in flight before shutdown",
              store8b.get_buffer_depth() == 1 and len(t8b._pending) == 1)
        handler.messages.clear()
        t8b.shutdown(timeout_s=2.0)
        check("in-flight PUBACK received during drain", store8b.get_buffer_depth() == 0)
        check("PUBACK still required for sync at shutdown",
              any("PUBLISH CONFIRMED (QoS 1 PUBACK)" in m for m in handler.messages))
        check("shutdown drain completed without timeout",
              not any("SHUTDOWN DRAIN TIMEOUT" in m for m in handler.messages))
        conn8b = sqlite3.connect(db8b)
        row8b = conn8b.execute(
            "SELECT synced, last_error FROM readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn8b.close()
        check("row marked synced only after PUBACK", row8b == (1, None), str(row8b))
        check("client disconnected after drain", not t8b.is_connected)
        store8b.close()

        # 8c: an expired bounded drain leaves the row durable and unsynchronized.
        store8c, db8c, fake8c, t8c, sim8c = isolated_setup("phase3_shutdown_timeout.db")
        fake8c.ack_delay = 1000
        t8c.start(); t8c.pump()
        sim8c.run_once(at=BASE)
        check("unconfirmed row exists before timeout shutdown",
              store8c.get_buffer_depth() == 1 and len(t8c._pending) == 1)
        handler.messages.clear()
        t8c.shutdown(timeout_s=0.0)
        check("bounded shutdown timeout logged",
              any("SHUTDOWN DRAIN TIMEOUT" in m for m in handler.messages))
        check("no PUBACK confirmation on timeout",
              not any("PUBLISH CONFIRMED" in m for m in handler.messages))
        store8c.close()
        store8c_reopen = TelemetryStore(StoreConfig(db_path=str(db8c)))
        durable = store8c_reopen.get_unsynced_batch(100)
        check("timed-out row remains unsynced and durable",
              len(durable) == 1 and durable[0].last_error == "connection lost before PUBACK")
        store8c_reopen.close()

        # ---------------------------------------------------------------- summary
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
        print("\nPhase 3 verification: ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
