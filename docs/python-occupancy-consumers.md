# Python occupancy consumers

Search: `rg -n "\.occupancy\b|_occupancy\b" --glob "*.py"`. Trace: `python tools/trace_occupancy_consumers.py`. The trace counts calls into the Python `TrafficOccupancyIndex`, including calls between index methods; it does not measure CPU time.

A 600-tick, 30-second signalized crossing with generated traffic reached 45 active cars in the native run and 46 in the data-first run. These runs are an observation of one scenario, not proof about all application paths.

| Mode | Direct caller | Index method | Calls |
| --- | --- | --- | ---: |
| native | traffic_testbed.py:351 `_mark_occupancy_changed` | `is_current` | 16,963 |
| native | traffic_testbed.py:359 `_publish_occupancy_changes` | `publish_changes` | 585 |
| native | native_spawning.py:275 `append` | `publish_changes` | 48 |
| data_first | traffic_testbed.py:351 `_mark_occupancy_changed` | `is_current` | 21,263 |
| data_first | traffic_testbed.py:1184 `_update_data_first` | `lead_car_gap` | 16,901 |
| data_first | traffic_occupancy.py:493 `lead_car_gap` | `lead_from` | 16,901 |
| data_first | traffic_occupancy.py:415 `gap_from` | `lead_from` | 16,231 |
| data_first | traffic_testbed.py:1147 `_update_data_first` | `gap_from` | 15,885 |
| data_first | traffic_testbed.py:359 `_publish_occupancy_changes` | `publish_changes` | 585 |
| data_first | traffic_testbed.py:625 `admit_route` | `lead_gap` | 346 |
| data_first | traffic_occupancy.py:485 `lead_gap` | `gap_from` | 346 |
| data_first | traffic_testbed.py:632 `admit_route` | `publish_changes` | 49 |

The native run made no calls to the traced gap or leader query methods. It checked whether vehicle entries were current and published changes nearly every tick, plus on admissions. Native driving and spawn clearance use the C++ engine. The data-first engine called Python gap/leader queries during vehicle decisions and Python admission.

Static search also found `tools/analyze_roundabouts.py` querying `sim.occupancy.lead_gap`, Python simulation paths in `traffic_testbed.py`, manual admission, occupancy rebuilds after reordering, and diagnostic/profiling tools. Other aliases, dynamic access, index methods not included in this trace, direct attribute inspection, UI paths, external integrations, and scenarios not run can contain additional consumers.

An on-demand index is promising for native mode, but must preserve fresh answers when any Python consumer queries it, account for removals, manual placement, switching engines and network/route changes, and retain the existing Python-engine behavior. This trace alone does not establish those changes are safe.
