from __future__ import annotations

from collections.abc import Callable
import heapq

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QMouseEvent

from vector_map_editor.model.coordinates import local_meter_to_pixel, pixel_to_local_meter
from vector_map_editor.model.enums import AreaSubtype, FeatureType, LineStringSubtype
from vector_map_editor.model.map_data import MapArea, MapLineString, MapPoint, VectorMap


UndoAction = dict[str, object]
WHITE_PIXEL_THRESHOLD = 40
WHITE_PIXEL_SNAP_RADIUS = 30
ASSIST_RESAMPLE_SPACING_M = 3.0


class MapCanvas(pg.PlotWidget):
    def __init__(self, on_status: Callable[[str], None], on_changed: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.on_status = on_status
        self.on_changed = on_changed
        self.vector_map = VectorMap(map_id="map_001")

        self.setBackground("k")
        self.showGrid(x=True, y=True, alpha=0.2)
        # Do not rely on a global invert; we'll set the view range when an image is loaded
        self.setAspectLocked(False)

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

    def set_assist_enabled(self, enabled: bool) -> None:
        self.assist_enabled = enabled
        self.on_status(f"Assist: {'on' if enabled else 'off'}")

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
        if corrected.ndim == 3:
            gray = np.mean(corrected[:, :, :3], axis=2)
        else:
            gray = corrected
        self._white_mask = gray > WHITE_PIXEL_THRESHOLD
        # アスペクト比を保つため、画像のサイズに基づいてrectを設定
        h, w = corrected.shape[:2]
        self._bg_size = (w, h)

        # Place the image so that pixel (0,0) (top-left) maps to the canvas origin (0,0).
        self._background_item.setRect(pg.QtCore.QRectF(0, 0, w, h))

        vb = self.getPlotItem().vb
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

            x_m, y_m = pixel_to_local_meter(x_pixel, y_pixel)
            if self.mode == "line" and self.assist_enabled and self.current_line_point_ids:
                try:
                    self._add_assisted_segment(x_pixel, y_pixel)
                except RuntimeError as exc:
                    self.on_status(str(exc))
                ev.accept()
                return

            if self.mode == "line" and self.assist_enabled:
                try:
                    snapped_x, snapped_y = self._snap_to_white_pixel((x_pixel, y_pixel))
                except RuntimeError as exc:
                    self.on_status(str(exc))
                    ev.accept()
                    return
                x_pixel = float(snapped_x)
                y_pixel = float(snapped_y)
                x_m, y_m = pixel_to_local_meter(x_pixel, y_pixel)

            pid = self._add_point(x_m, y_m)

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
                f"local=({x_m:.3f},{y_m:.3f}) m"
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

        raise RuntimeError(f"Unknown undo action type: {action_type}")

    def register_lanelet_created(self, lanelet_id: int) -> None:
        self._undo_stack.append({"type": "lanelet", "lanelet_id": lanelet_id})

    def register_connection_created(self, connection_id: int) -> None:
        self._undo_stack.append({"type": "connection", "connection_id": connection_id})

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

    def _add_point(self, x: float, y: float) -> int:
        point = MapPoint(id=self._next_point_id, x=x, y=y)
        self.vector_map.points.append(point)
        self._next_point_id += 1
        return point.id

    def _add_assisted_segment(self, x_pixel: float, y_pixel: float) -> None:
        previous_point = self._point_by_id(self.current_line_point_ids[-1])
        if previous_point is None:
            raise RuntimeError("Current LineString references an unknown point")

        start_pixel = local_meter_to_pixel(previous_point.x, previous_point.y)
        pixel_path = self._trace_white_pixel_path(start_pixel, (x_pixel, y_pixel))
        local_path = [pixel_to_local_meter(float(px), float(py)) for px, py in pixel_path]
        local_samples = self._resample_polyline(local_path, self.assist_spacing_m)
        if len(local_samples) < 2:
            raise RuntimeError("Assisted segment is too short to add points")

        new_point_ids: list[int] = []
        for x_m, y_m in local_samples[1:]:
            point_id = self._add_point(x_m, y_m)
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

        if self.feature_type == FeatureType.AREA and self.current_line_point_ids[0] != self.current_line_point_ids[-1]:
            self.current_line_point_ids.append(self.current_line_point_ids[0])

        point_ids = self.current_line_point_ids.copy()
        line = MapLineString(
            id=self._next_line_id,
            subtype=self.line_subtype if self.feature_type == FeatureType.LINE_STRING else LineStringSubtype.ROAD_BORDER,
            point_ids=point_ids,
        )
        self.vector_map.lines.append(line)
        self._next_line_id += 1
        if self.feature_type == FeatureType.AREA:
            area = MapArea(id=self._next_area_id, subtype=self.area_subtype, outer_line_id=line.id)
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

            item = pg.PlotDataItem(xs, ys, pen=pg.mkPen((255, 255, 255), width=2))
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
        return local_meter_to_pixel(point.x, point.y)

    def _line_by_id(self, line_id: int | None) -> MapLineString | None:
        if line_id is None:
            return None
        for line in self.vector_map.lines:
            if line.id == line_id:
                return line
        return None

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

    def _resample_line(self, line_id: int, spacing_m: float) -> dict[str, object]:
        line = self._line_by_id(line_id)
        if line is None:
            raise RuntimeError(f"LineString not found: {line_id}")

        old_point_ids = line.point_ids.copy()
        old_points = [self._point_by_id(point_id) for point_id in old_point_ids]
        if any(point is None for point in old_points):
            raise RuntimeError(f"LineString {line_id} references unknown points")

        local_points = [(point.x, point.y) for point in old_points if point is not None]
        resampled = self._resample_polyline(local_points, spacing_m)
        if len(resampled) < 2:
            raise RuntimeError(f"LineString {line_id} is too short to resample")

        new_point_ids: list[int] = []
        for x_m, y_m in resampled:
            new_point_ids.append(self._add_point(x_m, y_m))

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

    def _trace_white_pixel_path(
        self,
        start_pixel: tuple[float, float],
        end_pixel: tuple[float, float],
    ) -> list[tuple[int, int]]:
        if self._white_mask is None:
            raise RuntimeError("Assist requires a loaded binary image")

        start = self._snap_to_white_pixel(start_pixel)
        goal = self._snap_to_white_pixel(end_pixel)
        if start == goal:
            return [start]

        height, width = self._white_mask.shape
        open_heap: list[tuple[float, float, tuple[int, int]]] = []
        heapq.heappush(open_heap, (self._pixel_distance(start, goal), 0.0, start))
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        best_cost: dict[tuple[int, int], float] = {start: 0.0}
        neighbors = [
            (-1, 0, 1.0),
            (1, 0, 1.0),
            (0, -1, 1.0),
            (0, 1, 1.0),
            (-1, -1, 2**0.5),
            (-1, 1, 2**0.5),
            (1, -1, 2**0.5),
            (1, 1, 2**0.5),
        ]

        while open_heap:
            _, current_cost, current = heapq.heappop(open_heap)
            if current == goal:
                return self._reconstruct_pixel_path(came_from, current)
            if current_cost > best_cost[current]:
                continue

            cx, cy = current
            for dx, dy, step_cost in neighbors:
                nx = cx + dx
                ny = cy + dy
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                if not self._white_mask[ny, nx]:
                    continue
                next_point = (nx, ny)
                new_cost = current_cost + step_cost
                if new_cost >= best_cost.get(next_point, float("inf")):
                    continue
                best_cost[next_point] = new_cost
                came_from[next_point] = current
                priority = new_cost + self._pixel_distance(next_point, goal)
                heapq.heappush(open_heap, (priority, new_cost, next_point))

        raise RuntimeError("No connected white-pixel path found between the selected points")

    def _snap_to_white_pixel(
        self,
        pixel: tuple[float, float],
        max_radius: int = WHITE_PIXEL_SNAP_RADIUS,
    ) -> tuple[int, int]:
        if self._white_mask is None:
            raise RuntimeError("Assist requires a loaded binary image")

        x = int(round(pixel[0]))
        y = int(round(pixel[1]))
        height, width = self._white_mask.shape
        if x < 0 or y < 0 or x >= width or y >= height:
            raise RuntimeError("Selected point is outside the loaded image")
        if self._white_mask[y, x]:
            return x, y

        best: tuple[int, int] | None = None
        best_distance = float("inf")
        x_min = max(0, x - max_radius)
        x_max = min(width - 1, x + max_radius)
        y_min = max(0, y - max_radius)
        y_max = min(height - 1, y + max_radius)
        for yy in range(y_min, y_max + 1):
            for xx in range(x_min, x_max + 1):
                if not self._white_mask[yy, xx]:
                    continue
                distance = self._pixel_distance((x, y), (xx, yy))
                if distance < best_distance:
                    best_distance = distance
                    best = (xx, yy)
        if best is None:
            raise RuntimeError("No white pixel found near the selected point")
        return best

    @staticmethod
    def _reconstruct_pixel_path(
        came_from: dict[tuple[int, int], tuple[int, int]],
        current: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    @staticmethod
    def _resample_polyline(points: list[tuple[float, float]], spacing_m: float) -> list[tuple[float, float]]:
        if spacing_m <= 0.0:
            raise ValueError("Resampling spacing must be positive")
        if len(points) < 2:
            return points.copy()

        distances = [0.0]
        for p1, p2 in zip(points, points[1:]):
            distances.append(distances[-1] + float(np.hypot(p2[0] - p1[0], p2[1] - p1[1])))
        total_length = distances[-1]
        if total_length == 0.0:
            raise RuntimeError("Cannot resample a zero-length polyline")

        sample_distances = list(np.arange(0.0, total_length, spacing_m))
        if not sample_distances or sample_distances[-1] != total_length:
            sample_distances.append(total_length)

        samples: list[tuple[float, float]] = []
        segment_index = 0
        for target_distance in sample_distances:
            while segment_index < len(distances) - 2 and distances[segment_index + 1] < target_distance:
                segment_index += 1
            start_distance = distances[segment_index]
            end_distance = distances[segment_index + 1]
            p1 = points[segment_index]
            p2 = points[segment_index + 1]
            if end_distance == start_distance:
                samples.append(p1)
                continue
            ratio = (target_distance - start_distance) / (end_distance - start_distance)
            samples.append((p1[0] + (p2[0] - p1[0]) * ratio, p1[1] + (p2[1] - p1[1]) * ratio))
        return samples

    def _hover_text_at(self, x_pixel: float, y_pixel: float) -> str:
        labels: list[str] = []
        lanelet_ids = [
            lanelet.id
            for lanelet in self.vector_map.lanelets
            if self._point_in_polygon((x_pixel, y_pixel), self._lanelet_polygon(lanelet.id))
        ]
        if lanelet_ids:
            labels.append("Lanelet ID: " + ", ".join(str(lid) for lid in lanelet_ids))

        nearest_line_id = self._nearest_line_id(x_pixel, y_pixel, threshold_pixel=8.0)
        if nearest_line_id is not None:
            labels.append(f"LineString ID: {nearest_line_id}")

        return "\n".join(labels)

    def _nearest_line_id(self, x_pixel: float, y_pixel: float, threshold_pixel: float) -> int | None:
        nearest_id: int | None = None
        nearest_distance = threshold_pixel
        for line in self.vector_map.lines:
            pixels = self._line_pixel_points(line)
            for p1, p2 in zip(pixels, pixels[1:]):
                distance = self._distance_to_segment((x_pixel, y_pixel), p1, p2)
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

    @staticmethod
    def _pixel_distance(p1: tuple[int, int], p2: tuple[int, int]) -> float:
        return float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
