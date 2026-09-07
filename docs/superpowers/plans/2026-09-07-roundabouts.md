# Roundabouts implementation plan

Goal: deliver a pullable branch with generic merge observations, safe uncontrolled
crossings and editable single-lane roundabouts.
Spec: ../specs/2026-09-07-roundabouts-design.md

1. Establish clean baseline (88 unittest tests). Add failing behavioral tests in
   tests/test_junction_traffic.py for observations, priority, routing and saves.
2. Extend traffic_occupancy.py with route-distance queries across shared sections.
   Add merge_behavior.py for gap acceptance; extend intersection_controls.py for
   uncontrolled conflicts. Keep physical movement in traffic_testbed.py and
   decisions in car_brain.py. Run focused tests after each feature.
3. Add roundabouts.py to produce shared Lane arcs and entry/exit connections.
   Integrate models.py, city.py and mobility.py without replacing normal lanes.
   Add inspector conversion, rendering and persistence round-trip tests.
4. Run the full unittest suite, inspect a rendered scene and exercise competing
   traffic over many ticks. Document the design and manual test steps. Review the
   diff, commit, push feature/roundabouts-and-intersection-priority, verify its SHA.
