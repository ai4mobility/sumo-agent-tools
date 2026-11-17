# Knowledge Card: Traffic Operations and Spillback Assessment

This project develops four SUMO-based traffic analysis tools for a modeled urban corridor. The tools assess queue length, upstream storage, travel-time delay, vehicle speeds, and data limitations. They support preliminary traffic operations assessment relevant to maintenance planning, but the baseline simulation does not contain an actual bridge lane closure.

## Rules

| # | Rule: what a traffic engineer knows | Source | Where in tools.py | Test |
|---|---|---|---|---|
| 1 | Maximum queue length should be evaluated over the analysis period rather than inferred from one snapshot. Compare the queue with available upstream storage, but do not interpret storage occupancy alone as proof of physical intersection blockage. | FHWA, *A Primer on Work Zone Safety and Mobility Performance Measurement*, Table 3, Maximum Queue Length; SUMO Lanearea Detectors (E2) documentation. | `worst_queue_analysis`, `_scan`, `upstream_spillback_assessment` | `test_maximum_queue_matches_verified_data` |
| 2 | Corridor travel-time delay can be described by comparing an observed travel-time statistic with a clearly identified reference. The resulting difference must not automatically be attributed to maintenance activity when no work-zone scenario has been simulated. | FHWA, *A Primer on Work Zone Safety and Mobility Performance Measurement*, Table 4, Delay Performance Measures. | `corridor_delay_assessment` | `test_corridor_delay_verified_data` |
| 3 | Stopped vehicles and vehicles in a traffic queue are not necessarily identical. SUMO defines a halting vehicle as traveling below 0.1 m/s. Report observed vehicle speed and stopped count separately rather than assuming one measurement completely characterizes congestion. | SUMO TraCI Lane Value Retrieval, `getLastStepHaltingNumber`; FHWA, Table 5, Average Speed. | `approach_speed_assessment`, `_reading` | `test_speed_and_stopped_verified_data` |
| 4 | Traffic conditions must be interpreted with respect to the observation period and available sample. The scenario analysis hour is 900–4500 s; results obtained during warm-up or from an incomplete time interval must be distinguished from full analysis-hour results. The number of completed trips supporting a travel-time median must be disclosed. | FHWA, work-zone mobility performance measures and travel-time reliability discussion; scenario definitions in `sumo_agent_tools.py`. | `_scan`, `worst_queue_analysis`, `corridor_delay_assessment`, `approach_speed_assessment` | `test_analysis_period_warning` |

### Primary sources

1. Federal Highway Administration (FHWA). *A Primer on Work Zone Safety and Mobility Performance Measurement*, section "Selecting Useful Work Zone Performance Measures":
   https://ops.fhwa.dot.gov/wz/resources/publications/fhwahop11033/select_measures.htm

2. SUMO Documentation. *Lanearea Detectors (E2)*:
   https://sumo.dlr.de/docs/Simulation/Output/Lanearea_Detectors_%28E2%29.html

3. SUMO Documentation. *TraCI Lane Value Retrieval*:
   https://sumo.dlr.de/docs/TraCI/Lane_Value_Retrieval.html

4. Course SUMO scenario and toolkit:
   `sumo_agent_tools.py`, including the simulation analysis period and approach measurement functions.

### Verified simulation observations

The following values were obtained using the course scenario, demand `demand`, and random seed 1.

- At Bruce B Downs Blvd & USF Pine Dr, southbound, the queue at simulation time 1800 s was 359.6 ft.
- Available upstream storage was 1060.8 ft.
- At 1800 s, the queue occupied 33.9% of the available storage, leaving approximately 701.2 ft.
- Across 3601 measurements from 900 through 4500 s, the maximum observed queue was 853.4 ft at 4084 s.
- Fowler Avenue eastbound at 1800 s had a measured median travel time of 4.5 min from 31 completed trips and a free-flow reference of 2.0 min.
- The difference between these rounded travel-time values was approximately 2.5 min.
- The southbound approach had 17 vehicles, 16 stopped, and an instantaneous arithmetic mean vehicle speed of 2.5 mph at 1800 s.

These values are simulation-specific test references, not field measurements.

## Plain vs. yours

The plain outputs expose the toolkit's raw or minimally processed traffic measurements. The enriched tools make the observations easier to interpret for a traffic engineer.

`upstream_spillback_assessment` reports queue length, storage occupied, remaining storage, and the limitation that occupancy alone does not establish actual upstream intersection blockage. The corresponding plain function returns measurements without this explanatory interpretation.

`worst_queue_analysis` explicitly identifies the largest observed queue, its occurrence time, and whether the complete analysis hour was evaluated. This prevents a single queue snapshot from being mistaken for the maximum over the analysis period.

`corridor_delay_assessment` compares the measured median travel time with the free-flow reference and reports the difference, the completed-trip count, and the limitation that the observed delay is not necessarily attributable to a maintenance work zone.

`approach_speed_assessment` separates stopped vehicles from mean vehicle speed and describes the observation as a snapshot. Its plain function supplies raw vehicle-speed measurements.

The tests check expected numerical observations and relevant differences between plain and enriched outputs.

## What the data cannot tell

The simulation describes a synthetic-demand Fowler Avenue corridor rather than observed traffic at a real bridge rehabilitation project. No bridge lane closure or work-zone capacity reduction has been implemented.

The reported queue and storage measurements cannot independently confirm that an upstream intersection is physically blocked. The simulation also cannot establish the traffic effects of bridge maintenance without a separate maintenance scenario and an appropriate comparison with baseline conditions.

The queue results describe one simulation seed and one demand configuration. Maximum queue may change with demand, random seed, roadway geometry, traffic signals, and vehicle behavior.

The reported travel-time delay compares a simulated observed median with a free-flow reference. It is not an estimate of extra delay caused by construction. Thirty-one completed trips support the reported median at 1800 s, but a statistical confidence interval or formal reliability measure has not been calculated.

Mean speed and stopped-vehicle count are snapshots rather than summaries of traffic conditions over the entire analysis period.

## AI use

ChatGPT (OpenAI) assisted with Python implementation, debugging, test construction, source interpretation, and preparation of this knowledge card.

The project concepts were selected by the student: queue and spillback, travel-time delay, speed and stopped vehicles, and observation-period reliability.

Simulation observations were generated in GitHub Codespaces using the course SUMO environment and compared with the test expectations. Primary sources include FHWA guidance and SUMO technical documentation.

The student is responsible for reviewing this document, confirming the engineering interpretations, and ensuring that submitted source references and test expectations match the final implementation.
