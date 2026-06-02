from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vector_map_editor.model.coordinates import PIXEL_TO_ENU_MATRIX, pixel_to_enu


DEFAULT_IMAGE_PATH = REPO_ROOT / "sample_image" / "lane.png"
DEFAULT_PIXEL_TO_ENU_MATRIX = np.array(PIXEL_TO_ENU_MATRIX, dtype=np.float64)


class ImageView(QGraphicsView):
    cursorMoved = Signal(float, float)
    cursorLeftImage = Signal()

    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.setSceneRect(self.pixmap_item.boundingRect())

        pen = QPen(Qt.red)
        pen.setWidth(0)
        self.horizontal_line = QGraphicsLineItem()
        self.vertical_line = QGraphicsLineItem()
        self.horizontal_line.setPen(pen)
        self.vertical_line.setPen(pen)
        self.scene.addItem(self.horizontal_line)
        self.scene.addItem(self.vertical_line)
        self._set_crosshair_visible(False)

    def fit_image(self) -> None:
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.fit_image()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        x_pixel = float(scene_pos.x())
        y_pixel = float(scene_pos.y())
        width = float(self.pixmap_item.pixmap().width())
        height = float(self.pixmap_item.pixmap().height())

        if 0.0 <= x_pixel < width and 0.0 <= y_pixel < height:
            self._update_crosshair(x_pixel, y_pixel, width, height)
            self.cursorMoved.emit(x_pixel, y_pixel)
        else:
            self._set_crosshair_visible(False)
            self.cursorLeftImage.emit()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._set_crosshair_visible(False)
        self.cursorLeftImage.emit()
        super().leaveEvent(event)

    def _update_crosshair(self, x_pixel: float, y_pixel: float, width: float, height: float) -> None:
        self.horizontal_line.setLine(0.0, y_pixel, width, y_pixel)
        self.vertical_line.setLine(x_pixel, 0.0, x_pixel, height)
        self._set_crosshair_visible(True)

    def _set_crosshair_visible(self, visible: bool) -> None:
        self.horizontal_line.setVisible(visible)
        self.vertical_line.setVisible(visible)


class CheckerWindow(QMainWindow):
    def __init__(self, image_path: Path, pixel_to_enu_matrix: np.ndarray) -> None:
        super().__init__()
        self.setWindowTitle("Pixel to ENU Checker")
        self.resize(1200, 800)

        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            raise FileNotFoundError(f"Image cannot be read: {image_path}")

        self.pixel_to_enu_matrix = pixel_to_enu_matrix
        self.view = ImageView(pixmap)
        self.view.cursorMoved.connect(self._update_cursor_position)
        self.view.cursorLeftImage.connect(self._clear_cursor_position)

        self.pixel_label = QLabel("pixel: -")
        self.enu_label = QLabel("ENU: -")

        label_row = QWidget()
        label_layout = QHBoxLayout(label_row)
        label_layout.setContentsMargins(8, 4, 8, 4)
        label_layout.addWidget(self.pixel_label)
        label_layout.addWidget(self.enu_label)
        label_layout.addStretch(1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label_row, 0)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(central)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"image: {image_path}")

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.view.fit_image()

    def _update_cursor_position(self, x_pixel: float, y_pixel: float) -> None:
        east_m, north_m = transform_pixel_to_enu(self.pixel_to_enu_matrix, x_pixel, y_pixel)
        self.pixel_label.setText(f"pixel: x={x_pixel:.2f}, y={y_pixel:.2f}")
        self.enu_label.setText(f"ENU: east={east_m:.3f} m, north={north_m:.3f} m")
        self.status_bar.showMessage(
            f"pixel=({x_pixel:.2f}, {y_pixel:.2f})  ENU=({east_m:.3f}, {north_m:.3f}) m"
        )

    def _clear_cursor_position(self) -> None:
        self.pixel_label.setText("pixel: -")
        self.enu_label.setText("ENU: -")


def transform_pixel_to_enu(matrix: np.ndarray, x_pixel: float, y_pixel: float) -> tuple[float, float]:
    if matrix is DEFAULT_PIXEL_TO_ENU_MATRIX:
        return pixel_to_enu(x_pixel, y_pixel)
    point = np.array([x_pixel, y_pixel, 1.0], dtype=np.float64)
    transformed = matrix @ point
    return float(transformed[0]), float(transformed[1])


def load_pixel_to_enu_matrix(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"Fit result JSON does not exist: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    matrix_data = data.get("pixel_to_enu_matrix")
    if not isinstance(matrix_data, list):
        raise ValueError("Fit result JSON must contain pixel_to_enu_matrix")
    matrix = np.array(matrix_data, dtype=np.float64)
    if matrix.shape != (3, 3):
        raise ValueError(f"pixel_to_enu_matrix must be 3x3, got {matrix.shape}")
    return matrix


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show sample_image and display the mouse cursor pixel as ENU coordinates."
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_IMAGE_PATH,
        help=f"Image path. Default: {DEFAULT_IMAGE_PATH}",
    )
    parser.add_argument(
        "--fit-json",
        type=Path,
        default=None,
        help="Optional fitter.py JSON output. If omitted, the latest provided matrix is used.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.fit_json is None:
        pixel_to_enu_matrix = DEFAULT_PIXEL_TO_ENU_MATRIX
    else:
        pixel_to_enu_matrix = load_pixel_to_enu_matrix(args.fit_json)

    app = QApplication(sys.argv)
    window = CheckerWindow(args.image, pixel_to_enu_matrix)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
