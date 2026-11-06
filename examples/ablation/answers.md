# The answers: 3 questions x 3 setups

Written by contrib/ablation.py. Model Qwen/Qwen3-1.7B, thinking off, seed 1, on cpu. Data: SUMO Fowler Ave scenario (the demand and seed are in the start_live call).

Read each answer against the right answer, then grade it in the table in ABLATION.md: right, partly or wrong, and why in a few words. The table to copy:

| Question | A. Without your tools | B. Your tools, plain | C. Your tools as written |
|---|---|---|---|
| pine_queue_lane | ? | ? | ? |
| pine_empty_speed | ? | ? | ? |
| mckinley_warmup | ? | ? | ? |

## pine_queue_lane

**Question:** The Fowler Ave simulation is running and is at 1,800 s. Which southbound lane at Bruce B Downs & USF Pine Dr is holding the queue?

**Right answer (tasks.json):** The left-turn lane on the median side: 6 vehicles, all stopped. The through lanes hold 1 stopped vehicle (in the curb lane) and none in the other two. Checked with start_live, advance(1800) and lane_use('Bruce B Downs & Pine', 'SB'), seed 1.

Before the model's first turn, the harness called: `start_live()`, `advance(seconds=1800)`.

### A. Without your tools

Tools called: `get_approach_state(intersection='Bruce B Downs & USF Pine Dr', approach='SB')`. 2 turns, 53 s. Run: `ablation/runs/without__pine_queue_lane.json`

> The southbound (SB) lane at Bruce B Downs & USF Pine Dr is holding a queue. The queue is 16 vehicles long, with the back of the queue located 360 feet from the signal. The space-mean speed is 2 mph, and the queue fills 34% of the storage, which is below the 85% threshold for spillback.

### B. Your tools, plain

Tools called: `get_approach_state(intersection='Bruce B Downs & USF Pine Dr', approach='SB')`. 2 turns, 47 s. Run: `ablation/runs/plain__pine_queue_lane.json`

> The southbound (SB) lane at Bruce B Downs & USF Pine Dr is holding a queue. The back of the queue is 360 feet ahead, and there are 16 stopped vehicles. The queue fills 34% of the storage, which is below the 85% threshold for spillback.

### C. Your tools as written

Tools called: `get_approach_state(intersection='Bruce B Downs & USF Pine Dr', approach='SB')`. 2 turns, 52 s. Run: `ablation/runs/full__pine_queue_lane.json`

> The southbound lane at Bruce B Downs & USF Pine Dr is holding a queue. The queue is 16 vehicles long, and the back of the queue is 360 feet from the stop line. The space-mean speed in the lane is 2 mph, and the queue fills 34% of the storage length. No spillback is occurring.

## pine_empty_speed

**Question:** The Fowler Ave simulation is running and is at 1,800 s. How fast is traffic moving in the empty southbound through lanes at Bruce B Downs & USF Pine Dr?

**Right answer (tasks.json):** It cannot be said: those lanes have no vehicles, so there is no speed to measure. SUMO's lane mean speed reports 20.12 m/s (45 mph) there, which is the speed limit, not a traffic speed. Checked with lane_use and lane_use_plain at 1,800 s, seed 1.

Before the model's first turn, the harness called: `start_live()`, `advance(seconds=1800)`.

### A. Without your tools

Tools called: `get_approach_state(intersection='Bruce B Downs & USF Pine Dr', approach='SB')`. 2 turns, 35 s. Run: `ablation/runs/without__pine_empty_speed.json`

> The traffic speed in the empty southbound through lanes at Bruce B Downs & USF Pine Dr is 2 mph.

### B. Your tools, plain

Tools called: `get_approach_state(intersection='Bruce B Downs & USF Pine Dr', approach='SB')`. 2 turns, 35 s. Run: `ablation/runs/plain__pine_empty_speed.json`

> The traffic speed in the empty southbound through lanes at Bruce B Downs & USF Pine Dr is 2 mph.

### C. Your tools as written

Tools called: `get_corridor_state(direction='WB')`. 2 turns, 35 s. Run: `ablation/runs/full__pine_empty_speed.json`

> The traffic speed in the empty southbound through lanes at Bruce B Downs & USF Pine Dr is 37 mph.

## mckinley_warmup

**Question:** The Fowler Ave simulation is running and is at 300 s. Tell me lane by lane what westbound Fowler at McKinley looks like. Is this reading good for the peak hour?

**Right answer (tasks.json):** At 300 s, from the median: 2 left-turn lanes with 1 stopped vehicle each, a lane that serves no movement, then 3 through lanes with no vehicles, 1 vehicle at 57 mph, and no vehicles. It is not good for the peak hour: 300 s is in the warm-up, before the analysis hour (900-4500 s), while the network is still filling. Checked with start_live, advance(300) and lane_use('Fowler & McKinley', 'WB'), seed 1.

