"""Shared simulator dimensions, canonical units, and display defaults."""

WIDTH, HEIGHT = 1000, 640
ROAD_TOP, ROAD_BOTTOM = 110, 134
LANES = 2
LANE_HEIGHT = (ROAD_BOTTOM - ROAD_TOP) / LANES
MERGE_START = 590
MERGE_END = 960
POST_MERGE_END = WIDTH + 500

# Merge-demo road footprint and boundary paint, in world pixels/feet.
#
# The road itself is the dark polygon. ``ROAD_EDGE_WIDTH`` is the light-gray
# pavement rim drawn around its top and lower/merge-facing outside edge; it is
# visual scenery, not an additional lane or a collision boundary.
ROAD_START_X = 0
ROAD_EDGE_WIDTH = 3
MIN_SCALED_STROKE_WIDTH = 1

# Merge-demo road paint and label layout. With one pixel per foot, standard
# highway lane dashes are about 10 ft long with a 30 ft gap and are 6 in wide.
LANE_DASH_LENGTH = 10
LANE_DASH_GAP = 30
LANE_DASH_SPACING = LANE_DASH_LENGTH + LANE_DASH_GAP
LANE_DASH_START_X = -LANE_DASH_GAP
LANE_DASH_HALF_HEIGHT = 0.25
LANE_LABEL_X = LANE_DASH_LENGTH + LANE_DASH_GAP / 2
LANE_LABEL_Y_OFFSET = LANE_HEIGHT / 2
LANE_LABEL_FONT_SIZE = 10
LANE_LABEL_MIN_FONT_SIZE = 7

# World-space distances are stored in pixels. One pixel represents one foot.
PIXELS_PER_FOOT = 1.0
FEET_PER_MILE = 5_280.0
METERS_PER_MILE = 1_609.344
METERS_PER_FOOT = METERS_PER_MILE / FEET_PER_MILE
METERS_PER_KILOMETER = 1_000.0
KILOMETERS_PER_MILE = METERS_PER_MILE / METERS_PER_KILOMETER
SECONDS_PER_HOUR = 60 * 60
PIXELS_PER_MILE = PIXELS_PER_FOOT * FEET_PER_MILE
STANDARD_GRAVITY_METERS_PER_SECOND_SQUARED = 9.80665
STANDARD_GRAVITY_FEET_PER_SECOND_SQUARED = STANDARD_GRAVITY_METERS_PER_SECOND_SQUARED / METERS_PER_FOOT

# Stored speed-limit and preference values remain MPH for save compatibility.
DEFAULT_SPEED_LIMIT_MPH = 55.0
MIN_SPEED_LIMIT_MPH = 15.0
MAX_SPEED_LIMIT_MPH = 70.0
MIN_SPEED_PREFERENCE_MPH = -5.0
MAX_SPEED_PREFERENCE_MPH = 10.0

# Change this default for new simulator windows. Users can also switch units
# while the app is running through the Units toolbar menu.
DEFAULT_UNIT_SYSTEM = "imperial"
UNIT_SYSTEMS = ("imperial", "metric")
