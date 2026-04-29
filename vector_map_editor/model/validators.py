from __future__ import annotations

from .enums import LineRole, LineType, MarkingType
from .map_data import VectorMap


class ValidationError(Exception):
    pass


def validate_vector_map(vector_map: VectorMap) -> None:
    point_ids = {p.id for p in vector_map.points}
    if len(point_ids) != len(vector_map.points):
        raise ValidationError("Duplicate point IDs found")

    line_ids = {line.id for line in vector_map.lines}
    if len(line_ids) != len(vector_map.lines):
        raise ValidationError("Duplicate line IDs found")

    lanelet_ids = {lanelet.id for lanelet in vector_map.lanelets}
    if len(lanelet_ids) != len(vector_map.lanelets):
        raise ValidationError("Duplicate lanelet IDs found")

    area_ids = {area.id for area in vector_map.areas}
    if len(area_ids) != len(vector_map.areas):
        raise ValidationError("Duplicate area IDs found")

    for line in vector_map.lines:
        if len(line.point_ids) < 2:
            raise ValidationError(f"Line {line.id} must have at least two points")
        if any(pid not in point_ids for pid in line.point_ids):
            raise ValidationError(f"Line {line.id} references unknown point IDs")
        if line.line_type == LineType.LANE_CENTERLINE and line.marking_type == MarkingType.UNKNOWN:
            raise ValidationError(f"Line {line.id} centerline should not use unknown marking")
        if line.line_role == LineRole.LANE_CENTERLINE and line.is_observable:
            raise ValidationError(f"Line {line.id} lane centerline should usually be non-observable")

    for lanelet in vector_map.lanelets:
        if lanelet.left_boundary_line_id not in line_ids:
            raise ValidationError(f"Lanelet {lanelet.id} has invalid left boundary")
        if lanelet.right_boundary_line_id not in line_ids:
            raise ValidationError(f"Lanelet {lanelet.id} has invalid right boundary")
        if lanelet.centerline_id is not None and lanelet.centerline_id not in line_ids:
            raise ValidationError(f"Lanelet {lanelet.id} has invalid centerline")

    for area in vector_map.areas:
        if area.outer_line_id not in line_ids:
            raise ValidationError(f"Area {area.id} has invalid outer line")

    for conn in vector_map.connections:
        if conn.from_lanelet_id not in lanelet_ids or conn.to_lanelet_id not in lanelet_ids:
            raise ValidationError(f"Connection {conn.id} references unknown lanelet")
        if conn.from_lanelet_id == conn.to_lanelet_id:
            raise ValidationError(f"Connection {conn.id} loops to itself")
