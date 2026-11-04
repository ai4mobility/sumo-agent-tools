"""The same kind of SUMO tools written straight from the API: thin wrappers whose descriptions are TraCI's and
sumolib's own docstrings, copied word for word (SUMO 1.28.0). This is what you get when someone who knows
SUMO's functions, but not traffic engineering, writes the tools: often an AI coding assistant asked to
"wrap TraCI as tools".

The companion "Building SUMO Tools for AI Agents" uses this file as the comparison case. Nothing here is
wrong as code. The problems are in what the descriptions leave out, and in one place a unit the docstring gets
wrong; experiments.py measures each one, and test_claims.py tests the claims.
"""
import os, subprocess, statistics
import sumo, sumolib, traci

SUMO_HOME = os.environ.setdefault('SUMO_HOME', sumo.SUMO_HOME)


def list_traffic_lights():
    """getIDList() -> list(string)

    Returns a list of ids of all traffic lights within the scenario."""
    return traci.trafficlight.getIDList()


def get_lane_mean_speed(lane_id):
    """getLastStepMeanSpeed(string) -> double

    Returns the average speed in m/s for the last time step on the given lane."""
    return traci.lane.getLastStepMeanSpeed(lane_id)


def get_lane_vehicle_number(lane_id):
    """getLastStepVehicleNumber(string) -> integer

    Returns the total number of vehicles for the last time step on the given lane."""
    return traci.lane.getLastStepVehicleNumber(lane_id)


def get_lane_occupancy(lane_id):
    """getLastStepOccupancy(string) -> double

    Returns the occupancy in % for the last time step on the given lane."""
    return traci.lane.getLastStepOccupancy(lane_id)


def get_jam_length_meters(detector_id):
    """getJamLengthMeters(string) -> double

    Returns the jam length in meters within the last simulation step."""
    return traci.lanearea.getJamLengthMeters(detector_id)


def simulation_step(step=0):
    """simulationStep(float) -> None
    Make a simulation step and simulate up to the given second in sim time.
    If the given value is 0 or absent, exactly one step is performed.
    Values smaller than or equal to the current sim time result in no action."""
    traci.simulationStep(step)
    return traci.simulation.getTime()


def set_phase_duration(tls_id, phase_duration):
    """setPhaseDuration(string, double) -> None

    Set the remaining phase duration of the current phase in seconds.
    This value has no effect on subsquent repetitions of this phase."""
    traci.trafficlight.setPhaseDuration(tls_id, phase_duration)


def get_signal_program(net_file, tls_id):
    """Reads the network with sumolib.net.readNet(net_file) and returns the phases of the traffic light's
    programs as (duration, state) pairs."""
    net = sumolib.net.readNet(net_file)
    return [(p.duration, p.state) for prog in net.getTLS(tls_id).getPrograms().values() for p in prog.getPhases()]


def run_simulation(net_file, route_file, additional=None, seed=None, end=None):
    """Runs SUMO with the given network and routes and returns the average time loss of the vehicles [s] from
    the tripinfo output."""
    out = os.path.abspath('api_tripinfo.xml')
    cmd = [os.path.join(SUMO_HOME, 'bin', 'sumo'), '-n', net_file, '-r', route_file, '--tripinfo-output', out,
           '--no-step-log', '--no-warnings']
    cmd += ['-a', additional] if additional else []
    cmd += ['--seed', str(seed)] if seed is not None else []
    cmd += ['--end', str(end)] if end is not None else []
    subprocess.run(cmd, check=True, capture_output=True)
    return statistics.mean(float(t.timeLoss) for t in sumolib.xml.parse_fast(out, 'tripinfo', ['id', 'timeLoss']))
