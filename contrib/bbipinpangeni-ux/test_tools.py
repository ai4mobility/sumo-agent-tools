"""Tests for the queue analysis and spillback screening tools."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import traci
import tools as M
import sumo_agent_tools as T


PLACE = "Bruce B Downs & Pine"
APPROACH = "SB"


def at(t):
    """Start or advance the deterministic SUMO simulation."""
    if not T._LIVE.get("on") or traci.simulation.getTime() > t:
        T.start_live(demand="demand", seed=1)

    now = traci.simulation.getTime()
    if now < t:
        T.advance(int(t - now))


def test_queue_snapshot_matches_verified_data():
    at(1800)
    out = M.upstream_spillback_assessment(PLACE, APPROACH)

    assert "359.6 ft" in out, out
    assert "1060.8 ft" in out, out
    assert "33.9%" in out, out
    assert "701.2 ft" in out, out


def test_spillback_assessment_is_read_only():
    at(1800)
    before = traci.simulation.getTime()

    M.upstream_spillback_assessment(PLACE, APPROACH)

    after = traci.simulation.getTime()
    assert before == after, f"Time changed: {before} -> {after}"


def test_plain_vs_spillback_assessment():
    at(1800)

    plain = M.upstream_spillback_assessment_plain(
        PLACE, APPROACH
    )
    enriched = M.upstream_spillback_assessment(
        PLACE, APPROACH
    )

    assert '"queue_ft"' in plain, plain
    assert '"storage_ft"' in plain, plain

    assert "remaining storage" in enriched, enriched
    assert "Snapshot only" in enriched, enriched
    assert "not confirmation of actual intersection blockage" in enriched, enriched


def test_maximum_queue_matches_verified_data():
    at(900)

    out = M.worst_queue_analysis(PLACE, APPROACH)

    assert "853.4 ft" in out, out
    assert "4084 s" in out, out
    assert "1060.8 ft" in out, out


def test_full_analysis_hour_coverage():
    # The previous test advanced the simulation through 4500 s.
    assert traci.simulation.getTime() == 4500, (
        f"Unexpected final time: {traci.simulation.getTime()}"
    )




def test_corridor_delay_verified_data():
    at(1800)
    out = M.corridor_delay_assessment("EB")
    assert "4.50 min" in out, out
    assert "31 completed trips" in out, out
    assert "2.00 min" in out, out
    assert "+2.50 min" in out, out


def test_speed_and_stopped_verified_data():
    at(1800)
    out = M.approach_speed_assessment(PLACE, APPROACH)
    assert "17 vehicles, 16 stopped" in out, out
    assert "2.5 mph" in out, out
    assert "below 0.1 m/s" in out, out


def test_plain_vs_corridor_delay():
    at(1800)
    plain = M.corridor_delay_assessment_plain("EB")
    enriched = M.corridor_delay_assessment("EB")
    assert "median of 31 trips" in plain, plain
    assert "additional travel time +2.50 min" in enriched, enriched
    assert "not a measured bridge work-zone effect" in enriched, enriched


def test_analysis_period_warning():
    at(300)
    out = M.approach_speed_assessment(PLACE, APPROACH)
    assert "WARM-UP WARNING" in out, out

    at(1800)
    out = M.approach_speed_assessment(PLACE, APPROACH)
    assert "WARM-UP WARNING" not in out, out


def teardown():
    T.stop_live()


if __name__ == "__main__":
    tests = [
        (name, func)
        for name, func in list(globals().items())
        if name.startswith("test_") and callable(func)
    ]

    bad = 0

    try:
        for name, func in tests:
            try:
                func()
                print("PASS", name)
            except Exception as exc:
                bad += 1
                print("FAIL", name, type(exc).__name__, str(exc)[:400])
    finally:
        teardown()

    print(f"{len(tests) - bad} of {len(tests)} pass")
    sys.exit(1 if bad else 0)
