from enum import Enum


class LineType(str, Enum):
    UNKNOWN = "unknown"
    WHITE_LINE = "white_line"
    YELLOW_LINE = "yellow_line"
    STOP_LINE = "stop_line"
    CROSSWALK_LINE = "crosswalk_line"
    ROAD_EDGE = "road_edge"
    LANE_CENTERLINE = "lane_centerline"
    VIRTUAL_LINE = "virtual_line"


class FeatureType(str, Enum):
    LINE_STRING = "LineString"
    LANELET = "Lanelet"
    AREA = "Area"


class LineStringSubtype(str, Enum):
    SOLID = "solid"
    DASHED = "dashed"
    ROAD_BORDER = "road_border"
    STOP_LINE = "stop_line"


class LaneletSubtype(str, Enum):
    ROAD = "road"


class AreaSubtype(str, Enum):
    CROSSWALK = "crosswalk"


class LineRole(str, Enum):
    UNKNOWN = "unknown"
    LEFT_BOUNDARY = "left_boundary"
    RIGHT_BOUNDARY = "right_boundary"
    LANE_CENTERLINE = "lane_centerline"
    ROAD_CENTER_MARKING = "road_center_marking"
    STOP_LINE = "stop_line"
    CROSSWALK_STRIPE = "crosswalk_stripe"
    ROAD_EDGE = "road_edge"
    VIRTUAL_BOUNDARY = "virtual_boundary"


class MarkingType(str, Enum):
    UNKNOWN = "unknown"
    SOLID = "solid"
    DASHED = "dashed"
    DOUBLE = "double"
    VIRTUAL = "virtual"


class ConnectionType(str, Enum):
    UNKNOWN = "unknown"
    STRAIGHT = "straight"
    LEFT = "left"
    RIGHT = "right"
    MERGE = "merge"
    BRANCH = "branch"
    U_TURN = "u_turn"
