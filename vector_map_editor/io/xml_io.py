from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from vector_map_editor.model.enums import (
    AreaSubtype,
    ConnectionType,
    LaneletSubtype,
    LineRole,
    LineStringSubtype,
    LineType,
    MarkingType,
)
from vector_map_editor.model.map_data import (
    LaneConnection,
    MapArea,
    MapLanelet,
    MapLineString,
    MapPoint,
    Route,
    RouteSegment,
    VectorMap,
)
from vector_map_editor.model.validators import validate_vector_map


def _text(value: object) -> str:
    return "" if value is None else str(value)


def save_map_xml(vector_map: VectorMap, output_path: str | Path) -> None:
    validate_vector_map(vector_map)

    root = ET.Element(
        "osm",
        {
            "version": "0.6",
            "generator": "vector_map_editor",
            "map_id": vector_map.map_id,
            "map_version": vector_map.map_version,
            "frame_id": vector_map.frame_id,
        },
    )

    for point in vector_map.points:
        ET.SubElement(
            root,
            "node",
            {
                "id": _text(point.id),
                "visible": "true",
                "version": "1",
                "x": _text(point.x),
                "y": _text(point.y),
                "z": _text(point.z),
            },
        )

    for line in vector_map.lines:
        way_el = ET.SubElement(
            root,
            "way",
            {
                "id": _text(line.id),
                "visible": "true",
                "version": "1",
            },
        )
        for pid in line.point_ids:
            ET.SubElement(way_el, "nd", {"ref": _text(pid)})
        ET.SubElement(way_el, "tag", {"k": "type", "v": "LineString"})
        ET.SubElement(way_el, "tag", {"k": "subtype", "v": line.subtype.value})
        if line.name:
            ET.SubElement(way_el, "tag", {"k": "name", "v": line.name})

    for lanelet in vector_map.lanelets:
        relation_el = ET.SubElement(
            root,
            "relation",
            {
                "id": _text(lanelet.id),
                "visible": "true",
                "version": "1",
            },
        )
        ET.SubElement(
            relation_el,
            "member",
            {"type": "way", "ref": _text(lanelet.left_boundary_line_id), "role": "left"},
        )
        ET.SubElement(
            relation_el,
            "member",
            {"type": "way", "ref": _text(lanelet.right_boundary_line_id), "role": "right"},
        )
        if lanelet.centerline_id is not None:
            ET.SubElement(
                relation_el,
                "member",
                {"type": "way", "ref": _text(lanelet.centerline_id), "role": "centerline"},
            )
        for line_id in lanelet.associated_line_ids:
            ET.SubElement(relation_el, "member", {"type": "way", "ref": _text(line_id), "role": "ref_line"})
        ET.SubElement(relation_el, "tag", {"k": "subtype", "v": lanelet.subtype.value})
        ET.SubElement(relation_el, "tag", {"k": "type", "v": "lanelet"})
        if lanelet.turn_direction != ConnectionType.UNKNOWN:
            ET.SubElement(relation_el, "tag", {"k": "turn_direction", "v": lanelet.turn_direction.value})
        if lanelet.name:
            ET.SubElement(relation_el, "tag", {"k": "name", "v": lanelet.name})

    for area in vector_map.areas:
        relation_el = ET.SubElement(
            root,
            "relation",
            {
                "id": _text(area.id),
                "visible": "true",
                "version": "1",
            },
        )
        ET.SubElement(relation_el, "member", {"type": "way", "ref": _text(area.outer_line_id), "role": "outer"})
        ET.SubElement(relation_el, "tag", {"k": "subtype", "v": area.subtype.value})
        ET.SubElement(relation_el, "tag", {"k": "type", "v": "area"})
        if area.name:
            ET.SubElement(relation_el, "tag", {"k": "name", "v": area.name})

    for conn in vector_map.connections:
        relation_el = ET.SubElement(
            root,
            "relation",
            {
                "id": _text(conn.id),
                "visible": "true",
                "version": "1",
            },
        )
        ET.SubElement(relation_el, "member", {"type": "relation", "ref": _text(conn.from_lanelet_id), "role": "from"})
        ET.SubElement(relation_el, "member", {"type": "relation", "ref": _text(conn.to_lanelet_id), "role": "to"})
        ET.SubElement(relation_el, "tag", {"k": "type", "v": "lane_connection"})
        ET.SubElement(relation_el, "tag", {"k": "turn_direction", "v": conn.connection_type.value})
        ET.SubElement(relation_el, "tag", {"k": "cost", "v": _text(conn.cost)})

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)


