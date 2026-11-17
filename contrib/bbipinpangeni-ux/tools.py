"""Queue length and upstream storage measurements for the SUMO corridor."""

import os
import sys
import json

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

import traci
import sumo_agent_tools as T


def _approach(intersection: str, approach: str):
    T._need_live()
    tid, name = T._resolve(intersection)
    approaches = T._approaches(tid)

    if approach not in approaches:
        raise ValueError(
            f"{name} has approaches {sorted(approaches)}, not {approach}"
        )

    return name, approaches[approach]


def _reading(edge):
    vehicles, storage_m, _ = T._approach_vehicles(edge)
    queue_m, queued_count = T._queue_back(vehicles)

    return {
        "time_s": traci.simulation.getTime(),
        "queue_ft": queue_m / T.FT,
        "storage_ft": storage_m / T.FT,
        "queued_vehicles": queued_count,
    }


def _scan(intersection: str, approach: str):
    name, edge = _approach(intersection, approach)

    current = traci.simulation.getTime()
    if current > 4500:
        raise ValueError(
            "Simulation is past the analysis hour. Restart it."
        )

    if current < 900:
        T.advance(int(900 - current))

    start = traci.simulation.getTime()
    readings = []

    while True:
        readings.append(_reading(edge))

        if traci.simulation.getTime() >= 4500:
            break

        T.advance(1)

    peak = max(readings, key=lambda r: r["queue_ft"])

    return {
        "intersection": name,
        "approach": approach,
        "start_s": start,
        "end_s": traci.simulation.getTime(),
        "samples": len(readings),
        "peak": peak,
        "full_analysis_hour": start == 900,
    }


def worst_queue_analysis(intersection: str, approach: str) -> str:
    """Measure the largest observed queue on one intersection approach
    during the remaining SUMO analysis period, ending at 4500 seconds.
    Specify an intersection name and the direction of travel: EB, WB,
    NB or SB. This tool changes simulation time by advancing the live simulation, taking readings
    at one-second intervals. It reports the largest measured queue,
    when it occurred, the available upstream storage, and whether the
    complete analysis hour was observed. The result is a simulated
    queue measurement, not proof of physical intersection blockage.
    Do not call it after the analysis period has ended."""

    try:
        result = _scan(intersection, approach)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"

    p = result["peak"]
    coverage = (
        "Complete analysis hour."
        if result["full_analysis_hour"]
        else "Partial analysis hour: earlier peak may be missed."
    )

    return (
        f"{result['intersection']} {approach}: "
        f"maximum observed queue {p['queue_ft']:.1f} ft "
        f"at {p['time_s']:.0f} s. "
        f"Available storage {p['storage_ft']:.1f} ft. "
        f"{result['samples']} readings from "
        f"{result['start_s']:.0f} to {result['end_s']:.0f} s. "
        f"{coverage} This does not establish actual upstream blockage."
    )


def worst_queue_analysis_plain(
    intersection: str, approach: str
) -> str:
    """Baseline measurement without engineering interpretation."""
    try:
        result = _scan(intersection, approach)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"

    return json.dumps(result)


def upstream_spillback_assessment(
    intersection: str, approach: str
) -> str:
    """Inspect the current queue and available upstream storage on
    one SUMO intersection approach without advancing simulation time. Read-only.
    Specify the intersection and direction of travel: EB, WB, NB or
    SB. Report the simulated queue length, upstream storage length,
    percentage occupied, remaining storage and observation time.
    These measurements help an engineer investigate possible upstream
    queue spillback, but queue occupancy alone does not prove that
    an intersection is physically blocked. Treat this as a snapshot,
    not a maximum over time, and check the analysis period."""

    try:
        name, edge = _approach(intersection, approach)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"

    r = _reading(edge)

    if r["storage_ft"] <= 0:
        return "Error: no positive approach storage length."

    used = 100 * r["queue_ft"] / r["storage_ft"]
    remaining = r["storage_ft"] - r["queue_ft"]

    return (
        f"{name} {approach} at {r['time_s']:.0f} s: "
        f"queue {r['queue_ft']:.1f} ft; "
        f"available storage {r['storage_ft']:.1f} ft; "
        f"storage occupied {used:.1f}%; "
        f"remaining storage {remaining:.1f} ft. "
        f"{T._period_note()} "
        f"Snapshot only. Occupancy is a screening measurement, "
        f"not confirmation of actual intersection blockage."
    )


def upstream_spillback_assessment_plain(
    intersection: str, approach: str
) -> str:
    """Baseline output with raw measurements only."""
    name, edge = _approach(intersection, approach)
    return json.dumps({
        "intersection": name,
        "approach": approach,
        **_reading(edge),
    })


TOOLS = [
    worst_queue_analysis,
    upstream_spillback_assessment,
]

READ_ONLY = {
    "upstream_spillback_assessment",
}

SCHEMAS = {
    name: T._S(
        intersection=dict(T._INT),
        approach=dict(T._APP),
    )
    for name in [
        "worst_queue_analysis",
        "upstream_spillback_assessment",
    ]
}

PLAIN_DESCRIPTIONS = {
    "worst_queue_analysis":
        "Returns maximum observed queue measurements for an "
        "intersection and approach. Advances simulation.",
    "upstream_spillback_assessment":
        "Returns current queue and storage measurements for an "
        "intersection and approach. Read-only.",
}

RAW_RESULTS = {
    "worst_queue_analysis": worst_queue_analysis_plain,
    "upstream_spillback_assessment":
        upstream_spillback_assessment_plain,
}


