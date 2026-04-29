from pathlib import Path

import pytest

from vector_map_editor.io.xml_io import load_map_xml, save_map_xml
from vector_map_editor.canvas.map_canvas import MapCanvas
from vector_map_editor.model.coordinates import local_meter_to_pixel, pixel_to_local_meter
from vector_map_editor.model.enums import ConnectionType, LineRole, LineStringSubtype, LineType, MarkingType
from vector_map_editor.model.map_data import LaneConnection, MapArea, MapLanelet, MapLineString, MapPoint, VectorMap


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


def test_pixel_local_meter_roundtrip() -> None:
    x_pixel, y_pixel = 320.0, 240.0
    x_m, y_m = pixel_to_local_meter(x_pixel, y_pixel)
    restored_x_pixel, restored_y_pixel = local_meter_to_pixel(x_m, y_m)

    assert restored_x_pixel == pytest.approx(x_pixel)
    assert restored_y_pixel == pytest.approx(y_pixel)


def test_resample_polyline_uses_three_meter_spacing() -> None:
    samples = MapCanvas._resample_polyline([(0.0, 0.0), (7.5, 0.0)], 3.0)

    assert samples == [
        (0.0, 0.0),
        (3.0, 0.0),
        (6.0, 0.0),
        (7.5, 0.0),
    ]
