from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from vector_map_editor.canvas.map_canvas import MapCanvas
from vector_map_editor.io.xml_io import load_map_xml, save_map_xml
from vector_map_editor.model.enums import AreaSubtype, ConnectionType, FeatureType, LaneletSubtype, LineStringSubtype
from vector_map_editor.model.map_data import LaneConnection, MapLanelet


SAMPLE_IMAGE_PATH = Path(__file__).resolve().parents[2] / "sample_image" / "lane.png"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vector Map Editor (OSM XML)")
        self.resize(1400, 860)

        self.canvas = MapCanvas(on_status=self._set_status, on_changed=self._refresh_summary)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self._build_ui()
        self._build_menu()
        self._load_sample_background()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        layout.addWidget(left_panel, 0)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(right_panel, 0)

        self.setCentralWidget(central)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        mode_box = QGroupBox("Tools")
        mode_layout = QVBoxLayout(mode_box)

        btn_select = QPushButton("Select (V)")
        btn_point = QPushButton("Point (P)")
        btn_line = QPushButton("LineString (L)")

        btn_select.clicked.connect(lambda: self.canvas.set_mode("select"))
        btn_point.clicked.connect(lambda: self.canvas.set_mode("point"))
        btn_line.clicked.connect(lambda: self.canvas.set_mode("line"))

        mode_layout.addWidget(btn_select)
        mode_layout.addWidget(btn_point)
        mode_layout.addWidget(btn_line)

        class_box = QGroupBox("Class")
        class_layout = QFormLayout(class_box)
        self.feature_type = QComboBox()
        self.feature_type.addItems([item.value for item in FeatureType])
        self.subtype = QComboBox()
        self.turn_direction = QComboBox()
        self.turn_direction.addItems([item.value for item in ConnectionType])
        self.feature_type.currentTextChanged.connect(self._update_subtype_options)
        self.subtype.currentTextChanged.connect(self._apply_canvas_feature)
        class_layout.addRow("Type", self.feature_type)
        class_layout.addRow("Subtype", self.subtype)
        class_layout.addRow("Turn", self.turn_direction)
        self._update_subtype_options(self.feature_type.currentText())

        lanelet_box = QGroupBox("Lanelet")
        lanelet_layout = QFormLayout(lanelet_box)
        self.lanelet_left = QLineEdit()
        self.lanelet_right = QLineEdit()
        self.lanelet_center = QLineEdit()
        btn_lanelet = QPushButton("Create Lanelet")
        btn_lanelet.clicked.connect(self._create_lanelet)

        lanelet_layout.addRow("Left line ID", self.lanelet_left)
        lanelet_layout.addRow("Right line ID", self.lanelet_right)
        lanelet_layout.addRow("Centerline ID (optional)", self.lanelet_center)
        lanelet_layout.addRow(btn_lanelet)

        conn_box = QGroupBox("Connection")
        conn_layout = QFormLayout(conn_box)
        self.conn_from = QLineEdit()
        self.conn_to = QLineEdit()
        self.conn_type = QLineEdit(ConnectionType.STRAIGHT.value)
        btn_conn = QPushButton("Create Connection")
        btn_conn.clicked.connect(self._create_connection)

        conn_layout.addRow("From lanelet ID", self.conn_from)
        conn_layout.addRow("To lanelet ID", self.conn_to)
        conn_layout.addRow("Type", self.conn_type)
        conn_layout.addRow(btn_conn)

        image_box = QGroupBox("Image")
        image_layout = QVBoxLayout(image_box)
        btn_image = QPushButton("Load lane.png")
        btn_image.clicked.connect(self._open_background)
        image_layout.addWidget(btn_image)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Opacity"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._change_opacity)
        opacity_row.addWidget(self.opacity_slider)
        image_layout.addLayout(opacity_row)

        layout.addWidget(mode_box)
        layout.addWidget(class_box)
        layout.addWidget(lanelet_box)
        layout.addWidget(conn_box)
        layout.addWidget(image_box)
        layout.addStretch(1)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        summary = QGroupBox("Map Summary")
        s_layout = QFormLayout(summary)
        self.lbl_points = QLabel("0")
        self.lbl_lines = QLabel("0")
        self.lbl_lanelets = QLabel("0")
        self.lbl_areas = QLabel("0")
        self.lbl_connections = QLabel("0")

        s_layout.addRow("Points", self.lbl_points)
        s_layout.addRow("Lines", self.lbl_lines)
        s_layout.addRow("Lanelets", self.lbl_lanelets)
        s_layout.addRow("Areas", self.lbl_areas)
        s_layout.addRow("Connections", self.lbl_connections)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh_summary)
        s_layout.addRow(btn_refresh)

        layout.addWidget(summary)
        layout.addStretch(1)
        return panel

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")

        action_new = QAction("New", self)
        action_open = QAction("Open OSM/XML", self)
        action_save = QAction("Save OSM", self)
        action_exit = QAction("Exit", self)

        action_open.setShortcut(QKeySequence.Open)
        action_save.setShortcut(QKeySequence.Save)

        action_new.triggered.connect(self._new_document)
        action_open.triggered.connect(self._open_xml)
        action_save.triggered.connect(self._save_xml)
        action_exit.triggered.connect(self.close)

        file_menu.addAction(action_new)
        file_menu.addAction(action_open)
        file_menu.addAction(action_save)
        file_menu.addSeparator()
        file_menu.addAction(action_exit)

        edit_menu = self.menuBar().addMenu("Edit")
        action_undo = QAction("Undo", self)
        action_undo.setShortcut(QKeySequence.Undo)
        action_undo.triggered.connect(self._undo)
        edit_menu.addAction(action_undo)

        tool_menu = self.menuBar().addMenu("Tools")
        for text, mode, shortcut in [
            ("Select", "select", "V"),
            ("Point", "point", "P"),
            ("LineString", "line", "L"),
        ]:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, m=mode: self.canvas.set_mode(m))
            tool_menu.addAction(action)

    def _new_document(self) -> None:
        self.canvas.set_vector_map(self.canvas.vector_map.__class__(map_id="map_001"))
        self._refresh_summary()
        self._set_status("New document")

    def _undo(self) -> None:
        if self.canvas.undo_last_action():
            self._refresh_summary()

    def _open_background(self) -> None:
        self._load_sample_background()

    def _load_sample_background(self) -> None:
        img = cv2.imread(str(SAMPLE_IMAGE_PATH), cv2.IMREAD_UNCHANGED)
        if img is None:
            QMessageBox.warning(self, "Image Error", f"Failed to load {SAMPLE_IMAGE_PATH}")
            return

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        self.canvas.load_background(img)
        self._set_status(f"Loaded image: {SAMPLE_IMAGE_PATH.name}")

    def _change_opacity(self, value: int) -> None:
        self.canvas.set_background_opacity(value / 100.0)

    def _save_xml(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, "Save OSM", "", "OSM files (*.osm)")
        if not file_path:
            return
        output_path = Path(file_path)
        if output_path.suffix != ".osm":
            output_path = output_path.with_suffix(".osm")

        try:
            save_map_xml(self.canvas.vector_map, output_path)
            self._set_status(f"Saved OSM: {output_path.name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", str(exc))

    def _open_xml(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Open OSM/XML", "", "OSM/XML files (*.osm *.xml)")
        if not file_path:
            return

        try:
            vector_map = load_map_xml(file_path)
            self.canvas.set_vector_map(vector_map)
            self._refresh_summary()
            self._set_status(f"Loaded map: {Path(file_path).name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open Error", str(exc))

    def _update_subtype_options(self, type_text: str) -> None:
        self.subtype.blockSignals(True)
        self.subtype.clear()
        feature_type = FeatureType(type_text)
        if feature_type == FeatureType.LINE_STRING:
            self.subtype.addItems([item.value for item in LineStringSubtype])
        elif feature_type == FeatureType.LANELET:
            self.subtype.addItems([item.value for item in LaneletSubtype])
        elif feature_type == FeatureType.AREA:
            self.subtype.addItems([item.value for item in AreaSubtype])
        self.subtype.blockSignals(False)
        self._apply_canvas_feature()

    def _apply_canvas_feature(self) -> None:
        feature_type = FeatureType(self.feature_type.currentText())
        if self.subtype.currentText():
            self.canvas.set_feature(feature_type, self.subtype.currentText())

    def _create_lanelet(self) -> None:
        try:
            left_id = int(self.lanelet_left.text().strip())
            right_id = int(self.lanelet_right.text().strip())
            center_text = self.lanelet_center.text().strip()
            center_id = int(center_text) if center_text else None
            subtype = LaneletSubtype(self.subtype.currentText()) if FeatureType(self.feature_type.currentText()) == FeatureType.LANELET else LaneletSubtype.ROAD
            turn_direction = ConnectionType(self.turn_direction.currentText())
            next_id = max((l.id for l in self.canvas.vector_map.lanelets), default=300) + 1
            lanelet = MapLanelet(
                id=next_id,
                subtype=subtype,
                left_boundary_line_id=left_id,
                right_boundary_line_id=right_id,
                centerline_id=center_id,
                turn_direction=turn_direction,
            )
            self.canvas.vector_map.lanelets.append(lanelet)
            self.canvas.register_lanelet_created(lanelet.id)
            self.canvas.redraw_all()
            self._refresh_summary()
            self._set_status(f"Lanelet created: {lanelet.id}")
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Lanelet line IDs must be integers")

    def _create_connection(self) -> None:
        try:
            from_id = int(self.conn_from.text().strip())
            to_id = int(self.conn_to.text().strip())
            conn_type = ConnectionType(self.conn_type.text().strip())
            next_id = max((c.id for c in self.canvas.vector_map.connections), default=400) + 1
            conn = LaneConnection(
                id=next_id,
                from_lanelet_id=from_id,
                to_lanelet_id=to_id,
                connection_type=conn_type,
            )
            self.canvas.vector_map.connections.append(conn)
            self.canvas.register_connection_created(conn.id)
            self._refresh_summary()
            self._set_status(f"Connection created: {conn.id}")
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Connection values are invalid (IDs must be ints, type must match enum)",
            )

    def _refresh_summary(self) -> None:
        vm = self.canvas.vector_map
        self.lbl_points.setText(str(len(vm.points)))
        self.lbl_lines.setText(str(len(vm.lines)))
        self.lbl_lanelets.setText(str(len(vm.lanelets)))
        self.lbl_areas.setText(str(len(vm.areas)))
        self.lbl_connections.setText(str(len(vm.connections)))

    def _set_status(self, text: str) -> None:
        self.status_bar.showMessage(text, 5000)
