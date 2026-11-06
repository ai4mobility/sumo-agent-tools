# Knowledge card: lane_use

*This card describes the template's example tool. In your copy, replace every section with your own tools,
rules and tests. The checker reads the section titles, so keep them.*

## Who it is for

A signal timing engineer checking a timing plan in the Fowler Ave model, who wants to see which lane is holding
the queue at an approach (the left-turn bay or the through lanes) before changing a split. They read it at the end
of red, several times during the analysis hour.

## Rules

| # | Rule: what a traffic engineer knows | Source | Where in tools.py | Test |
|---|---|---|---|---|
| 1 | Name a lane by what it serves (left-turn, through, right-turn, shared through-right), and list lanes from the median to the curb, as a driver sees them. SUMO numbers lanes the other way: index 0 is the curb lane. | SUMO documentation, "Networks/SUMO Road Networks" (lane indices start at 0 on the rightmost lane); lane groups by movement, HCM signalized intersections chapter | `MOVE`, `_lane_movements`, `_lane_name`, the sort in `lane_use` | `test_lanes_from_median_named_by_movement` |
| 2 | A lane that no connection leaves at the stop line serves no movement: it is not an approach lane, and it should be checked in the network (a lane that ends, or a missing connection). Fowler & Leroy Collins EB has 5 lanes in SUMO and 3 that serve a movement. | The network file (`fowler/fowler.net.xml`, read with sumolib); lane groups by movement, HCM | the `if not moves` branch | `test_lane_without_movement_not_counted` |
| 3 | Speed is undefined on an empty lane (no vehicles, no space-mean speed). SUMO's lane mean speed reports the speed limit there, which reads as free flow. Say "no vehicles". | Traffic flow theory: space-mean speed is the mean over vehicles present; SUMO TraCI lane value retrieval (`getLastStepMeanSpeed`) | the `if sp else` branch | `test_empty_lane_has_no_speed` |
| 4 | "Stopped" needs a definition: below 0.1 m/s, SUMO's halting rule. Say which one: SUMO's lane-area detectors call a vehicle jammed below 5 km/h, a different threshold. | TraCI lane value retrieval, `getLastStepHaltingNumber` ("a speed of less than 0.1 m/s is considered a halt"); `T.STOPPED_MPS` | `T.STOPPED_MPS` in the state line | `test_stopped_is_sumo_halting` |
| 5 | A reading before 900 s is the warm-up, and after 4,500 s the peak has ended: say so, or a model will answer a peak-hour question from an empty network. | The scenario's analysis hour (`T.WARMUP`, `T.END`); the toolkit's recorded run C (walkthrough/README.md) | `T._period_note()` | `test_warmup_warning` |

## Plain vs. yours

The plain version (`lane_use_plain`) returns what TraCI's lane getters give. At Bruce B Downs & USF Pine Dr SB at
1,800 s it says three lanes run at 20.12 m/s with nobody halting, which reads as free flow; two of them are empty
through lanes and the third serves no movement at all. The queue, 6 stopped vehicles, is in the left-turn lane,
which the plain version calls `_4` because SUMO counts from the curb. A model reading the plain result could tell
the engineer the southbound through lanes flow at 45 mph and point to the wrong lane for the queue.
`test_plain_vs_lane_use` checks both readings.

## What the data cannot tell

The tool reads one moment, on the edge at the stop line only (139 ft at Pine Dr SB, 29 ft at McKinley NB): it does
not see the queue behind that edge, and a queue at a signal rises and falls every cycle. It cannot say whether a lane
with no movement is a real lane drop or a mistake in the OpenStreetMap data; a site visit or an aerial photo would.
The demand in this scenario is synthetic, so the readings describe the model, not Fowler Ave on a real afternoon.

## AI use

Claude (Opus 5.5) wrote this template, code and card, for the course. The test cases (Pine Dr NB and SB, Leroy
Collins EB, 1,800 s, seed 1) were found by running the simulation and reading every approach lane by lane, and
each expected value was checked against TraCI's own readings. In your card, say which AI tools you used and for
what, and which rules, sources and expected answers you checked yourself.