def save_legacy_map_xml(vector_map: VectorMap, output_path: str | Path) -> None:
    validate_vector_map(vector_map)

    root = ET.Element(
        "VectorMap",
        {
            "map_id": vector_map.map_id,
            "map_version": vector_map.map_version,
            "frame_id": vector_map.frame_id,
        },
    )

    points_el = ET.SubElement(root, "Points")
    for point in vector_map.points:
        ET.SubElement(
            points_el,
            "Point",
            {
                "id": _text(point.id),
                "x": _text(point.x),
                "y": _text(point.y),
                "z": _text(point.z),
            },
        )

    lines_el = ET.SubElement(root, "LineStrings")
    for line in vector_map.lines:
        line_el = ET.SubElement(
            lines_el,
            "LineString",
            {
                "id": _text(line.id),
                "name": line.name,
                "subtype": line.subtype.value,
                "line_type": line.line_type.value,
                "line_role": line.line_role.value,
                "marking_type": line.marking_type.value,
                "is_observable": _text(line.is_observable).lower(),
            },
        )
        point_ids_el = ET.SubElement(line_el, "PointIds")
        for pid in line.point_ids:
            ET.SubElement(point_ids_el, "PointRef", {"id": _text(pid)})

    lanelets_el = ET.SubElement(root, "Lanelets")
    for lanelet in vector_map.lanelets:
        lanelet_el = ET.SubElement(
            lanelets_el,
            "Lanelet",
            {
                "id": _text(lanelet.id),
                "name": lanelet.name,
                "subtype": lanelet.subtype.value,
                "left_boundary_line_id": _text(lanelet.left_boundary_line_id),
                "right_boundary_line_id": _text(lanelet.right_boundary_line_id),
                "centerline_id": _text(lanelet.centerline_id),
                "is_virtual": _text(lanelet.is_virtual).lower(),
                "turn_direction": lanelet.turn_direction.value,
            },
        )
        if lanelet.width is not None:
            lanelet_el.set("width", _text(lanelet.width))

        assoc_el = ET.SubElement(lanelet_el, "AssociatedLineIds")
        for lid in lanelet.associated_line_ids:
            ET.SubElement(assoc_el, "LineRef", {"id": _text(lid)})

    areas_el = ET.SubElement(root, "Areas")
    for area in vector_map.areas:
        ET.SubElement(
            areas_el,
            "Area",
            {
                "id": _text(area.id),
                "name": area.name,
                "subtype": area.subtype.value,
                "outer_line_id": _text(area.outer_line_id),
            },
        )

    conns_el = ET.SubElement(root, "Connections")
    for conn in vector_map.connections:
        ET.SubElement(
            conns_el,
            "Connection",
            {
                "id": _text(conn.id),
                "from_lanelet_id": _text(conn.from_lanelet_id),
                "to_lanelet_id": _text(conn.to_lanelet_id),
                "connection_type": conn.connection_type.value,
                "cost": _text(conn.cost),
            },
        )

    routes_el = ET.SubElement(root, "Routes")
    for route in vector_map.routes:
        route_el = ET.SubElement(routes_el, "Route", {"id": _text(route.id), "name": route.name})
        segments_el = ET.SubElement(route_el, "Segments")
        for seg in route.segments:
            attrs = {
                "lanelet_id": _text(seg.lanelet_id),
                "turn_direction": seg.turn_direction.value,
            }
            if seg.target_speed_mps is not None:
                attrs["target_speed_mps"] = _text(seg.target_speed_mps)
            ET.SubElement(segments_el, "Segment", attrs)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)


