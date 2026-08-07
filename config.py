"""Shared simulator dimensions and unit conversions."""

WIDTH, HEIGHT = 1000, 640
ROAD_TOP, ROAD_BOTTOM = 110, 220
LANES = 2
LANE_HEIGHT = (ROAD_BOTTOM - ROAD_TOP) / LANES
MERGE_START = 590
MERGE_END = 960
POST_MERGE_END = WIDTH + 500

# One screen pixel represents one foot of roadway.
PIXELS_PER_MILE = 5280
