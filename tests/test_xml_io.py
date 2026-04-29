from pathlib import Path

import pytest

from vector_map_editor.model.coordinates import local_meter_to_pixel, pixel_to_local_meter
from vector_map_editor.model.enums import ConnectionType, LineRole, LineStringSubtype, LineType, MarkingType
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
            line_type=LineType.WHITE_LINE,
            line_role=LineRole.LEFT_BOUNDARY,
            marking_type=MarkingType.SOLID,
            point_ids=[1, 2],
        ),
        MapLineString(
            id=102,
            subtype=LineStringSubtype.DASHED,
            line_type=LineType.WHITE_LINE,
            line_role=LineRole.RIGHT_BOUNDARY,
            marking_type=MarkingType.SOLID,
            point_ids=[3, 4],
        ),
        MapLineString(
            id=201,
            subtype=LineStringSubtype.ROAD_BORDER,
            line_type=LineType.LANE_CENTERLINE,
            line_role=LineRole.LANE_CENTERLINE,
            marking_type=MarkingType.VIRTUAL,
            point_ids=[1, 2],
            is_observable=False,
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
            left_boundary_line_id=101,
            right_boundary_line_id=102,
            centerline_id=201,
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
    assert 'k="type" v="virtual"' in text
    assert 'k="line_role" v="left_boundary"' in text
    assert 'v="lanelet"' in text
    assert 'k="turn_direction" v="left"' in text
    assert 'v="lane_connection"' in text
    assert 'v="area"' in text

    restored = load_map_xml(output)

    assert restored.map_id == "test"
    assert len(restored.points) == 4
    assert len(restored.lines) == 3
    assert len(restored.lanelets) == 2
    assert len(restored.areas) == 1
    assert len(restored.connections) == 1
    assert restored.lanelets[0].turn_direction == ConnectionType.LEFT
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
    <tag k="type" v="road_border" />
  </way>
  <way id="103">
    <nd ref="5" />
    <nd ref="6" />
    <tag k="type" v="virtual" />
  </way>
  <relation id="301">
    <member type="way" ref="101" role="left" />
    <member type="way" ref="102" role="right" />
    <member type="way" ref="103" role="centerline" />
    <tag k="type" v="lanelet" />
    <tag k="subtype" v="road" />
  </relation>
</osm>
""",
        encoding="utf-8",
    )

    restored = load_map_xml(path)

    assert len(restored.lines) == 3
    assert restored.lines[0].subtype == LineStringSubtype.SOLID
    assert restored.lines[1].line_type == LineType.ROAD_EDGE
    assert restored.lines[2].line_role == LineRole.LANE_CENTERLINE
    assert restored.lanelets[0].centerline_id == 103


def test_pixel_local_meter_roundtrip() -> None:
    x_pixel, y_pixel = 320.0, 240.0
    x_m, y_m = pixel_to_local_meter(x_pixel, y_pixel)
    restored_x_pixel, restored_y_pixel = local_meter_to_pixel(x_m, y_m)

    assert restored_x_pixel == pytest.approx(x_pixel)
    assert restored_y_pixel == pytest.approx(y_pixel)


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
