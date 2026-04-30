from pathlib import Path

import pytest

from vector_map_editor.model.coordinates import enu_to_pixel, pixel_to_enu
from vector_map_editor.model.enums import ConnectionType, LaneletSubtype, LineRole, LineStringSubtype, LineType, MarkingType
from vector_map_editor.model.geometry import infer_centerline_points, resample_polyline
from vector_map_editor.model.map_data import LaneConnection, MapArea, MapLanelet, MapLineString, MapPoint, VectorMap
from vector_map_editor.io.xml_io import load_map_xml, save_map_xml


def test_save_load_roundtrip(tmp_path: Path) -> None:
    vm = VectorMap(map_id="test")
    vm.points.extend([
        MapPoint(id=1, x=0.0, y=0.0),
        MapPoint(id=2, x=1.0, y=0.0),
        MapPoint(id=3, x=0.0, y=1.0),
        MapPoint(id=4, x=1.0, y=1.0),
    ])
    vm.lines.extend([
        MapLineString(
            id=101,
            subtype=LineStringSubtype.SOLID,
            line_type=LineType.LANE_THIN,
            line_role=LineRole.LEFT_BOUNDARY,
            marking_type=MarkingType.SOLID,
            point_ids=[1, 2],
        ),
        MapLineString(
            id=102,
            subtype=LineStringSubtype.DASHED,
            line_type=LineType.LANE_THIN,
            line_role=LineRole.RIGHT_BOUNDARY,
            marking_type=MarkingType.SOLID,
            point_ids=[3, 4],
        ),
        MapLineString(
            id=201,
            subtype=LineStringSubtype.VIRTUAL,
            line_type=LineType.VIRTUAL_LINE,
            line_role=LineRole.LANE_CENTERLINE,
            marking_type=MarkingType.VIRTUAL,
            point_ids=[1, 2],
            is_observable=False,
        ),
        MapLineString(
            id=202,
            subtype=LineStringSubtype.STOP_LINE,
            line_type=LineType.STOP_LINE,
            line_role=LineRole.STOP_LINE,
            marking_type=MarkingType.SOLID,
            point_ids=[2, 4],
        ),
    ])
    vm.lanelets.append(
        MapLanelet(
            id=301,
            left_boundary_line_id=101,
            right_boundary_line_id=102,
            centerline_id=201,
            turn_direction=ConnectionType.LEFT,
        )
    )
    vm.lanelets.append(
        MapLanelet(
            id=302,
            subtype=LaneletSubtype.INTERSECTION,
            left_boundary_line_id=101,
            right_boundary_line_id=102,
            centerline_id=201,
            is_virtual=True,
            turn_direction=ConnectionType.RIGHT,
        )
    )
    vm.areas.append(MapArea(id=501, outer_line_id=201))
    vm.connections.append(
        LaneConnection(
            id=401,
            from_lanelet_id=301,
            to_lanelet_id=302,
            connection_type=ConnectionType.BRANCH,
        )
    )

    output = tmp_path / "sample.osm"
    save_map_xml(vm, output)

    text = output.read_text()
    assert "<osm" in text
    assert 'k="type" v="line_thin"' in text
    assert 'k="type" v="virtual_line"' in text
    assert 'k="type" v="stop_line"' in text
    assert 'k="subtype" v="virtual_line"' in text
    assert 'k="line_role"' not in text
    assert 'k="line_type"' not in text
    assert 'k="route_role"' not in text
    assert 'v="lanelet"' in text
    assert 'k="subtype" v="intersection"' in text
    assert 'k="is_virtual" v="true"' in text
    assert 'k="turn_direction" v="left"' in text
    assert 'v="lane_connection"' in text
    assert 'v="area"' in text

    restored = load_map_xml(output)

    assert restored.map_id == "test"
    assert len(restored.points) == 4
    assert len(restored.lines) == 4
    assert len(restored.lanelets) == 2
    assert len(restored.areas) == 1
    assert len(restored.connections) == 1
    assert restored.lanelets[0].turn_direction == ConnectionType.LEFT
    assert restored.lanelets[1].subtype == LaneletSubtype.INTERSECTION
    assert restored.lanelets[1].is_virtual is True
    assert restored.lines[0].line_role == LineRole.LEFT_BOUNDARY
    assert restored.lines[2].line_role == LineRole.LANE_CENTERLINE


def test_load_lanelet2_way_types(tmp_path: Path) -> None:
    path = tmp_path / "lanelet2.osm"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <node id="1" x="0" y="0" z="0" />
  <node id="2" x="10" y="0" z="0" />
  <node id="3" x="0" y="4" z="0" />
  <node id="4" x="10" y="4" z="0" />
  <node id="5" x="0" y="2" z="0" />
  <node id="6" x="10" y="2" z="0" />
  <way id="101">
    <nd ref="1" />
    <nd ref="2" />
    <tag k="type" v="line_thin" />
    <tag k="subtype" v="solid" />
  </way>
  <way id="102">
    <nd ref="3" />
    <nd ref="4" />
    <tag k="type" v="line_thin" />
    <tag k="subtype" v="road_border" />
  </way>
  <way id="103">
    <nd ref="5" />
    <nd ref="6" />
    <tag k="type" v="virtual_line" />
    <tag k="subtype" v="virtual_line" />
  </way>
  <relation id="301">
    <member type="way" ref="101" role="left" />
    <member type="way" ref="102" role="right" />
    <member type="way" ref="103" role="centerline" />
    <tag k="type" v="lanelet" />
    <tag k="subtype" v="intersection" />
    <tag k="is_virtual" v="true" />
  </relation>
</osm>
""",
        encoding="utf-8",
    )

    restored = load_map_xml(path)

    assert len(restored.lines) == 3
    assert restored.lines[0].subtype == LineStringSubtype.SOLID
    assert restored.lines[1].line_type == LineType.LANE_THIN
    assert restored.lines[2].line_role == LineRole.LANE_CENTERLINE
    assert restored.lines[2].subtype == LineStringSubtype.VIRTUAL
    assert restored.lanelets[0].centerline_id == 103
    assert restored.lanelets[0].subtype == LaneletSubtype.INTERSECTION
    assert restored.lanelets[0].is_virtual is True


def test_pixel_enu_roundtrip() -> None:
    x_pixel, y_pixel = 320.0, 240.0
    east_m, north_m = pixel_to_enu(x_pixel, y_pixel)
    restored_x_pixel, restored_y_pixel = enu_to_pixel(east_m, north_m)

    assert restored_x_pixel == pytest.approx(x_pixel)
    assert restored_y_pixel == pytest.approx(y_pixel)
    assert pixel_to_enu(532.0, 328.0) == pytest.approx((-0.012410176975961917, -0.4534401517148865))
    assert enu_to_pixel(-0.012410176975961917, -0.4534401517148865) == pytest.approx((532.0, 328.0))


def test_resample_polyline_uses_three_meter_spacing() -> None:
    samples = resample_polyline([(0.0, 0.0), (7.5, 0.0)], 3.0)

    assert samples == [
        (0.0, 0.0),
        (3.0, 0.0),
        (6.0, 0.0),
        (7.5, 0.0),
    ]


def test_infer_centerline_points_orients_boundaries() -> None:
    samples = infer_centerline_points(
        left_points=[(0.0, 0.0), (9.0, 0.0)],
        right_points=[(9.0, 4.0), (0.0, 4.0)],
        spacing_m=3.0,
    )

    assert samples == [
        (0.0, 2.0),
        (3.0, 2.0),
        (6.0, 2.0),
        (9.0, 2.0),
    ]