def _bool(text: str | None, default: bool = False) -> bool:
    if text is None:
        return default
    return text.lower() in {"true", "1", "yes"}


def _int(text: str | None, default: int | None = None) -> int | None:
    if text in (None, ""):
        return default
    return int(text)


def _float(text: str | None, default: float | None = None) -> float | None:
    if text in (None, ""):
        return default
    return float(text)


def load_map_xml(input_path: str | Path) -> VectorMap:
    tree = ET.parse(str(input_path))
    root = tree.getroot()
    if root.tag == "osm":
        return _load_map_osm(root)

    return _load_legacy_map_xml(root)


def _tags(element: ET.Element) -> dict[str, str]:
    return {tag.get("k", ""): tag.get("v", "") for tag in element.findall("./tag")}


def _load_map_osm(root: ET.Element) -> VectorMap:
    vector_map = VectorMap(
        map_id=root.get("map_id", "map_001"),
        map_version=root.get("map_version", "0.1.0"),
        frame_id=root.get("frame_id", "map"),
    )

    for node_el in root.findall("./node"):
        tags = _tags(node_el)
        x = node_el.get("x", tags.get("local_x", "0"))
        y = node_el.get("y", tags.get("local_y", "0"))
        z = node_el.get("z", tags.get("ele", "0"))
        vector_map.points.append(
            MapPoint(
                id=int(node_el.get("id", "0")),
                x=float(x),
                y=float(y),
                z=float(z),
            )
        )

    for way_el in root.findall("./way"):
        tags = _tags(way_el)
        if tags.get("type") != "LineString":
            continue
        point_ids = [int(ref.get("ref", "0")) for ref in way_el.findall("./nd")]
        vector_map.lines.append(
            MapLineString(
                id=int(way_el.get("id", "0")),
                name=tags.get("name", ""),
                subtype=LineStringSubtype(tags.get("subtype", LineStringSubtype.SOLID.value)),
                point_ids=point_ids,
            )
        )

    for relation_el in root.findall("./relation"):
        tags = _tags(relation_el)
        relation_type = tags.get("type")
        members = relation_el.findall("./member")
        if relation_type == "lanelet":
            left_id = _member_ref(members, "left")
            right_id = _member_ref(members, "right")
            centerline_id = _member_ref(members, "centerline")
            assoc_ids = [int(member.get("ref", "0")) for member in members if member.get("role") == "ref_line"]
            vector_map.lanelets.append(
                MapLanelet(
                    id=int(relation_el.get("id", "0")),
                    name=tags.get("name", ""),
                    subtype=LaneletSubtype(tags.get("subtype", LaneletSubtype.ROAD.value)),
                    left_boundary_line_id=left_id,
                    right_boundary_line_id=right_id,
                    centerline_id=centerline_id,
                    associated_line_ids=assoc_ids,
                    turn_direction=ConnectionType(tags.get("turn_direction", ConnectionType.UNKNOWN.value)),
                )
            )
        elif relation_type == "area":
            outer_id = _member_ref(members, "outer")
            if outer_id is None:
                raise ValueError(f"Area relation {relation_el.get('id', '0')} has no outer member")
            vector_map.areas.append(
                MapArea(
                    id=int(relation_el.get("id", "0")),
                    name=tags.get("name", ""),
                    subtype=AreaSubtype(tags.get("subtype", AreaSubtype.CROSSWALK.value)),
                    outer_line_id=outer_id,
                )
            )
        elif relation_type == "lane_connection":
            from_id = _member_ref(members, "from")
            to_id = _member_ref(members, "to")
            if from_id is None or to_id is None:
                raise ValueError(f"Connection relation {relation_el.get('id', '0')} has invalid members")
            vector_map.connections.append(
                LaneConnection(
                    id=int(relation_el.get("id", "0")),
                    from_lanelet_id=from_id,
                    to_lanelet_id=to_id,
                    connection_type=ConnectionType(tags.get("turn_direction", ConnectionType.UNKNOWN.value)),
                    cost=float(tags.get("cost", "1.0")),
                )
            )

    validate_vector_map(vector_map)
    return vector_map


