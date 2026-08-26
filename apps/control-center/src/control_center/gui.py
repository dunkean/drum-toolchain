"""Optional PySide front end for offline, operator-selected workflows.

The DDrum4 matrix is a selected-file viewer. It has no MIDI, SysEx,
device-discovery, or module-memory operations.
"""
from __future__ import annotations

from pathlib import Path

from .ddrum4_matrix import Ddrum4KitMatrix, MatrixLayer, UNKNOWN, load_kit_matrix
from .service import ControlCenter
from .simulator import RigSimulator, SimulationError
from .campaign import (CaptureRow, Sd3CaptureCampaign, STARTER_ROWS,
                       METALCORE_ELECTRONIC_V1_ADDITIONS)


def launch() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtCore import QProcess
        from PySide6.QtGui import QTextCursor
        from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog,
                                       QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                                       QMainWindow, QMessageBox, QPushButton,
                                       QSplitter, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                                       QTextEdit, QVBoxLayout, QWidget)
    except ImportError as error:
        raise RuntimeError("Install drum-control-center[gui], or use drum-control-center CLI.") from error

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.center = ControlCenter()
            self.matrix: Ddrum4KitMatrix | None = None
            self.report_paths: list[Path] = []
            self.campaign_directory: Path | None = None
            self.campaign_process: QProcess | None = None
            self.setWindowTitle("Drum Control Center — offline")
            tabs = QTabWidget()
            tabs.addTab(self._campaign_workspace(), "SD3 capture campaign")
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
            layout.addWidget(self._simulation_panel())
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
            launch_sd3 = QPushButton("Launch SD3 / DAW host…")
            launch_sd3.setToolTip("Choose the SD3 standalone application or the DAW that hosts SD3. It is launched explicitly and can run alongside this Control Center.")
            launch_sd3.clicked.connect(lambda: self.launch_external_app("SD3 / DAW host")); layout.addWidget(launch_sd3)
            launch_drumgizmo = QPushButton("Launch DrumGizmo host…")
            launch_drumgizmo.setToolTip("Choose the Linux/Windows host or helper used for DrumGizmo. It is launched explicitly.")
            launch_drumgizmo.clicked.connect(lambda: self.launch_external_app("DrumGizmo host")); layout.addWidget(launch_drumgizmo)
            self.application_status = QLabel("Applications launched by this Control Center: none")
            refresh_apps = QPushButton("Refresh application status"); refresh_apps.clicked.connect(self.refresh_application_status)
            stop_apps = QPushButton("Stop applications launched here…"); stop_apps.clicked.connect(self.stop_launched_applications)
            layout.addWidget(self.application_status); layout.addWidget(refresh_apps); layout.addWidget(stop_apps)
            self.log = QTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log)
            holder = QWidget(); holder.setLayout(layout)
            tabs.addTab(holder, "Rig, DDrum4, and applications")
            self.setCentralWidget(tabs)

        def _campaign_workspace(self) -> QWidget:
            workspace = QWidget()
            layout = QVBoxLayout()
            layout.addWidget(QLabel(
                "Start here for a new SD3 kit. Create a versioned campaign, review every articulation, "
                "then run capture, quality review, and DrumGizmo export from this page. Nothing starts MIDI "
                "or audio recording until you explicitly confirm Capture."
            ))
            setup = QGroupBox("1. Campaign identity and SD3 routing")
            setup_layout = QVBoxLayout()
            self.campaign_root = QLineEdit()
            choose_root = QPushButton("Select campaign root…"); choose_root.clicked.connect(self.select_campaign_root)
            row = QHBoxLayout(); row.addWidget(QLabel("Campaign root:")); row.addWidget(self.campaign_root); row.addWidget(choose_root)
            setup_layout.addLayout(row)
            self.campaign_id = QLineEdit(); self.campaign_id.setPlaceholderText("for example: sd3_metal_2026_08")
            self.sd3_preset = QLineEdit(); self.sd3_preset.setPlaceholderText("Exact SD3 MegaKit / preset name")
            self.capture_midi_output = QLineEdit(); self.capture_midi_output.setPlaceholderText("SD3 MIDI input / virtual port name")
            self.capture_audio_input = QLineEdit(); self.capture_audio_input.setPlaceholderText("for example: loopback:OUT 3-4 (BEHRINGER UMC 404HD 192k)")
            self.capture_channels = QLineEdit("left,right")
            for label, field in (("Campaign ID:", self.campaign_id), ("SD3 MegaKit / preset:", self.sd3_preset),
                                 ("MIDI output:", self.capture_midi_output), ("Audio input:", self.capture_audio_input),
                                 ("Capture channels:", self.capture_channels)):
                row = QHBoxLayout(); row.addWidget(QLabel(label)); row.addWidget(field); setup_layout.addLayout(row)
            setup.setLayout(setup_layout); layout.addWidget(setup)

            grid = QGroupBox("2. Complete articulation inventory")
            grid_layout = QVBoxLayout()
            grid_layout.addWidget(QLabel(
                "One row is one SD3 articulation. Review MIDI notes against the loaded kit before creating the campaign. "
                "The starter grid is only a starting point, not proof of your SD3 mapping."
            ))
            self.capture_rows = QTableWidget(0, 6)
            self.capture_rows.setHorizontalHeaderLabels(("Instrument", "Articulation", "MIDI note", "Velocities", "Variations", "Channel"))
            self.capture_rows.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            grid_layout.addWidget(self.capture_rows)
            starter = QPushButton("Load starter grid"); starter.clicked.connect(self.load_starter_grid)
            v1_additions = QPushButton("Add V1 Metalcore/electronic additions")
            v1_additions.setToolTip("Adds the architecture-defined electronic/perc capture rows without replacing the current inventory.")
            v1_additions.clicked.connect(self.add_v1_electronic_additions)
            add_row = QPushButton("Add articulation"); add_row.clicked.connect(self.add_capture_row)
            remove_row = QPushButton("Remove selected articulation"); remove_row.clicked.connect(self.remove_capture_row)
            row = QHBoxLayout(); row.addWidget(starter); row.addWidget(v1_additions); row.addWidget(add_row); row.addWidget(remove_row); grid_layout.addLayout(row)
            grid.setLayout(grid_layout); layout.addWidget(grid)

            actions = QGroupBox("3. Guided campaign actions")
            actions_layout = QVBoxLayout()
            create = QPushButton("Create new campaign and capture session")
            create.setToolTip("Writes campaign.json and capture-session.json only. It never opens MIDI or audio devices.")
            create.clicked.connect(self.create_campaign); actions_layout.addWidget(create)
            open_campaign = QPushButton("Open existing campaign…"); open_campaign.clicked.connect(self.open_campaign); actions_layout.addWidget(open_campaign)
            self.campaign_status = QLabel("No campaign is open."); actions_layout.addWidget(self.campaign_status)
            capture = QPushButton("Capture pending takes…"); capture.clicked.connect(lambda: self.run_campaign_action("capture")); actions_layout.addWidget(capture)
            quality = QPushButton("Run quality review"); quality.clicked.connect(lambda: self.run_campaign_action("audit-quality")); actions_layout.addWidget(quality)
            self.note_map = QLineEdit(); self.note_map.setPlaceholderText("Compiled drumgizmo-midimap.json for export")
            choose_map = QPushButton("Select DrumGizmo note map…"); choose_map.clicked.connect(self.select_note_map)
            row = QHBoxLayout(); row.addWidget(self.note_map); row.addWidget(choose_map); actions_layout.addLayout(row)
            export = QPushButton("Export complete DrumGizmo kit"); export.clicked.connect(lambda: self.run_campaign_action("export-drumgizmo")); actions_layout.addWidget(export)
            verify = QPushButton("Verify DrumGizmo kit"); verify.clicked.connect(lambda: self.run_campaign_action("verify-drumgizmo")); actions_layout.addWidget(verify)
            actions.setLayout(actions_layout); layout.addWidget(actions)

            self.campaign_log = QTextEdit(); self.campaign_log.setReadOnly(True); layout.addWidget(self.campaign_log)
            workspace.setLayout(layout)
            return workspace

        def select_campaign_root(self) -> None:
            directory = QFileDialog.getExistingDirectory(self, "Select parent directory for SD3 campaigns")
            if directory:
                self.campaign_root.setText(directory)

        def select_note_map(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select compiled DrumGizmo note map", "", "JSON files (*.json)")
            if filename:
                self.note_map.setText(filename)

        def add_capture_row(self, row: CaptureRow | None = None) -> None:
            values = row or CaptureRow("instrument", "articulation", 36, (24, 48, 72, 96, 120), 3)
            index = self.capture_rows.rowCount()
            self.capture_rows.insertRow(index)
            cells = (values.instrument, values.articulation, str(values.note),
                     ",".join(str(value) for value in values.velocities), str(values.repetitions), str(values.channel))
            for column, value in enumerate(cells):
                self.capture_rows.setItem(index, column, QTableWidgetItem(value))

        def remove_capture_row(self) -> None:
            selected = self.capture_rows.currentRow()
            if selected >= 0:
                self.capture_rows.removeRow(selected)

        def load_starter_grid(self) -> None:
            if self.capture_rows.rowCount() and QMessageBox.question(
                    self, "Replace inventory", "Replace the current articulation inventory with the editable starter grid?") != QMessageBox.StandardButton.Yes:
                return
            self.capture_rows.setRowCount(0)
            for row in STARTER_ROWS:
                self.add_capture_row(row)
            self.campaign_log.setPlainText(
                "Starter grid loaded. Review every MIDI note and add all kit-specific articulations before creating the campaign."
            )

        def add_v1_electronic_additions(self) -> None:
            existing = {
                (self.capture_rows.item(index, 0).text() if self.capture_rows.item(index, 0) else "",
                 self.capture_rows.item(index, 1).text() if self.capture_rows.item(index, 1) else "",
                 self.capture_rows.item(index, 2).text() if self.capture_rows.item(index, 2) else "")
                for index in range(self.capture_rows.rowCount())
            }
            added = 0
            for row in METALCORE_ELECTRONIC_V1_ADDITIONS:
                key = (row.instrument, row.articulation, str(row.note))
                if key not in existing:
                    self.add_capture_row(row); added += 1
            self.campaign_log.setPlainText(
                f"Added {added} V1 Metalcore/electronic capture rows. Note 49 deliberately reuses the note-48 industrial/trap snare source; it is a routing assignment, not a second raw capture."
            )

        def _rows_from_table(self) -> tuple[CaptureRow, ...]:
            rows: list[CaptureRow] = []
            for index in range(self.capture_rows.rowCount()):
                def cell(column: int) -> str:
                    item = self.capture_rows.item(index, column)
                    return item.text().strip() if item is not None else ""
                try:
                    velocities = tuple(int(value.strip()) for value in cell(3).split(",") if value.strip())
                    rows.append(CaptureRow(cell(0), cell(1), int(cell(2)), velocities, int(cell(4)), int(cell(5))))
                except ValueError as error:
                    raise ValueError(f"invalid articulation row {index + 1}: {error}") from error
            return tuple(rows)

        def _campaign_from_form(self) -> Sd3CaptureCampaign:
            channels = tuple(value.strip() for value in self.capture_channels.text().split(",") if value.strip())
            return Sd3CaptureCampaign(
                identifier=self.campaign_id.text().strip(), sd3_preset=self.sd3_preset.text().strip(),
                midi_output=self.capture_midi_output.text().strip(), audio_input=self.capture_audio_input.text().strip(),
                channels=channels, rows=self._rows_from_table(),
            )

        def _campaign_path_from_form(self) -> Path:
            root = Path(self.campaign_root.text().strip())
            if not self.campaign_root.text().strip():
                raise ValueError("select a campaign root directory")
            return root / self.campaign_id.text().strip()

        def create_campaign(self) -> None:
            try:
                campaign = self._campaign_from_form()
                directory = self._campaign_path_from_form()
                campaign.write_new(directory)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot create SD3 capture campaign", str(error)); return
            self.campaign_directory = directory
            self.campaign_log.setPlainText(
                f"Created {directory}\n\nNext: load the SD3 preset, confirm routing/gain, then choose Capture pending takes. "
                "Capture will ask for a separate confirmation before it sends MIDI or records audio."
            )
            self.refresh_campaign_status()

        def open_campaign(self) -> None:
            directory = QFileDialog.getExistingDirectory(self, "Select a campaign directory containing campaign.json")
            if not directory:
                return
            path = Path(directory)
            try:
                campaign = Sd3CaptureCampaign.read(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot open SD3 capture campaign", str(error)); return
            self.campaign_directory = path
            self.campaign_root.setText(str(path.parent)); self.campaign_id.setText(campaign.identifier)
            self.sd3_preset.setText(campaign.sd3_preset); self.capture_midi_output.setText(campaign.midi_output)
            self.capture_audio_input.setText(campaign.audio_input); self.capture_channels.setText(",".join(campaign.channels))
            self.capture_rows.setRowCount(0)
            for row in campaign.rows:
                self.add_capture_row(row)
            self.campaign_log.setPlainText(f"Opened existing campaign: {path}")
            self.refresh_campaign_status()

        def refresh_campaign_status(self) -> None:
            if self.campaign_directory is None:
                self.campaign_status.setText("No campaign is open."); return
            try:
                progress = Sd3CaptureCampaign.read(self.campaign_directory).progress(self.campaign_directory)
            except (OSError, ValueError) as error:
                self.campaign_status.setText(f"Campaign status unavailable: {error}"); return
            self.campaign_status.setText(
                f"{progress.stage}. Raw takes: {progress.captured_takes}/{progress.total_takes}; "
                f"library: {'yes' if progress.library_exists else 'no'}; "
                f"quality: {'yes' if progress.quality_report_exists else 'no'}; "
                f"DrumGizmo: {'yes' if progress.drumgizmo_export_exists else 'no'}."
            )

        def run_campaign_action(self, action: str) -> None:
            if self.campaign_process is not None and self.campaign_process.state() != QProcess.ProcessState.NotRunning:
                QMessageBox.warning(self, "Campaign action already running", "Wait for the current campaign command to finish."); return
            if self.campaign_directory is None:
                QMessageBox.warning(self, "No campaign", "Create or open an SD3 capture campaign first."); return
            if action == "capture":
                answer = QMessageBox.warning(
                    self, "Confirm SD3 capture",
                    "This will send all pending notes in the saved session to the declared SD3 MIDI input and record the declared audio input. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                note_map = Path(self.note_map.text()) if self.note_map.text().strip() else None
                command = self.center.sampler_command(action, self.campaign_directory, note_map=note_map,
                                                      confirm_capture=action == "capture")
            except ValueError as error:
                QMessageBox.warning(self, "Cannot start campaign action", str(error)); return
            self.campaign_process = QProcess(self)
            self.campaign_process.setProgram(command[0]); self.campaign_process.setArguments(list(command[1:]))
            self.campaign_process.readyReadStandardOutput.connect(self.append_campaign_output)
            self.campaign_process.readyReadStandardError.connect(self.append_campaign_error)
            self.campaign_process.finished.connect(self.campaign_command_finished)
            self.campaign_log.setPlainText("Starting:\n" + " ".join(command) + "\n\n")
            self.campaign_process.start()

        def append_campaign_output(self) -> None:
            if self.campaign_process is not None:
                self.campaign_log.moveCursor(QTextCursor.MoveOperation.End)
                self.campaign_log.insertPlainText(bytes(self.campaign_process.readAllStandardOutput()).decode(errors="replace"))

        def append_campaign_error(self) -> None:
            if self.campaign_process is not None:
                self.campaign_log.moveCursor(QTextCursor.MoveOperation.End)
                self.campaign_log.insertPlainText(bytes(self.campaign_process.readAllStandardError()).decode(errors="replace"))

        def campaign_command_finished(self, exit_code: int, _status: object) -> None:
            self.campaign_log.append(f"\nCampaign command finished with exit code {exit_code}.")
            self.refresh_campaign_status()

        def _simulation_panel(self) -> QGroupBox:
            panel = QGroupBox("Complete chain simulator — no MIDI, VST, or hardware I/O")
            panel.setToolTip("Traces one declared raw pad event through the logical state and all three renderers.")
            layout = QVBoxLayout()
            self.sim_source = QLineEdit(); self.sim_source.setPlaceholderText("edrumin, ddti, ddrum4…")
            self.sim_note = QSpinBox(); self.sim_note.setRange(0, 127)
            self.sim_velocity = QSpinBox(); self.sim_velocity.setRange(1, 127); self.sim_velocity.setValue(100)
            self.sim_scene = QLineEdit(); self.sim_scene.setPlaceholderText("project default")
            row = QHBoxLayout(); row.addWidget(QLabel("Source:")); row.addWidget(self.sim_source)
            row.addWidget(QLabel("Raw note:")); row.addWidget(self.sim_note)
            row.addWidget(QLabel("Velocity:")); row.addWidget(self.sim_velocity)
            row.addWidget(QLabel("Scene:")); row.addWidget(self.sim_scene)
            layout.addLayout(row)
            simulate = QPushButton("Simulate complete chain")
            simulate.clicked.connect(self.simulate_chain); layout.addWidget(simulate)
            panel.setLayout(layout)
            return panel

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

        def simulate_chain(self) -> None:
            if not self.project.text():
                self.log.setPlainText("Select a rig project first."); return
            if not self.sim_source.text():
                self.log.setPlainText("Enter a declared source module for the simulation."); return
            try:
                simulator = RigSimulator.from_path(Path(self.project.text()))
                simulator.set_state(scene=self.sim_scene.text() or None)
                result = simulator.simulate_pad(self.sim_source.text(), self.sim_note.value(), self.sim_velocity.value())
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot simulate drum chain", str(error)); return
            self.log.setPlainText(result.render_text())

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
            self.refresh_application_status()

        def launch_external_app(self, label: str) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, f"Choose {label}", "", "Executables (*.exe);;All files (*)")
            if not filename:
                return
            try:
                result = self.center.launch("external", external=Path(filename))
            except (OSError, RuntimeError, ValueError) as error:
                QMessageBox.warning(self, f"Cannot launch {label}", str(error)); return
            self.log.setPlainText(f"Launched {label}: " + " ".join(result.command))
            self.refresh_application_status()

        def refresh_application_status(self) -> None:
            processes = self.center.launched_processes()
            running = [name for name, is_running in processes if is_running]
            finished = [name for name, is_running in processes if not is_running]
            text = "Applications launched by this Control Center: "
            text += ", ".join(running) if running else "none running"
            if finished:
                text += "; finished: " + ", ".join(finished)
            self.application_status.setText(text)

        def stop_launched_applications(self) -> None:
            running = [name for name, alive in self.center.launched_processes() if alive]
            if not running:
                self.refresh_application_status(); return
            answer = QMessageBox.warning(
                self, "Stop launched applications",
                "Request termination for applications started by this Control Center only?\n\n" + "\n".join(running),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                stopped = self.center.stop_launched_processes()
                self.log.setPlainText("Termination requested for: " + ", ".join(stopped))
                self.refresh_application_status()

    app = QApplication.instance() or QApplication([])
    window = Window(); window.resize(960, 900); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch())
