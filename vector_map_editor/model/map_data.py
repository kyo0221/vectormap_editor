from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import AreaSubtype, ConnectionType, LaneletSubtype, LineRole, LineStringSubtype, LineType, MarkingType


class MapPoint(BaseModel):
    id: int
    x: float
    y: float
    z: float = 0.0


class MapLineString(BaseModel):
    id: int
    name: str = ""
    subtype: LineStringSubtype = LineStringSubtype.SOLID
    line_type: LineType = LineType.UNKNOWN
    line_role: LineRole = LineRole.UNKNOWN
    marking_type: MarkingType = MarkingType.UNKNOWN
    point_ids: list[int]
    is_observable: bool = True


class MapLanelet(BaseModel):
    id: int
    name: str = ""
    subtype: LaneletSubtype = LaneletSubtype.ROAD
    left_boundary_line_id: Optional[int] = None
    right_boundary_line_id: Optional[int] = None
    centerline_id: Optional[int] = None
    associated_line_ids: list[int] = Field(default_factory=list)
    width: Optional[float] = None
    is_virtual: bool = False
    turn_direction: ConnectionType = ConnectionType.UNKNOWN


class MapArea(BaseModel):
    id: int
    name: str = ""
    subtype: AreaSubtype = AreaSubtype.CROSSWALK
    outer_line_id: int


class LaneConnection(BaseModel):
    id: int
    from_lanelet_id: int
    to_lanelet_id: int
    connection_type: ConnectionType = ConnectionType.UNKNOWN
    cost: float = 1.0


class RouteSegment(BaseModel):
    lanelet_id: int
    target_speed_mps: Optional[float] = None
    turn_direction: ConnectionType = ConnectionType.UNKNOWN


class Route(BaseModel):
    id: int
    name: str = ""
    segments: list[RouteSegment] = Field(default_factory=list)


class VectorMap(BaseModel):
    map_id: str = "map_001"
    map_version: str = "0.1.0"
    frame_id: str = "map"
    points: list[MapPoint] = Field(default_factory=list)
    lines: list[MapLineString] = Field(default_factory=list)
    lanelets: list[MapLanelet] = Field(default_factory=list)
    areas: list[MapArea] = Field(default_factory=list)
    connections: list[LaneConnection] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
