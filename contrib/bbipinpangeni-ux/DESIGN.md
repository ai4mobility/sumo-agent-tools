# Design: SUMO Traffic Operations and Spillback Assessment

## 1. The task

This project develops an AI-assisted traffic operations assessment workflow for a transportation engineer evaluating congestion in a simulated urban corridor. The engineering motivation is to identify traffic conditions that could become important when planning roadway or bridge maintenance activities. However, the current SUMO scenario represents baseline traffic on the Fowler Avenue corridor and does not include an actual bridge maintenance lane closure.

A transportation engineer needs information about queue accumulation, available upstream storage, corridor travel time, and traffic operating speed before evaluating potential maintenance impacts. These measurements can help identify approaches that warrant further investigation and locations where congestion could affect upstream intersections.

The engineer might ask:

- "What is the maximum southbound queue at Bruce B Downs Boulevard and USF Pine Drive during the complete analysis hour, and when does it occur?"
- "How much upstream storage remains on this approach at 1,800 seconds?"
- "How much longer does it take to travel eastbound along Fowler Avenue compared with free-flow conditions?"
- "How many vehicles are stopped on the southbound approach, and what is their average speed?"

Without an AI assistant, the engineer would use SUMO, TraCI scripts, simulation logs, and manually calculated performance measures. These questions may need to be answered repeatedly for different intersections, directions, and simulation conditions.

## 2. The tools

Four tools were developed to address different aspects of traffic operations.

**`worst_queue_analysis`** identifies the maximum observed queue on a selected intersection approach during the remaining simulation analysis period. It records queue measurements at one-second intervals and reports the maximum queue length, the corresponding simulation time, and the available storage. It also identifies whether the complete analysis hour was covered. This is more informative than relying on a single simulation snapshot because traffic queues change throughout the analysis period.

**`upstream_spillback_assessment`** evaluates queue length relative to available upstream storage at the current simulation time. It reports queue length, storage occupancy percentage, and remaining storage distance. These measurements support preliminary spillback screening, but storage occupancy alone cannot confirm that an upstream intersection is physically blocked.

**`corridor_delay_assessment`** evaluates the difference between observed median travel time and the free-flow reference for the Fowler Avenue corridor. It reports the number of completed trips supporting the travel-time estimate. The output explicitly distinguishes baseline corridor delay from additional delay attributable to a construction project.

**`approach_speed_assessment`** reports the number of vehicles, stopped vehicles, and instantaneous mean vehicle speed on a selected approach. It identifies stopped vehicles using SUMO's speed threshold of 0.1 m/s and explains that stopped vehicles and queued vehicles are not necessarily identical.

The tools are separated because queue length, storage utilization, travel-time delay, and operating speed answer different engineering questions. The tools also distinguish between operations that advance the simulation and read-only observations. Their engineering interpretations correspond to the concepts documented in `KNOWLEDGE.md`.

## 3. The descriptions

The descriptions help an AI agent identify an appropriate tool for a natural-language transportation engineering question. They also communicate the required inputs, observation periods, and limitations.

For `worst_queue_analysis`, the phrase **"Measure the largest observed queue on one intersection approach"** identifies the tool's main purpose. Its description explains that it examines the analysis period and advances simulation time. A question about the maximum queue should therefore lead the agent toward this tool rather than a tool that reads only the current simulation state.

For `upstream_spillback_assessment`, the phrase **"Inspect the current queue and available upstream storage"** indicates that the tool evaluates a current observation. Its description specifies the intersection and approach inputs and explains that the result is not proof of physical intersection blockage. This distinction is important because a model could otherwise interpret a high storage occupancy value as confirmed spillback.

For `corridor_delay_assessment`, the description begins **"Assess Fowler Avenue corridor travel-time delay"** and specifies the travel direction. This allows the model to associate questions about travel time and additional minutes with the corridor-level tool rather than an intersection queue measurement.

For `approach_speed_assessment`, the phrase **"Report current traffic speed and stopped vehicles"** identifies the measurements returned. Its description also specifies the stopping threshold and explains that the result represents one simulation snapshot.

The descriptions provide transportation terminology while the input schemas constrain the permitted parameters. This combination is intended to reduce incorrect tool selection, unsupported interpretations, and invalid tool arguments.

The agent's actual tool-selection behavior still needs to be evaluated using the Qwen transcripts. Any observed errors and subsequent description improvements should be documented after those runs.

## 4. The results

The tool results use recognizable intersection names, travel directions, simulation times, engineering units, and explanatory limitations so that an AI agent can interpret the observations without relying on undocumented SUMO identifiers.

For example, `worst_queue_analysis` returned:

> Bruce B Downs Blvd & USF Pine Dr SB: maximum observed queue 853.4 ft at 4084 s. Available storage 1060.8 ft. 3601 readings from 900 to 4500 s. Complete analysis hour. This does not establish actual upstream blockage.

This output identifies the approach, maximum queue, time of occurrence, and total observation period. It prevents the 359.6 ft queue measured at 1,800 seconds from being mistaken for the maximum queue during the analysis hour.

The `upstream_spillback_assessment` result reported a queue of 359.6 ft, storage occupancy of 33.9%, and remaining storage of 701.2 ft at 1,800 seconds. The interpretation explicitly states that storage occupancy is a screening measurement and not confirmation of actual blockage.
In the Qwen agent transcript [runs/q1.md](runs/q1.md), the `upstream_spillback_assessment` tool returned:

> "Bruce B Downs Blvd & USF Pine Dr SB at 1800 s: queue 359.6 ft; available storage 1060.8 ft; storage occupied 33.9%; remaining storage 701.2 ft."

The agent used the reported remaining storage to answer the question correctly. This demonstrates how the model extracted the engineering value from the tool response.


The `corridor_delay_assessment` result reported a measured eastbound median travel time of 4.50 minutes from 31 completed trips, compared with a free-flow reference of 2.00 minutes. The approximately 2.50-minute difference describes baseline corridor travel-time delay. It must not be presented as delay caused by bridge maintenance because the simulation contains no maintenance lane closure.

The `approach_speed_assessment` result reported 17 vehicles, of which 16 were stopped, and an instantaneous mean vehicle speed of 2.5 mph at the selected southbound approach. The output defines stopped vehicles as traveling below 0.1 m/s and distinguishes a snapshot from a time-averaged measurement.

These numerical results have been checked using the project simulation and automated tests. However, numerical correctness alone does not establish that the AI agent interprets them correctly. The Qwen agent transcripts must be reviewed to identify which tools the model actually called, whether it communicated the limitations accurately, and what changes improved its responses.