def _member_ref(members: list[ET.Element], role: str) -> int | None:
    for member in members:
        if member.get("role") == role:
            return int(member.get("ref", "0"))
    return None



def _load_legacy_map_xml(root: ET.Element) -> VectorMap:
    vector_map = VectorMap(
        map_id=root.get("map_id", "map_001"),
        map_version=root.get("map_version", "0.1.0"),
        frame_id=root.get("frame_id", "map"),
    )

    for p in root.findall("./Points/Point"):
        vector_map.points.append(
            MapPoint(
                id=int(p.get("id", "0")),
                x=float(p.get("x", "0")),
                y=float(p.get("y", "0")),
                z=float(p.get("z", "0")),
            )
        )

    for line_el in root.findall("./LineStrings/LineString"):
        point_ids = [int(ref.get("id", "0")) for ref in line_el.findall("./PointIds/PointRef")]
        vector_map.lines.append(
            MapLineString(
                id=int(line_el.get("id", "0")),
                name=line_el.get("name", ""),
                subtype=LineStringSubtype(line_el.get("subtype", LineStringSubtype.SOLID.value)),
                line_type=LineType(line_el.get("line_type", LineType.UNKNOWN.value)),
                line_role=LineRole(line_el.get("line_role", LineRole.UNKNOWN.value)),
                marking_type=MarkingType(line_el.get("marking_type", MarkingType.UNKNOWN.value)),
                point_ids=point_ids,
                is_observable=_bool(line_el.get("is_observable"), default=True),
            )
        )

    for lanelet_el in root.findall("./Lanelets/Lanelet"):
        assoc_ids = [int(ref.get("id", "0")) for ref in lanelet_el.findall("./AssociatedLineIds/LineRef")]
        vector_map.lanelets.append(
            MapLanelet(
                id=int(lanelet_el.get("id", "0")),
                name=lanelet_el.get("name", ""),
                subtype=LaneletSubtype(lanelet_el.get("subtype", LaneletSubtype.ROAD.value)),
                left_boundary_line_id=_int(lanelet_el.get("left_boundary_line_id")),
                right_boundary_line_id=_int(lanelet_el.get("right_boundary_line_id")),
                centerline_id=_int(lanelet_el.get("centerline_id")),
                associated_line_ids=assoc_ids,
                width=_float(lanelet_el.get("width")),
                is_virtual=_bool(lanelet_el.get("is_virtual"), default=False),
                turn_direction=ConnectionType(lanelet_el.get("turn_direction", ConnectionType.UNKNOWN.value)),
            )
        )

    for area_el in root.findall("./Areas/Area"):
        vector_map.areas.append(
            MapArea(
                id=int(area_el.get("id", "0")),
                name=area_el.get("name", ""),
                subtype=AreaSubtype(area_el.get("subtype", AreaSubtype.CROSSWALK.value)),
                outer_line_id=int(area_el.get("outer_line_id", "0")),
            )
        )

    for conn_el in root.findall("./Connections/Connection"):
        vector_map.connections.append(
            LaneConnection(
                id=int(conn_el.get("id", "0")),
                from_lanelet_id=int(conn_el.get("from_lanelet_id", "0")),
                to_lanelet_id=int(conn_el.get("to_lanelet_id", "0")),
                connection_type=ConnectionType(conn_el.get("connection_type", ConnectionType.UNKNOWN.value)),
                cost=float(conn_el.get("cost", "1.0")),
            )
        )

    for route_el in root.findall("./Routes/Route"):
        route = Route(id=int(route_el.get("id", "0")), name=route_el.get("name", ""))
        for seg_el in route_el.findall("./Segments/Segment"):
            route.segments.append(
                RouteSegment(
                    lanelet_id=int(seg_el.get("lanelet_id", "0")),
                    target_speed_mps=_float(seg_el.get("target_speed_mps")),
                    turn_direction=ConnectionType(seg_el.get("turn_direction", ConnectionType.UNKNOWN.value)),
                )
            )
        vector_map.routes.append(route)

    validate_vector_map(vector_map)
    return vector_map
