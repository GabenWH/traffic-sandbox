# Roundabouts and uncontrolled intersections

Approved direction: reuse lane geometry, directed routing and occupancy. Cars
look across connected route sections; roundabouts are single-lane rings with
ordinary yield-controlled entrances and exits. Right-hand traffic circulates
counterclockwise. No new dependencies; explain decisions in plain-English comments.

Uncontrolled crossings use movement conflicts, arrival order, yield-to-right
for close arrivals and left-turn yielding to opposing through traffic. Cars may
enter compatible movements together, must have room to exit, and reserve a
movement until their rear clears it. Existing all-way stops retain full stops.

Generate shared ring sections in the mobility graph, never a separate complete
circle for each destination. Roundabout geometry belongs in roundabouts.py;
gap acceptance belongs in merge_behavior.py. Entry yields to vehicles arriving
on the circulating lane; cars on the ring follow shared section occupancy.
The inspector converts standard junctions to roundabouts and back. Conversion
clears temporary traffic because existing cars hold immutable old routes.
World saves persist the junction kind; generated geometry is rebuilt on load.

Tests cover connected-section following, competing entry claims, compatible
movements, blocked exits, roundabout geometry and shared routing, yielding,
progress under traffic, inspector conversion, persistence and legacy regressions.
