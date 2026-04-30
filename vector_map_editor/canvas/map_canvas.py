from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QMouseEvent

from vector_map_editor.model.coordinates import enu_to_pixel, pixel_to_enu
from vector_map_editor.model.enums import (
    AreaSubtype,
    FeatureType,
    LineRole,
    LineStringSubtype,
    LineType,
    MarkingType,
)
from vector_map_editor.model.geometry import ASSIST_RESAMPLE_SPACING_M, infer_centerline_points, resample_polyline
from vector_map_editor.model.map_data import MapArea, MapLanelet, MapLineString, MapPoint, VectorMap
from vector_map_editor.tools.white_pixel_assist import create_white_mask, snap_to_white_pixel, trace_white_pixel_path


UndoAction = dict[str, object]


class MapCanvas(pg.PlotWidget):
    def __init__(
        self,
        on_status: Callable[[str], None],
        on_changed: Callable[[], None] | None = None,
        on_selected: Callable[[str, int], None] | None = None,
        on_subtype_requested: Callable[[FeatureType], str | None] | None = None,
    ) -> None:
        super().__init__()
        self.on_status = on_status
        self.on_changed = on_changed
        self.on_selected = on_selected
        self.on_subtype_requested = on_subtype_requested
        self.vector_map = VectorMap(map_id="map_001")

        self.setBackground("k")
        self.showGrid(x=True, y=True, alpha=0.2)
        # Keep x/y display resolution equal so background images are not distorted.
        self.setAspectLocked(True, ratio=1.0)

        self._background_item = pg.ImageItem(axisOrder="row-major")
        self.addItem(self._background_item)
        self._background_item.setVisible(False)

        # store background image pixel size (width, height)
        self._bg_size: tuple[int, int] | None = None
        self._white_mask: np.ndarray | None = None

        self._points_item = pg.ScatterPlotItem(size=7, brush=pg.mkBrush(255, 220, 0))
        self.addItem(self._points_item)

        self._line_items: list[pg.PlotDataItem] = []
        self._area_items: list[pg.PlotDataItem] = []
        self._lanelet_items: list[pg.PlotDataItem] = []
        self._temp_line_item = pg.PlotDataItem(pen=pg.mkPen((100, 220, 255), width=2, style=Qt.DashLine))
        self.addItem(self._temp_line_item)
        self._hover_label = pg.TextItem(anchor=(0, 1), color=(255, 255, 255), fill=pg.mkBrush(0, 0, 0, 190))
        self._hover_label.setZValue(100)
        self._hover_label.setVisible(False)
        self.addItem(self._hover_label)
        self.setMouseTracking(True)

        self.mode = "select"
        self.feature_type = FeatureType.LINE_STRING
        self.line_subtype = LineStringSubtype.SOLID
        self.area_subtype = AreaSubtype.CROSSWALK
        self.assist_enabled = False
        self.assist_spacing_m = ASSIST_RESAMPLE_SPACING_M
        self.current_line_point_ids: list[int] = []
        self._next_point_id = 1
        self._next_line_id = 100
        self._next_area_id = 500
        self._last_hover_text = ""
        self._selection_target: str | None = None
        self._undo_stack: list[UndoAction] = []

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.current_line_point_ids = []
        self._temp_line_item.setData([], [])
        self.on_status(f"Mode: {mode}")

    def set_feature(self, feature_type: FeatureType, subtype: str) -> None:
        self.feature_type = feature_type
        if feature_type == FeatureType.LINE_STRING:
            self.line_subtype = LineStringSubtype(subtype)
        elif feature_type == FeatureType.AREA:
            self.area_subtype = AreaSubtype(subtype)

    def set_feature_type(self, feature_type: FeatureType) -> None:
        self.feature_type = feature_type

    def set_assist_enabled(self, enabled: bool) -> None:
        self.assist_enabled = enabled
        self.on_status(f"Assist: {'on' if enabled else 'off'}")

    def set_selection_target(self, target: str | None) -> None:
        self._selection_target = target
        if target is not None:
            self.set_mode("select")

    def set_vector_map(self, vector_map: VectorMap) -> None:
        self.vector_map = vector_map
        self._next_point_id = (max((p.id for p in vector_map.points), default=0) + 1)
        self._next_line_id = (max((l.id for l in vector_map.lines), default=99) + 1)
        self._next_area_id = (max((a.id for a in vector_map.areas), default=499) + 1)
        self.current_line_point_ids = []
        self._undo_stack.clear()
        self._temp_line_item.setData([], [])
        self.redraw_all()

    def load_background(self, image: np.ndarray) -> None:
        corrected = image

        self._background_item.setImage(corrected)
        self._white_mask = create_white_mask(corrected)
        # アスペクト比を保つため、画像のサイズに基づいてrectを設定
        h, w = corrected.shape[:2]
        self._bg_size = (w, h)

        # Place the image so that pixel (0,0) (top-left) maps to the canvas origin (0,0).
        self._background_item.setRect(pg.QtCore.QRectF(0, 0, w, h))

        vb = self.getPlotItem().vb
        # Keep one canvas x-unit equal to one canvas y-unit on screen.
        vb.setAspectLocked(True, ratio=1.0)
        # Ensure y increases downward like image coordinates by inverting the viewbox Y
        vb.invertY(True)
        # Fix the visible range to image pixel extents (no padding)
        vb.setRange(xRange=(0, w), yRange=(0, h), padding=0)

        self._background_item.setVisible(True)

    def set_background_opacity(self, value: float) -> None:
        self._background_item.setOpacity(value)

    def redraw_all(self) -> None:
        self._draw_points()
        self._draw_lines()
        self._draw_areas()
        self._draw_lanelets()

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton and self.mode == "select" and self._selection_target is not None:
            plot_pos = self.getPlotItem().vb.mapSceneToView(ev.position())
            x_pixel = float(plot_pos.x())
            y_pixel = float(plot_pos.y())
            if self._handle_selection_click(x_pixel, y_pixel):
                ev.accept()
                return

        if ev.button() == Qt.LeftButton and self.mode in {"point", "line"}:
            if self.mode == "line" and self.feature_type == FeatureType.LANELET:
                self.on_status("Lanelet creation uses existing left/right line IDs")
                ev.accept()
                return

            plot_pos = self.getPlotItem().vb.mapSceneToView(ev.position())
            x_pixel = float(plot_pos.x())
            y_pixel = float(plot_pos.y())

            # If a background image is loaded, clamp coordinates to image pixel extents
            if self._bg_size is not None:
                w, h = self._bg_size
                # clamp to [0, w) and [0, h)
                x_pixel = max(0.0, min(x_pixel, float(w - 1)))
                y_pixel = max(0.0, min(y_pixel, float(h - 1)))

            east_m, north_m = pixel_to_enu(x_pixel, y_pixel)
            if self.mode == "line" and self.assist_enabled and self.current_line_point_ids:
                try:
                    self._add_assisted_segment(x_pixel, y_pixel)
                except RuntimeError as exc:
                    self.on_status(str(exc))
                ev.accept()
                return

            if self.mode == "line" and self.assist_enabled:
                try:
                    if self._white_mask is None:
                        raise RuntimeError("Assist requires a loaded binary image")
                    snapped_x, snapped_y = snap_to_white_pixel(self._white_mask, (x_pixel, y_pixel))
                except RuntimeError as exc:
                    self.on_status(str(exc))
                    ev.accept()
                    return
                x_pixel = float(snapped_x)
                y_pixel = float(snapped_y)
                east_m, north_m = pixel_to_enu(x_pixel, y_pixel)

            pid = self._add_point(east_m, north_m)

            if self.mode == "line":
                self.current_line_point_ids.append(pid)
                self._update_temp_line()
                self._undo_stack.append({"type": "line_point", "point_id": pid})
            else:
                self._undo_stack.append({"type": "point", "point_id": pid})

            self.redraw_all()
            self._notify_changed()
            # show created point id and pixel coordinates
            self.on_status(
                f"Point added: {pid} pixel=({int(x_pixel)},{int(y_pixel)}) "
                f"ENU=({east_m:.3f},{north_m:.3f}) m"
            )
            ev.accept()
            return

        if ev.button() == Qt.RightButton and self.mode == "line":
            self._finalize_line()
            ev.accept()
            return

        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        plot_pos = self.getPlotItem().vb.mapSceneToView(ev.position())
        x_pixel = float(plot_pos.x())
        y_pixel = float(plot_pos.y())
        hover_text = self._hover_text_at(x_pixel, y_pixel)

        if hover_text:
            self._hover_label.setText(hover_text)
            self._hover_label.setPos(x_pixel, y_pixel)
            self._hover_label.setVisible(True)
            if hover_text != self._last_hover_text:
                self.on_status(hover_text)
                self._last_hover_text = hover_text
        else:
            self._hover_label.setVisible(False)
            self._last_hover_text = ""

        super().mouseMoveEvent(ev)

    def keyPressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.matches(QKeySequence.Undo):
            self.undo_last_action()
            ev.accept()
            return

        if self.mode == "line" and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finalize_line()
            ev.accept()
            return

        if self.mode == "line" and ev.key() == Qt.Key_Escape:
            self.current_line_point_ids = []
            self._temp_line_item.setData([], [])
            self.on_status("Line drawing canceled")
            ev.accept()
            return

        super().keyPressEvent(ev)

    def undo_last_action(self) -> bool:
        if not self._undo_stack:
            self.on_status("Nothing to undo")
            return False

        action = self._undo_stack.pop()
        action_type = action["type"]
        if action_type == "line_point":
            point_id = int(action["point_id"])
            if self.current_line_point_ids and self.current_line_point_ids[-1] == point_id:
                self.current_line_point_ids.pop()
            elif point_id in self.current_line_point_ids:
                raise RuntimeError(f"Undo history is inconsistent for line point {point_id}")
            self._remove_point_if_unreferenced(point_id)
            self._update_temp_line()
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid point: {point_id}")
            return True

        if action_type == "point":
            point_id = int(action["point_id"])
            self._remove_point_if_unreferenced(point_id)
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid point: {point_id}")
            return True

        if action_type == "line":
            line_id = int(action["line_id"])
            point_ids = [int(pid) for pid in action["point_ids"]]
            self._remove_line(line_id)
            for point_id in reversed(point_ids):
                self._remove_point_if_unreferenced(point_id)
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid LineString: {line_id}")
            return True

        if action_type == "line_from_existing_points":
            line_id = int(action["line_id"])
            self._remove_line(line_id)
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid LineString: {line_id}")
            return True

        if action_type == "area":
            area_id = int(action["area_id"])
            line_id = int(action["line_id"])
            point_ids = [int(pid) for pid in action["point_ids"]]
            self._remove_area(area_id)
            self._remove_line(line_id)
            for point_id in reversed(point_ids):
                self._remove_point_if_unreferenced(point_id)
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid Area: {area_id}")
            return True

        if action_type == "lanelet":
            lanelet_id = int(action["lanelet_id"])
            self.vector_map.lanelets = [lanelet for lanelet in self.vector_map.lanelets if lanelet.id != lanelet_id]
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid Lanelet: {lanelet_id}")
            return True

        if action_type == "connection":
            connection_id = int(action["connection_id"])
            self.vector_map.connections = [
                connection for connection in self.vector_map.connections if connection.id != connection_id
            ]
            self._notify_changed()
            self.on_status(f"Undid Connection: {connection_id}")
            return True

        if action_type == "assist_segment":
            point_ids = [int(pid) for pid in action["point_ids"]]
            for point_id in reversed(point_ids):
                if self.current_line_point_ids and self.current_line_point_ids[-1] == point_id:
                    self.current_line_point_ids.pop()
                elif point_id in self.current_line_point_ids:
                    raise RuntimeError(f"Undo history is inconsistent for assisted point {point_id}")
                self._remove_point_if_unreferenced(point_id)
            self._update_temp_line()
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid assisted segment: {len(point_ids)} points")
            return True

        if action_type == "resample_line":
            changes = action["changes"]
            if not isinstance(changes, list):
                raise RuntimeError("Undo history is inconsistent for resampling")
            for change in reversed(changes):
                if not isinstance(change, dict):
                    raise RuntimeError("Undo history is inconsistent for resampling")
                line = self._line_by_id(int(change["line_id"]))
                if line is None:
                    raise RuntimeError(f"Resampled LineString {change['line_id']} no longer exists")
                line.point_ids = [int(pid) for pid in change["old_point_ids"]]
                for point_id in [int(pid) for pid in change["new_point_ids"]]:
                    self._remove_point_if_unreferenced(point_id)
                for point in change["removed_points"]:
                    if not isinstance(point, MapPoint):
                        raise RuntimeError("Undo history is inconsistent for removed points")
                    self.vector_map.points.append(point)
            self._sync_next_ids()
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid LineString resampling: {action['line_id']}")
            return True

        if action_type == "infer_centerline":
            lanelet_id = int(action["lanelet_id"])
            line_id = int(action["line_id"])
            point_ids = [int(pid) for pid in action["point_ids"]]
            lanelet = self._lanelet_by_id(lanelet_id)
            if lanelet is None:
                raise RuntimeError(f"Lanelet {lanelet_id} no longer exists")
            lanelet.centerline_id = action["old_centerline_id"] if action["old_centerline_id"] is None else int(action["old_centerline_id"])
            self._remove_line(line_id)
            for point_id in reversed(point_ids):
                self._remove_point_if_unreferenced(point_id)
            self._sync_next_ids()
            self.redraw_all()
            self._notify_changed()
            self.on_status(f"Undid inferred centerline: {line_id}")
            return True

        raise RuntimeError(f"Unknown undo action type: {action_type}")

    def register_lanelet_created(self, lanelet_id: int) -> None:
        self._undo_stack.append({"type": "lanelet", "lanelet_id": lanelet_id})

    def register_connection_created(self, connection_id: int) -> None:
        self._undo_stack.append({"type": "connection", "connection_id": connection_id})

    def create_line_from_point_ids(self, point_ids: list[int], subtype: LineStringSubtype) -> int:
        if len(point_ids) < 2:
            raise RuntimeError("LineString requires at least 2 point IDs")
        missing_ids = [point_id for point_id in point_ids if self._point_by_id(point_id) is None]
        if missing_ids:
            raise RuntimeError("Unknown point IDs: " + ", ".join(str(point_id) for point_id in missing_ids))

        line = MapLineString(id=self._next_line_id, subtype=subtype, point_ids=point_ids)
        self._apply_default_line_semantics(line)
        self.vector_map.lines.append(line)
        self._next_line_id += 1
        self._undo_stack.append({"type": "line_from_existing_points", "line_id": line.id})
        self.redraw_all()
        self._notify_changed()
        self.on_status(f"LineString created from existing points: {line.id}")
        return line.id

    def resample_line_string(self, line_id: int, spacing_m: float = ASSIST_RESAMPLE_SPACING_M) -> bool:
        if self._line_by_id(line_id) is None:
            self.on_status(f"LineString not found: {line_id}")
            return False

        changes = [self._resample_line(line_id, spacing_m)]
        self._undo_stack.append({"type": "resample_line", "line_id": line_id, "changes": changes})
        self.redraw_all()
        self._notify_changed()
        self.on_status(f"Resampled LineString {line_id} at {spacing_m:.1f} m")
        return True

    def infer_center_line(self, lanelet_id: int, spacing_m: float = ASSIST_RESAMPLE_SPACING_M) -> bool:
        lanelet = self._lanelet_by_id(lanelet_id)
        if lanelet is None:
            self.on_status(f"Lanelet not found: {lanelet_id}")
            return False
        if lanelet.centerline_id is not None:
            raise RuntimeError(f"Lanelet {lanelet_id} already has centerline {lanelet.centerline_id}")

        left_line = self._line_by_id(lanelet.left_boundary_line_id)
        right_line = self._line_by_id(lanelet.right_boundary_line_id)
        if left_line is None or right_line is None:
            raise RuntimeError(f"Lanelet {lanelet_id} requires valid left and right LineStrings")

        left_points = self._line_enu_points(left_line)
        right_points = self._line_enu_points(right_line)
        center_points = infer_centerline_points(left_points, right_points, spacing_m)

        point_ids: list[int] = []
        for east_m, north_m in center_points:
            point_ids.append(self._add_point(east_m, north_m))

        line = MapLineString(
            id=self._next_line_id,
            subtype=LineStringSubtype.VIRTUAL,
            line_type=LineType.VIRTUAL_LINE,
            line_role=LineRole.LANE_CENTERLINE,
            marking_type=MarkingType.VIRTUAL,
            point_ids=point_ids,
            is_observable=False,
        )
        self.vector_map.lines.append(line)
        self._next_line_id += 1

        old_centerline_id = lanelet.centerline_id
        lanelet.centerline_id = line.id
        self._undo_stack.append(
            {
                "type": "infer_centerline",
                "lanelet_id": lanelet_id,
                "old_centerline_id": old_centerline_id,
                "line_id": line.id,
                "point_ids": point_ids,
            }
        )
        self.redraw_all()
        self._notify_changed()
        self.on_status(f"Inferred centerline {line.id} for Lanelet {lanelet_id}")
        return True

    def _add_point(self, x: float, y: float) -> int:
        point = MapPoint(id=self._next_point_id, x=x, y=y)
        self.vector_map.points.append(point)
        self._next_point_id += 1
        return point.id

    def _add_assisted_segment(self, x_pixel: float, y_pixel: float) -> None:
        previous_point = self._point_by_id(self.current_line_point_ids[-1])
        if previous_point is None:
            raise RuntimeError("Current LineString references an unknown point")

        start_pixel = enu_to_pixel(previous_point.x, previous_point.y)
        if self._white_mask is None:
            raise RuntimeError("Assist requires a loaded binary image")
        pixel_path = trace_white_pixel_path(self._white_mask, start_pixel, (x_pixel, y_pixel))
        enu_path = [pixel_to_enu(float(px), float(py)) for px, py in pixel_path]
        enu_samples = resample_polyline(enu_path, self.assist_spacing_m)
        if len(enu_samples) < 2:
            raise RuntimeError("Assisted segment is too short to add points")

        new_point_ids: list[int] = []
        for east_m, north_m in enu_samples[1:]:
            point_id = self._add_point(east_m, north_m)
            self.current_line_point_ids.append(point_id)
            new_point_ids.append(point_id)

        self._undo_stack.append({"type": "assist_segment", "point_ids": new_point_ids})
        self._update_temp_line()
        self.redraw_all()
        self._notify_changed()
        self.on_status(f"Assisted segment added: {len(new_point_ids)} points")

    def _update_temp_line(self) -> None:
        points = [self._point_by_id(pid) for pid in self.current_line_point_ids]
        pixels = [self._point_to_pixel(p) for p in points if p is not None]
        xs = [p[0] for p in pixels]
        ys = [p[1] for p in pixels]
        self._temp_line_item.setData(xs, ys)

    def _finalize_line(self) -> None:
        if len(self.current_line_point_ids) < 2:
            self.on_status("Line requires at least 2 points")
            self.current_line_point_ids = []
            self._temp_line_item.setData([], [])
            return
        if self.feature_type == FeatureType.AREA and len(self.current_line_point_ids) < 3:
            self.on_status("Area requires at least 3 points")
            self.current_line_point_ids = []
            self._temp_line_item.setData([], [])
            return

        subtype_text = self._request_subtype(self.feature_type)
        if subtype_text is None:
            self.on_status("Subtype selection canceled")
            return

        if self.feature_type == FeatureType.AREA:
            area_subtype = AreaSubtype(subtype_text)
            line_subtype = LineStringSubtype.ROAD_BORDER
            if self.current_line_point_ids[0] != self.current_line_point_ids[-1]:
                self.current_line_point_ids.append(self.current_line_point_ids[0])
        else:
            area_subtype = None
            line_subtype = LineStringSubtype(subtype_text)

        point_ids = self.current_line_point_ids.copy()
        line = MapLineString(
            id=self._next_line_id,
            subtype=line_subtype,
            point_ids=point_ids,
        )
        self._apply_default_line_semantics(line)
        self.vector_map.lines.append(line)
        self._next_line_id += 1
        if self.feature_type == FeatureType.AREA:
            if area_subtype is None:
                raise RuntimeError("Area subtype was not selected")
            area = MapArea(id=self._next_area_id, subtype=area_subtype, outer_line_id=line.id)
            self.vector_map.areas.append(area)
            self._next_area_id += 1
            self._discard_line_point_undo_actions(point_ids)
            self._undo_stack.append({"type": "area", "area_id": area.id, "line_id": line.id, "point_ids": point_ids})
        else:
            self._discard_line_point_undo_actions(point_ids)
            self._undo_stack.append({"type": "line", "line_id": line.id, "point_ids": point_ids})
        self.current_line_point_ids = []
        self._temp_line_item.setData([], [])
        self.redraw_all()
        self._notify_changed()
        if self.feature_type == FeatureType.AREA:
            self.on_status(f"Area created: {area.id} outer line: {line.id}")
        else:
            self.on_status(f"LineString created: {line.id}")

    def _point_by_id(self, point_id: int) -> MapPoint | None:
        for point in self.vector_map.points:
            if point.id == point_id:
                return point
        return None

    def _lanelet_by_id(self, lanelet_id: int):
        for lanelet in self.vector_map.lanelets:
            if lanelet.id == lanelet_id:
                return lanelet
        return None

    def _draw_points(self) -> None:
        if not self.vector_map.points:
            self._points_item.setData([], [])
            return

        pixels = [self._point_to_pixel(p) for p in self.vector_map.points]
        xs = [p[0] for p in pixels]
        ys = [p[1] for p in pixels]
        self._points_item.setData(xs, ys)

    def _draw_lines(self) -> None:
        for item in self._line_items:
            self.removeItem(item)
        self._line_items.clear()

        for line in self.vector_map.lines:
            pixels = self._line_pixel_points(line)
            xs = [p[0] for p in pixels]
            ys = [p[1] for p in pixels]
            if len(xs) < 2:
                continue

            item = pg.PlotDataItem(xs, ys, pen=self._line_pen(line))
            self.addItem(item)
            self._line_items.append(item)

    def _draw_areas(self) -> None:
        for item in self._area_items:
            self.removeItem(item)
        self._area_items.clear()

        for area in self.vector_map.areas:
            line = self._line_by_id(area.outer_line_id)
            if line is None:
                continue
            pixels = self._line_pixel_points(line)
            if len(pixels) < 3:
                continue
            xs = [p[0] for p in pixels]
            ys = [p[1] for p in pixels]
            item = pg.PlotDataItem(xs, ys, pen=pg.mkPen((80, 220, 160), width=2))
            self.addItem(item)
            self._area_items.append(item)

    def _draw_lanelets(self) -> None:
        for item in self._lanelet_items:
            self.removeItem(item)
        self._lanelet_items.clear()

        for lanelet in self.vector_map.lanelets:
            polygon = self._lanelet_polygon(lanelet.id)
            if len(polygon) < 3:
                continue
            xs = [p[0] for p in polygon] + [polygon[0][0]]
            ys = [p[1] for p in polygon] + [polygon[0][1]]
            item = pg.PlotDataItem(xs, ys, pen=pg.mkPen((255, 160, 60), width=1, style=Qt.DashLine))
            self.addItem(item)
            self._lanelet_items.append(item)

    def _point_to_pixel(self, point: MapPoint) -> tuple[float, float]:
        return enu_to_pixel(point.x, point.y)

    def _line_by_id(self, line_id: int | None) -> MapLineString | None:
        if line_id is None:
            return None
        for line in self.vector_map.lines:
            if line.id == line_id:
                return line
        return None

    def line_exists(self, line_id: int | None) -> bool:
        return self._line_by_id(line_id) is not None

    def lanelet_exists(self, lanelet_id: int | None) -> bool:
        return lanelet_id is not None and self._lanelet_by_id(lanelet_id) is not None

    def apply_lanelet_boundary_semantics(self, left_id: int, right_id: int, centerline_id: int | None = None) -> None:
        left_line = self._line_by_id(left_id)
        if left_line is not None and left_line.line_role == LineRole.UNKNOWN:
            left_line.line_role = LineRole.LEFT_BOUNDARY
        right_line = self._line_by_id(right_id)
        if right_line is not None and right_line.line_role == LineRole.UNKNOWN:
            right_line.line_role = LineRole.RIGHT_BOUNDARY
        centerline = self._line_by_id(centerline_id)
        if centerline is not None:
            centerline.line_type = LineType.VIRTUAL_LINE
            centerline.line_role = LineRole.LANE_CENTERLINE
            centerline.marking_type = MarkingType.VIRTUAL
            centerline.is_observable = False

    def _line_enu_points(self, line: MapLineString) -> list[tuple[float, float]]:
        points = [self._point_by_id(pid) for pid in line.point_ids]
        if any(point is None for point in points):
            raise RuntimeError(f"LineString {line.id} references unknown points")
        return [(point.x, point.y) for point in points if point is not None]

    def _remove_line(self, line_id: int) -> None:
        self.vector_map.lines = [line for line in self.vector_map.lines if line.id != line_id]

    def _remove_area(self, area_id: int) -> None:
        self.vector_map.areas = [area for area in self.vector_map.areas if area.id != area_id]

    def _remove_point_if_unreferenced(self, point_id: int) -> None:
        if any(point_id in line.point_ids for line in self.vector_map.lines):
            raise RuntimeError(f"Point {point_id} is still referenced by a LineString")
        self.vector_map.points = [point for point in self.vector_map.points if point.id != point_id]

    def _discard_line_point_undo_actions(self, point_ids: list[int]) -> None:
        pending_ids = set(point_ids)
        while self._undo_stack and self._undo_stack[-1]["type"] in {"line_point", "assist_segment"}:
            action = self._undo_stack[-1]
            if action["type"] == "line_point":
                current_point_ids = {int(action["point_id"])}
            else:
                current_point_ids = {int(point_id) for point_id in action["point_ids"]}
            if not current_point_ids <= pending_ids:
                break
            self._undo_stack.pop()
            pending_ids -= current_point_ids

    def _notify_changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def _sync_next_ids(self) -> None:
        self._next_point_id = (max((p.id for p in self.vector_map.points), default=0) + 1)
        self._next_line_id = (max((l.id for l in self.vector_map.lines), default=99) + 1)
        self._next_area_id = (max((a.id for a in self.vector_map.areas), default=499) + 1)

    def _line_pixel_points(self, line: MapLineString) -> list[tuple[float, float]]:
        points = [self._point_by_id(pid) for pid in line.point_ids]
        return [self._point_to_pixel(point) for point in points if point is not None]

    def _handle_selection_click(self, x_pixel: float, y_pixel: float) -> bool:
        target = self._selection_target
        if target is None or self.on_selected is None:
            return False

        if target in {"lanelet_left", "lanelet_right", "lanelet_center", "resample_line"}:
            line_id = self._nearest_line_id(x_pixel, y_pixel, threshold_m=2.0)
            if line_id is None:
                self.on_status("No LineString near click")
                return True
            self.on_selected(target, line_id)
            self._selection_target = None
            return True

        if target in {"conn_from", "conn_to", "infer_center_lanelet"}:
            lanelet_id = self._lanelet_id_at(x_pixel, y_pixel)
            if lanelet_id is None:
                self.on_status("No Lanelet at click")
                return True
            self.on_selected(target, lanelet_id)
            self._selection_target = None
            return True

        return False

    def _lanelet_id_at(self, x_pixel: float, y_pixel: float) -> int | None:
        for lanelet in reversed(self.vector_map.lanelets):
            if self._point_in_polygon((x_pixel, y_pixel), self._lanelet_polygon(lanelet.id)):
                return lanelet.id
        return None

    @staticmethod
    def _apply_default_line_semantics(line: MapLineString) -> None:
        if line.subtype == LineStringSubtype.ROAD_BORDER:
            line.line_type = LineType.LANE_THIN
            line.line_role = LineRole.ROAD_EDGE
            line.marking_type = MarkingType.SOLID
        elif line.subtype == LineStringSubtype.STOP_LINE:
            line.line_type = LineType.STOP_LINE
            line.line_role = LineRole.STOP_LINE
            line.marking_type = MarkingType.SOLID
        elif line.subtype == LineStringSubtype.VIRTUAL:
            line.line_type = LineType.VIRTUAL_LINE
            line.marking_type = MarkingType.VIRTUAL
            line.is_observable = False
        elif line.subtype == LineStringSubtype.DASHED:
            line.line_type = LineType.LANE_THIN
            line.marking_type = MarkingType.DASHED
        else:
            line.line_type = LineType.LANE_THIN
            line.marking_type = MarkingType.SOLID

    @staticmethod
    def _line_pen(line: MapLineString):
        style = Qt.SolidLine
        if line.subtype == LineStringSubtype.DASHED or line.marking_type == MarkingType.DASHED:
            style = Qt.DashLine
        if (
            line.line_role == LineRole.LANE_CENTERLINE
            or line.line_type == LineType.LANE_CENTERLINE
            or line.subtype == LineStringSubtype.VIRTUAL
        ):
            return pg.mkPen((100, 220, 255), width=2, style=Qt.DashLine)
        if line.subtype == LineStringSubtype.ROAD_BORDER or line.line_type == LineType.ROAD_EDGE:
            return pg.mkPen((80, 220, 160), width=2, style=style)
        if line.subtype == LineStringSubtype.STOP_LINE or line.line_type == LineType.STOP_LINE:
            return pg.mkPen((255, 80, 80), width=3, style=style)
        return pg.mkPen((255, 255, 255), width=2, style=style)

    def _resample_line(self, line_id: int, spacing_m: float) -> dict[str, object]:
        line = self._line_by_id(line_id)
        if line is None:
            raise RuntimeError(f"LineString not found: {line_id}")

        old_point_ids = line.point_ids.copy()
        old_points = [self._point_by_id(point_id) for point_id in old_point_ids]
        if any(point is None for point in old_points):
            raise RuntimeError(f"LineString {line_id} references unknown points")

        enu_points = [(point.x, point.y) for point in old_points if point is not None]
        resampled = resample_polyline(enu_points, spacing_m)
        if len(resampled) < 2:
            raise RuntimeError(f"LineString {line_id} is too short to resample")

        new_point_ids: list[int] = []
        for east_m, north_m in resampled:
            new_point_ids.append(self._add_point(east_m, north_m))

        line.point_ids = new_point_ids
        removed_points: list[MapPoint] = []
        for point_id in old_point_ids:
            if not any(point_id in other_line.point_ids for other_line in self.vector_map.lines):
                point = self._point_by_id(point_id)
                if point is None:
                    raise RuntimeError(f"Point not found during resampling: {point_id}")
                removed_points.append(point)
                self.vector_map.points = [item for item in self.vector_map.points if item.id != point_id]

        return {
            "line_id": line_id,
            "old_point_ids": old_point_ids,
            "new_point_ids": new_point_ids,
            "removed_points": removed_points,
        }

    def _hover_text_at(self, x_pixel: float, y_pixel: float) -> str:
        labels: list[str] = []
        lanelets = [
            lanelet
            for lanelet in self.vector_map.lanelets
            if self._point_in_polygon((x_pixel, y_pixel), self._lanelet_polygon(lanelet.id))
        ]
        labels.extend(self._lanelet_hover_text(lanelet) for lanelet in lanelets)

        areas = [
            area
            for area in self.vector_map.areas
            if self._point_in_polygon((x_pixel, y_pixel), self._area_polygon(area))
        ]
        labels.extend(self._area_hover_text(area) for area in areas)

        nearest_line_id = self._nearest_line_id(x_pixel, y_pixel, threshold_m=1.4)
        if nearest_line_id is not None:
            line = self._line_by_id(nearest_line_id)
            if line is not None:
                labels.append(self._line_hover_text(line))

        return "\n".join(labels)

    def _request_subtype(self, feature_type: FeatureType) -> str | None:
        if self.on_subtype_requested is not None:
            return self.on_subtype_requested(feature_type)
        if feature_type == FeatureType.LINE_STRING:
            return self.line_subtype.value
        if feature_type == FeatureType.AREA:
            return self.area_subtype.value
        return None

    @staticmethod
    def _line_hover_text(line: MapLineString) -> str:
        return (
            f"LineString ID: {line.id} "
            f"subtype={line.subtype.value} "
            f"type={line.line_type.value} "
            f"marking={line.marking_type.value} "
            f"observable={str(line.is_observable).lower()}"
        )

    @staticmethod
    def _lanelet_hover_text(lanelet: MapLanelet) -> str:
        members = [
            f"left={lanelet.left_boundary_line_id}",
            f"right={lanelet.right_boundary_line_id}",
        ]
        if lanelet.centerline_id is not None:
            members.append(f"center={lanelet.centerline_id}")
        return (
            f"Lanelet ID: {lanelet.id} "
            f"subtype={lanelet.subtype.value} "
            f"virtual={str(lanelet.is_virtual).lower()} "
            + " ".join(members)
        )

    @staticmethod
    def _area_hover_text(area: MapArea) -> str:
        return f"Area ID: {area.id} subtype={area.subtype.value} outer={area.outer_line_id}"

    def _nearest_line_id(self, x_pixel: float, y_pixel: float, threshold_m: float) -> int | None:
        nearest_id: int | None = None
        nearest_distance = threshold_m
        point_enu = pixel_to_enu(x_pixel, y_pixel)
        for line in self.vector_map.lines:
            points_enu = self._line_enu_points(line)
            for p1, p2 in zip(points_enu, points_enu[1:]):
                distance = self._distance_to_segment(point_enu, p1, p2)
                if distance <= nearest_distance:
                    nearest_distance = distance
                    nearest_id = line.id
        return nearest_id

    def _lanelet_polygon(self, lanelet_id: int) -> list[tuple[float, float]]:
        lanelet = next((item for item in self.vector_map.lanelets if item.id == lanelet_id), None)
        if lanelet is None:
            return []
        left_line = self._line_by_id(lanelet.left_boundary_line_id)
        right_line = self._line_by_id(lanelet.right_boundary_line_id)
        if left_line is None or right_line is None:
            return []
        left_points = self._line_pixel_points(left_line)
        right_points = self._line_pixel_points(right_line)
        if len(left_points) < 2 or len(right_points) < 2:
            return []
        return left_points + list(reversed(right_points))

    def _area_polygon(self, area: MapArea) -> list[tuple[float, float]]:
        line = self._line_by_id(area.outer_line_id)
        if line is None:
            return []
        return self._line_pixel_points(line)

    @staticmethod
    def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
        if len(polygon) < 3:
            return False
        x, y = point
        inside = False
        j = len(polygon) - 1
        for i, pi in enumerate(polygon):
            xi, yi = pi
            xj, yj = polygon[j]
            crosses = (yi > y) != (yj > y)
            if crosses:
                x_intersection = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < x_intersection:
                    inside = not inside
            j = i
        return inside

    @staticmethod
    def _distance_to_segment(
        point: tuple[float, float],
        segment_start: tuple[float, float],
        segment_end: tuple[float, float],
    ) -> float:
        px, py = point
        ax, ay = segment_start
        bx, by = segment_end
        dx = bx - ax
        dy = by - ay
        if dx == 0.0 and dy == 0.0:
            return float(np.hypot(px - ax, py - ay))
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        closest_x = ax + t * dx
        closest_y = ay + t * dy
        return float(np.hypot(px - closest_x, py - closest_y))
