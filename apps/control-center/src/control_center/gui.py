"""Optional PySide front end for offline, operator-selected workflows.

The DDrum4 matrix is a selected-file viewer. It has no MIDI, SysEx,
device-discovery, or module-memory operations.
"""
from __future__ import annotations

from pathlib import Path

from .ddrum4_matrix import Ddrum4KitMatrix, MatrixLayer, UNKNOWN, load_kit_matrix
from .service import ControlCenter


def launch() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog,
                                       QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                                       QMainWindow, QMessageBox, QPushButton,
                                       QSplitter, QTableWidget, QTableWidgetItem,
                                       QTextEdit, QVBoxLayout, QWidget)
    except ImportError as error:
        raise RuntimeError("Install drum-control-center[gui], or use drum-control-center CLI.") from error

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.center = ControlCenter()
            self.matrix: Ddrum4KitMatrix | None = None
            self.report_paths: list[Path] = []
            self.setWindowTitle("Drum Control Center — offline")
            layout = QVBoxLayout()
            self.project = QLineEdit()
            choose = QPushButton("Select rig project"); choose.clicked.connect(self.select_project)
            row = QHBoxLayout(); row.addWidget(QLabel("Rig project:")); row.addWidget(self.project); row.addWidget(choose)
            layout.addLayout(row)
            self.output = QLineEdit()
            choose_output = QPushButton("Select output"); choose_output.clicked.connect(self.select_output)
            output_row = QHBoxLayout(); output_row.addWidget(QLabel("Compile output:")); output_row.addWidget(self.output); output_row.addWidget(choose_output)
            layout.addLayout(output_row)
            for action in ("validate", "report"):
                button = QPushButton(action.title())
                button.clicked.connect(lambda _=False, a=action: self.run(a))
                layout.addWidget(button)
            compile_button = QPushButton("Compile offline artifacts"); compile_button.clicked.connect(self.compile_project)
            layout.addWidget(compile_button)
            layout.addWidget(self._matrix_panel())
            launch_ddti = QPushButton("Launch DDTi Editor")
            launch_ddti.setToolTip("Explicitly launches the existing DDTi editor; it does not connect to MIDI here.")
            launch_ddti.clicked.connect(lambda: self.launch_target("ddti")); layout.addWidget(launch_ddti)
            launch_ui = QPushButton("Launch ddrum4UI…")
            launch_ui.setToolTip("Choose ddrum4UI explicitly. No desktop automation is performed.")
            launch_ui.clicked.connect(lambda: self.launch_target("ddrum4ui")); layout.addWidget(launch_ui)
            launch_converter = QPushButton("Launch converter…")
            launch_converter.setToolTip("Choose the already-built converter executable explicitly.")
            launch_converter.clicked.connect(lambda: self.launch_target("converter")); layout.addWidget(launch_converter)
            self.log = QTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log)
            holder = QWidget(); holder.setLayout(layout); self.setCentralWidget(holder)

        def _matrix_panel(self) -> QGroupBox:
            panel = QGroupBox("DDrum4 kit matrix — selected local files only")
            panel.setToolTip("Read-only manifest/report inspection. No MIDI, SysEx, device discovery, or module-memory query.")
            layout = QVBoxLayout()
            self.manifest = QLineEdit()
            manifest_button = QPushButton("Select manifest…"); manifest_button.clicked.connect(self.select_manifest)
            row = QHBoxLayout(); row.addWidget(QLabel("Manifest:")); row.addWidget(self.manifest); row.addWidget(manifest_button)
            layout.addLayout(row)
            self.reports = QLineEdit(); self.reports.setReadOnly(True)
            reports_button = QPushButton("Select reports…"); reports_button.clicked.connect(self.select_reports)
            row = QHBoxLayout(); row.addWidget(QLabel("Reports:")); row.addWidget(self.reports); row.addWidget(reports_button)
            layout.addLayout(row)
            load = QPushButton("Load 10-slot matrix"); load.clicked.connect(self.load_matrix); layout.addWidget(load)
            self.matrix_table = QTableWidget(10, 8)
            self.matrix_table.setHorizontalHeaderLabels(("Slot", "Sound ID", "Source", "Layers", "Encoded blocks", "MEM.LEFT Δ", "Status", "Provenance"))
            self.matrix_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.matrix_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.matrix_table.itemSelectionChanged.connect(self.show_layers)
            self.layer_table = QTableWidget(0, 6)
            self.layer_table.setHorizontalHeaderLabels(("Layer", "WAV", "Resource", "Source", "Status", "Provenance"))
            self.layer_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.layer_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            split = QSplitter(Qt.Orientation.Vertical); split.addWidget(self.matrix_table); split.addWidget(self.layer_table); layout.addWidget(split)
            self.audition = QPushButton("Audition selected WAV")
            self.audition.setToolTip("Explicitly opens the selected local WAV in the operating system default player.")
            self.audition.clicked.connect(self.audition_layer); layout.addWidget(self.audition)
            panel.setLayout(layout)
            return panel

        @staticmethod
        def _cell(value: object, unknown: str = UNKNOWN) -> QTableWidgetItem:
            return QTableWidgetItem(unknown if value is None or value == "" else str(value))

        def select_project(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select rig project", "", "Rig projects (*.yaml *.yml)")
            if filename: self.project.setText(filename)

        def select_output(self) -> None:
            directory = QFileDialog.getExistingDirectory(self, "Select empty compiler output directory")
            if directory: self.output.setText(directory)

        def select_manifest(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select DDrum4 kit manifest", "", "Manifest files (*.yaml *.yml *.json)")
            if filename: self.manifest.setText(filename)

        def select_reports(self) -> None:
            filenames, _ = QFileDialog.getOpenFileNames(self, "Select optional bank-builder reports", "", "Report files (*.yaml *.yml *.json)")
            if filenames:
                self.report_paths = [Path(filename) for filename in filenames]
                self.reports.setText("; ".join(str(path) for path in self.report_paths))

        def load_matrix(self) -> None:
            if not self.manifest.text():
                self.log.setPlainText("Select a DDrum4 manifest first."); return
            try:
                self.matrix = load_kit_matrix(Path(self.manifest.text()), self.report_paths)
            except ValueError as error:
                QMessageBox.warning(self, "Cannot load DDrum4 matrix", str(error)); return
            for row, sound in enumerate(self.matrix.sounds):
                values = (sound.slot, sound.sound_id or "missing", sound.source, sound.layer_count,
                          sound.encoded_blocks, sound.mem_left_delta_blocks, sound.status, sound.provenance)
                for column, value in enumerate(values): self.matrix_table.setItem(row, column, self._cell(value))
            self.layer_table.setRowCount(0)
            self.log.setPlainText("Loaded selected manifest and reports. MEM.LEFT is 'unknown' unless explicitly reported.")

        def show_layers(self) -> None:
            if self.matrix is None or self.matrix_table.currentRow() < 0: return
            layers = self.matrix.sound(self.matrix_table.currentRow() + 1).layers
            self.layer_table.setRowCount(len(layers))
            for row, layer in enumerate(layers):
                values = (layer.index, layer.wav, layer.resource_status, layer.source, layer.status, layer.provenance)
                for column, value in enumerate(values): self.layer_table.setItem(row, column, self._cell(value))

        def audition_layer(self) -> None:
            if self.matrix is None or self.matrix_table.currentRow() < 0 or self.layer_table.currentRow() < 0:
                self.log.setPlainText("Select a matrix slot and a declared WAV layer first."); return
            layer: MatrixLayer = self.matrix.sound(self.matrix_table.currentRow() + 1).layers[self.layer_table.currentRow()]
            if layer.wav is None:
                self.log.setPlainText("The selected layer has no declared WAV file."); return
            try:
                result = self.center.audition_wav(layer.wav)
            except (FileNotFoundError, ValueError) as error:
                QMessageBox.warning(self, "Cannot audition WAV", str(error)); return
            self.log.setPlainText("Opened selected WAV explicitly: " + " ".join(result.command))

        def run(self, action: str) -> None:
            if not self.project.text(): self.log.setPlainText("Select a rig project first."); return
            result = self.center.run_rig(action, Path(self.project.text()))
            self.log.setPlainText(" ".join(result.command) + "\n\n" + result.text)

        def compile_project(self) -> None:
            if not self.project.text() or not self.output.text():
                self.log.setPlainText("Select a rig project and an explicit output directory first."); return
            result = self.center.run_rig("compile", Path(self.project.text()), output=Path(self.output.text()))
            self.log.setPlainText(" ".join(result.command) + "\n\n" + result.text)

        def launch_target(self, target: str) -> None:
            if target == "ddti": result = self.center.launch("ddti")
            else:
                label = "Choose ddrum4UI" if target == "ddrum4ui" else "Choose converter executable"
                filename, _ = QFileDialog.getOpenFileName(self, label, "", "Executables (*.exe);;All files (*)")
                if not filename: return
                path = Path(filename); runtime_profile = None
                if target == "converter":
                    runtime, _ = QFileDialog.getOpenFileName(self, "Select compiled runtime-profile.yaml", self.output.text(), "Runtime profile (runtime-profile.yaml);;YAML (*.yaml *.yml)")
                    if not runtime: return
                    runtime_profile = Path(runtime)
                    renderer, accepted = QInputDialog.getItem(self, "Choose renderer", "Renderer", ("sd3", "drumgizmo"), 0, False)
                    if not accepted: return
                result = self.center.launch(target, ddrum4ui=path if target == "ddrum4ui" else None,
                                            converter=path if target == "converter" else None, runtime_profile=runtime_profile,
                                            renderer_target=renderer if target == "converter" else "sd3")
            self.log.setPlainText("Launched explicitly: " + " ".join(result.command))

    app = QApplication.instance() or QApplication([])
    window = Window(); window.resize(960, 900); window.show()
    return app.exec()
