from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QMouseEvent

from vector_map_editor.model.coordinates import local_meter_to_pixel, pixel_to_local_meter
from vector_map_editor.model.enums import AreaSubtype, FeatureType, LineStringSubtype
from vector_map_editor.model.map_data import MapArea, MapLineString, MapPoint, VectorMap


UndoAction = dict[str, object]


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

        self._background_item = pg.ImageItem()
        self.addItem(self._background_item)
        self._background_item.setVisible(False)

        # store background image pixel size (width, height)
        self._bg_size: tuple[int, int] | None = None

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
        # Some display setups caused the image to appear rotated and flipped
        # (observed: image shown as y-flipped and rotated left 90deg). To
        # ensure the background matches the original image orientation, apply
        # a corrective transform here so that the shown image aligns with the
        # image pixel axes (x→right, y→down).
        try:
            corrected = np.rot90(np.flipud(image), k=3)
        except Exception:
            corrected = image

        self._background_item.setImage(corrected)
        # アスペクト比を保つため、画像のサイズに基づいてrectを設定
        h, w = corrected.shape[:2]
        self._bg_size = (w, h)

        # Place the image so that pixel (0,0) (top-left) maps to the canvas origin (0,0)
        # and one pixel corresponds to one canvas unit. We set the ImageItem rect to
        # (0,0,w,h) and set the viewbox range to exactly that area so clicks map to
        # image pixel coordinates directly.
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

        raise RuntimeError(f"Unknown undo action type: {action_type}")

    def register_lanelet_created(self, lanelet_id: int) -> None:
        self._undo_stack.append({"type": "lanelet", "lanelet_id": lanelet_id})

    def register_connection_created(self, connection_id: int) -> None:
        self._undo_stack.append({"type": "connection", "connection_id": connection_id})

    def _add_point(self, x: float, y: float) -> int:
        point = MapPoint(id=self._next_point_id, x=x, y=y)
        self.vector_map.points.append(point)
        self._next_point_id += 1
        return point.id

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
        while self._undo_stack and self._undo_stack[-1]["type"] == "line_point":
            point_id = int(self._undo_stack[-1]["point_id"])
            if point_id not in pending_ids:
                break
            self._undo_stack.pop()
            pending_ids.discard(point_id)

    def _notify_changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def _line_pixel_points(self, line: MapLineString) -> list[tuple[float, float]]:
        points = [self._point_by_id(pid) for pid in line.point_ids]
        return [self._point_to_pixel(point) for point in points if point is not None]

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