import re
import statistics


def corridor_delay_assessment(direction: str) -> str:
    """Assess Fowler Avenue corridor travel-time delay in the requested
    direction of travel, EB or WB, at the current SUMO simulation time.
    Read-only. This tool compares the median observed travel time of
    recently completed trips with the corridor free-flow reference and
    reports the additional travel time in minutes. It identifies the
    number of completed trips supporting the median, because results
    with few observations deserve caution. It also reports whether the
    current simulation time is outside the analysis hour. No completed
    trips means the tool cannot estimate a measured travel-time delay.
    This baseline corridor simulation does not represent a bridge
    maintenance lane closure."""

    if direction not in ("EB", "WB"):
        return "Error: direction must be EB or WB."

    T._need_live()
    report = T.get_corridor_state(direction)

    match = re.search(
        r"measured travel time\s+([0-9.]+)\s+min"
        r"\s*\(median of\s+(\d+)\s+trips.*?"
        r"free-flow\s+([0-9.]+)\s+min",
        report,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return (
            f"Fowler Avenue {direction}: measured trip-based travel "
            f"time is unavailable or could not be parsed at "
            f"{traci.simulation.getTime():.0f} s. "
            "Do not infer a measured delay without completed-trip "
            "observations. Original toolkit report: " + report
        )

    measured, count, freeflow = (
        float(match.group(1)),
        int(match.group(2)),
        float(match.group(3)),
    )
    delay = measured - freeflow

    return (
        f"Fowler Avenue {direction} at "
        f"{traci.simulation.getTime():.0f} s: "
        f"measured median travel time {measured:.2f} min "
        f"from {count} completed trips; "
        f"free-flow reference {freeflow:.2f} min; "
        f"additional travel time {delay:+.2f} min. "
        "These are rounded toolkit travel-time values, so the "
        "calculated difference is approximate. "
        f"{T._period_note()} "
        "The sample count is reported; no statistical precision "
        "or reliability threshold has been established. "
        "This is not a measured bridge work-zone effect."
    )


def corridor_delay_assessment_plain(direction: str) -> str:
    """Uninterpreted corridor report from the existing toolkit."""
    T._need_live()
    if direction not in ("EB", "WB"):
        return "Error: direction must be EB or WB."
    return T.get_corridor_state(direction)


def approach_speed_assessment(
    intersection: str, approach: str
) -> str:
    """Use this tool when the question asks for mean vehicle speed,
    the number of stopped vehicles, or both, on a specific intersection
    approach. Report current traffic speed and stopped vehicles for a
    specified SUMO intersection approach, using the full upstream
    approach chain.
    Read-only. Accept an intersection name and travel direction EB, WB,
    NB or SB. The stopped count follows SUMO's halting definition of
    vehicle speed below 0.1 metres per second, which is different from
    the slower-moving vehicles counted by the toolkit queue algorithm.
    Report the number of vehicles and their instantaneous arithmetic
    mean speed in mph, without treating an empty approach as free-flow
    traffic. This result describes one simulation snapshot; it is not
    a speed history or direct evidence of a maintenance work zone."""

    try:
        name, edge = _approach(intersection, approach)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"

    vehicles, storage_m, _ = T._approach_vehicles(edge)
    speeds = [v for _, _, v in vehicles]
    stopped = sum(v < 0.1 for v in speeds)

    if speeds:
        avg_mph = statistics.mean(speeds) / T.MPH
        speed_text = f"{avg_mph:.1f} mph"
    else:
        speed_text = "not measured (no vehicles present)"

    return (
        f"{name} {approach} at "
        f"{traci.simulation.getTime():.0f} s: "
        f"{len(speeds)} vehicles, {stopped} stopped "
        f"(speed below 0.1 m/s); "
        f"instantaneous mean vehicle speed {speed_text}. "
        f"Upstream approach storage {storage_m / T.FT:.1f} ft. "
        f"{T._period_note()} "
        "Stopped vehicles are not necessarily the same as queued "
        "vehicles. This is a snapshot, not a time-averaged speed."
    )


def approach_speed_assessment_plain(
    intersection: str, approach: str
) -> str:
    """Return raw approach vehicle-speed observations."""
    name, edge = _approach(intersection, approach)
    vehicles, storage_m, _ = T._approach_vehicles(edge)
    return json.dumps({
        "intersection": name,
        "approach": approach,
        "time_s": traci.simulation.getTime(),
        "storage_m": storage_m,
        "vehicle_speeds_mps": [v for _, _, v in vehicles],
    })


TOOLS.extend([
    corridor_delay_assessment,
    approach_speed_assessment,
])

READ_ONLY.update({
    "corridor_delay_assessment",
    "approach_speed_assessment",
})

SCHEMAS.update({
    "corridor_delay_assessment":
        T._S(direction={"EB": "eastbound", "WB": "westbound"}),
    "approach_speed_assessment":
        T._S(intersection=dict(T._INT), approach=dict(T._APP)),
})

PLAIN_DESCRIPTIONS.update({
    "corridor_delay_assessment":
        "Return current Fowler Avenue corridor travel-time data "
        "for a specified eastbound or westbound direction. Read-only.",
    "approach_speed_assessment":
        "Return current vehicle speeds and counts for an "
        "intersection approach. Read-only.",
})

RAW_RESULTS.update({
    "corridor_delay_assessment": corridor_delay_assessment_plain,
    "approach_speed_assessment": approach_speed_assessment_plain,
})
