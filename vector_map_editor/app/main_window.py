from __future__ import annotations

import re
from pathlib import Path

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vector_map_editor.canvas.map_canvas import MapCanvas
from vector_map_editor.io.xml_io import load_map_xml, save_map_xml
from vector_map_editor.model.enums import AreaSubtype, ConnectionType, FeatureType, LaneletSubtype, LineStringSubtype
from vector_map_editor.model.geometry import ASSIST_RESAMPLE_SPACING_M
from vector_map_editor.model.map_data import LaneConnection, MapLanelet


SAMPLE_IMAGE_PATH = Path(__file__).resolve().parents[2] / "sample_image" / "lane.png"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vector Map Editor (OSM XML)")
        self.resize(1400, 860)

        self.canvas = MapCanvas(
            on_status=self._set_status,
            on_changed=self._refresh_summary,
            on_selected=self._handle_canvas_selection,
            on_subtype_requested=self._select_subtype_for_feature,
        )
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

        edit_tab = QWidget()
        edit_layout = QVBoxLayout(edit_tab)

        class_box = QGroupBox("Class")
        class_layout = QFormLayout(class_box)
        self.feature_type = QComboBox()
        self.feature_type.addItems([item.value for item in FeatureType])
        self.feature_type.currentTextChanged.connect(self._apply_canvas_feature_type)
        class_layout.addRow("Type", self.feature_type)
        self._apply_canvas_feature_type()

        line_box = QGroupBox("LineString from Points")
        line_layout = QFormLayout(line_box)
        self.line_point_ids = QLineEdit()
        self.line_point_ids.setPlaceholderText("1, 2, 3")
        btn_line_from_points = QPushButton("Create LineString")
        btn_line_from_points.clicked.connect(self._create_line_from_point_ids)
        line_layout.addRow("Point IDs", self.line_point_ids)
        line_layout.addRow(btn_line_from_points)

        lanelet_box = QGroupBox("Lanelet")
        lanelet_layout = QFormLayout(lanelet_box)
        self.lanelet_left = QLineEdit()
        self.lanelet_right = QLineEdit()
        self.lanelet_center = QLineEdit()
        self.lanelet_auto_center = QCheckBox("Auto centerline")
        self.lanelet_auto_center.setChecked(True)
        self.lanelet_is_virtual = QCheckBox("Virtual lanelet")
        btn_lanelet = QPushButton("Create Lanelet")
        btn_lanelet.clicked.connect(self._create_lanelet)

        lanelet_layout.addRow("Left line ID", self._line_pick_row(self.lanelet_left, "lanelet_left"))
        lanelet_layout.addRow("Right line ID", self._line_pick_row(self.lanelet_right, "lanelet_right"))
        lanelet_layout.addRow("Centerline ID", self._line_pick_row(self.lanelet_center, "lanelet_center"))
        lanelet_layout.addRow(self.lanelet_auto_center)
        lanelet_layout.addRow(self.lanelet_is_virtual)
        lanelet_layout.addRow(btn_lanelet)

        conn_box = QGroupBox("Connection")
        conn_layout = QFormLayout(conn_box)
        self.conn_from = QLineEdit()
        self.conn_to = QLineEdit()
        self.conn_type = QComboBox()
        self.conn_type.addItems([item.value for item in ConnectionType])
        self.conn_type.setCurrentText(ConnectionType.STRAIGHT.value)
        btn_conn = QPushButton("Create Connection")
        btn_conn.clicked.connect(self._create_connection)

        conn_layout.addRow("From lanelet ID", self._lanelet_pick_row(self.conn_from, "conn_from"))
        conn_layout.addRow("To lanelet ID", self._lanelet_pick_row(self.conn_to, "conn_to"))
        conn_layout.addRow("Type", self.conn_type)
        conn_layout.addRow(btn_conn)

        edit_layout.addWidget(class_box)
        edit_layout.addWidget(line_box)
        edit_layout.addWidget(lanelet_box)
        edit_layout.addWidget(conn_box)
        edit_layout.addStretch(1)

        assist_tab = QWidget()
        assist_layout = QVBoxLayout(assist_tab)
        assist_box = QGroupBox("White-pixel Assist")
        assist_form = QFormLayout(assist_box)
        self.assist_enabled = QCheckBox("Enable")
        self.assist_enabled.toggled.connect(self.canvas.set_assist_enabled)
        self.resample_line_id = QLineEdit()
        btn_resample = QPushButton("Resample LineString")
        btn_resample.clicked.connect(self._resample_line_string)
        self.infer_center_lanelet_id = QLineEdit()
        btn_infer_center = QPushButton("Infer Center Line")
        btn_infer_center.clicked.connect(self._infer_center_line)
        assist_form.addRow("Assist", self.assist_enabled)
        assist_form.addRow("LineString ID", self._line_pick_row(self.resample_line_id, "resample_line"))
        assist_form.addRow(btn_resample)
        assist_form.addRow("Lanelet ID", self._lanelet_pick_row(self.infer_center_lanelet_id, "infer_center_lanelet"))
        assist_form.addRow(btn_infer_center)
        assist_layout.addWidget(assist_box)
        assist_layout.addStretch(1)

        tabs = QTabWidget()
        tabs.addTab(edit_tab, "Edit")
        tabs.addTab(assist_tab, "Assist")

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
        layout.addWidget(tabs)
        layout.addWidget(image_box)
        layout.addStretch(1)

        return panel

    def _line_pick_row(self, editor: QLineEdit, target: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(editor)
        btn_pick = QPushButton("Pick")
        btn_pick.clicked.connect(lambda: self._start_canvas_pick(target))
        layout.addWidget(btn_pick)
        return row

    def _lanelet_pick_row(self, editor: QLineEdit, target: str) -> QWidget:
        return self._line_pick_row(editor, target)

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

    def _apply_canvas_feature_type(self, _type_text: str | None = None) -> None:
        feature_type = FeatureType(self.feature_type.currentText())
        self.canvas.set_feature_type(feature_type)

    def _select_subtype_for_feature(self, feature_type: FeatureType) -> str | None:
        options_by_type = {
            FeatureType.LINE_STRING: [item.value for item in LineStringSubtype],
            FeatureType.LANELET: [item.value for item in LaneletSubtype],
            FeatureType.AREA: [item.value for item in AreaSubtype],
        }
        options = options_by_type[feature_type]
        subtype, ok = QInputDialog.getItem(
            self,
            "Select subtype",
            f"{feature_type.value} subtype",
            options,
            0,
            False,
        )
        if not ok:
            return None
        return subtype

    def _start_canvas_pick(self, target: str) -> None:
        self.canvas.set_selection_target(target)
        self._set_status("Click an item on the canvas")

    def _handle_canvas_selection(self, target: str, item_id: int) -> None:
        editors = {
            "lanelet_left": self.lanelet_left,
            "lanelet_right": self.lanelet_right,
            "lanelet_center": self.lanelet_center,
            "resample_line": self.resample_line_id,
            "conn_from": self.conn_from,
            "conn_to": self.conn_to,
            "infer_center_lanelet": self.infer_center_lanelet_id,
        }
        editor = editors.get(target)
        if editor is None:
            return
        editor.setText(str(item_id))
        self._set_status(f"Selected ID: {item_id}")

    def _create_line_from_point_ids(self) -> None:
        try:
            point_ids = [
                int(part)
                for part in re.split(r"[\s,]+", self.line_point_ids.text().strip())
                if part
            ]
            subtype_text = self._select_subtype_for_feature(FeatureType.LINE_STRING)
            if subtype_text is None:
                self._set_status("LineString creation canceled")
                return
            subtype = LineStringSubtype(subtype_text)
            self.canvas.create_line_from_point_ids(point_ids, subtype)
            self._refresh_summary()
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Point IDs must be integers")
        except RuntimeError as exc:
            QMessageBox.warning(self, "LineString Error", str(exc))

    def _create_lanelet(self) -> None:
        try:
            left_id = int(self.lanelet_left.text().strip())
            right_id = int(self.lanelet_right.text().strip())
            center_text = self.lanelet_center.text().strip()
            center_id = int(center_text) if center_text else None
            if not self.canvas.line_exists(left_id):
                raise RuntimeError(f"Left LineString not found: {left_id}")
            if not self.canvas.line_exists(right_id):
                raise RuntimeError(f"Right LineString not found: {right_id}")
            if center_id is not None and not self.canvas.line_exists(center_id):
                raise RuntimeError(f"Centerline LineString not found: {center_id}")
            subtype_text = self._select_subtype_for_feature(FeatureType.LANELET)
            if subtype_text is None:
                self._set_status("Lanelet creation canceled")
                return
            subtype = LaneletSubtype(subtype_text)
            next_id = max((l.id for l in self.canvas.vector_map.lanelets), default=300) + 1
            lanelet = MapLanelet(
                id=next_id,
                subtype=subtype,
                left_boundary_line_id=left_id,
                right_boundary_line_id=right_id,
                centerline_id=center_id,
                is_virtual=self.lanelet_is_virtual.isChecked(),
            )
            self.canvas.vector_map.lanelets.append(lanelet)
            self.canvas.apply_lanelet_boundary_semantics(left_id, right_id, center_id)
            self.canvas.register_lanelet_created(lanelet.id)
            if center_id is None and self.lanelet_auto_center.isChecked():
                self.canvas.infer_center_line(lanelet.id, spacing_m=ASSIST_RESAMPLE_SPACING_M)
            self.canvas.redraw_all()
            self._refresh_summary()
            self._set_status(f"Lanelet created: {lanelet.id}")
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Lanelet line IDs must be integers")
        except RuntimeError as exc:
            QMessageBox.warning(self, "Lanelet Error", str(exc))

    def _create_connection(self) -> None:
        try:
            from_id = int(self.conn_from.text().strip())
            to_id = int(self.conn_to.text().strip())
            if not self.canvas.lanelet_exists(from_id):
                raise RuntimeError(f"From Lanelet not found: {from_id}")
            if not self.canvas.lanelet_exists(to_id):
                raise RuntimeError(f"To Lanelet not found: {to_id}")
            conn_type = ConnectionType(self.conn_type.currentText())
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
        except RuntimeError as exc:
            QMessageBox.warning(self, "Connection Error", str(exc))

    def _resample_line_string(self) -> None:
        try:
            line_id = int(self.resample_line_id.text().strip())
            self.canvas.resample_line_string(line_id, spacing_m=ASSIST_RESAMPLE_SPACING_M)
            self._refresh_summary()
        except ValueError:
            QMessageBox.warning(self, "Input Error", "LineString ID must be an integer")
        except RuntimeError as exc:
            QMessageBox.warning(self, "Resample Error", str(exc))

    def _infer_center_line(self) -> None:
        try:
            lanelet_id = int(self.infer_center_lanelet_id.text().strip())
            self.canvas.infer_center_line(lanelet_id, spacing_m=ASSIST_RESAMPLE_SPACING_M)
            self._refresh_summary()
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Lanelet ID must be an integer")
        except RuntimeError as exc:
            QMessageBox.warning(self, "Center Line Error", str(exc))

    def _refresh_summary(self) -> None:
        vm = self.canvas.vector_map
        self.lbl_points.setText(str(len(vm.points)))
        self.lbl_lines.setText(str(len(vm.lines)))
        self.lbl_lanelets.setText(str(len(vm.lanelets)))
        self.lbl_areas.setText(str(len(vm.areas)))
        self.lbl_connections.setText(str(len(vm.connections)))

    def _set_status(self, text: str) -> None:
        self.status_bar.showMessage(text, 5000)