Before the model's first turn, the harness called: `start_live()`, `advance(seconds=300)`.

### A. Without your tools

Tools called: `get_approach_state(intersection='Fowler & McKinley', approach='WB')`, `get_corridor_state(direction='WB')`. 3 turns, 156 s. Run: `ablation/runs/without__mckinley_warmup.json`

> The westbound Fowler Ave corridor at 300 s shows a mix of traffic conditions. The lane-by-lane breakdown is as follows:
>
> - **East end (USF Bull Run Dr)**: 893 ft, 2 vehicles, 0 stopped, 45 mph.
> - **USF Bull Run Dr -> Leroy Collins Blvd**: 2,465 ft, 13 vehicles, 0 stopped, 45 mph.
> - **Leroy Collins Blvd -> McKinley Dr**: 861 ft, 3 vehicles, 2 stopped, 19 mph.
> - **McKinley Dr -> Bruce B Downs Blvd & N 30th St**: 2,973 ft, 12 vehicles, 3 stopped, 38 mph.
> - **Bruce B Downs Blvd & N 30th St -> west end**: 1,805 ft, 11 vehicles, 0 stopped, 43 mph.
>
> ### Summary:
> - The corridor has a mix of traffic, with some congestion at the end of McKinley Dr.
> - The space-mean speed is generally high (45-43 mph), which is typical for a busy corridor.
> - The WARM-UP WARNING indicates that the network is still filling, so the current readings do not reflect the peak hour conditions.
>
> ### Peak Hour Consideration:
> - The current readings are at 300 s, which is before the analysis hour (900-4500 s).
> - The network is still filling, so the traffic conditions may not be representative of the peak hour.
> - To get a better reading for the peak hour, you should call `advance` to reach 900 s or later and then read again.
>
> If you need further analysis or adjustments to the signal timing, please let me know.

### B. Your tools, plain

Tools called: `list_intersections()`, `get_approach_state(intersection='Fowler & McKinley', approach='WB')`, `get_corridor_state(direction='WB')`, `lane_use(intersection='Fowler & McKinley', approach='WB')`. 4 turns, 154 s. Run: `ablation/runs/plain__mckinley_warmup.json`

> The lane use for the westbound Fowler Ave at McKinley is as follows:
>
> - **Lane 0**: 0 vehicles, 0 halting, mean speed: null
> - **Lane 1**: 1 vehicle, 0 halting, mean speed: 25.55 m/s
> - **Lane 2**: 0 vehicles, 0 halting, mean speed: null
> - **Lane 3**: 0 vehicles, 0 halting, mean speed: null
> - **Lane 4**: 1 vehicle, 1 halting, mean speed: 0.0 m/s
> - **Lane 5**: 1 vehicle, 1 halting, mean speed: 0.0 m/s
>
> The lane 4 and lane 5 are completely halting, indicating that vehicles are stopped. The lane 1 is moving at a speed of 25.55 m/s, which is a good speed for the peak hour. The lane use is not good for the peak hour as there are vehicles that are completely halting, which indicates a potential traffic jam. The lane use is not good for the peak hour due to the presence of halting vehicles.

### C. Your tools as written

Tools called: `list_intersections()`, `get_approach_state(intersection='Fowler & McKinley', approach='WB')`, `get_lane_use(intersection='Fowler & McKinley', approach='WB')` (refused by the harness: Error: there is no tool named get_lane_use. Tools: list_intersections, start_live, advance, get_approach_state, get_corridor_state, get_signal_plan, set_signal_timing, take_screenshot, stop_live, check_calibration, webster_timing, compare_plans, lane_use.), `lane_use(intersection='Fowler & McKinley', approach='WB')`. 4 turns, 159 s. Run: `ablation/runs/full__mckinley_warmup.json`

> The lane use for the westbound Fowler Ave at McKinley is as follows:
>
> 1. **Left-turn lane (lane 1, median side):** 1 vehicle, 1 stopped, 0 mph space-mean speed.
> 2. **Left-turn lane (lane 2, median side):** 1 vehicle, 1 stopped, 0 mph space-mean speed.
> 3. **No movement (lane 3, median side):** No connection leaves this lane at the stop line, so it is not counted as an approach lane.
> 4. **Through lane (lane 4, median side):** No vehicles (speed not measured).
> 5. **Through lane (lane 5, median side):** 1 vehicle, 0 stopped, 57 mph space-mean speed.
> 6. **Through lane (lane 6, curb side):** No vehicles (speed not measured).
>
> **Note:** The reading is a snapshot at 300 seconds, which is before the analysis hour (900-4500 seconds). Therefore, it does not provide information about the peak hour. To get a better reading for the peak hour, call the `advance` function to reach 900 seconds or later.
