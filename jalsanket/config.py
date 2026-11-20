"""Configuration for MQTT/TLS transport and Cloud REST access.

Secrets are supplied only through environment variables or a git-ignored
``.env`` file at the project root. Nothing in this module hard-codes a token,
and ``safe_summary()`` is the only representation allowed in logs.

ThingsBoard Cloud uses the same hostname for MQTT/TLS on 8883 and HTTPS REST
on 443. ``TB_REST_HOST`` and the HTTP settings allow a Cloud tenant with a
separate REST hostname without changing the MQTT path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ConfigurationError(Exception):
    """Raised when required MQTT/TLS configuration is missing or invalid."""


def load_dotenv(path: str | Path = ".env") -> None:
    """Load ``KEY=VALUE`` lines into os.environ without overriding real env vars."""
    env_file = Path(path)
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _get_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None or value == "" else float(value)


def _get_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


@dataclass(frozen=True)
class MqttConfig:
    """Connection, retry and replay settings. Port 8883/TLS are mandatory."""

    host: str
    token: str
    port: int = 8883
    ca_cert: Optional[str] = None
    client_id: Optional[str] = None
    reconnect_min_delay_s: float = 2.0
    reconnect_max_delay_s: float = 60.0
    replay_batch_size: int = 20
    publish_timeout_s: float = 30.0
    telemetry_topic: str = "v1/devices/me/telemetry"
    attributes_topic: str = "v1/devices/me/attributes"
    tls_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.host:
            raise ConfigurationError("TB_HOST must be set")
        if not self.token:
            raise ConfigurationError("TB_DEVICE_TOKEN must be set")
        if self.port != 8883:
            raise ConfigurationError("the assignment requires MQTT over TLS on port 8883")
        if not self.tls_enabled:
            raise ConfigurationError("TLS is mandatory")
        if self.reconnect_min_delay_s <= 0 or self.reconnect_max_delay_s < self.reconnect_min_delay_s:
            raise ConfigurationError("invalid reconnect delay bounds")
        if self.replay_batch_size <= 0:
            raise ConfigurationError("replay_batch_size must be positive")
        if self.publish_timeout_s <= 0:
            raise ConfigurationError("publish_timeout_s must be positive")

    @classmethod
    def from_env(cls, token: Optional[str] = None) -> "MqttConfig":
        """Build configuration from environment / .env; never fabricate secrets.

        ``token`` lets the multi-node fleet supply a per-device token while all
        other settings remain shared. Phase 3's single-node path passes none.
        """
        load_dotenv()
        return cls(
            host=os.environ.get("TB_HOST", ""),
            token=token if token is not None else os.environ.get("TB_DEVICE_TOKEN", ""),
            port=_get_int("TB_MQTT_PORT", 8883),
            ca_cert=os.environ.get("TB_CA_CERT") or None,
            client_id=os.environ.get("MQTT_CLIENT_ID") or None,
            reconnect_min_delay_s=_get_float("MQTT_RECONNECT_MIN_DELAY_S", 2.0),
            reconnect_max_delay_s=_get_float("MQTT_RECONNECT_MAX_DELAY_S", 60.0),
            replay_batch_size=_get_int("MQTT_REPLAY_BATCH_SIZE", 20),
            publish_timeout_s=_get_float("MQTT_PUBLISH_TIMEOUT_S", 30.0),
        )

    def safe_summary(self) -> dict:
        """Loggable representation that never exposes the token."""
        return {
            "host": self.host,
            "port": self.port,
            "tls": self.tls_enabled,
            "ca_cert": self.ca_cert or "system trust store",
            "client_id": self.client_id or "derived from node id",
            "token_present": bool(self.token),
            "reconnect_min_delay_s": self.reconnect_min_delay_s,
            "reconnect_max_delay_s": self.reconnect_max_delay_s,
            "replay_batch_size": self.replay_batch_size,
            "telemetry_topic": self.telemetry_topic,
        }


@dataclass(frozen=True)
class RestConfig:
    """HTTPS REST endpoint settings for ThingsBoard Cloud."""

    host: str
    rest_host: str = ""
    scheme: str = "https"
    port: int = 443

    def __post_init__(self) -> None:
        if not self.host:
            raise ConfigurationError("TB_HOST must be set")
        if not self.rest_host:
            raise ConfigurationError("REST host must resolve to TB_HOST or TB_REST_HOST")
        if self.scheme not in ("http", "https"):
            raise ConfigurationError("TB_HTTP_SCHEME must be http or https")
        if self.port <= 0 or self.port > 65535:
            raise ConfigurationError("TB_HTTP_PORT is out of range")

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.rest_host}:{self.port}"

    @classmethod
    def from_env(cls) -> "RestConfig":
        load_dotenv()
        host = os.environ.get("TB_HOST", "")
        rest_host = os.environ.get("TB_REST_HOST") or host
        return cls(
            host=host,
            rest_host=rest_host,
            scheme=(os.environ.get("TB_HTTP_SCHEME") or "https").strip().lower(),
            port=_get_int("TB_HTTP_PORT", 443),
        )

    def safe_summary(self) -> dict:
        """Loggable representation that never exposes credentials."""
        return {
            "mqtt_host": self.host,
            "rest_host": self.rest_host,
            "scheme": self.scheme,
            "port": self.port,
            "base_url": self.base_url,
        }
