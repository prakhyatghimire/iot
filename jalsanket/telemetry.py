"""Physically plausible water-quality telemetry generator (Phase 1).

This module models the sensing behavior of a virtual ESP32-S3 node. It does
not contain any storage, networking or cloud code yet.

Design notes
------------
* The generator keeps a *simulation clock* measured in physical seconds. The
  physical model (diurnal temperature, contamination pulse, flow transients)
  is expressed in those seconds so it can be justified against real units.
* ``time_scale`` controls how many physical seconds pass per wall-clock
  second. This is what makes the rainfall-triggered event repeatable *and*
  watchable in a short live demonstration. It never changes the physics.
* Every reading is stamped with an acquisition time (UTC). The caller may
  supply an explicit timestamp with ``tick(at=...)`` which makes tests fully
  deterministic.
* Correlated behavior comes from a small number of mean-reverting latent
  drivers (runoff, flow, temperature deviation) rather than drawing each
  parameter independently.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

TWO_PI = 2.0 * math.pi
SECONDS_PER_DAY = 86_400.0


def clamp(value: float, low: float, high: float) -> float:
    """Constrain ``value`` to the closed interval [low, high]."""
    return max(low, min(high, value))


@dataclass
class GeneratorConfig:
    """All tunable parameters of the virtual sensor node.

    Ranges and baselines follow the assignment brief. Values grouped under
    "contamination" define the repeatable rainfall/runoff event shape.
    """

    # ---- Node identity and location -------------------------------------
    node_id: str = "node-01"
    latitude: float = 28.1100  # Rasuwa default (overridden per node in the fleet)
    longitude: float = 85.2900

    # ---- Repeatability / clock ------------------------------------------
    seed: int = 42
    sample_interval_s: float = 2.0  # wall-clock seconds between generated readings
    time_scale: float = 20.0  # physical seconds elapsed per wall-clock second
    initial_sim_time_s: float = 21_600.0  # start at 06:00 physical time (temp rising)

    # ---- Normal operating baselines -------------------------------------
    ph_baseline: float = 7.2
    ph_min: float = 6.8
    ph_max: float = 7.6

    turbidity_baseline: float = 5.0
    turbidity_min: float = 2.0
    turbidity_max: float = 8.0

    tds_baseline: float = 185.0
    tds_min: float = 120.0
    tds_max: float = 250.0

    temp_mean: float = 20.0
    temp_amplitude: float = 4.0  # 20 +/- 4 -> 16..24 deg C
    temp_min: float = 16.0
    temp_max: float = 24.0

    flow_baseline: float = 13.0
    flow_min: float = 8.0
    flow_max: float = 18.0

    # ---- Rainfall-triggered contamination event --------------------------
    # A two-timescale pulse: fast advective rise, slow dispersive washout.
    contamination_rise_tau_s: float = 120.0  # ~2 min to 63% of the rise
    contamination_washout_tau_s: float = 2400.0  # ~40 min decay constant

    contamination_peak_turbidity: float = 260.0  # NTU at the top of the pulse
    contamination_peak_tds: float = 535.0  # ppm at the top of the pulse

    # Hill-type pH suppression with a hard, physically sensible lower limit.
    contamination_ph_floor: float = 6.0
    contamination_ph_hill_k: float = 0.35
    contamination_ph_hill_n: float = 1.5

    # Inflow pressure transient: short positive surge, then a mild reduction.
    contamination_pressure_surge_amp: float = 4.0  # L/min added at surge peak
    contamination_pressure_surge_tau_s: float = 40.0  # physical seconds
    contamination_flow_reduction: float = 2.5  # L/min removed at event peak

    # ---- Supply interruption --------------------------------------------
    interrupted_flow_lpm: float = 0.0

    def __post_init__(self) -> None:
        if self.sample_interval_s <= 0:
            raise ValueError("sample_interval_s must be positive")
        if self.time_scale <= 0:
            raise ValueError("time_scale must be positive")
        if self.contamination_washout_tau_s <= self.contamination_rise_tau_s:
            raise ValueError("washout tau must be greater than rise tau")
        if self.contamination_pressure_surge_tau_s <= 0:
            raise ValueError("contamination_pressure_surge_tau_s must be positive")


@dataclass(frozen=True)
class Reading:
    """One acquisition produced by the virtual node."""

    node_id: str
    acquired_at: datetime
    ph: float
    turbidity_ntu: float
    tds_ppm: float
    water_temp_c: float
    flow_lpm: float
    latitude: float
    longitude: float

    def acquisition_ms(self) -> int:
        """Epoch milliseconds in UTC (the format ThingsBoard expects)."""
        return int(self.acquired_at.timestamp() * 1000)

    def to_dict(self) -> dict:
        """Plain dictionary form; useful for SQLite insertion and logs."""
        return {
            "node_id": self.node_id,
            "acquired_at": self.acquired_at.isoformat(),
            "ph": self.ph,
            "turbidity_ntu": self.turbidity_ntu,
            "tds_ppm": self.tds_ppm,
            "water_temp_c": self.water_temp_c,
            "flow_lpm": self.flow_lpm,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


class TelemetryGenerator:
    """Stateful generator that behaves like one virtual ESP32-S3 edge node.

    Typical use::

        gen = TelemetryGenerator(GeneratorConfig(node_id="node-01"))
        reading = gen.tick()          # normal telemetry
        gen.trigger_contamination()   # repeatable rainfall event
        reading = gen.tick()
        gen.set_supply_interrupted(True)
        reading = gen.tick()
        gen.reset()                   # back to the seeded starting state
    """

    def __init__(self, config: Optional[GeneratorConfig] = None) -> None:
        self.config = config or GeneratorConfig()
        self._peak_envelope = self._compute_peak_envelope()
        self.reset()

    # ------------------------------------------------------------------ setup
    def _compute_peak_envelope(self) -> float:
        """Normalising constant so the contamination pulse peaks at exactly 1.

        For f(u) = e^(-u/td) - e^(-u/tr) the peak occurs at
        u* = (tr*td/(td-tr)) * ln(td/tr).
        """
        tr = self.config.contamination_rise_tau_s
        td = self.config.contamination_washout_tau_s
        u_peak = (tr * td / (td - tr)) * math.log(td / tr)
        return math.exp(-u_peak / td) - math.exp(-u_peak / tr)

    def reset(self) -> None:
        """Restore the seeded starting state so a scenario can be repeated."""
        self._rng = random.Random(self.config.seed)
        self._sim_time_s = self.config.initial_sim_time_s
        self._runoff = 0.0
        self._flow_state = 0.0
        self._temp_state = 0.0
        self._contamination_start_s: Optional[float] = None
        self._supply_interrupted = False

    # ---------------------------------------------------------- event control
    def trigger_contamination(self) -> None:
        """Start the rainfall/runoff contamination event at the current time."""
        self._contamination_start_s = self._sim_time_s

    def set_supply_interrupted(self, interrupted: bool) -> None:
        """Force flow to exactly zero (True) or restore normal flow (False)."""
        self._supply_interrupted = bool(interrupted)

    @property
    def contamination_intensity(self) -> float:
        """Current event envelope in [0, 1]; 0 means no active contamination."""
        return self._contamination_envelope()

    @property
    def is_contaminated(self) -> bool:
        return self.contamination_intensity > 0.0

    @property
    def simulation_time_s(self) -> float:
        """Current physical simulation time in seconds."""
        return self._sim_time_s

    # ------------------------------------------------------------- primitives
    def _ou_step(
        self, value: float, tau_s: float, stationary_sigma: float, dt: float
    ) -> float:
        """One mean-reverting Ornstein-Uhlenbeck update with sub-stepping.

        ``stationary_sigma`` is the long-run standard deviation, which is more
        intuitive than the raw diffusion coefficient. Sub-stepping keeps the
        update stable when a demo uses a large ``time_scale``.
        """
        steps = max(1, math.ceil(dt / (tau_s / 4.0)))
        h = dt / steps
        theta = 1.0 / tau_s
        diffusion = stationary_sigma * math.sqrt(2.0 * theta)
        for _ in range(steps):
            value += -theta * value * h + diffusion * math.sqrt(h) * self._rng.gauss(0.0, 1.0)
        return value

    def _contamination_envelope(self) -> float:
        """Two-timescale rainfall pulse: fast rise, slow exponential washout."""
        if self._contamination_start_s is None:
            return 0.0
        elapsed = self._sim_time_s - self._contamination_start_s
        if elapsed <= 0.0:
            return 0.0
        tr = self.config.contamination_rise_tau_s
        td = self.config.contamination_washout_tau_s
        raw = math.exp(-elapsed / td) - math.exp(-elapsed / tr)
        return max(0.0, raw / self._peak_envelope)

    # ------------------------------------------------------------------ main
    def tick(self, at: Optional[datetime] = None) -> Reading:
        """Advance the simulation and produce one reading.

        ``at`` overrides the acquisition timestamp (useful for deterministic
        tests). Naive datetimes are treated as UTC.
        """
        cfg = self.config
        dt = cfg.sample_interval_s * cfg.time_scale
        self._sim_time_s += dt

        acquired_at = at or datetime.now(timezone.utc)
        if acquired_at.tzinfo is None:
            acquired_at = acquired_at.replace(tzinfo=timezone.utc)

        # Latent drivers: correlated "weather/hydrology" and smooth noise.
        self._runoff = self._ou_step(self._runoff, tau_s=300.0, stationary_sigma=0.55, dt=dt)
        self._flow_state = self._ou_step(self._flow_state, tau_s=120.0, stationary_sigma=1.0, dt=dt)
        self._temp_state = self._ou_step(self._temp_state, tau_s=900.0, stationary_sigma=0.25, dt=dt)

        # --- Water temperature: slow diurnal sinusoid + smooth noise -------
        phase = TWO_PI * (self._sim_time_s - 6.0 * 3600.0) / SECONDS_PER_DAY
        temp = (
            cfg.temp_mean
            + cfg.temp_amplitude * math.sin(phase)
            + self._temp_state
            + self._rng.gauss(0.0, 0.08)
        )
        water_temp_c = round(clamp(temp, cfg.temp_min, cfg.temp_max), 2)

        # --- Normal baselines with shared runoff coupling ------------------
        ph_normal = cfg.ph_baseline - 0.06 * self._runoff + self._rng.gauss(0.0, 0.035)
        ph_normal = clamp(ph_normal, cfg.ph_min, cfg.ph_max)

        turb_normal = cfg.turbidity_baseline + 1.1 * self._runoff + self._rng.gauss(0.0, 0.25)
        turb_normal = clamp(turb_normal, cfg.turbidity_min, cfg.turbidity_max)

        tds_normal = cfg.tds_baseline + 11.0 * self._runoff + self._rng.gauss(0.0, 2.0)
        tds_normal = clamp(tds_normal, cfg.tds_min, cfg.tds_max)

        flow_normal = cfg.flow_baseline + self._flow_state + self._rng.gauss(0.0, 0.25)
        flow_normal = clamp(flow_normal, cfg.flow_min, cfg.flow_max)

        # --- Contamination: one event drives all four parameters -----------
        envelope = self._contamination_envelope()

        turbidity_ntu = turb_normal + (cfg.contamination_peak_turbidity - turb_normal) * envelope

        tds_ppm = tds_normal + (cfg.contamination_peak_tds - tds_normal) * envelope

        # pH falls non-linearly (Hill inhibition) toward a hard floor, rather
        # than being pushed to arbitrary low values to force an alarm.
        if envelope > 0.0:
            hill = (envelope / cfg.contamination_ph_hill_k) ** cfg.contamination_ph_hill_n
            ph = cfg.contamination_ph_floor + (ph_normal - cfg.contamination_ph_floor) / (1.0 + hill)
        else:
            ph = ph_normal

        # Short inflow pressure surge at onset, then a mild sustained drop.
        flow = flow_normal
        if self._contamination_start_s is not None:
            elapsed = self._sim_time_s - self._contamination_start_s
            if elapsed >= 0.0:
                ts = cfg.contamination_pressure_surge_tau_s
                surge = cfg.contamination_pressure_surge_amp * (elapsed / ts) * math.exp(1.0 - elapsed / ts)
                flow += surge - cfg.contamination_flow_reduction * envelope
        flow = clamp(flow, 0.0, cfg.flow_max + 4.0)

        # A complete interruption overrides every other flow effect.
        if self._supply_interrupted:
            flow = cfg.interrupted_flow_lpm

        return Reading(
            node_id=cfg.node_id,
            acquired_at=acquired_at,
            ph=round(clamp(ph, 3.0, 14.0), 3),
            turbidity_ntu=round(max(0.0, turbidity_ntu), 2),
            tds_ppm=round(max(0.0, tds_ppm), 1),
            water_temp_c=water_temp_c,
            flow_lpm=round(flow, 2),
            latitude=cfg.latitude,
            longitude=cfg.longitude,
        )

    def generate(self, count: int, start_at: Optional[datetime] = None) -> list[Reading]:
        """Generate ``count`` consecutive readings with evenly spaced timestamps."""
        if count < 0:
            raise ValueError("count must be non-negative")
        base = start_at or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return [
            self.tick(at=base + timedelta(seconds=i * self.config.sample_interval_s))
            for i in range(count)
        ]
