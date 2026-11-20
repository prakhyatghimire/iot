#!/usr/bin/env python3
"""Phase 1 verification: exercise the telemetry generator and prove the model.

Run with::

    python3 verify_phase1.py

This script uses fixed acquisition timestamps so the whole demonstration is
repeatable. It exits non-zero if any check fails.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jalsanket import GeneratorConfig, TelemetryGenerator

START = datetime(2026, 6, 15, 6, 0, 0, tzinfo=timezone.utc)
REQUIRED_FIELDS = (
    "node_id",
    "acquired_at",
    "ph",
    "turbidity_ntu",
    "tds_ppm",
    "water_temp_c",
    "flow_lpm",
    "latitude",
    "longitude",
)

results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((bool(passed), name, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))


def times(count: int):
    return [START + timedelta(seconds=i * 2.0) for i in range(count)]


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    cfg = GeneratorConfig(node_id="node-01", seed=42)
    gen = TelemetryGenerator(cfg)
    stamps = times(60)

    # ---------------------------------------------------------------- normal
    section("1. Normal telemetry (60 readings)")
    normal = gen.generate(len(stamps), start_at=START)

    check("all required fields present", all(hasattr(normal[0], f) for f in REQUIRED_FIELDS))
    check("node id propagated", all(r.node_id == "node-01" for r in normal))
    check("timestamps are UTC aware", all(r.acquired_at.tzinfo is not None for r in normal))
    check("timestamps strictly increasing", all(b.acquired_at > a.acquired_at for a, b in zip(normal, normal[1:])))
    check("timestamps match expected sequence", all(r.acquired_at == s for r, s in zip(normal, stamps)))
    check("acquisition_ms is epoch milliseconds", normal[0].acquisition_ms() == int(START.timestamp() * 1000))

    phs = [r.ph for r in normal]
    turbs = [r.turbidity_ntu for r in normal]
    tdss = [r.tds_ppm for r in normal]
    temps = [r.water_temp_c for r in normal]
    flows = [r.flow_lpm for r in normal]

    check("pH within 6.8-7.6", all(6.8 <= v <= 7.6 for v in phs), f"{min(phs):.3f}..{max(phs):.3f}")
    check("turbidity within 2-8 NTU", all(2.0 <= v <= 8.0 for v in turbs), f"{min(turbs):.2f}..{max(turbs):.2f}")
    check("TDS within 120-250 ppm", all(120.0 <= v <= 250.0 for v in tdss), f"{min(tdss):.1f}..{max(tdss):.1f}")
    check("temperature within 16-24 C", all(16.0 <= v <= 24.0 for v in temps), f"{min(temps):.2f}..{max(temps):.2f}")
    check("flow within 8-18 L/min", all(8.0 <= v <= 18.0 for v in flows), f"{min(flows):.2f}..{max(flows):.2f}")
    check("coordinates present", all(r.latitude == cfg.latitude and r.longitude == cfg.longitude for r in normal))

    temp_steps = [abs(b - a) for a, b in zip(temps, temps[1:])]
    check("temperature varies smoothly", max(temp_steps) < 0.5, f"max step {max(temp_steps):.3f} C")
    check("normal flow actually varies", max(flows) - min(flows) > 0.5, f"spread {max(flows) - min(flows):.2f} L/min")

    print("  sample rows:")
    for r in normal[:3]:
        print("   ", r.to_dict())

    # ---------------------------------------------------------- contamination
    section("2. Rainfall-triggered contamination (rising phase)")
    gen.trigger_contamination()
    contam = gen.generate(15, start_at=START + timedelta(seconds=120))
    c_phs = [r.ph for r in contam]
    c_turbs = [r.turbidity_ntu for r in contam]
    c_tdss = [r.tds_ppm for r in contam]
    c_flows = [r.flow_lpm for r in contam]

    check("turbidity crosses warning threshold (>50)", max(c_turbs) > 50, f"peak {max(c_turbs):.2f} NTU")
    check("turbidity crosses critical threshold (>200)", max(c_turbs) > 200, f"peak {max(c_turbs):.2f} NTU")
    check("TDS rises above 500 ppm", max(c_tdss) > 500, f"peak {max(c_tdss):.1f} ppm")
    check("pH falls below 6.5", min(c_phs) < 6.5, f"min {min(c_phs):.3f}")
    check("pH never drops below physical floor (6.0)", min(c_phs) >= 6.0, f"min {min(c_phs):.3f}")
    check("flow is perturbed", max(c_flows) > max(flows) or min(c_flows) < min(flows),
          f"normal {min(flows):.1f}-{max(flows):.1f}, event {min(c_flows):.1f}-{max(c_flows):.1f}")
    check("turbidity rise is gradual (not a single jump)", sum(b > a for a, b in zip(c_turbs, c_turbs[1:])) >= 3)

    print("  event rows (first 6):")
    for r in contam[:6]:
        print("   ", r.to_dict())

    # --------------------------------------------------------------- washout
    section("3. Washout phase")
    wash = gen.generate(200, start_at=START + timedelta(seconds=150))
    w_turbs = [r.turbidity_ntu for r in wash]
    w_tdss = [r.tds_ppm for r in wash]
    w_phs = [r.ph for r in wash]

    check("turbidity washes out below 40 NTU", w_turbs[-1] < 40.0, f"final {w_turbs[-1]:.2f} NTU")
    check("washout is monotonic overall", w_turbs[-1] < w_turbs[0])
    check("TDS returns toward baseline", w_tdss[-1] < 300, f"final {w_tdss[-1]:.1f} ppm")
    check("pH recovers above 6.5", w_phs[-1] > 6.5, f"final {w_phs[-1]:.3f}")
    check("envelope eventually reaches zero", gen.contamination_intensity < 0.05,
          f"intensity {gen.contamination_intensity:.4f}")

    # ----------------------------------------------------------- interruption
    section("4. Complete supply interruption")
    gen.set_supply_interrupted(True)
    interrupted = gen.generate(5, start_at=START + timedelta(seconds=500))
    check("flow becomes exactly zero", all(r.flow_lpm == 0.0 for r in interrupted))
    gen.set_supply_interrupted(False)
    restored = gen.generate(3, start_at=START + timedelta(seconds=510))
    check("flow resumes after restoration", all(r.flow_lpm > 0.0 for r in restored),
          f"{[r.flow_lpm for r in restored]}")

    # ----------------------------------------------------------- repeatability
    section("5. Repeatability after reset()")
    # Replay the exact same scenario (normal phase -> trigger -> event) so the
    # RNG state and simulation clock match the original run.
    gen.reset()
    gen.generate(60, start_at=START)
    gen.trigger_contamination()
    replay = gen.generate(15, start_at=START + timedelta(seconds=120))
    check("contamination curve is bit-for-bit repeatable",
          [r.turbidity_ntu for r in replay] == c_turbs
          and [r.ph for r in replay] == c_phs
          and [r.flow_lpm for r in replay] == c_flows)
    gen.reset()
    after_reset = gen.generate(1, start_at=START)
    fresh = TelemetryGenerator(cfg).generate(1, start_at=START)
    check("reset() restores seeded initial state", after_reset[0] == fresh[0])

    gen2 = TelemetryGenerator(cfg)
    gen2.trigger_contamination()
    event_a = gen2.generate(15, start_at=START + timedelta(seconds=120))
    gen3 = TelemetryGenerator(cfg)
    gen3.trigger_contamination()
    event_b = gen3.generate(15, start_at=START + timedelta(seconds=120))
    check("two fresh generators produce identical events",
          [r.turbidity_ntu for r in event_a] == [r.turbidity_ntu for r in event_b]
          and [r.ph for r in event_a] == [r.ph for r in event_b])

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
    print("\nPhase 1 verification: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
