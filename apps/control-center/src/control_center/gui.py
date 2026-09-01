"""Optional PySide front end for offline, operator-selected workflows.

The DDrum4 matrix is a selected-file viewer. It has no MIDI, SysEx,
device-discovery, or module-memory operations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import yaml

from .ddrum4_matrix import Ddrum4KitMatrix, MatrixLayer, UNKNOWN, load_kit_matrix
from .service import ControlCenter, active_sd3_window_titles
from .simulator import RigSimulator, SimulationError
from .virtual_kit import build_virtual_kit
from .campaign import (CaptureRow, Sd3CaptureCampaign, STARTER_ROWS, capture_rows_from_megakit_plan,
                       fingerprint_sd3_preset, METALCORE_ELECTRONIC_V1_ADDITIONS)
from .live_measurement import (HihatCalibration, LiveMeasurementCampaign, PressureConfirmation,
                               discover_midi_port_inventory)
from midi_lab.ddrum4_programs import decode_ddrum4_program


def format_measurement_review_row(row: dict[str, object]) -> str:
    """Render one measured route without assuming that every event is a note."""
    identifier = str(row.get("id", "unknown"))
    status = str(row.get("status", "unknown"))
    if status != "observed":
        return f"{status.upper()} {identifier} — {row.get('reason', 'review required')}"
    channel = row.get("channel", "?")
    message_type = row.get("message_type")
    if message_type == "note":
        address = f"Note {row.get('note', row.get('data1', '?'))}"
    elif message_type == "note_range":
        measured = row.get("note_range", ["?", "?"])
        if not isinstance(measured, list) or len(measured) != 2:
            measured = ["?", "?"]
        address = f"Notes {measured[0]}..{measured[1]} ({len(row.get('observed_notes', []))} positions)"
    elif message_type == "cc":
        values = row.get("observed_values", [])
        value_text = ""
        if isinstance(values, list) and values:
            value_text = f"; values {min(values)}..{max(values)}"
        address = f"CC{row.get('data1', '?')}{value_text}"
    elif message_type == "poly_aftertouch":
        address = f"Poly-aftertouch note {row.get('data1', '?')}"
    elif message_type == "program_change":
        address = f"Program {row.get('data1', '?')}"
    else:
        address = f"data1 {row.get('data1', '?')}"
    return f"PASS {identifier} — C{channel} {address}"


def launch() -> int:
    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtCore import QProcess
        from PySide6.QtGui import QTextCursor
        from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog,
                                       QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                                       QHeaderView, QMainWindow, QMessageBox, QPushButton,
                                       QScrollArea, QSlider, QSplitter, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                                       QTextEdit, QVBoxLayout, QWidget)
    except ImportError as error:
        raise RuntimeError("Install drum-control-center[gui], or use drum-control-center CLI.") from error

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.center = ControlCenter()
            self._visual_project_syncing = False
            self._active_simulator: RigSimulator | None = None
            self._active_simulator_path: Path | None = None
            self.matrix: Ddrum4KitMatrix | None = None
            self._studio_rows = []
            self._studio_velocity_sliders: list[QSlider] = []
            self._studio_events: list[dict[str, object]] = []
            self._studio_variable_controls: dict[str, QSpinBox | QComboBox] = {}
            self._studio_state_syncing = False
            self.report_paths: list[Path] = []
            self.campaign_directory: Path | None = None
            self.campaign_process: QProcess | None = None
            self.live_measurement_directory: Path | None = None
            self.live_measurement_process: QProcess | None = None
            self.live_measurement_trace_id: str | None = None
            self.live_measurement_operation = ""
            self.live_measurement_log = ""
            self.setWindowTitle("Drum Control Center — offline")
            tabs = QTabWidget()
            tabs.addTab(self._project_editor_workspace(), "Kit, MIDI map, and palettes")
            tabs.addTab(self._virtual_kit_workspace(), "Virtual kit & simulator")
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
            self.ddti_base_dump = QLineEdit()
            self.ddti_base_dump.setPlaceholderText("Optional complete DDTi .syx dump; required for a transferable staged preset")
            choose_ddti_dump = QPushButton("Select DDTi dump…")
            choose_ddti_dump.clicked.connect(self.select_ddti_base_dump)
            dump_row = QHBoxLayout(); dump_row.addWidget(QLabel("DDTi base dump:")); dump_row.addWidget(self.ddti_base_dump); dump_row.addWidget(choose_ddti_dump)
            layout.addLayout(dump_row)
            self.ddti_input_layout = QLineEdit(str(
                Path(__file__).resolve().parents[4] / "profiles" / "physical" / "greg-hybrid-ddti-layout.yaml"
            ))
            self.ddti_input_layout.setPlaceholderText("Explicit DDTi Input/Tip/Ring layout")
            choose_ddti_layout = QPushButton("Select DDTi layout…")
            choose_ddti_layout.clicked.connect(self.select_ddti_input_layout)
            layout_row = QHBoxLayout(); layout_row.addWidget(QLabel("DDTi input layout:")); layout_row.addWidget(self.ddti_input_layout); layout_row.addWidget(choose_ddti_layout)
            layout.addLayout(layout_row)
            self.replace_compile_output = QCheckBox("Replace generated build artifacts")
            self.replace_compile_output.setToolTip("Allows the compiler to replace its generated output directory; source profiles and captures are never deleted.")
            layout.addWidget(self.replace_compile_output)
            for action in ("validate", "report"):
                button = QPushButton(action.title())
                button.clicked.connect(lambda _=False, a=action: self.run(a))
                layout.addWidget(button)
            compile_button = QPushButton("Compile offline artifacts"); compile_button.clicked.connect(self.compile_project)
            layout.addWidget(compile_button)
            stage_ddti = QPushButton("Stage DDTi notes from compiled role template…")
            stage_ddti.setToolTip("Creates a new reviewable .syx from the receive-only base dump, generated note roles, and explicit input layout. It never opens MIDI.")
            stage_ddti.clicked.connect(self.stage_ddti_from_build)
            layout.addWidget(stage_ddti)
            layout.addWidget(self._simulation_panel())
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
            if os.environ.get("DRUM_CONTROL_CENTER_PROJECT", "").strip():
                QTimer.singleShot(0, self.load_default_workspace)

        def load_default_workspace(self) -> None:
            """Load the launcher-selected project and its simulator without hardware I/O."""
            project = os.environ.get("DRUM_CONTROL_CENTER_PROJECT", "").strip()
            if not project:
                return
            self.editor_project.setText(project)
            self.project.setText(project)
            output = os.environ.get("DRUM_CONTROL_CENTER_OUTPUT", "").strip()
            if output:
                self.output.setText(output)
            self.load_editor_project()
            if self.editor_project.text().strip() == project:
                self.load_virtual_kit_workspace()

        def _project_editor_workspace(self) -> QWidget:
            """Editable source-of-truth project document, always validated before save.

            The rig project deliberately contains the kit map, scene/VP state,
            renderer notes and native actions in one file.  This prevents the
            DDrum4 palette and PC renderer from silently drifting apart.
            """
            workspace = QWidget()
            layout = QVBoxLayout()
            layout.addWidget(QLabel(
                "One project is the source of truth for sources, pads, logical sounds, DDrum4 NOTE P routes, "
                "Scenes/Virtual Palettes, SD3/DrumGizmo maps, and declared DDrum4 Program/SysEx actions. "
                "Save validates the complete project first; it never opens MIDI or writes hardware."
            ))
            self.editor_project = QLineEdit()
            choose = QPushButton("Open rig project…"); choose.clicked.connect(self.select_editor_project)
            load = QPushButton("Load"); load.clicked.connect(self.load_editor_project)
            row = QHBoxLayout(); row.addWidget(QLabel("Project:")); row.addWidget(self.editor_project); row.addWidget(choose); row.addWidget(load)
            layout.addLayout(row)
            editor_tabs = QTabWidget()
            self.visual_sounds = QTableWidget(0, 9)
            self.visual_sounds.setHorizontalHeaderLabels((
                "Logical sound", "DDrum4 note", "DDrum4 bank slot / NOTE P",
                "SD3 channel", "SD3 note", "DrumGizmo channel", "DrumGizmo note",
                "DrumGizmo instrument", "DrumGizmo articulation",
            ))
            self.visual_sounds.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_sounds.itemChanged.connect(lambda _: self._sync_visual_project("sounds"))
            self.visual_sounds.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.visual_sounds.horizontalHeader().setStretchLastSection(True)
            sounds_page = QWidget(); sounds_layout = QVBoxLayout(); sounds_layout.addWidget(self.visual_sounds)
            sound_actions = QHBoxLayout()
            add_sound = QPushButton("Add logical sound…"); add_sound.clicked.connect(self.add_visual_sound)
            duplicate_sound = QPushButton("Duplicate selected sound…"); duplicate_sound.clicked.connect(self.duplicate_visual_sound)
            remove_sound = QPushButton("Delete selected sound…"); remove_sound.clicked.connect(self.delete_visual_sound)
            for button in (add_sound, duplicate_sound, remove_sound):
                sound_actions.addWidget(button)
            sound_actions.addStretch(1); sounds_layout.addLayout(sound_actions)
            sounds_page.setLayout(sounds_layout)
            editor_tabs.addTab(sounds_page, "Sounds and renderer map")
            self.visual_routes = QTableWidget(0, 3)
            self.visual_routes.setHorizontalHeaderLabels(("Scene", "Physical pad / articulation", "Logical sound"))
            self.visual_routes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_routes.itemChanged.connect(lambda _: self._sync_visual_project("routes"))
            routes_page = QWidget(); routes_layout = QVBoxLayout(); routes_layout.addWidget(self.visual_routes)
            scene_actions = QHBoxLayout()
            add_scene = QPushButton("Add scene…"); add_scene.clicked.connect(self.add_visual_scene)
            duplicate_scene = QPushButton("Duplicate selected scene…"); duplicate_scene.clicked.connect(self.duplicate_visual_scene)
            rename_scene = QPushButton("Rename selected scene…"); rename_scene.clicked.connect(self.rename_visual_scene)
            remove_scene = QPushButton("Delete selected scene…"); remove_scene.clicked.connect(self.delete_visual_scene)
            for button in (add_scene, duplicate_scene, rename_scene, remove_scene):
                scene_actions.addWidget(button)
            scene_actions.addStretch(1); routes_layout.addLayout(scene_actions)
            routes_page.setLayout(routes_layout)
            editor_tabs.addTab(routes_page, "Scenes and palettes")
            self.visual_actions = QTableWidget(0, 6)
            self.visual_actions.setHorizontalHeaderLabels(("Scene", "Native action", "Channel", "Program", "Status", "Description"))
            self.visual_actions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_actions.itemChanged.connect(lambda _: self._sync_visual_project("actions"))
            actions_page = QWidget(); actions_layout = QVBoxLayout(); actions_layout.addWidget(self.visual_actions)
            action_buttons = QHBoxLayout()
            add_action = QPushButton("Add DDrum4 Program action…"); add_action.clicked.connect(self.add_visual_action)
            remove_action = QPushButton("Delete selected action…"); remove_action.clicked.connect(self.delete_visual_action)
            action_buttons.addWidget(add_action); action_buttons.addWidget(remove_action); action_buttons.addStretch(1)
            actions_layout.addLayout(action_buttons); actions_page.setLayout(actions_layout)
            editor_tabs.addTab(actions_page, "DDrum4 kit / palette actions")
            self.visual_native_controls = QTableWidget(0, 7)
            self.visual_native_controls.setHorizontalHeaderLabels((
                "Control", "Source", "Channel", "MIDI type", "Address", "Logical target", "Value",
            ))
            self.visual_native_controls.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_native_controls.itemChanged.connect(lambda _: self._sync_visual_project("native"))
            self.visual_native_controls.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.visual_native_controls.horizontalHeader().setStretchLastSection(True)
            native_page = QWidget(); native_layout = QVBoxLayout()
            native_layout.addWidget(QLabel(
                "Exact Program/Palette messages observed from the DDrum4 panel and their Scene/VP meaning. "
                "Decoder inputs are never echoed back to the module."
            ))
            native_layout.addWidget(self.visual_native_controls)
            native_buttons = QHBoxLayout()
            add_native = QPushButton("Add panel control…"); add_native.clicked.connect(self.add_visual_native_control)
            remove_native = QPushButton("Delete selected control…"); remove_native.clicked.connect(self.delete_visual_native_control)
            native_buttons.addWidget(add_native); native_buttons.addWidget(remove_native); native_buttons.addStretch(1)
            native_layout.addLayout(native_buttons); native_page.setLayout(native_layout)
            editor_tabs.addTab(native_page, "DDrum4 panel controls")
            self.visual_sources = QTableWidget(0, 4)
            self.visual_sources.setHorizontalHeaderLabels(("Module", "Endpoint", "Raw channel", "Primary input"))
            self.visual_sources.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_sources.itemChanged.connect(lambda _: self._sync_visual_project("sources"))
            self.visual_physical = QTableWidget(0, 6)
            self.visual_physical.setHorizontalHeaderLabels((
                "Physical event", "Module", "Pad", "Zone", "MIDI type", "Raw note",
            ))
            self.visual_physical.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_physical.itemChanged.connect(lambda _: self._sync_visual_project("physical"))
            self.visual_expressions = QTableWidget(0, 7)
            self.visual_expressions.setHorizontalHeaderLabels((
                "Module", "Physical event", "Expression", "Raw control", "DDrum4", "SD3", "DrumGizmo",
            ))
            self.visual_expressions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.visual_expressions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            module_page = QWidget(); module_layout = QVBoxLayout()
            module_layout.addWidget(QLabel("Module endpoints and channels")); module_layout.addWidget(self.visual_sources)
            module_layout.addWidget(QLabel("Physical wiring and raw Note-On decoder")); module_layout.addWidget(self.visual_physical)
            module_layout.addWidget(QLabel("Continuous controls and renderer readiness")); module_layout.addWidget(self.visual_expressions)
            module_page.setLayout(module_layout)
            editor_tabs.addTab(module_page, "Pads, modules and MIDI map")
            editor_tabs.addTab(self._matrix_panel(), "DDrum4 bank — slots, layers, variations")
            self.project_document = QTextEdit(); self.project_document.setAcceptRichText(False)
            self.project_document.setPlaceholderText("Advanced YAML source.")
            editor_tabs.addTab(self.project_document, "Advanced YAML")
            readiness_page = QWidget(); readiness_layout = QVBoxLayout()
            readiness_layout.addWidget(QLabel(
                "The readiness inspector validates and compiles only a temporary local copy of the YAML shown above; "
                "it never opens MIDI or changes hardware. The dedicated validation actions below state explicitly whether "
                "they are receive-only or transmit a bounded diagnostic sequence."
            ))
            self.editor_readiness = QTextEdit(); self.editor_readiness.setReadOnly(True)
            self.editor_readiness.setPlainText("Load a rig project, then inspect readiness.")
            inspect_readiness = QPushButton("Inspect compiler / firmware readiness")
            inspect_readiness.clicked.connect(self.inspect_editor_readiness)
            create_measurement = QPushButton("Create live measurement campaign…")
            create_measurement.setToolTip("Writes a checklist and no MIDI/firmware data. It never converts SIM_* addresses into live mappings.")
            create_measurement.clicked.connect(self.create_live_measurement_campaign)
            capture_measurement = QPushButton("Capture next physical trace (receive-only)…")
            capture_measurement.setObjectName("captureLiveMeasurementTrace")
            capture_measurement.setToolTip(
                "Receive-only: opens one explicitly selected MIDI input for a bounded recording. It never opens an output, sends MIDI, or flashes firmware."
            )
            capture_measurement.clicked.connect(self.capture_live_measurement_trace)
            capture_native = QPushButton("Capture all Scene/Palette controls (receive-only)…")
            capture_native.setObjectName("captureNativeControlSequence")
            capture_native.setToolTip(
                "One bounded input recording, validated in exact order and atomically split into 30 isolated proofs. No MIDI output is opened."
            )
            capture_native.clicked.connect(self.capture_native_control_sequence)
            echo_probe = QPushButton("Probe isolated DDrum4 echo/soft-through…")
            echo_probe.setObjectName("probeDdrum4SoftThrough")
            echo_probe.setToolTip(
                "Hardware-output diagnostic with two confirmations. It remains preview-only until Arduino OUT is physically disconnected."
            )
            echo_probe.clicked.connect(self.probe_ddrum4_soft_through)
            review_measurement = QPushButton("Review captured live traces…")
            review_measurement.setToolTip("Reads isolated trace files only. It never writes a live profile or opens a MIDI port.")
            review_measurement.clicked.connect(self.review_live_measurement_campaign)
            promote_measurement = QPushButton("Create measured live profile…")
            promote_measurement.setToolTip("Creates a new YAML only after every isolated trace matches the prescribed source map. It never flashes or writes MIDI.")
            promote_measurement.clicked.connect(self.promote_live_measurement_campaign)
            promote_configured = QPushButton("Create configured live profile (no pads)…")
            promote_configured.setToolTip(
                "Uses the DDTi readback and eDRUMin snapshot receipts. Prescribed notes are preserved; only live endpoints are selected."
            )
            promote_configured.clicked.connect(self.promote_configured_live_profile)
            inspect_ports = QPushButton("Inspect visible MIDI ports (read-only)")
            inspect_ports.setToolTip("Lists OS-visible MIDI names only. It does not open, send to, or bind any MIDI port.")
            inspect_ports.clicked.connect(self.inspect_visible_midi_ports)
            readiness_layout.addWidget(self.editor_readiness); readiness_layout.addWidget(inspect_readiness); readiness_layout.addWidget(create_measurement); readiness_layout.addWidget(capture_measurement); readiness_layout.addWidget(capture_native); readiness_layout.addWidget(echo_probe); readiness_layout.addWidget(review_measurement); readiness_layout.addWidget(promote_measurement); readiness_layout.addWidget(promote_configured); readiness_layout.addWidget(inspect_ports)
            readiness_page.setLayout(readiness_layout)
            editor_tabs.addTab(readiness_page, "Validation & deployment")
            layout.addWidget(editor_tabs)
            validate = QPushButton("Validate project")
            validate.clicked.connect(self.validate_editor_project)
            save = QPushButton("Save validated project")
            save.setToolTip("Writes only the selected YAML project after complete validation. It does not compile, flash, or send MIDI.")
            save.clicked.connect(self.save_editor_project)
            row = QHBoxLayout(); row.addWidget(validate); row.addWidget(save); layout.addLayout(row)
            self.editor_status = QLabel("No project loaded."); layout.addWidget(self.editor_status)
            workspace.setLayout(layout)
            return workspace

        def select_editor_project(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Open rig project", "", "Rig projects (*.yaml *.yml)")
            if filename:
                self.editor_project.setText(filename)
                self.load_editor_project()

        def load_editor_project(self) -> None:
            path = Path(self.editor_project.text().strip())
            try:
                self.project_document.setPlainText(path.read_text(encoding="utf-8"))
                RigSimulator.from_path(path)
                document = yaml.safe_load(self.project_document.toPlainText())
                self._populate_visual_project_editor(document)
                self._load_project_bank_reference(path, document)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot load rig project", str(error)); return
            self._invalidate_simulator_workspace()
            self.project.setText(str(path))
            self.editor_status.setText("Loaded and validated. Edit, validate, then save.")

        def _load_project_bank_reference(self, project_path: Path, document: object) -> None:
            """Resolve an optional bank reference relative to the rig project.

            This only selects local manifest/report files for the read-only
            matrix; it never probes the DDrum4 or assumes installed memory.
            """
            self._clear_matrix()
            if not isinstance(document, dict) or not isinstance(document.get("ddrum4_bank"), dict):
                return
            reference = document["ddrum4_bank"]
            manifest = (project_path.parent / str(reference["manifest"])).resolve()
            reports = [(project_path.parent / str(item)).resolve() for item in reference.get("reports", ())]
            self.manifest.setText(str(manifest))
            self.report_paths = reports
            self.reports.setText("; ".join(str(item) for item in reports))
            self.load_matrix()

        def _clear_matrix(self, *, clear_reference: bool = True) -> None:
            """Forget the displayed bank before changing projects or loading a new file."""
            self.matrix = None
            self.matrix_table.clearContents(); self.matrix_table.setRowCount(10)
            self.layer_table.clearContents(); self.layer_table.setRowCount(0)
            self.bank_summary.setText("No DDrum4 bank loaded. Select a local manifest or load a rig project that declares ddrum4_bank.")
            self.bank_action_status.setText("No bank actions available until a local manifest is loaded.")
            self._refresh_visual_sound_bank_facts()
            if clear_reference:
                self.report_paths = []
                self.manifest.clear()
                self.reports.clear()

        def _bank_note_text(self, note: object) -> str:
            """Resolve a DDrum4 renderer note to a loaded bank slot without guessing."""
            if not isinstance(note, int):
                return "not declared"
            if self.matrix is None:
                return "bank not loaded"
            sound = self.matrix.sound_for_note(note)
            if sound is None or sound.note_base is None:
                return "no declared bank slot"
            return f"S{sound.slot} · P{note - sound.note_base + 1} · {sound.sound_id or 'missing'}"

        def _refresh_visual_sound_bank_facts(self) -> None:
            """Refresh only the read-only bank-resolution column after loading a bank."""
            if not hasattr(self, "visual_sounds"):
                return
            self._visual_project_syncing = True
            try:
                for row in range(self.visual_sounds.rowCount()):
                    note_item = self.visual_sounds.item(row, 1)
                    try:
                        note = int(note_item.text()) if note_item is not None else None
                    except ValueError:
                        note = None
                    item = QTableWidgetItem(self._bank_note_text(note))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_sounds.setItem(row, 2, item)
            finally:
                self._visual_project_syncing = False

        def _populate_visual_project_editor(self, document: object) -> None:
            if not isinstance(document, dict):
                raise ValueError("rig project root must be a mapping")
            self._visual_project_syncing = True
            try:
                self._populate_visual_project_tables(document)
            finally:
                self._visual_project_syncing = False

        def _populate_visual_project_tables(self, document: object) -> None:
            """Populate editable tables without changing their YAML source."""
            renderers = document.get("renderers", {})
            if not isinstance(renderers, dict):
                raise ValueError("rig project renderers must be a mapping")
            logical_ids = sorted(set().union(*(set(rows) for rows in renderers.values() if isinstance(rows, dict))))
            self.visual_sounds.setRowCount(len(logical_ids))
            for row, logical in enumerate(logical_ids):
                ddrum = renderers.get("ddrum4", {}).get(logical, {}) if isinstance(renderers.get("ddrum4"), dict) else {}
                sd3 = renderers.get("sd3", {}).get(logical, {}) if isinstance(renderers.get("sd3"), dict) else {}
                drumgizmo = renderers.get("drumgizmo", {}).get(logical, {}) if isinstance(renderers.get("drumgizmo"), dict) else {}
                ddrum_note = ddrum.get("note", "—") if isinstance(ddrum, dict) else "—"
                values = [
                    logical, ddrum_note, self._bank_note_text(ddrum_note),
                    sd3.get("channel", "—") if isinstance(sd3, dict) else "—",
                    sd3.get("note", "—") if isinstance(sd3, dict) else "—",
                    drumgizmo.get("channel", "—") if isinstance(drumgizmo, dict) else "—",
                    drumgizmo.get("note", "—") if isinstance(drumgizmo, dict) else "—",
                    drumgizmo.get("instrument", "—") if isinstance(drumgizmo, dict) else "—",
                    drumgizmo.get("articulation", "—") if isinstance(drumgizmo, dict) else "—",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column in (0, 2):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_sounds.setItem(row, column, item)
            routes = document.get("logical_routes", {})
            route_rows = []
            if isinstance(routes, dict):
                for scene, mappings in routes.items():
                    if isinstance(mappings, dict):
                        for physical, target in mappings.items():
                            fixed_target = isinstance(target, str)
                            if isinstance(target, list):
                                target = " / ".join(str(item.get("logical_target", "?")) for item in target if isinstance(item, dict))
                            route_rows.append((scene, physical, target, fixed_target))
            self.visual_routes.setRowCount(len(route_rows))
            for row, values in enumerate(route_rows):
                for column, value in enumerate(values[:3]):
                    item = QTableWidgetItem(str(value))
                    if column < 2 or not values[3]:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_routes.setItem(row, column, item)
            action_rows = []
            for scene, actions in document.get("ddrum_state_actions", {}).items():
                if isinstance(actions, list):
                    for index, action in enumerate(actions):
                        if isinstance(action, dict):
                            action_rows.append((scene, index, action.get("type", "—"), action.get("channel", "—"), action.get("program", "—"), action.get("status", "—"), action.get("description", "")))
            self._visual_action_rows = [(scene, index) for scene, index, *_ in action_rows]
            self.visual_actions.setRowCount(len(action_rows))
            for row, values in enumerate(action_rows):
                for column, value in enumerate(values[0:1] + values[2:]):
                    item = QTableWidgetItem(str(value))
                    if column < 2:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_actions.setItem(row, column, item)
            native_rows = []
            native_controls = document.get("native_control_map", {})
            if isinstance(native_controls, dict):
                for name, control in native_controls.items():
                    if not isinstance(control, dict):
                        continue
                    message_type = str(control.get("type", "—"))
                    address_key = {"program_change": "program", "cc": "cc", "note": "note"}.get(message_type)
                    native_rows.append((
                        name, control.get("source", "—"), control.get("channel", "—"), message_type,
                        control.get(address_key, "—") if address_key else "—",
                        control.get("decode_to", "—"), control.get("value", "—"),
                    ))
            self.visual_native_controls.setRowCount(len(native_rows))
            for row, values in enumerate(native_rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_native_controls.setItem(row, column, item)
            sources = document.get("sources", {})
            source_rows = [(name, item.get("endpoint", "—"), item.get("channel", "—"), item.get("primary", "—")) for name, item in sources.items() if isinstance(item, dict)]
            self.visual_sources.setRowCount(len(source_rows))
            for row, values in enumerate(source_rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_sources.setItem(row, column, item)
            bindings = document.get("physical_bindings", {})
            note_decoders = {
                decoder.get("emit", {}).get("physical"): decoder
                for decoder in document.get("source_decoders", [])
                if isinstance(decoder, dict) and decoder.get("match", {}).get("type") == "note"
            }
            physical_rows = []
            for physical in document.get("physical_events", []):
                binding = bindings.get(physical, {}) if isinstance(bindings, dict) else {}
                decoder = note_decoders.get(physical, {})
                match = decoder.get("match", {}) if isinstance(decoder, dict) else {}
                physical_rows.append((
                    physical, match.get("source", "MISSING"), binding.get("instrument", "MISSING"),
                    binding.get("zone", "MISSING"), match.get("type", "MISSING"), match.get("note", "MISSING"),
                ))
            self.visual_physical.setRowCount(len(physical_rows))
            for row, values in enumerate(physical_rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column in (0, 1, 4):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if value == "MISSING":
                        item.setBackground(Qt.GlobalColor.darkRed)
                    self.visual_physical.setItem(row, column, item)
            expression_rows = []
            decoder_controls = {
                (decoder.get("match", {}).get("source"), decoder.get("emit", {}).get("physical"),
                 next(iter(decoder.get("emit", {}).get("expressions", [])), None)):
                    f"{str(decoder.get('match', {}).get('type', '')).upper()} "
                    f"{decoder.get('match', {}).get('cc', decoder.get('match', {}).get('active_note', '—'))}"
                for decoder in document.get("source_decoders", []) if isinstance(decoder, dict)
                and decoder.get("match", {}).get("type") in {"cc", "poly_aftertouch"}
            }
            for route in document.get("expression_routing", []):
                if not isinstance(route, dict):
                    continue
                source, physical, expression = route.get("source"), route.get("physical"), route.get("expression")
                targets = route.get("targets", {})
                expression_rows.append((
                    source, physical, expression, decoder_controls.get((source, physical, expression), "MISSING"),
                    targets.get("ddrum4", {}).get("status", "MISSING"),
                    targets.get("sd3", {}).get("status", "MISSING"),
                    targets.get("drumgizmo", {}).get("status", "MISSING"),
                ))
            self.visual_expressions.setRowCount(len(expression_rows))
            for row, values in enumerate(expression_rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if value in {"MISSING", "planned", "unsupported"}:
                        item.setBackground(Qt.GlobalColor.darkRed)
                    elif value in {"measured", "user-confirmed"}:
                        item.setBackground(Qt.GlobalColor.darkGreen)
                    self.visual_expressions.setItem(row, column, item)

        def _sync_visual_project(self, table: str) -> None:
            """Write a table edit back into Advanced YAML, preserving one source of truth."""
            if self._visual_project_syncing:
                return
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                if table == "sounds":
                    for row in range(self.visual_sounds.rowCount()):
                        logical = self.visual_sounds.item(row, 0).text()
                        ddrum = document["renderers"]["ddrum4"][logical]
                        sd3 = document["renderers"]["sd3"][logical]
                        drumgizmo = document["renderers"]["drumgizmo"][logical]
                        ddrum_note = self.visual_sounds.item(row, 1)
                        if ddrum_note is not None and ddrum_note.text().strip() != "—":
                            ddrum["note"] = int(ddrum_note.text())
                        for column, field in ((3, "channel"), (4, "note")):
                            item = self.visual_sounds.item(row, column)
                            if item is not None and item.text().strip() != "—":
                                sd3[field] = int(item.text())
                        for column, field in ((5, "channel"), (6, "note")):
                            item = self.visual_sounds.item(row, column)
                            if item is not None and item.text().strip() != "—":
                                drumgizmo[field] = int(item.text())
                        for column, field in ((7, "instrument"), (8, "articulation")):
                            item = self.visual_sounds.item(row, column)
                            if item is not None and item.text().strip() != "—":
                                drumgizmo[field] = item.text().strip()
                elif table == "routes":
                    for row in range(self.visual_routes.rowCount()):
                        scene = self.visual_routes.item(row, 0).text()
                        physical = self.visual_routes.item(row, 1).text()
                        document["logical_routes"][scene][physical] = self.visual_routes.item(row, 2).text().strip()
                elif table == "sources":
                    for row in range(self.visual_sources.rowCount()):
                        name = self.visual_sources.item(row, 0).text()
                        source = document["sources"][name]
                        source["endpoint"] = self.visual_sources.item(row, 1).text().strip()
                        source["channel"] = int(self.visual_sources.item(row, 2).text())
                        source["primary"] = self.visual_sources.item(row, 3).text().strip()
                elif table == "physical":
                    note_decoders = {
                        decoder.get("emit", {}).get("physical"): decoder
                        for decoder in document.get("source_decoders", [])
                        if isinstance(decoder, dict) and decoder.get("match", {}).get("type") == "note"
                    }
                    for row in range(self.visual_physical.rowCount()):
                        physical = self.visual_physical.item(row, 0).text()
                        binding = document["physical_bindings"][physical]
                        binding["instrument"] = self.visual_physical.item(row, 2).text().strip()
                        binding["zone"] = self.visual_physical.item(row, 3).text().strip()
                        decoder = note_decoders.get(physical)
                        if decoder is None:
                            raise ValueError(f"{physical} has no editable Note-On decoder")
                        decoder["match"]["note"] = int(self.visual_physical.item(row, 5).text())
                elif table == "native":
                    native_controls = document.get("native_control_map")
                    if not isinstance(native_controls, dict):
                        raise ValueError("native_control_map must be a mapping")
                    address_keys = {"program_change": "program", "cc": "cc", "note": "note"}
                    for row in range(self.visual_native_controls.rowCount()):
                        name = self.visual_native_controls.item(row, 0).text()
                        control = native_controls[name]
                        message_type = self.visual_native_controls.item(row, 3).text().strip()
                        if message_type not in address_keys:
                            raise ValueError(f"unsupported native control type {message_type!r}")
                        for key in address_keys.values():
                            control.pop(key, None)
                        source = self.visual_native_controls.item(row, 1).text().strip()
                        if source == "—":
                            control.pop("source", None)
                        else:
                            control["source"] = source
                        control["channel"] = int(self.visual_native_controls.item(row, 2).text())
                        control["type"] = message_type
                        control[address_keys[message_type]] = int(self.visual_native_controls.item(row, 4).text())
                        control["decode_to"] = self.visual_native_controls.item(row, 5).text().strip()
                        control["value"] = int(self.visual_native_controls.item(row, 6).text())
                else:
                    action_rows = [(scene, action) for scene, actions in document.get("ddrum_state_actions", {}).items()
                                   if isinstance(actions, list) for action in actions if isinstance(action, dict)]
                    for row, (_, action) in enumerate(action_rows):
                        action["channel"] = int(self.visual_actions.item(row, 2).text())
                        action["program"] = int(self.visual_actions.item(row, 3).text())
                        action["status"] = self.visual_actions.item(row, 4).text().strip()
                        action["description"] = self.visual_actions.item(row, 5).text().strip()
                self._visual_project_syncing = True
                self.project_document.setPlainText(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
                self._visual_project_syncing = False
                self._refresh_visual_sound_bank_facts()
                self.editor_status.setText("Table edit applied to Advanced YAML. Validate before saving.")
            except (TypeError, ValueError, KeyError) as error:
                self._visual_project_syncing = True
                self._populate_visual_project_tables(yaml.safe_load(self.project_document.toPlainText()))
                self._visual_project_syncing = False
                self.editor_status.setText(f"Table edit rejected: {error}")

        def add_visual_native_control(self) -> None:
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                native_controls = document.setdefault("native_control_map", {})
                if not isinstance(native_controls, dict):
                    raise ValueError("native_control_map must be a mapping")
                name, accepted = QInputDialog.getText(self, "Add DDrum4 panel control", "Stable control identifier:")
                name = name.strip()
                if not accepted:
                    return
                if not name:
                    raise ValueError("control identifier cannot be empty")
                if name in native_controls:
                    raise ValueError(f"native control {name!r} already exists")
                sources = tuple(document.get("sources", {}))
                source, accepted = QInputDialog.getItem(self, "Add DDrum4 panel control", "Source module:", sources, 0, False)
                if not accepted:
                    return
                targets = ("scene", *document["state"]["variables"])
                target, accepted = QInputDialog.getItem(self, "Add DDrum4 panel control", "Logical target:", targets, 0, False)
                if not accepted:
                    return
                message_type, accepted = QInputDialog.getItem(
                    self, "Add DDrum4 panel control", "MIDI message:", ("program_change", "cc", "note"), 0, False,
                )
                if not accepted:
                    return
                address, accepted = QInputDialog.getInt(self, "Add DDrum4 panel control", "Program / CC / note address:", 0, 0, 127)
                if not accepted:
                    return
                maximum = len(document["state"]["scenes"]) - 1 if target == "scene" else 127
                value, accepted = QInputDialog.getInt(self, "Add DDrum4 panel control", "Decoded logical value:", 0, 0, maximum)
                if not accepted:
                    return
                source_document = document["sources"][source]
                address_key = {"program_change": "program", "cc": "cc", "note": "note"}[message_type]
                native_controls[name] = {
                    "decode_to": target, "source": source, "channel": int(source_document["channel"]),
                    "type": message_type, address_key: address, "value": value,
                }
                self._apply_visual_project_document(document, f"Native panel control {name!r} added.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Cannot add DDrum4 panel control", str(error))

        def delete_visual_native_control(self) -> None:
            try:
                row = self.visual_native_controls.currentRow()
                if row < 0 or self.visual_native_controls.item(row, 0) is None:
                    raise ValueError("select a native panel control first")
                name = self.visual_native_controls.item(row, 0).text()
                answer = QMessageBox.question(self, "Delete panel control", f"Delete native control {name!r}?")
                if answer != QMessageBox.StandardButton.Yes:
                    return
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict) or not isinstance(document.get("native_control_map"), dict):
                    raise ValueError("native_control_map must be a mapping")
                del document["native_control_map"][name]
                self._apply_visual_project_document(document, f"Native panel control {name!r} deleted.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Cannot delete DDrum4 panel control", str(error))

        def _selected_visual_scene(self) -> str:
            row = self.visual_routes.currentRow()
            if row < 0 or self.visual_routes.item(row, 0) is None:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                return str(document["state"]["defaults"]["scene"])
            return self.visual_routes.item(row, 0).text()

        def _selected_visual_sound(self) -> str:
            row = self.visual_sounds.currentRow()
            if row < 0 or self.visual_sounds.item(row, 0) is None:
                raise ValueError("select a logical sound first")
            return self.visual_sounds.item(row, 0).text()

        @staticmethod
        def _route_uses_logical_sound(value: object, logical_sound: str) -> bool:
            if value == logical_sound:
                return True
            if isinstance(value, list):
                return any(isinstance(item, dict) and item.get("logical_target") == logical_sound for item in value)
            return False

        def _apply_visual_project_document(self, document: dict[str, object], message: str) -> None:
            """Refresh all editable views after a structural project edit."""
            self._visual_project_syncing = True
            try:
                self.project_document.setPlainText(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
                self._populate_visual_project_tables(document)
                self._refresh_visual_sound_bank_facts()
            finally:
                self._visual_project_syncing = False
            self.editor_status.setText(message + " Validate before saving.")

        def add_visual_sound(self) -> None:
            self._copy_visual_sound("Add logical sound", "Logical sound identifier:", None)

        def duplicate_visual_sound(self) -> None:
            try:
                source = self._selected_visual_sound()
            except ValueError as error:
                QMessageBox.warning(self, "Duplicate logical sound", str(error)); return
            self._copy_visual_sound("Duplicate logical sound", "New logical sound identifier:", source)

        def _copy_visual_sound(self, title: str, prompt: str, source: str | None) -> None:
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict) or not isinstance(document.get("renderers"), dict):
                    raise ValueError("Advanced YAML is not a project renderer mapping")
                suggested = f"{source}.copy" if source else "new.sound"
                logical, accepted = QInputDialog.getText(self, title, prompt, text=suggested)
                if not accepted:
                    return
                logical = logical.strip()
                if not logical:
                    raise ValueError("logical sound identifier cannot be empty")
                renderers = document["renderers"]
                known = set().union(*(set(items) for items in renderers.values() if isinstance(items, dict)))
                if logical in known:
                    raise ValueError(f"logical sound {logical!r} already exists")
                for target in ("ddrum4", "sd3", "drumgizmo"):
                    target_map = renderers.get(target)
                    if not isinstance(target_map, dict):
                        raise ValueError(f"renderer {target!r} is missing")
                    target_map[logical] = deepcopy(target_map[source]) if source is not None else {}
                message = f"Logical sound {logical!r} duplicated from {source!r}." if source else f"Logical sound {logical!r} added."
                self._apply_visual_project_document(document, message)
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, title, str(error))

        def delete_visual_sound(self) -> None:
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                logical = self._selected_visual_sound()
                uses = [
                    f"{scene}.{physical}"
                    for scene, mappings in document.get("logical_routes", {}).items() if isinstance(mappings, dict)
                    for physical, target in mappings.items()
                    if self._route_uses_logical_sound(target, logical)
                ]
                if uses:
                    raise ValueError(f"{logical!r} is still used by: {', '.join(uses)}")
                answer = QMessageBox.question(self, "Delete logical sound", f"Delete {logical!r} from all three renderer maps?")
                if answer != QMessageBox.StandardButton.Yes:
                    return
                renderers = document.get("renderers", {})
                if not isinstance(renderers, dict):
                    raise ValueError("project renderers must be a mapping")
                for target in ("ddrum4", "sd3", "drumgizmo"):
                    target_map = renderers.get(target)
                    if isinstance(target_map, dict):
                        target_map.pop(logical, None)
                self._apply_visual_project_document(document, f"Logical sound {logical!r} deleted.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Delete logical sound", str(error))

        def add_visual_action(self) -> None:
            """Append one deliberately unconfirmed Program Change action to a Scene."""
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                scenes = document["state"]["scenes"]
                if not isinstance(scenes, list) or not scenes:
                    raise ValueError("project has no declared scenes")
                current = self._selected_visual_scene()
                scene, accepted = QInputDialog.getItem(self, "Add DDrum4 Program action", "Scene:", scenes,
                                                       max(0, scenes.index(current) if current in scenes else 0), False)
                if not accepted:
                    return
                output_channel = document.get("ddrum4_output_channel")
                if not isinstance(output_channel, int):
                    raise ValueError("ddrum4_output_channel must be an integer")
                actions = document.setdefault("ddrum_state_actions", {})
                if not isinstance(actions, dict):
                    raise ValueError("ddrum_state_actions must be a mapping")
                scene_actions = actions.setdefault(scene, [])
                if not isinstance(scene_actions, list):
                    raise ValueError(f"ddrum_state_actions.{scene} must be a list")
                scene_actions.append({
                    "type": "program_change", "status": "planned", "channel": output_channel, "program": 0,
                    "description": "New action — verify on the DDrum4 before marking user-confirmed.",
                })
                self._apply_visual_project_document(document, f"Unconfirmed DDrum4 Program action added to {scene!r}.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Add DDrum4 Program action", str(error))

        def delete_visual_action(self) -> None:
            try:
                row = self.visual_actions.currentRow()
                if row < 0 or row >= len(getattr(self, "_visual_action_rows", ())):
                    raise ValueError("select a DDrum4 action first")
                scene, index = self._visual_action_rows[row]
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                actions = document.get("ddrum_state_actions", {})
                if not isinstance(actions, dict) or not isinstance(actions.get(scene), list) or index >= len(actions[scene]):
                    raise ValueError("selected action no longer exists in Advanced YAML")
                answer = QMessageBox.question(self, "Delete DDrum4 action", f"Delete action {index + 1} from {scene!r}?")
                if answer != QMessageBox.StandardButton.Yes:
                    return
                del actions[scene][index]
                if not actions[scene]:
                    del actions[scene]
                self._apply_visual_project_document(document, f"DDrum4 action deleted from {scene!r}.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Delete DDrum4 action", str(error))

        def _apply_scene_document(self, document: dict[str, object], message: str) -> None:
            """Refresh all visual tables after a structural scene edit.

            Structural edits use the same Advanced YAML source as scalar table
            edits. Validation remains explicit before saving, so creating a
            Scene cannot trigger a compile or a MIDI message.
            """
            self._visual_project_syncing = True
            try:
                self.project_document.setPlainText(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
                self._populate_visual_project_tables(document)
            finally:
                self._visual_project_syncing = False
            self.editor_status.setText(message + " Validate before saving.")

        def add_visual_scene(self) -> None:
            self._copy_visual_scene("Add scene", "New scene identifier:", self._selected_visual_scene())

        def duplicate_visual_scene(self) -> None:
            source = self._selected_visual_scene()
            self._copy_visual_scene("Duplicate scene", "New scene identifier:", source, source)

        def _copy_visual_scene(self, title: str, prompt: str, source_scene: str, suggested: str | None = None) -> None:
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                scenes = document["state"]["scenes"]
                if source_scene not in scenes:
                    raise ValueError(f"unknown source scene {source_scene!r}")
                name, accepted = QInputDialog.getText(self, title, prompt, text=suggested or f"{source_scene}.copy")
                if not accepted:
                    return
                name = name.strip()
                if not name:
                    raise ValueError("scene identifier cannot be empty")
                if name in scenes:
                    raise ValueError(f"scene {name!r} already exists")
                scenes.append(name)
                document["logical_routes"][name] = deepcopy(document["logical_routes"][source_scene])
                actions = document.setdefault("ddrum_state_actions", {})
                if source_scene in actions:
                    actions[name] = deepcopy(actions[source_scene])
                self._apply_scene_document(document, f"Scene {name!r} created from {source_scene!r}.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, title, str(error))

        def rename_visual_scene(self) -> None:
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                old = self._selected_visual_scene()
                new, accepted = QInputDialog.getText(self, "Rename scene", "Scene identifier:", text=old)
                if not accepted or new.strip() == old:
                    return
                new = new.strip()
                scenes = document["state"]["scenes"]
                if not new:
                    raise ValueError("scene identifier cannot be empty")
                if new in scenes:
                    raise ValueError(f"scene {new!r} already exists")
                scenes[scenes.index(old)] = new
                document["logical_routes"][new] = document["logical_routes"].pop(old)
                actions = document.setdefault("ddrum_state_actions", {})
                if old in actions:
                    actions[new] = actions.pop(old)
                if document["state"]["defaults"]["scene"] == old:
                    document["state"]["defaults"]["scene"] = new
                self._apply_scene_document(document, f"Scene {old!r} renamed to {new!r}.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Rename scene", str(error))

        def delete_visual_scene(self) -> None:
            try:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                name = self._selected_visual_scene()
                scenes = document["state"]["scenes"]
                if len(scenes) <= 1:
                    raise ValueError("the only scene cannot be deleted")
                if name == document["state"]["defaults"]["scene"]:
                    raise ValueError("select another default scene before deleting this scene")
                answer = QMessageBox.question(self, "Delete scene", f"Delete scene {name!r} and all of its route variants?")
                if answer != QMessageBox.StandardButton.Yes:
                    return
                scenes.remove(name)
                del document["logical_routes"][name]
                document.get("ddrum_state_actions", {}).pop(name, None)
                self._apply_scene_document(document, f"Scene {name!r} deleted.")
            except (TypeError, ValueError, KeyError) as error:
                QMessageBox.warning(self, "Delete scene", str(error))

        def _validate_editor_text(self) -> None:
            path = Path(self.editor_project.text().strip())
            if not path.is_file():
                raise ValueError("select an existing rig project")
            temporary = path.with_suffix(path.suffix + ".validate.tmp")
            if temporary.exists():
                raise ValueError(f"remove stale validation file first: {temporary}")
            try:
                temporary.write_text(self.project_document.toPlainText(), encoding="utf-8", newline="\n")
                RigSimulator.from_path(temporary)
            finally:
                temporary.unlink(missing_ok=True)

        def validate_editor_project(self) -> None:
            try:
                self._validate_editor_text()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Project validation failed", str(error)); return
            self.editor_status.setText("Valid project. Safe to save or compile.")

        def inspect_editor_readiness(self) -> None:
            """Explain compiler/flash gates for the exact unsaved editor text.

            A sibling temporary file preserves relative references (especially
            ``ddrum4_bank.manifest``) while making this a strictly offline
            preview.  The result is deliberately not a substitute for a live
            hardware measurement or an Arduino flash.
            """
            path = Path(self.editor_project.text().strip())
            if not path.is_file():
                self.editor_readiness.setPlainText("Select an existing rig project first.")
                return
            temporary = path.with_suffix(path.suffix + ".readiness.tmp")
            try:
                if temporary.exists():
                    raise ValueError(f"remove stale readiness file first: {temporary}")
                temporary.write_text(self.project_document.toPlainText(), encoding="utf-8", newline="\n")
                from rig_compiler.compiler import validate_project
                compilation = validate_project(temporary)
                report = compilation.artifacts["project-report.json"]
                firmware = compilation.artifacts["firmware-project-mapping.json"]
                statuses = {item["name"]: item["status"] for item in report["artifacts"]}
                lines = [
                    f"Project: {report['project']}",
                    f"Deployment: {report['deployment']}",
                    f"Firmware mapping: {statuses['firmware-project-mapping']}",
                    f"Arduino flash gate: {firmware['hardware_flash']}",
                    f"Runtime profile: {statuses['runtime-profile']}",
                    f"Virtual-kit parity map: {statuses['virtual-kit-map']}",
                    "",
                ]
                blockers = firmware.get("lowering_blockers", [])
                if blockers:
                    lines.append("Firmware blockers:")
                    lines.extend(f"• {item['id']}: {item['reason']}" for item in blockers)
                elif firmware["hardware_flash"] != "ready":
                    lines.append("Firmware is not flashable. Check deployment=live, measured values, and exact Note decoders.")
                else:
                    lines.append("Firmware mapping is ready to generate. Flash still requires the separate hardware review gate.")
                self.editor_readiness.setPlainText("\n".join(lines))
            except (ImportError, OSError, ValueError) as error:
                self.editor_readiness.setPlainText(f"Readiness inspection failed: {error}")
            finally:
                temporary.unlink(missing_ok=True)

        def create_live_measurement_campaign(self) -> None:
            """Create the hand-off folder needed before a measured live profile.

            This intentionally consumes the saved project only: an unsaved
            YAML buffer cannot be mistaken for an observed hardware contract.
            """
            try:
                project = self._selected_simulator_project_path()
            except SimulationError as error:
                QMessageBox.warning(self, "Cannot create measurement campaign", str(error)); return
            directory = QFileDialog.getExistingDirectory(self, "Select empty live measurement campaign directory")
            if not directory:
                return
            try:
                plan, guide = LiveMeasurementCampaign.from_path(project).write_new(Path(directory))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot create measurement campaign", str(error)); return
            self.editor_readiness.setPlainText(
                f"Live measurement campaign created.\n\nPlan: {plan}\nGuide: {guide}\n\n"
                "It is a checklist only: no MIDI port, DDrum4 state, or Arduino firmware was touched."
            )

        def inspect_visible_midi_ports(self) -> None:
            """Show only the current OS inventory; no port handle is opened."""
            try:
                inventory = discover_midi_port_inventory()
            except (RuntimeError, ValueError) as error:
                QMessageBox.warning(self, "Cannot inspect MIDI ports", str(error)); return
            lines = ["Visible MIDI ports — observation only", "", "Inputs:"]
            lines.extend(f"• {name}" for name in inventory["inputs"])
            lines.extend(["", "Outputs:"])
            lines.extend(f"• {name}" for name in inventory["outputs"])
            lines.extend(["", "Validate a physical cable and capture a trace before adding any name to deployment: live."])
            self.editor_readiness.setPlainText("\n".join(lines))

        def capture_native_control_sequence(self) -> None:
            """Capture every native panel command in one exact receive-only sequence."""
            if (self.live_measurement_process is not None and
                    self.live_measurement_process.state() != QProcess.ProcessState.NotRunning):
                QMessageBox.warning(self, "Measurement already running", "Wait for the current validation process to finish.")
                return
            repository = Path(__file__).resolve().parents[4]
            initial = self.live_measurement_directory or repository / "build" / "measurements" / "greg-hybrid-r15-v23-r10"
            directory = QFileDialog.getExistingDirectory(self, "Select live measurement campaign", str(initial))
            if not directory:
                return
            root = Path(directory).resolve()
            try:
                campaign = LiveMeasurementCampaign.read(root)
                review = campaign.review_traces(root)
                native_rows = [row for row in review["rows"] if str(row["id"]).startswith("native.")]
                observed = [row for row in native_rows if row["status"] == "observed"]
                if observed:
                    if len(observed) == len(native_rows):
                        self.editor_readiness.setPlainText("All native Scene/Palette controls are already observed.")
                    else:
                        QMessageBox.warning(
                            self, "Partial native evidence already exists",
                            "The atomic bulk importer never overwrites evidence. Capture the remaining controls individually, "
                            "or archive the partial campaign before starting a fresh full sequence.",
                        )
                    return
                requests = [item for item in campaign.to_document()["trace_requests"]
                            if str(item["id"]).startswith("native.")]
                inventory = discover_midi_port_inventory()
                inputs = list(inventory["inputs"])
                if not inputs:
                    raise ValueError("no MIDI input is currently visible")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                QMessageBox.warning(self, "Cannot prepare native-control capture", str(error)); return
            input_port, accepted = QInputDialog.getItem(
                self, "Receive-only DDrum4 input", "Input receiving the DDrum4 panel Program Change:", inputs,
                next((index for index, name in enumerate(inputs) if "UMC" in name), 0), False,
            )
            if not accepted:
                return
            seconds, accepted = QInputDialog.getDouble(
                self, "Sequence duration", "Time allowed for all 30 panel actions (seconds):", 120.0, 30.0, 300.0, 0,
            )
            if not accepted:
                return
            sequence = [f"{index:2}. PC {int(item['matcher']['program']):3} — "
                        f"{decode_ddrum4_program(int(item['matcher']['program'])).label}"
                        for index, item in enumerate(requests, start=1)]
            answer = QMessageBox.warning(
                self, "Start atomic Scene/Palette capture",
                f"Campaign: {root}\nInput: {input_port}\nDuration: {seconds:.0f} s\n\n"
                + "\n".join(sequence)
                + "\n\nPerform every action once and in this exact order. Only the selected input is opened. "
                  "No MIDI output, module write, SysEx or firmware flash occurs. If one item is missing or out of order, "
                  "no isolated proof is published. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
            script = repository / "scripts" / "capture-greg-hybrid-native-controls.ps1"
            if powershell is None or not script.is_file():
                QMessageBox.warning(self, "Cannot start capture", "PowerShell or the native-control helper is missing."); return
            arguments = [
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Campaign", str(root), "-InputPort", str(input_port), "-Seconds", str(seconds),
                "-Capture", "-ConfirmSequence",
            ]
            self.live_measurement_directory = root
            self.live_measurement_trace_id = None
            self.live_measurement_operation = "native-sequence"
            self.live_measurement_log = (
                f"Atomic native-control capture started.\nInput: {input_port}\nDuration: {seconds:.0f} s\n\n"
            )
            self.editor_readiness.setPlainText(self.live_measurement_log)
            self.live_measurement_process = QProcess(self)
            self.live_measurement_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.live_measurement_process.setProgram(powershell)
            self.live_measurement_process.setArguments(arguments)
            self.live_measurement_process.readyReadStandardOutput.connect(self.append_live_measurement_output)
            self.live_measurement_process.errorOccurred.connect(self.live_measurement_failed)
            self.live_measurement_process.finished.connect(self.live_measurement_finished)
            self.live_measurement_process.start()

        def probe_ddrum4_soft_through(self) -> None:
            """Run the bounded echo probe only after an explicit isolated-cable confirmation."""
            if (self.live_measurement_process is not None and
                    self.live_measurement_process.state() != QProcess.ProcessState.NotRunning):
                QMessageBox.warning(self, "Validation already running", "Wait for the current validation process to finish.")
                return
            topology = (
                "Before continuing:\n\n"
                "1. Disconnect Arduino MIDI OUT from DDrum4 MIDI IN.\n"
                "2. Connect UMC MIDI OUT directly to DDrum4 MIDI IN.\n"
                "3. Keep DDrum4 OUT → merger/Arduino IN → hardware THRU → UMC IN.\n"
                "4. Set Local Off, C12 and aftertouch ON; do not touch any pad.\n\n"
                "The probe sends 100 cycles of Note On → Poly Aftertouch → velocity-zero Note On on unused note 127. "
                "Do not continue unless Arduino OUT is physically disconnected."
            )
            if QMessageBox.warning(
                    self, "Isolate the DDrum4 return path", topology,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            try:
                inventory = discover_midi_port_inventory()
                inputs, outputs = list(inventory["inputs"]), list(inventory["outputs"])
                if not inputs or not outputs:
                    raise ValueError("both one MIDI input and one MIDI output must be visible")
            except (RuntimeError, ValueError) as error:
                QMessageBox.warning(self, "Cannot prepare echo probe", str(error)); return
            input_port, accepted = QInputDialog.getItem(
                self, "DDrum4 return input", "Input receiving DDrum4 OUT through hardware THRU:", inputs,
                next((index for index, name in enumerate(inputs) if "UMC" in name), 0), False,
            )
            if not accepted:
                return
            output_port, accepted = QInputDialog.getItem(
                self, "Direct DDrum4 output", "Output wired directly to DDrum4 MIDI IN:", outputs,
                next((index for index, name in enumerate(outputs) if "UMC" in name), 0), False,
            )
            if not accepted:
                return
            if QMessageBox.warning(
                    self, "Final hardware-output confirmation",
                    f"Input: {input_port}\nOutput: {output_port}\n\n"
                    "Confirm again that Arduino OUT is disconnected. This operation will now transmit 300 bounded MIDI messages.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            repository = Path(__file__).resolve().parents[4]
            powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
            script = repository / "scripts" / "probe-ddrum4-soft-through.ps1"
            if powershell is None or not script.is_file():
                QMessageBox.warning(self, "Cannot start echo probe", "PowerShell or the echo-probe helper is missing."); return
            arguments = [
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-MidiInput", str(input_port), "-MidiOutput", str(output_port),
                "-Run", "-ConfirmIsolatedTopology",
            ]
            self.live_measurement_directory = None
            self.live_measurement_trace_id = None
            self.live_measurement_operation = "echo-probe"
            self.live_measurement_log = "Isolated DDrum4 soft-through probe started.\n\n"
            self.editor_readiness.setPlainText(self.live_measurement_log)
            self.live_measurement_process = QProcess(self)
            self.live_measurement_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.live_measurement_process.setProgram(powershell)
            self.live_measurement_process.setArguments(arguments)
            self.live_measurement_process.readyReadStandardOutput.connect(self.append_live_measurement_output)
            self.live_measurement_process.errorOccurred.connect(self.live_measurement_failed)
            self.live_measurement_process.finished.connect(self.live_measurement_finished)
            self.live_measurement_process.start()

        def capture_live_measurement_trace(self) -> None:
            """Capture one explicitly selected raw input into a campaign trace.

            This is the only hardware-capable action in the deployment page.
            It is deliberately receive-only, bounded, confirmed by the user,
            and delegated to the same reviewed helper used by the CLI workflow.
            """
            if (self.live_measurement_process is not None and
                    self.live_measurement_process.state() != QProcess.ProcessState.NotRunning):
                QMessageBox.warning(self, "Measurement already running", "Wait for the current receive-only capture to finish.")
                return
            repository = Path(__file__).resolve().parents[4]
            initial = self.live_measurement_directory or repository / "build" / "measurements" / "greg-hybrid-r15-v23-r10"
            directory = QFileDialog.getExistingDirectory(
                self, "Select live measurement campaign", str(initial)
            )
            if not directory:
                return
            root = Path(directory).resolve()
            try:
                campaign = LiveMeasurementCampaign.read(root)
                review = campaign.review_traces(root)
                request_by_id = {str(item["id"]): item for item in campaign.to_document()["trace_requests"]}
                pending = [row for row in review["rows"] if row["status"] != "observed"]
                if not pending:
                    self.editor_readiness.setPlainText(
                        "Every isolated trace is observed. Review the campaign, then create the measured live profile."
                    )
                    return
                inventory = discover_midi_port_inventory()
                inputs = list(inventory["inputs"])
                if not inputs:
                    raise ValueError("no MIDI input is currently visible")
            except (OSError, KeyError, RuntimeError, TypeError, ValueError) as error:
                QMessageBox.warning(self, "Cannot prepare live trace capture", str(error))
                return

            labels: list[str] = []
            rows_by_label: dict[str, dict[str, object]] = {}
            for row in pending:
                identifier = str(row["id"])
                request = request_by_id.get(identifier, {})
                physical = request.get("physical", "unknown physical control")
                label = f"{str(row['status']).upper()} — {identifier} — {physical}"
                labels.append(label)
                rows_by_label[label] = row
            selected_label, accepted = QInputDialog.getItem(
                self, "Physical trace", "Capture exactly one isolated event:", labels, 0, False
            )
            if not accepted:
                return
            selected = rows_by_label[str(selected_label)]
            trace_id = str(selected["id"])
            request = request_by_id[trace_id]
            input_port, accepted = QInputDialog.getItem(
                self, "Receive-only MIDI input", "Exact raw input to open:", inputs, 0, False
            )
            if not accepted:
                return
            seconds, accepted = QInputDialog.getDouble(
                self, "Capture duration", "Listening window in seconds:", 5.0, 0.5, 60.0, 1
            )
            if not accepted:
                return
            replacing = str(selected["status"]) != "missing"
            replacement_note = (
                "\nThe existing rejected/invalid trace will be archived beside the new trace."
                if replacing else ""
            )
            answer = QMessageBox.warning(
                self, "Start receive-only physical capture",
                f"Campaign: {root}\nTrace: {trace_id}\nPhysical event: {request.get('physical')}\n"
                f"Expected matcher: {json.dumps(request.get('matcher'), ensure_ascii=False)}\n"
                f"Input: {input_port}\nDuration: {seconds:.1f} s\n\n"
                "Only this MIDI input will be opened. Strike/move only the named control during the window. "
                "No MIDI output, SysEx, module write, audio capture, or Arduino flash will occur."
                f"{replacement_note}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
            script = repository / "scripts" / "capture-greg-hybrid-live-trace.ps1"
            if powershell is None or not script.is_file():
                QMessageBox.warning(self, "Cannot start capture", "PowerShell or the guided capture helper is missing.")
                return
            arguments = [
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Campaign", str(root), "-InputPort", str(input_port), "-TraceId", trace_id,
                "-Seconds", str(seconds), "-Capture",
            ]
            if replacing:
                arguments.append("-ReplaceTrace")
            self.live_measurement_directory = root
            self.live_measurement_trace_id = trace_id
            self.live_measurement_operation = "single-trace"
            self.live_measurement_log = (
                f"Receive-only capture started.\nTrace: {trace_id}\nInput: {input_port}\nDuration: {seconds:.1f} s\n\n"
            )
            self.editor_readiness.setPlainText(self.live_measurement_log)
            self.live_measurement_process = QProcess(self)
            self.live_measurement_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.live_measurement_process.setProgram(powershell)
            self.live_measurement_process.setArguments(arguments)
            self.live_measurement_process.readyReadStandardOutput.connect(self.append_live_measurement_output)
            self.live_measurement_process.errorOccurred.connect(self.live_measurement_failed)
            self.live_measurement_process.finished.connect(self.live_measurement_finished)
            self.live_measurement_process.start()

        def append_live_measurement_output(self) -> None:
            if self.live_measurement_process is None:
                return
            output = bytes(self.live_measurement_process.readAllStandardOutput()).decode(errors="replace")
            if output:
                self.live_measurement_log += output
                self.editor_readiness.setPlainText(self.live_measurement_log)

        def live_measurement_failed(self, error: object) -> None:
            """Expose QProcess startup/runtime errors and release failed starts."""
            self.append_live_measurement_output()
            process = self.live_measurement_process
            if process is None:
                return
            self.live_measurement_log += f"\nCapture process error: {process.errorString()}\n"
            safety = ("The isolated probe may have transmitted its bounded diagnostic sequence; inspect the log and restore cabling."
                      if self.live_measurement_operation == "echo-probe" else
                      "No MIDI output, module write, or firmware flash was performed.")
            self.editor_readiness.setPlainText(self.live_measurement_log + safety)
            if error == QProcess.ProcessError.FailedToStart:
                process.deleteLater()
                self.live_measurement_process = None
                self.live_measurement_trace_id = None
                self.live_measurement_operation = ""

        def live_measurement_finished(self, exit_code: int, _status: object) -> None:
            self.append_live_measurement_output()
            directory = self.live_measurement_directory
            trace_id = self.live_measurement_trace_id
            operation = self.live_measurement_operation
            lines = [self.live_measurement_log.rstrip(), "", f"Capture command exit code: {exit_code}."]
            if operation == "native-sequence" and directory is not None:
                try:
                    review = LiveMeasurementCampaign.read(directory).review_traces(directory)
                    native = [row for row in review["rows"] if str(row["id"]).startswith("native.")]
                    observed = sum(row["status"] == "observed" for row in native)
                    lines.extend([f"Native Scene/Palette evidence: {observed}/{len(native)} observed.", "", str(review["next"])])
                except (OSError, ValueError) as error:
                    lines.append(f"Could not review native-control evidence: {error}")
            elif directory is not None and trace_id is not None:
                try:
                    review = LiveMeasurementCampaign.read(directory).review_traces(directory)
                    row = next(item for item in review["rows"] if item["id"] == trace_id)
                    lines.extend([format_measurement_review_row(row), "", str(review["next"])])
                except (OSError, StopIteration, ValueError) as error:
                    lines.append(f"Could not review the captured trace: {error}")
            lines.append(
                "Restore Arduino OUT only after reviewing the probe report; the operation transmitted bounded diagnostic MIDI."
                if operation == "echo-probe" else
                "No MIDI output, module write, or firmware flash was performed."
            )
            self.editor_readiness.setPlainText("\n".join(lines))
            if self.live_measurement_process is not None:
                self.live_measurement_process.deleteLater()
            self.live_measurement_process = None
            self.live_measurement_trace_id = None
            self.live_measurement_operation = ""

        def review_live_measurement_campaign(self) -> None:
            """Render a read-only completeness report for one campaign folder."""
            directory = QFileDialog.getExistingDirectory(self, "Select live measurement campaign directory")
            if not directory:
                return
            try:
                review = LiveMeasurementCampaign.read(Path(directory)).review_traces(Path(directory))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot review measurement campaign", str(error)); return
            rows = review["rows"]
            observed = sum(row["status"] == "observed" for row in rows)
            lines = [f"Live trace review: {observed}/{len(rows)} isolated routes observed", f"Status: {review['status']}", ""]
            for row in rows:
                lines.append(format_measurement_review_row(row))
            lines.extend(["", str(review["next"]),
                          "This report is evidence only; it does not modify the rig or authorize a firmware flash."])
            self.editor_readiness.setPlainText("\n".join(lines))

        def promote_live_measurement_campaign(self) -> None:
            """Create a new live YAML only from complete, isolated evidence."""
            directory = QFileDialog.getExistingDirectory(self, "Select completed live measurement campaign directory")
            if not directory:
                return
            try:
                campaign = LiveMeasurementCampaign.read(Path(directory))
                review = campaign.review_traces(Path(directory))
                if review["status"] != "capture-complete-not-live":
                    raise ValueError("review must be capture-complete-not-live before creating a live profile")
                hihat_calibration, accepted = self.prompt_hihat_calibration(campaign, review)
                if not accepted:
                    return
                pressure_confirmation, accepted = self.prompt_pressure_confirmation(campaign, review)
                if not accepted:
                    return
                endpoints: dict[str, str] = {}
                transports: dict[str, str] = {}
                for identifier, source in campaign.project.sources.items():
                    value, accepted = QInputDialog.getText(
                        self, f"Measured {identifier} input", f"Exact operating-system MIDI input for {identifier} (C{source.channel}):"
                    )
                    if not accepted:
                        return
                    endpoints[identifier] = value.strip()
                    choices = ("din", "usb")
                    current = choices.index(source.primary) if source.primary in choices else 0
                    transport, accepted = QInputDialog.getItem(
                        self, f"{identifier} transport",
                        "How does this source reach the PC? Use din for the Arduino/UMC THRU, usb for a direct device port:",
                        choices, current, False,
                    )
                    if not accepted:
                        return
                    transports[identifier] = str(transport)
                control_endpoint, accepted = QInputDialog.getText(
                    self, "Measured control output", "Exact PC/Master-Merger MIDI output for CH15 logical controls:"
                )
                if not accepted:
                    return
                filename, _ = QFileDialog.getSaveFileName(
                    self, "Create new measured live rig project", str(Path(directory) / "rig-live.yaml"), "Rig projects (*.yaml *.yml)"
                )
                if not filename:
                    return
                output = campaign.promote_live(Path(directory), Path(filename), endpoints=endpoints,
                                               control_endpoint=control_endpoint.strip(), transports=transports,
                                               hihat_calibration=hihat_calibration,
                                               pressure_confirmation=pressure_confirmation)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot create measured live profile", str(error)); return
            self.editor_readiness.setPlainText(
                f"Created measured live profile: {output}\n\n"
                "No MIDI, SysEx, DDTi staging, Arduino generation, or flash occurred. Compile this file next; "
                "the compiler will continue to block firmware until expression/state-action gates are satisfied."
            )

        def promote_configured_live_profile(self) -> None:
            """Create the first flashable profile from configuration receipts."""
            project = Path(self.editor_project.text().strip())
            if not project.is_file():
                QMessageBox.warning(self, "No rig project", "Load the canonical rig project first."); return
            contract_name, _ = QFileDialog.getOpenFileName(
                self, "Select compiled source-note-contract.yaml", "", "YAML (*.yaml *.yml)"
            )
            if not contract_name:
                return
            ddti_name, _ = QFileDialog.getOpenFileName(
                self, "Select verified DDTi readback receipt", "", "JSON (*.json)"
            )
            if not ddti_name:
                return
            edrumin_name, _ = QFileDialog.getOpenFileName(
                self, "Select confirmed eDRUMin snapshot receipt", "", "JSON (*.json)"
            )
            if not edrumin_name:
                return
            try:
                campaign = LiveMeasurementCampaign.from_path(project)
                inventory = discover_midi_port_inventory()
                inputs, outputs = list(inventory["inputs"]), list(inventory["outputs"])
                defaults = {
                    "ddrum4": next((name for name in inputs if "UMC" in name), ""),
                    "ddti": next((name for name in inputs if "TriggerIO" in name), ""),
                    "edrumin": next((name for name in inputs if "eDrumIn" in name), ""),
                }
                endpoints: dict[str, str] = {}
                transports = {"ddrum4": "din", "ddti": "usb", "edrumin": "usb"}
                for source in campaign.project.sources:
                    value, accepted = QInputDialog.getText(
                        self, f"{source} live input", f"Exact MIDI input for {source}:", text=defaults.get(source, "")
                    )
                    if not accepted:
                        return
                    endpoints[source] = value.strip()
                control_default = next((name for name in outputs if "UMC" in name), "")
                control, accepted = QInputDialog.getText(
                    self, "Arduino control output", "Exact MIDI output feeding the Arduino/merger:", text=control_default
                )
                if not accepted:
                    return
                accepted = QMessageBox.question(
                    self, "Confirm configured expression contract",
                    "Use the prescribed first-flash hi-hat map (CC4 closed=127/open=0 and declared zones) "
                    "and configured active-hit Poly Aftertouch routes? Physical calibration and audible choke tests remain mandatory after pads are connected.",
                ) == QMessageBox.StandardButton.Yes
                if not accepted:
                    return
                filename, _ = QFileDialog.getSaveFileName(
                    self, "Create configured live rig project", str(project.parent / "greg-hybrid-r15-live.yaml"),
                    "Rig projects (*.yaml *.yml)"
                )
                if not filename:
                    return
                output = campaign.promote_configured(
                    Path(filename), endpoints=endpoints, transports=transports,
                    control_endpoint=control.strip(), source_contract=Path(contract_name),
                    ddti_receipt=Path(ddti_name), edrumin_receipt=Path(edrumin_name),
                    hihat_calibration=HihatCalibration(
                        127, 0, {
                            "ddrum4": {"hh.bow": (15, 47, 79, 111), "hh.edge": (31, 63, 95)},
                            "drumgizmo": {"hh.bow": (15, 47, 79, 111), "hh.edge": (21, 52, 74, 106)},
                        },
                    ),
                    pressure_confirmation=PressureConfirmation(frozenset({"ddrum4", "sd3"})),
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot create configured live profile", str(error)); return
            self.editor_readiness.setPlainText(
                f"Created flash-only configured profile: {output}\n"
                f"Evidence ledger: {output.with_suffix('.configuration-receipts.json')}\n\n"
                "No MIDI output or firmware flash occurred. Compile this profile, then use only the gated flash "
                "script. Live play stays blocked until post-flash pad traces create a hardware-verified profile."
            )

        def prompt_hihat_calibration(
            self,
            campaign: LiveMeasurementCampaign,
            review: dict[str, object],
        ) -> tuple[HihatCalibration | None, bool]:
            """Collect explicit measured endpoints and renderer thresholds.

            No proposed simulation boundary is pre-filled. The operator sees
            it only as a comparison and must type every reviewed value.
            """
            requirements = campaign.hihat_calibration_requirements(review)
            if requirements is None:
                return None, True
            observed_values = list(requirements["observed_values"])
            QMessageBox.information(
                self, "Measured hi-hat calibration required",
                f"The isolated CC{requirements['input_cc']} trace observed values "
                f"{min(observed_values)}..{max(observed_values)}.\n\n"
                "Confirm which observed endpoint is physically closed and open, then enter every normalized "
                "0..126 zone boundary. Proposed simulation values are shown only for comparison and are never accepted automatically."
            )
            input_closed, accepted = QInputDialog.getInt(
                self, "Hi-hat closed endpoint", "Observed CC value with the pedal physically closed:",
                max(observed_values), 0, 127, 1,
            )
            if not accepted:
                return None, False
            input_open, accepted = QInputDialog.getInt(
                self, "Hi-hat open endpoint", "Observed CC value with the pedal physically open:",
                min(observed_values), 0, 127, 1,
            )
            if not accepted:
                return None, False
            boundaries: dict[str, dict[str, tuple[int, ...]]] = {}
            for target_name, target in requirements["targets"].items():
                target_boundaries: dict[str, tuple[int, ...]] = {}
                for physical, articulation in target["articulations"].items():
                    count = int(articulation["count"])
                    proposed = ",".join(str(value) for value in articulation["proposed"]) or "none"
                    while True:
                        value, accepted = QInputDialog.getText(
                            self, f"{target_name} — {physical}",
                            f"Enter exactly {count} strictly ascending normalized boundaries (comma-separated).\n"
                            f"Proposed simulation values, not pre-filled: {proposed}",
                        )
                        if not accepted:
                            return None, False
                        try:
                            parsed = tuple(int(item.strip()) for item in value.split(",") if item.strip())
                            if (len(parsed) != count or not all(0 <= item < 127 for item in parsed)
                                    or any(right <= left for left, right in zip(parsed, parsed[1:]))):
                                raise ValueError
                        except ValueError:
                            QMessageBox.warning(
                                self, "Invalid hi-hat boundaries",
                                f"Enter exactly {count} ascending integers from 0 to 126.",
                            )
                            continue
                        target_boundaries[physical] = parsed
                        break
                boundaries[target_name] = target_boundaries
            try:
                return HihatCalibration(input_closed, input_open, boundaries), True
            except ValueError as error:
                QMessageBox.warning(self, "Invalid hi-hat calibration", str(error))
                return None, False

        def prompt_pressure_confirmation(
            self,
            campaign: LiveMeasurementCampaign,
            review: dict[str, object],
        ) -> tuple[PressureConfirmation | None, bool]:
            """Keep raw choke evidence separate from renderer acceptance."""
            requirements = campaign.pressure_confirmation_requirements(review)
            if requirements is None:
                return None, True
            routes = requirements["routes"]
            targets = requirements["targets"]
            details = "\n".join(
                f"• {item['source']}.{item['physical']} — {item['trace_id']}"
                for item in routes
            )
            answer = QMessageBox.question(
                self, "Confirm active-hit choke routing",
                "The traces below prove only that each source emitted one Note-On followed by same-note "
                "poly-aftertouch. They do not prove how DDrum4 or SD3 reacts.\n\n"
                f"Observed raw routes ({len(routes)}):\n{details}\n\n"
                f"Explicitly accept the configured active-hit aftertouch behavior for: {', '.join(targets)}?\n"
                "This enables those renderer routes in the generated live profile; their audible behavior must still "
                "be checked during the guided post-flash test.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None, False
            return PressureConfirmation(frozenset(targets)), True

        def save_editor_project(self) -> None:
            try:
                self._validate_editor_text()
                path = Path(self.editor_project.text().strip())
                temporary = path.with_suffix(path.suffix + ".save.tmp")
                if temporary.exists():
                    raise ValueError(f"remove stale save file first: {temporary}")
                temporary.write_text(self.project_document.toPlainText(), encoding="utf-8", newline="\n")
                temporary.replace(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot save rig project", str(error)); return
            self._invalidate_simulator_workspace()
            self.project.setText(str(path))
            self.editor_status.setText("Saved validated project. Compile explicitly to generate PC/Arduino artifacts.")

        def _virtual_kit_workspace(self) -> QWidget:
            """Visual operator workspace for one logical kit and its three renderers.

            This deliberately remains an offline control surface.  It uses the
            same rig-project selected in the editor, so the three output cards
            cannot silently display a different mapping from the compiler.
            """
            workspace = QWidget()
            layout = QVBoxLayout()
            title = QLabel("Virtual kit & signal simulator")
            title.setObjectName("workspaceTitle")
            layout.addWidget(title)
            subtitle = QLabel(
                "Un kit logique, trois renderers. Clique une articulation (double-clic) pour obtenir la trace exacte "
                "vers la banque DDrum4, SD3 et DrumGizmo. Les cartes sont un simulateur déterministe : aucun MIDI, "
                "audio ou module matériel n’est ouvert."
            )
            subtitle.setWordWrap(True); layout.addWidget(subtitle)
            self.studio_project_identity = QLabel("No active saved rig project.")
            self.studio_project_identity.setObjectName("projectIdentity")
            self.studio_project_identity.setWordWrap(True)
            layout.addWidget(self.studio_project_identity)

            controls = QGroupBox("Transport de simulation")
            controls_layout = QHBoxLayout()
            self.studio_source = QComboBox()
            self.studio_scene = QComboBox()
            self.studio_velocity = QSpinBox(); self.studio_velocity.setRange(1, 127); self.studio_velocity.setValue(100)
            self.studio_velocity.setPrefix("V ")
            load = QPushButton("Load virtual kit")
            load.clicked.connect(self.load_virtual_kit_workspace)
            trigger = QPushButton("▶ Trigger selected pad")
            trigger.setToolTip("Runs an offline trace with the selected source, state, pad and velocity.")
            trigger.clicked.connect(lambda _=False: self.trigger_virtual_kit_pad())
            reset = QPushButton("Reset state")
            reset.clicked.connect(self.reset_virtual_kit_state)
            panic = QPushButton("● Panic (simulated)")
            panic.setToolTip("Records an offline all-notes-off action. It does not emit MIDI.")
            panic.clicked.connect(self.virtual_kit_panic)
            for label, field in (("Raw source", self.studio_source), ("Scene", self.studio_scene), ("Velocity", self.studio_velocity)):
                controls_layout.addWidget(QLabel(label + ":")); controls_layout.addWidget(field)
            for value in (48, 80, 110, 127):
                velocity = QPushButton(str(value))
                velocity.setToolTip(f"Set simulation velocity to {value}")
                velocity.clicked.connect(lambda _=False, v=value: self.studio_velocity.setValue(v))
                controls_layout.addWidget(velocity)
            controls_layout.addWidget(load); controls_layout.addWidget(trigger); controls_layout.addWidget(reset); controls_layout.addWidget(panic)
            controls.setLayout(controls_layout); layout.addWidget(controls)
            self.studio_source.currentTextChanged.connect(self._studio_source_changed)
            self.studio_scene.currentTextChanged.connect(self._studio_scene_changed)

            state_group = QGroupBox("Logical state — Scene and virtual palettes")
            self.studio_variable_holder = QWidget()
            self.studio_variable_layout = QHBoxLayout()
            self.studio_variable_layout.setContentsMargins(2, 2, 2, 2)
            self.studio_variable_layout.addWidget(QLabel("Load a project to expose VP1–VP4 (or its declared state variables)."))
            self.studio_variable_layout.addStretch(1)
            self.studio_variable_holder.setLayout(self.studio_variable_layout)
            state_layout = QVBoxLayout(); state_layout.addWidget(self.studio_variable_holder); state_group.setLayout(state_layout)
            layout.addWidget(state_group)

            native_controls = QGroupBox("DDrum4 panel — native Program / Palette input")
            native_layout = QHBoxLayout()
            self.studio_native_control = QComboBox()
            self.studio_native_control.addItem("Load a project to expose native panel controls", None)
            native_trigger = QPushButton("▶ Apply panel control")
            native_trigger.setToolTip(
                "Decodes the selected Program/Palette exactly as if it came from the DDrum4 panel. "
                "The simulator never echoes it or opens MIDI."
            )
            native_trigger.clicked.connect(self.trigger_virtual_native_control)
            native_layout.addWidget(QLabel("Observed control:")); native_layout.addWidget(self.studio_native_control, 2)
            native_layout.addWidget(native_trigger); native_layout.addStretch(1)
            native_controls.setLayout(native_layout); layout.addWidget(native_controls)

            expressions = QGroupBox("Expression input — CC / aftertouch")
            expressions_layout = QHBoxLayout()
            self.studio_expression = QComboBox()
            self.studio_expression_value = QSpinBox(); self.studio_expression_value.setRange(0, 127); self.studio_expression_value.setValue(64); self.studio_expression_value.setPrefix("V ")
            expression_trigger = QPushButton("▶ Trigger expression")
            expression_trigger.setToolTip("Traces the selected declared CC/aftertouch route. It never writes MIDI.")
            expression_trigger.clicked.connect(self.trigger_virtual_expression)
            expressions_layout.addWidget(QLabel("Declared expression:")); expressions_layout.addWidget(self.studio_expression, 2)
            expressions_layout.addWidget(QLabel("Value:")); expressions_layout.addWidget(self.studio_expression_value)
            expressions_layout.addWidget(expression_trigger); expressions_layout.addStretch(1)
            expressions.setLayout(expressions_layout); layout.addWidget(expressions)

            body = QSplitter(Qt.Orientation.Horizontal)
            left = QWidget(); left_layout = QVBoxLayout()
            left_layout.addWidget(QLabel("Pads / articulations — use ▶ (or double-click a row) to route that articulation at the selected velocity. Raw input notes remain visible for all declared modules."))
            self.virtual_kit_table = QTableWidget(0, 8)
            self.virtual_kit_table.setHorizontalHeaderLabels((
                "Trigger @ velocity", "Physical event", "Hardware pad / zone", "Raw MIDI", "Logical sound", "DDrum4 bank", "SD3", "DrumGizmo",
            ))
            self.virtual_kit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.virtual_kit_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.virtual_kit_table.cellDoubleClicked.connect(lambda _row, _column: self.trigger_virtual_kit_pad())
            self.virtual_kit_table.setAlternatingRowColors(True)
            self.virtual_kit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.virtual_kit_table.horizontalHeader().setStretchLastSection(True)
            left_layout.addWidget(self.virtual_kit_table)
            coverage = QLabel("Coverage: DDrum4 bank note, SD3 MIDI note and DrumGizmo instrument/articulation must all be declared for a playable logical sound.")
            coverage.setWordWrap(True); left_layout.addWidget(coverage)
            left.setLayout(left_layout); body.addWidget(left)

            right = QWidget(); right_layout = QVBoxLayout()
            flow = QLabel("INPUT  →  LOGICAL KIT  →  DDrum4 BANK  +  SD3  +  DRUMGIZMO")
            flow.setObjectName("signalFlow")
            flow.setAlignment(Qt.AlignmentFlag.AlignCenter)
            right_layout.addWidget(flow)
            self.studio_cards: dict[str, QTextEdit] = {}
            cards_row = QHBoxLayout()
            for heading, object_name in (("Raw input", "rawStage"), ("Arduino → DDrum4", "ddrumStage"),
                                         ("SD3 reference", "sd3Stage"), ("DrumGizmo", "drumgizmoStage")):
                card = QGroupBox(heading)
                card.setObjectName(object_name)
                card_layout = QVBoxLayout(); output = QTextEdit(); output.setReadOnly(True); output.setMinimumHeight(235)
                output.setPlainText("No simulated event yet.")
                card_layout.addWidget(output); card.setLayout(card_layout)
                self.studio_cards[heading] = output
                cards_row.addWidget(card)
            right_layout.addLayout(cards_row)
            self.studio_route_summary = QLabel("Select a pad to inspect its three renderer destinations.")
            self.studio_route_summary.setObjectName("routeSummary")
            self.studio_route_summary.setWordWrap(True)
            right_layout.addWidget(self.studio_route_summary)
            right.setLayout(right_layout); body.addWidget(right)
            body.setStretchFactor(0, 5); body.setStretchFactor(1, 7); layout.addWidget(body, 5)

            log_group = QGroupBox("Event log — offline simulation")
            log_layout = QVBoxLayout()
            self.virtual_kit_log = QTableWidget(0, 9)
            self.virtual_kit_log.setHorizontalHeaderLabels(("Time", "Event", "Input", "Physical", "Logical", "Velocity", "DDrum4", "SD3", "DrumGizmo"))
            self.virtual_kit_log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.virtual_kit_log.setAlternatingRowColors(True)
            self.virtual_kit_log.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.virtual_kit_log.horizontalHeader().setStretchLastSection(True)
            clear_log = QPushButton("Clear event log")
            clear_log.clicked.connect(self.clear_virtual_kit_log)
            export_log = QPushButton("Export offline session…")
            export_log.setToolTip("Writes the exact simulated traces as JSON. It never captures or sends MIDI.")
            export_log.clicked.connect(self.export_virtual_kit_session)
            log_actions = QHBoxLayout(); log_actions.addWidget(clear_log); log_actions.addWidget(export_log); log_actions.addStretch(1)
            log_layout.addWidget(self.virtual_kit_log); log_layout.addLayout(log_actions); log_group.setLayout(log_layout)
            layout.addWidget(log_group, 2)
            self.virtual_kit_status = QLabel("Load a rig project from the editor, then load the virtual kit.")
            layout.addWidget(self.virtual_kit_status)
            workspace.setLayout(layout)
            return workspace

        def load_virtual_kit_workspace(self) -> None:
            try:
                simulator = self.current_simulator()
                self.studio_source.blockSignals(True); self.studio_source.clear(); self.studio_source.addItems(tuple(simulator.project.sources)); self.studio_source.blockSignals(False)
                self.studio_scene.blockSignals(True); self.studio_scene.clear(); self.studio_scene.addItems(simulator.project.scenes); self.studio_scene.setCurrentText(simulator.state["scene"]); self.studio_scene.blockSignals(False)
                self.studio_native_control.clear()
                for name, control in sorted(simulator.project.native_control_map.items()):
                    address_key = {"program_change": "program", "cc": "cc", "note": "note"}[control["type"]]
                    label = (f"{name}  ·  CH{control['channel']} {control['type']} {control[address_key]}  "
                             f"→ {control['decode_to']}={control['value']}")
                    self.studio_native_control.addItem(label, name)
                if self.studio_native_control.count() == 0:
                    self.studio_native_control.addItem("No native panel controls declared", None)
                self._rebuild_studio_variable_controls(simulator)
                self._refresh_studio_expression_choices(simulator)
                self._load_project_bank_reference(self._active_simulator_path or Path(), simulator.project.raw)
                self.refresh_virtual_kit_workspace()
                active_path = self._active_simulator_path
                if active_path is not None:
                    digest = sha256(active_path.read_bytes()).hexdigest()[:12]
                    self.studio_project_identity.setText(f"ACTIVE SAVED PROJECT  ·  {active_path}  ·  SHA-256 {digest}")
                self.virtual_kit_status.setText("Virtual kit loaded from the same saved rig project as the compiler.")
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot load virtual kit", str(error))

        def _studio_scene_changed(self, scene: str) -> None:
            if not scene or self._studio_state_syncing:
                return
            try:
                simulator = self.current_simulator()
                scene_index = simulator.project.scenes.index(scene)
                self._apply_virtual_logical_control("scene", scene_index)
            except (OSError, ValueError, SimulationError) as error:
                self.virtual_kit_status.setText(f"Scene change rejected: {error}")

        def _studio_source_changed(self, _source: str) -> None:
            try:
                simulator = self.current_simulator()
                self._refresh_studio_expression_choices(simulator)
                self.refresh_virtual_kit_workspace()
            except (OSError, ValueError, SimulationError):
                return

        def _refresh_studio_expression_choices(self, simulator: RigSimulator) -> None:
            """List CC/aftertouch routes for the selected raw module only."""
            source = self.studio_source.currentText()
            self.studio_expression.blockSignals(True)
            self.studio_expression.clear()
            for decoder in simulator.project.source_decoders:
                if decoder.source != source or decoder.message_type not in {"cc", "poly_aftertouch"}:
                    continue
                if decoder.message_type == "poly_aftertouch" and decoder.match.get("active_note"):
                    # Pressure/choke has no fixed note of its own: expose the
                    # exact raw hit(s) it may correlate with, rather than a
                    # meaningless placeholder ``0`` in the simulator UI.
                    primary_notes: list[int] = []
                    for primary in simulator.project.source_decoders:
                        if primary.source != source or primary.physical != decoder.physical:
                            continue
                        if primary.message_type == "note":
                            primary_notes.append(primary.match["note"])
                        elif primary.message_type == "note_range":
                            low, high = primary.match["note_range"]
                            primary_notes.extend(range(low, high + 1))
                    for data1 in sorted(set(primary_notes)):
                        label = f"{decoder.physical} · pressure active hit {data1}"
                        self.studio_expression.addItem(label, (decoder.message_type, data1, decoder.physical))
                    continue
                data1 = decoder.match.get("cc") if decoder.message_type == "cc" else decoder.match.get("note", 0)
                label = f"{decoder.physical} · {decoder.message_type} {data1}"
                self.studio_expression.addItem(label, (decoder.message_type, data1, decoder.physical))
            if self.studio_expression.count() == 0:
                self.studio_expression.addItem("No declared expression for this source", None)
            self.studio_expression.blockSignals(False)

        def _rebuild_studio_variable_controls(self, simulator: RigSimulator) -> None:
            """Expose exactly the project’s declared virtual-palette variables.

            The UI deliberately does not assume VP1–VP4 exist: a compact kit
            may declare one palette, while a larger kit can expose all four.
            Every control mutates only the offline simulator state.
            """
            while self.studio_variable_layout.count():
                item = self.studio_variable_layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            self._studio_variable_controls.clear()
            if not simulator.project.variables:
                self.studio_variable_layout.addWidget(QLabel("This project has no virtual-palette variables."))
            labels_by_variable = simulator.project.raw.get("state", {}).get("value_labels", {})
            for name in simulator.project.variables:
                label = QLabel(name.upper() + ":")
                labels = labels_by_variable.get(name, {}) if isinstance(labels_by_variable, dict) else {}
                if isinstance(labels, dict) and labels:
                    control = QComboBox()
                    for value, text in sorted(((int(value), str(text)) for value, text in labels.items())):
                        control.addItem(f"V{value} · {text}", value)
                    control.setCurrentIndex(max(0, control.findData(simulator.state[name])))
                    control.currentIndexChanged.connect(
                        lambda _index, variable=name, widget=control: self._studio_variable_changed(
                            variable, int(widget.currentData())
                        )
                    )
                else:
                    control = QSpinBox(); control.setRange(0, 127); control.setValue(simulator.state[name]); control.setPrefix("V ")
                    control.valueChanged.connect(lambda value, variable=name: self._studio_variable_changed(variable, value))
                control.setToolTip(f"Offline value for {name}. It is applied to the logical route matrix.")
                self._studio_variable_controls[name] = control
                self.studio_variable_layout.addWidget(label); self.studio_variable_layout.addWidget(control)
            self.studio_variable_layout.addStretch(1)

        @staticmethod
        def _set_studio_variable_control(control: QSpinBox | QComboBox, value: int) -> None:
            if isinstance(control, QComboBox):
                index = control.findData(value)
                if index >= 0:
                    control.setCurrentIndex(index)
            else:
                control.setValue(value)

        def _studio_variable_changed(self, variable: str, value: int) -> None:
            if self._studio_state_syncing:
                return
            try:
                self._apply_virtual_logical_control(variable, value)
            except (OSError, ValueError, SimulationError) as error:
                self.virtual_kit_status.setText(f"Virtual-palette change rejected: {error}")

        def _apply_virtual_logical_control(self, target: str, value: int) -> None:
            """Apply one visible Scene/VP control through the declared protocol.

            This is intentionally not a direct state mutation when a protocol
            exists: the operator sees the exact PC/CC command, control-bus
            safety status, and any DDrum4 reconciliation action in the same
            trace as a pad hit.  Sparse/offline projects without a protocol
            remain inspectable, but are labelled as local-only state edits.
            """
            simulator = self.current_simulator()
            control = simulator.project.logical_control_protocol.get(target)
            if control is None:
                if target == "scene":
                    simulator.set_state(scene=simulator.project.scenes[value])
                else:
                    simulator.set_state(values={target: value})
                self.refresh_virtual_kit_workspace()
                self._append_virtual_kit_status("Local state", target, f"{target}={value}; no logical MIDI control is declared")
                self.virtual_kit_status.setText(f"Local-only state: {target}={value}. No MIDI control is declared.")
                return
            channel = control["channels"][0]
            message_type = control["type"]
            data1 = value if message_type == "program_change" else control["cc"]
            result = simulator.simulate_logical_control("simulator", channel, message_type, data1, value)
            self._present_virtual_state_change(target, result)
            self.refresh_virtual_kit_workspace()

        def _present_virtual_state_change(self, target: str, result: object) -> None:
            """Render a state-command trace in the four simulator stages."""
            state = getattr(result, "state")
            self._studio_state_syncing = True
            try:
                self.studio_scene.setCurrentText(str(state["scene"]))
                for name, control in self._studio_variable_controls.items():
                    self._set_studio_variable_control(control, int(state[name]))
            finally:
                self._studio_state_syncing = False
            by_stage = {step.stage: step for step in result.steps}
            self.studio_cards["Raw input"].setPlainText(
                self._format_studio_card(by_stage, ("logical control", "Arduino state"))
            )
            self.studio_cards["Arduino → DDrum4"].setPlainText(
                self._format_studio_card(by_stage, ("control bus", "Arduino DDrum4 state"))
            )
            state_text = "Logical state is shared by all renderer resolutions; no hit was triggered."
            self.studio_cards["SD3 reference"].setPlainText(state_text)
            self.studio_cards["DrumGizmo"].setPlainText(state_text)
            event_name = "Scene" if target == "scene" else "Palette"
            self.studio_route_summary.setText(
                f"{event_name} control applied  |  " + " · ".join(f"{name}={value}" for name, value in state.items()) +
                "  |  subsequent pad hits resolve through this logical-kit state"
            )
            self._append_virtual_state_event(event_name, target, result)
            self.virtual_kit_status.setText(
                f"Offline {event_name.lower()} control traced. No MIDI, SysEx, or hardware action was emitted."
            )

        def refresh_virtual_kit_workspace(self) -> None:
            try:
                simulator = self.current_simulator()
            except (OSError, ValueError, SimulationError):
                return
            scene = self.studio_scene.currentText()
            if scene:
                simulator.set_state(scene=scene)
            self._studio_state_syncing = True
            try:
                for name, control in self._studio_variable_controls.items():
                    self._set_studio_variable_control(control, simulator.state[name])
            finally:
                self._studio_state_syncing = False
            self._studio_rows = build_virtual_kit(simulator)
            self._studio_velocity_sliders.clear()
            self.virtual_kit_table.setRowCount(len(self._studio_rows))
            for row, kit_row in enumerate(self._studio_rows):
                logical = kit_row.logical_sound or "MISSING"
                ddrum_text = (f"S{kit_row.ddrum4_slot} {kit_row.ddrum4_sound_id} · P{kit_row.ddrum4_note_p} · "
                              f"{len(kit_row.ddrum4_layer_candidates)} layer candidate(s) · "
                              f"C{simulator.project.ddrum4_output_channel} N{kit_row.ddrum4_note}"
                              + (" · position → " + "/".join(str(note) for note in kit_row.ddrum4_position_notes)
                                 if kit_row.ddrum4_position_notes else "")
                              if kit_row.ddrum4_note is not None and kit_row.ddrum4_sound_id else
                              (f"C{simulator.project.ddrum4_output_channel} · note {kit_row.ddrum4_note}" if kit_row.ddrum4_note is not None else "MISSING"))
                sd3_text = (
                    f"C{kit_row.sd3_channel} · "
                    + (f"CC{kit_row.sd3_position_cc} position + " if kit_row.sd3_position_cc is not None else "")
                    + "notes "
                    + "+".join(str(note) for note in (kit_row.sd3_note, *kit_row.sd3_layers))
                    if kit_row.sd3_note is not None else "MISSING"
                )
                gizmo_text = (f"{kit_row.drumgizmo_instrument} / {kit_row.drumgizmo_articulation} · note {kit_row.drumgizmo_note}"
                              if kit_row.drumgizmo_note is not None and kit_row.drumgizmo_instrument and kit_row.drumgizmo_articulation else "MISSING")
                values = (kit_row.physical, kit_row.hardware_summary, kit_row.raw_note_summary,
                          logical, ddrum_text, sd3_text, gizmo_text)
                trigger_holder = QWidget()
                trigger_layout = QHBoxLayout()
                trigger_layout.setContentsMargins(2, 1, 2, 1)
                trigger = QPushButton("▶")
                trigger.setObjectName("padTrigger")
                trigger.setToolTip(f"Simulate {kit_row.physical} at the selected velocity")
                velocity = QSlider(Qt.Orientation.Horizontal)
                velocity.setRange(1, 127)
                velocity.setValue(self.studio_velocity.value())
                velocity.setMinimumWidth(105)
                velocity.setToolTip(f"{kit_row.physical}: release to trigger at this velocity")
                velocity.valueChanged.connect(lambda value, control=trigger: control.setText(f"▶ {value}"))
                velocity.sliderReleased.connect(
                    lambda index=row, control=velocity: self._trigger_virtual_kit_row(index, control.value())
                )
                trigger.setText(f"▶ {velocity.value()}")
                trigger.clicked.connect(
                    lambda _=False, index=row, control=velocity: self._trigger_virtual_kit_row(index, control.value())
                )
                trigger_layout.addWidget(trigger)
                trigger_layout.addWidget(velocity, 1)
                trigger_container = QVBoxLayout()
                trigger_container.setContentsMargins(0, 0, 0, 0)
                trigger_container.addLayout(trigger_layout)
                source = self.studio_source.currentText()
                raw_range = kit_row.raw_note_ranges.get(source)
                if raw_range is not None:
                    position_layout = QHBoxLayout()
                    position_layout.setContentsMargins(0, 0, 0, 0)
                    low, high = raw_range
                    for position_index, raw_note in enumerate(range(low, high + 1), start=1):
                        position = QPushButton(f"P{position_index}")
                        position.setObjectName("positionTrigger")
                        normalized = ((raw_note - low) * 127) // (high - low)
                        position.setToolTip(
                            f"Trigger {kit_row.physical} raw note {raw_note}; normalized position {normalized}/127"
                        )
                        position.clicked.connect(
                            lambda _=False, index=row, note=raw_note, control=velocity:
                            self._trigger_virtual_kit_row(index, control.value(), note)
                        )
                        position_layout.addWidget(position)
                    trigger_container.addLayout(position_layout)
                trigger_holder.setLayout(trigger_container)
                self._studio_velocity_sliders.append(velocity)
                self.virtual_kit_table.setCellWidget(row, 0, trigger_holder)
                for column, value in enumerate(values, start=1):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if column == 5:
                        item.setToolTip(kit_row.ddrum4_content_summary)
                    if value == "MISSING":
                        item.setBackground(Qt.GlobalColor.darkRed)
                    self.virtual_kit_table.setItem(row, column, item)
            self.virtual_kit_table.resizeColumnsToContents()
            self.virtual_kit_table.resizeRowsToContents()
            if self.virtual_kit_table.rowCount() and self.virtual_kit_table.currentRow() < 0:
                self.virtual_kit_table.selectRow(0)

        def _trigger_virtual_kit_row(self, row: int, velocity: int, raw_note: int | None = None) -> None:
            """Trigger one visible row directly from its local velocity strip."""
            if row < 0 or row >= self.virtual_kit_table.rowCount():
                return
            self.virtual_kit_table.selectRow(row)
            self.studio_velocity.setValue(velocity)
            self.trigger_virtual_kit_pad(raw_note)

        def trigger_virtual_kit_pad(self, raw_note: int | None = None) -> None:
            row = self.virtual_kit_table.currentRow()
            if row < 0 or row >= len(self._studio_rows):
                self.virtual_kit_status.setText("Select a declared pad/articulation first."); return
            source = self.studio_source.currentText()
            kit_row = self._studio_rows[row]
            if source not in kit_row.raw_notes:
                self.virtual_kit_status.setText(f"{kit_row.physical} has no exact Note-On decoder for {source}."); return
            try:
                simulator = self.current_simulator()
                simulator.set_state(scene=self.studio_scene.currentText() or None)
                selected_note = kit_row.raw_notes[source] if raw_note is None else raw_note
                result = simulator.simulate_pad(source, selected_note, self.studio_velocity.value())
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot trigger virtual pad", str(error)); return
            by_stage = {step.stage: step for step in result.steps}
            self.studio_cards["Raw input"].setPlainText(self._format_studio_card(by_stage, ("raw MIDI", "source profile", "logical state", "logical sound")))
            ddrum_card = self._format_studio_card(by_stage, ("Arduino DDrum4 renderer", "DDrum4 declared target", "DDrum4 echo guard"))
            self.studio_cards["Arduino → DDrum4"].setPlainText(ddrum_card + "\n\nBank content\n" + kit_row.ddrum4_content_summary)
            self.studio_cards["SD3 reference"].setPlainText(self._format_studio_card(by_stage, ("SD3 renderer", "SD3 declared target")))
            self.studio_cards["DrumGizmo"].setPlainText(self._format_studio_card(by_stage, ("DrumGizmo renderer", "DrumGizmo declared target")))
            self.studio_route_summary.setText(
                f"{result.physical}  →  {result.logical_target}  |  source {result.source}, raw note {result.raw_note}, velocity {result.velocity}  |  "
                "three declared destinations resolved; this offline trace does not prove audio playback"
            )
            self._append_virtual_kit_event(result)
            self.virtual_kit_status.setText(f"Offline route resolved: {result.physical} → {result.logical_target}. No MIDI or audio was emitted.")

        def trigger_virtual_native_control(self) -> None:
            name = self.studio_native_control.currentData()
            if not isinstance(name, str):
                self.virtual_kit_status.setText("This project declares no native DDrum4 panel control.")
                return
            try:
                simulator = self.current_simulator()
                result = simulator.simulate_native_control(name)
                target = simulator.project.native_control_map[name]["decode_to"]
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot apply DDrum4 panel control", str(error)); return
            self._present_virtual_state_change(target, result)
            self.refresh_virtual_kit_workspace()
            self.virtual_kit_status.setText(
                f"Native panel control {name!r} decoded offline without MIDI echo or hardware output."
            )

        def trigger_virtual_expression(self) -> None:
            data = self.studio_expression.currentData()
            if not isinstance(data, tuple) or len(data) != 3:
                self.virtual_kit_status.setText("The selected raw source has no declared expression route.")
                return
            message_type, data1, physical = data
            try:
                simulator = self.current_simulator()
                simulator.set_state(scene=self.studio_scene.currentText() or None)
                result = simulator.simulate_expression(self.studio_source.currentText(), str(message_type), int(data1),
                                                       self.studio_expression_value.value())
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot trigger virtual expression", str(error)); return
            by_stage = {step.stage: step for step in result.steps}
            self.studio_cards["Raw input"].setPlainText(self._format_studio_card(by_stage, ("raw MIDI", "source profile", "logical state", "logical sound")))
            self.studio_cards["Arduino → DDrum4"].setPlainText(self._format_studio_card(by_stage, ("Arduino DDrum4 renderer",)))
            self.studio_cards["SD3 reference"].setPlainText(self._format_studio_card(by_stage, ("SD3 renderer", "SD3 declared target")))
            self.studio_cards["DrumGizmo"].setPlainText(self._format_studio_card(by_stage, ("DrumGizmo renderer",)))
            self.studio_route_summary.setText(
                f"{physical} expression  |  source {result.source}, value {result.velocity}  |  "
                "renderer capability is shown explicitly; planned and unsupported outputs are not emitted"
            )
            self._append_virtual_expression_event(result)
            self.virtual_kit_status.setText("Offline expression trace completed. No MIDI or audio was emitted.")

        @staticmethod
        def _format_studio_card(by_stage: dict[str, object], stages: tuple[str, ...]) -> str:
            lines: list[str] = []
            for name in stages:
                step = by_stage.get(name)
                if step is None:
                    continue
                detail = getattr(step, "detail")
                message = getattr(step, "message")
                lines.append(name + "\n" + detail)
                if message:
                    lines.append("  " + " · ".join(f"{key}={value}" for key, value in message.items()))
            return "\n\n".join(lines) or "No declared destination."

        def _append_virtual_kit_event(self, result: object) -> None:
            # The cards and chronological log both derive from the canonical
            # trace. Do not look up the renderer map a second time here: a
            # future transform could otherwise make the two views disagree.
            by_stage = {step.stage: step for step in result.steps}
            ddrum_message = getattr(by_stage.get("Arduino DDrum4 renderer"), "message", {}) or {}
            sd3_message = getattr(by_stage.get("SD3 renderer"), "message", {}) or {}
            gizmo_message = getattr(by_stage.get("DrumGizmo renderer"), "message", {}) or {}
            ddrum = f"C{ddrum_message.get('channel', '—')} N{ddrum_message.get('note', '—')}"
            sd3 = f"C{sd3_message.get('channel', '—')} N{sd3_message.get('note', '—')}"
            gizmo = f"{gizmo_message.get('instrument', '—')}/{gizmo_message.get('articulation', '—')} · N{gizmo_message.get('note', '—')}"
            row = self.virtual_kit_log.rowCount(); self.virtual_kit_log.insertRow(row)
            values = (datetime.now().strftime("%H:%M:%S.%f")[:-3], "Note On", result.source, result.physical,
                      result.logical_target, result.velocity, ddrum, sd3, gizmo)
            for column, value in enumerate(values): self.virtual_kit_log.setItem(row, column, QTableWidgetItem(str(value)))
            self._studio_events.append(result.to_document())
            self.virtual_kit_log.scrollToBottom(); self.virtual_kit_log.resizeColumnsToContents()

        def _append_virtual_expression_event(self, result: object) -> None:
            by_stage = {step.stage: step for step in result.steps}
            ddrum = getattr(by_stage.get("Arduino DDrum4 renderer"), "detail", "—")
            sd3_step = by_stage.get("SD3 renderer")
            sd3_message = getattr(sd3_step, "message", None)
            sd3 = " · ".join(f"{key}={value}" for key, value in sd3_message.items()) if sd3_message else getattr(sd3_step, "detail", "—")
            gizmo = getattr(by_stage.get("DrumGizmo renderer"), "detail", "—")
            row = self.virtual_kit_log.rowCount(); self.virtual_kit_log.insertRow(row)
            values = (datetime.now().strftime("%H:%M:%S.%f")[:-3], result.raw_type, result.source, result.physical,
                      result.logical_target, result.velocity, ddrum, sd3, gizmo)
            for column, value in enumerate(values):
                self.virtual_kit_log.setItem(row, column, QTableWidgetItem(str(value)))
            self._studio_events.append(result.to_document())
            self.virtual_kit_log.scrollToBottom(); self.virtual_kit_log.resizeColumnsToContents()

        def _append_virtual_state_event(self, event_name: str, target: str, result: object) -> None:
            """Keep control changes in the same chronological session as hits.

            The DDrum4 column preserves the declared Program Change/SysEx
            action (including its confirmation status).  SD3 and DrumGizmo do
            not receive a synthetic MIDI event: they share the selected
            logical state and will use it on the next triggered pad.
            """
            by_stage = {step.stage: step for step in result.steps}
            ddrum_step = by_stage.get("Arduino DDrum4 state")
            ddrum_message = getattr(ddrum_step, "message", None)
            if ddrum_message:
                ddrum = " · ".join(f"{key}={value}" for key, value in ddrum_message.items())
            else:
                ddrum = getattr(ddrum_step, "detail", "no DDrum4 action")
            state = getattr(result, "state")
            state_text = " · ".join(f"{name}={value}" for name, value in state.items())
            row = self.virtual_kit_log.rowCount(); self.virtual_kit_log.insertRow(row)
            values = (datetime.now().strftime("%H:%M:%S.%f")[:-3], event_name, getattr(result, "source"), target,
                      state_text, "—", ddrum, "logical state", "logical state")
            for column, value in enumerate(values):
                self.virtual_kit_log.setItem(row, column, QTableWidgetItem(str(value)))
            self._studio_events.append(result.to_document())
            self.virtual_kit_log.scrollToBottom(); self.virtual_kit_log.resizeColumnsToContents()

        def reset_virtual_kit_state(self) -> None:
            self.reset_simulator()
            self.load_virtual_kit_workspace()
            self.virtual_kit_status.setText("State reset to the rig project defaults. No MIDI was sent.")

        def virtual_kit_panic(self) -> None:
            self._append_virtual_kit_status("Panic", "All Notes Off", "simulation only")
            self.virtual_kit_status.setText("Panic recorded in the simulator only. No hardware MIDI was emitted.")

        def _append_virtual_kit_status(self, source: str, physical: str, detail: str) -> None:
            row = self.virtual_kit_log.rowCount(); self.virtual_kit_log.insertRow(row)
            values = (datetime.now().strftime("%H:%M:%S.%f")[:-3], "System", source, physical, "—", "—", "—", "—", detail)
            for column, value in enumerate(values): self.virtual_kit_log.setItem(row, column, QTableWidgetItem(value))
            self._studio_events.append({"kind": "drum-chain-simulation-status/v1", "hardware_io": "disabled",
                                        "source": source, "physical": physical, "detail": detail})
            self.virtual_kit_log.scrollToBottom()

        def clear_virtual_kit_log(self) -> None:
            self.virtual_kit_log.setRowCount(0)
            self._studio_events.clear()
            self.virtual_kit_status.setText("Offline event log cleared.")

        def export_virtual_kit_session(self) -> None:
            """Persist only the already-produced offline trace, never MIDI data from a port."""
            if not self._studio_events:
                self.virtual_kit_status.setText("Trigger at least one simulated event before exporting a session.")
                return
            filename, _ = QFileDialog.getSaveFileName(self, "Export offline simulation session", "simulation-session.json",
                                                       "JSON (*.json)")
            if not filename:
                return
            try:
                simulator = self.current_simulator()
                output = Path(filename)
                payload = {
                    "kind": "drum-chain-simulation-session/v1", "hardware_io": "disabled",
                    "project": simulator.project.project, "state": dict(simulator.state),
                    "events": self._studio_events,
                }
                output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot export simulation session", str(error)); return
            self.virtual_kit_status.setText(f"Offline simulation session exported: {output}")

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
            self.sd3_midi_map = QLineEdit("Kit_Metalcore_MidiMapping_Capture_V1")
            self.sd3_midi_map.setPlaceholderText("Exact SD3 MIDI Mapping preset")
            self.sd3_preset_file = QLineEdit(); self.sd3_preset_file.setPlaceholderText("Exact generated .sd3p used by this campaign")
            choose_preset = QPushButton("Select .sd3p…"); choose_preset.clicked.connect(self.select_sd3_preset_file)
            self.capture_midi_output = QLineEdit(); self.capture_midi_output.setPlaceholderText("SD3 MIDI input / virtual port name")
            self.capture_audio_input = QLineEdit(); self.capture_audio_input.setPlaceholderText("for example: loopback:OUT 3-4 (BEHRINGER UMC 404HD 192k)")
            self.capture_channels = QLineEdit("left,right")
            for label, field in (("Campaign ID:", self.campaign_id), ("SD3 MegaKit / preset:", self.sd3_preset),
                                 ("SD3 MIDI map:", self.sd3_midi_map),
                                 ("MIDI output:", self.capture_midi_output), ("Audio input:", self.capture_audio_input),
                                 ("Capture channels:", self.capture_channels)):
                row = QHBoxLayout(); row.addWidget(QLabel(label)); row.addWidget(field); setup_layout.addLayout(row)
            row = QHBoxLayout(); row.addWidget(QLabel("Fingerprint preset file:")); row.addWidget(self.sd3_preset_file); row.addWidget(choose_preset)
            setup_layout.addLayout(row)
            setup.setLayout(setup_layout); layout.addWidget(setup)

            grid = QGroupBox("2. Complete articulation inventory")
            grid_layout = QVBoxLayout()
            grid_layout.addWidget(QLabel(
                "One row is one SD3 articulation. Review MIDI notes against the loaded kit before creating the campaign. "
                "The starter grid is only a starting point, not proof of your SD3 mapping."
            ))
            self.capture_rows = QTableWidget(0, 8)
            self.capture_rows.setHorizontalHeaderLabels((
                "Instrument", "Articulation", "SD3 note", "Velocities", "Round robins", "Channel",
                "Controllers", "DrumGizmo note",
            ))
            self.capture_rows.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.capture_rows.setAlternatingRowColors(True)
            self.capture_rows.verticalHeader().setVisible(False)
            self.capture_rows.horizontalHeader().setStretchLastSection(True)
            grid_layout.addWidget(self.capture_rows)
            complete = QPushButton("Load complete MegaKit plan…")
            complete.setToolTip("Loads every distinct captured note, velocity layer and round-robin count from the reviewed MegaKit plan.")
            complete.clicked.connect(self.load_complete_megakit_plan)
            starter = QPushButton("Load starter grid"); starter.clicked.connect(self.load_starter_grid)
            v1_additions = QPushButton("Add V1 Metalcore/electronic additions")
            v1_additions.setToolTip("Adds the architecture-defined electronic/perc capture rows without replacing the current inventory.")
            v1_additions.clicked.connect(self.add_v1_electronic_additions)
            add_row = QPushButton("Add articulation"); add_row.clicked.connect(self.add_capture_row)
            remove_row = QPushButton("Remove selected articulation"); remove_row.clicked.connect(self.remove_capture_row)
            row = QHBoxLayout(); row.addWidget(complete); row.addWidget(starter); row.addWidget(v1_additions); row.addWidget(add_row); row.addWidget(remove_row); grid_layout.addLayout(row)
            grid.setLayout(grid_layout); layout.addWidget(grid)

            actions = QGroupBox("3. Guided campaign actions")
            actions_layout = QVBoxLayout()
            create = QPushButton("Create new campaign and capture session")
            create.setToolTip("Writes campaign.json and capture-session.json only. It never opens MIDI or audio devices.")
            create.clicked.connect(self.create_campaign); actions_layout.addWidget(create)
            open_campaign = QPushButton("Open existing campaign…"); open_campaign.clicked.connect(self.open_campaign); actions_layout.addWidget(open_campaign)
            status = QGroupBox("Campaign readiness")
            status_layout = QVBoxLayout()
            self.campaign_status = QLabel("No campaign is open.")
            self.campaign_status.setWordWrap(True)
            self.campaign_status.setStyleSheet("font-size: 15px; font-weight: 600; padding: 6px;")
            status_layout.addWidget(self.campaign_status)
            summary = QGridLayout()
            self.campaign_capture_summary = QLabel("Raw takes\n—")
            self.campaign_calibration_summary = QLabel("Calibration\nNot run")
            self.campaign_output_summary = QLabel("Outputs\n—")
            self.campaign_outlier_summary = QLabel("Attention\nNone")
            for column, card in enumerate((self.campaign_capture_summary, self.campaign_calibration_summary,
                                           self.campaign_output_summary, self.campaign_outlier_summary)):
                card.setWordWrap(True)
                card.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                card.setStyleSheet("border: 1px solid palette(mid); border-radius: 5px; padding: 8px;")
                summary.addWidget(card, 0, column)
            status_layout.addLayout(summary)
            self.calibration_groups = QTableWidget(0, 6)
            self.calibration_groups.setHorizontalHeaderLabels((
                "Comparable family", "Articulations", "Quietest peak", "Loudest peak", "Span", "Outliers",
            ))
            self.calibration_groups.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.calibration_groups.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.calibration_groups.setAlternatingRowColors(True)
            self.calibration_groups.verticalHeader().setVisible(False)
            self.calibration_groups.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for column in range(1, 6):
                self.calibration_groups.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            self.calibration_groups.setMinimumHeight(210)
            status_layout.addWidget(self.calibration_groups)
            status.setLayout(status_layout)
            actions_layout.addWidget(status)
            self.campaign_calibrate_button = QPushButton("Run SD3 signal calibration…")
            self.campaign_calibrate_button.setToolTip("Captures one short representative hit per articulation and reports silence, clipping, headroom and level spread before the full campaign.")
            self.campaign_calibrate_button.clicked.connect(lambda: self.run_campaign_action("calibrate")); actions_layout.addWidget(self.campaign_calibrate_button)
            self.campaign_capture_button = QPushButton("Capture pending takes…")
            self.campaign_capture_button.setToolTip("Enabled only after a complete, current, passing calibration v2.")
            self.campaign_capture_button.clicked.connect(lambda: self.run_campaign_action("capture")); actions_layout.addWidget(self.campaign_capture_button)
            self.campaign_quality_button = QPushButton("Run quality review")
            self.campaign_quality_button.clicked.connect(lambda: self.run_campaign_action("audit-quality")); actions_layout.addWidget(self.campaign_quality_button)
            self.campaign_composite_button = QPushButton("Capture simultaneous layered centers…")
            self.campaign_composite_button.setToolTip("Captures the approved multi-note SD3 snare centers directly, preserving one coherent attack for DrumGizmo.")
            self.campaign_composite_button.clicked.connect(lambda: self.run_campaign_action("capture-composites")); actions_layout.addWidget(self.campaign_composite_button)
            self.note_map = QLineEdit(); self.note_map.setPlaceholderText("Compiled drumgizmo-midimap.json for export")
            choose_map = QPushButton("Select DrumGizmo note map…"); choose_map.clicked.connect(self.select_note_map)
            row = QHBoxLayout(); row.addWidget(self.note_map); row.addWidget(choose_map); actions_layout.addLayout(row)
            self.export_megakit_plan = QLineEdit(); self.export_megakit_plan.setPlaceholderText("Required MegaKit plan for HH positions and shared variations")
            choose_plan = QPushButton("Select MegaKit plan…"); choose_plan.clicked.connect(self.select_export_megakit_plan)
            row = QHBoxLayout(); row.addWidget(self.export_megakit_plan); row.addWidget(choose_plan); actions_layout.addLayout(row)
            self.campaign_export_button = QPushButton("Export complete DrumGizmo kit")
            self.campaign_export_button.clicked.connect(lambda: self.run_campaign_action("export-drumgizmo")); actions_layout.addWidget(self.campaign_export_button)
            self.campaign_validate_button = QPushButton("Validate exported DrumGizmo files")
            self.campaign_validate_button.setToolTip("Validates XML, WAV channel references, mappings and records a SHA-256 manifest without requiring DrumGizmo.")
            self.campaign_validate_button.clicked.connect(lambda: self.run_campaign_action("validate-drumgizmo")); actions_layout.addWidget(self.campaign_validate_button)
            self.campaign_verify_button = QPushButton("Probe installed DrumGizmo host")
            self.campaign_verify_button.clicked.connect(lambda: self.run_campaign_action("verify-drumgizmo")); actions_layout.addWidget(self.campaign_verify_button)
            for button in (self.campaign_calibrate_button, self.campaign_capture_button,
                           self.campaign_quality_button, self.campaign_composite_button, self.campaign_export_button,
                           self.campaign_validate_button, self.campaign_verify_button):
                button.setEnabled(False)
            actions.setLayout(actions_layout); layout.addWidget(actions)

            self.campaign_log = QTextEdit(); self.campaign_log.setReadOnly(True); layout.addWidget(self.campaign_log)
            workspace.setLayout(layout)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(workspace)
            return scroll

        def select_campaign_root(self) -> None:
            directory = QFileDialog.getExistingDirectory(self, "Select parent directory for SD3 campaigns")
            if directory:
                self.campaign_root.setText(directory)

        def select_sd3_preset_file(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select the generated SD3 MegaKit", "", "SD3 presets (*.sd3p)",
            )
            if filename:
                self.sd3_preset_file.setText(filename)

        def select_note_map(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select compiled DrumGizmo note map", "", "JSON files (*.json)")
            if filename:
                self.note_map.setText(filename)

        def select_export_megakit_plan(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select SD3 MegaKit plan", "", "YAML files (*.yaml *.yml)")
            if filename:
                self.export_megakit_plan.setText(filename)

        def add_capture_row(self, row: CaptureRow | None = None) -> None:
            values = row or CaptureRow("instrument", "articulation", 36, (24, 48, 72, 96, 120), 3)
            index = self.capture_rows.rowCount()
            self.capture_rows.insertRow(index)
            cells = (values.instrument, values.articulation, str(values.note),
                     ",".join(str(value) for value in values.velocities), str(values.repetitions), str(values.channel),
                     ",".join(f"{controller}={value}" for controller, value in values.controllers),
                     "" if values.drumgizmo_note is None else str(values.drumgizmo_note))
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

        def load_complete_megakit_plan(self) -> None:
            default = Path(__file__).resolve().parents[4] / "profiles" / "sd3" / "metalcore-r15-megakit-plan.yaml"
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select reviewed SD3 MegaKit plan", str(default), "YAML files (*.yaml *.yml)"
            )
            if not filename:
                return
            if self.capture_rows.rowCount() and QMessageBox.question(
                    self, "Replace inventory", "Replace the current inventory with the complete reviewed MegaKit capture grid?") != QMessageBox.StandardButton.Yes:
                return
            try:
                rows = capture_rows_from_megakit_plan(Path(filename))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot load MegaKit plan", str(error)); return
            self.capture_rows.setRowCount(0)
            for capture_row in rows:
                self.add_capture_row(capture_row)
            self.export_megakit_plan.setText(filename)
            self.campaign_log.setPlainText(
                f"Loaded {len(rows)} capture articulations from {filename}, including explicit CC4 hi-hat positions. "
                f"Total planned takes: {sum(len(row.raw_filenames()) for row in rows)}."
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
                    controllers: list[tuple[int, int]] = []
                    for assignment in (value.strip() for value in cell(6).split(",") if value.strip()):
                        controller, separator, value = assignment.partition("=")
                        if not separator:
                            raise ValueError("controllers must use CC=VALUE, for example 4=127")
                        controllers.append((int(controller), int(value)))
                    drumgizmo_note = int(cell(7)) if cell(7) else None
                    rows.append(CaptureRow(
                        cell(0), cell(1), int(cell(2)), velocities, int(cell(4)), int(cell(5)),
                        tuple(controllers), drumgizmo_note,
                    ))
                except ValueError as error:
                    raise ValueError(f"invalid articulation row {index + 1}: {error}") from error
            return tuple(rows)

        def _campaign_from_form(self) -> Sd3CaptureCampaign:
            channels = tuple(value.strip() for value in self.capture_channels.text().split(",") if value.strip())
            preset_file, preset_sha256 = fingerprint_sd3_preset(Path(self.sd3_preset_file.text().strip()))
            return Sd3CaptureCampaign(
                identifier=self.campaign_id.text().strip(), sd3_preset=self.sd3_preset.text().strip(),
                sd3_midi_map=self.sd3_midi_map.text().strip(),
                midi_output=self.capture_midi_output.text().strip(), audio_input=self.capture_audio_input.text().strip(),
                channels=channels, rows=self._rows_from_table(), sd3_preset_file=preset_file,
                sd3_preset_sha256=preset_sha256,
                megakit_plan_file=(str(Path(self.export_megakit_plan.text().strip()).expanduser().resolve())
                                   if self.export_megakit_plan.text().strip() else None),
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
            self.sd3_midi_map.setText(campaign.sd3_midi_map)
            self.sd3_preset_file.setText(campaign.sd3_preset_file or "")
            self.export_megakit_plan.setText(campaign.megakit_plan_file or "")
            self.capture_audio_input.setText(campaign.audio_input); self.capture_channels.setText(",".join(campaign.channels))
            self.capture_rows.setRowCount(0)
            for row in campaign.rows:
                self.add_capture_row(row)
            self.campaign_log.setPlainText(f"Opened existing campaign: {path}")
            self.refresh_campaign_status()

        def refresh_campaign_status(self) -> None:
            if self.campaign_directory is None:
                self.campaign_status.setText("No campaign is open.")
                self.calibration_groups.setRowCount(0)
                for button in (self.campaign_calibrate_button, self.campaign_capture_button,
                               self.campaign_quality_button, self.campaign_composite_button, self.campaign_export_button,
                               self.campaign_validate_button, self.campaign_verify_button):
                    button.setEnabled(False)
                return
            try:
                progress = Sd3CaptureCampaign.read(self.campaign_directory).progress(self.campaign_directory)
            except (OSError, ValueError) as error:
                self.campaign_status.setText(f"Campaign status unavailable: {error}"); return
            self.campaign_status.setText(progress.stage)
            calibration_passed = progress.calibration_status == "technical-pass-user-mix-review-required"
            self.campaign_status.setStyleSheet(
                ("font-size: 15px; font-weight: 600; padding: 6px; color: #15803d;"
                 if calibration_passed else
                 "font-size: 15px; font-weight: 600; padding: 6px; color: #b45309;")
            )
            self.campaign_calibrate_button.setEnabled(True)
            self.campaign_capture_button.setEnabled(calibration_passed)
            capture_complete = progress.captured_takes == progress.total_takes and progress.library_exists
            self.campaign_quality_button.setEnabled(capture_complete)
            self.campaign_composite_button.setEnabled(capture_complete and progress.quality_report_passed
                                                      and progress.composite_takes > 0)
            composites_complete = (progress.composite_takes == 0
                                   or (progress.captured_composite_takes == progress.composite_takes
                                       and progress.composite_quality_passed))
            self.campaign_export_button.setEnabled(calibration_passed and capture_complete and progress.quality_report_passed
                                                   and composites_complete)
            self.campaign_validate_button.setEnabled(progress.drumgizmo_export_exists)
            self.campaign_verify_button.setEnabled(progress.drumgizmo_validation_passed)
            self.campaign_capture_summary.setText(
                f"Raw takes\n{progress.captured_takes} / {progress.total_takes}\n"
                f"{progress.missing_takes} remaining\n"
                f"Layered centers: {progress.captured_composite_takes} / {progress.composite_takes}"
            )
            calibration = progress.calibration_status or "not run"
            self.campaign_calibration_summary.setText(
                f"Calibration\n{calibration}\n{progress.calibration_technical_failures} technical failures"
            )
            self.campaign_output_summary.setText(
                "Outputs\n"
                f"Library: {'ready' if progress.library_exists else 'pending'}\n"
                f"Quality: {'ready' if progress.quality_report_passed else ('failed/stale' if progress.quality_report_exists else 'pending')} "
                f"({progress.quality_accepted}/{progress.total_takes}, {progress.quality_rejected} rejected, {progress.quality_missing} missing)\n"
                f"Layered QC: {'ready' if progress.composite_quality_passed else 'pending'}\n"
                f"DrumGizmo: {'validated' if progress.drumgizmo_validation_passed else ('exported' if progress.drumgizmo_export_exists else 'pending')}"
            )
            self.campaign_outlier_summary.setText(
                "Attention\n" + ("\n".join(progress.calibration_outliers)
                                  if progress.calibration_outliers else "No level outlier")
            )
            self.calibration_groups.setRowCount(0)
            for group in progress.calibration_level_groups:
                row = self.calibration_groups.rowCount()
                self.calibration_groups.insertRow(row)
                values = (
                    group.name, str(group.articulations), f"{group.quietest_peak_dbfs:.2f} dBFS",
                    f"{group.loudest_peak_dbfs:.2f} dBFS", f"{group.peak_span_db:.2f} dB",
                    ", ".join(group.outliers) if group.outliers else "—",
                )
                for column, value in enumerate(values):
                    self.calibration_groups.setItem(row, column, QTableWidgetItem(value))

        def run_campaign_action(self, action: str) -> None:
            if self.campaign_process is not None and self.campaign_process.state() != QProcess.ProcessState.NotRunning:
                QMessageBox.warning(self, "Campaign action already running", "Wait for the current campaign command to finish."); return
            if self.campaign_directory is None:
                QMessageBox.warning(self, "No campaign", "Create or open an SD3 capture campaign first."); return
            active_sd3_title: str | None = None
            confirm_midi_map = False
            if action in {"capture", "capture-composites", "calibrate"}:
                try:
                    campaign = Sd3CaptureCampaign.read(self.campaign_directory)
                    active_sd3_title = " | ".join(active_sd3_window_titles())
                except (OSError, ValueError) as error:
                    QMessageBox.warning(self, "Cannot verify SD3 state", str(error)); return
                answer = QMessageBox.warning(
                    self, "Confirm SD3 capture" if action != "calibrate" else "Confirm SD3 calibration",
                    ((f"Active SD3 window: {active_sd3_title or 'not detected'}\n"
                      f"Required MIDI map: {campaign.sd3_midi_map}\n\n"
                      + ("Confirm that this exact MIDI map is active. This will send the pending simultaneous layer chords "
                         "to SD3 and record the coherent layered centers. Continue?"
                         if action == "capture-composites" else
                         "Confirm that this exact MIDI map is active. This will send all pending notes in the saved session "
                         "to the declared SD3 MIDI input and record the declared audio input. Continue?"))
                     if action != "calibrate" else
                     (f"Active SD3 window: {active_sd3_title or 'not detected'}\n"
                      f"Required MIDI map: {campaign.sd3_midi_map}\n\n"
                      "Confirm that this exact MIDI map is active. This will send one bounded representative hit "
                      "per articulation to SD3 and record short level probes. Continue?")),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                confirm_midi_map = True
            try:
                note_map = Path(self.note_map.text()) if self.note_map.text().strip() else None
                megakit_plan = Path(self.export_megakit_plan.text()) if self.export_megakit_plan.text().strip() else None
                command = self.center.sampler_command(action, self.campaign_directory, note_map=note_map,
                                                      megakit_plan=megakit_plan,
                                                      confirm_capture=action in {"capture", "capture-composites", "calibrate"},
                                                      active_sd3_title=active_sd3_title,
                                                      confirm_midi_map=confirm_midi_map)
            except (OSError, ValueError) as error:
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
            pad_actions = QHBoxLayout()
            load_pads = QPushButton("Load declared virtual pads")
            load_pads.setToolTip("Creates clickable buttons for the exact note decoders of the selected source. Offline only.")
            load_pads.clicked.connect(self.load_simulator_pads)
            reset_pads = QPushButton("Reset simulator state")
            reset_pads.clicked.connect(self.reset_simulator)
            pad_actions.addWidget(load_pads); pad_actions.addWidget(reset_pads); layout.addLayout(pad_actions)
            self.sim_pad_group = QGroupBox("Virtual pads — load a project to populate")
            self.sim_pad_grid = QGridLayout(); self.sim_pad_group.setLayout(self.sim_pad_grid)
            layout.addWidget(self.sim_pad_group)
            expressions = QGroupBox("Expression simulator — CC / aftertouch")
            expressions_layout = QHBoxLayout()
            self.sim_expression_type = QLineEdit("cc")
            self.sim_expression_data1 = QSpinBox(); self.sim_expression_data1.setRange(0, 127); self.sim_expression_data1.setValue(4)
            self.sim_expression_value = QSpinBox(); self.sim_expression_value.setRange(0, 127); self.sim_expression_value.setValue(64)
            expression_button = QPushButton("Simulate expression")
            expression_button.clicked.connect(self.simulate_expression)
            for label, field in (("Type:", self.sim_expression_type), ("CC / note:", self.sim_expression_data1), ("Value:", self.sim_expression_value)):
                expressions_layout.addWidget(QLabel(label)); expressions_layout.addWidget(field)
            expressions_layout.addWidget(expression_button); expressions.setLayout(expressions_layout); layout.addWidget(expressions)
            controls = QGroupBox("Logical control bus — PC/external → Arduino → DDrum4")
            controls_layout = QVBoxLayout()
            controls_layout.addWidget(QLabel(
                "Offline only. Program Change selects Scene; the declared CC values select Virtual Palettes. "
                "DDrum4 native actions are traced but never sent from this editor."
            ))
            self.sim_control_source = QLineEdit("pc")
            self.sim_control_channel = QSpinBox(); self.sim_control_channel.setRange(1, 16); self.sim_control_channel.setValue(15)
            self.sim_control_type = QLineEdit("program_change")
            self.sim_control_data1 = QSpinBox(); self.sim_control_data1.setRange(0, 127)
            self.sim_control_value = QSpinBox(); self.sim_control_value.setRange(0, 127)
            row = QHBoxLayout()
            for label, field in (("Origin:", self.sim_control_source), ("Channel:", self.sim_control_channel),
                                 ("Type:", self.sim_control_type), ("Program / CC:", self.sim_control_data1),
                                 ("Value:", self.sim_control_value)):
                row.addWidget(QLabel(label)); row.addWidget(field)
            controls_layout.addLayout(row)
            simulate_control = QPushButton("Simulate scene / virtual-palette control")
            simulate_control.clicked.connect(self.simulate_control); controls_layout.addWidget(simulate_control)
            diagnose = QPushButton("Run full offline no-pad diagnostic")
            diagnose.setToolTip("Checks every declared playable input, Scene/VP state vector, and native control. No MIDI is opened.")
            diagnose.clicked.connect(self.run_offline_diagnostic); controls_layout.addWidget(diagnose)
            controls.setLayout(controls_layout); layout.addWidget(controls)
            panel.setLayout(layout)
            return panel

        def _matrix_panel(self) -> QGroupBox:
            panel = QGroupBox("DDrum4 bank inventory — selected local files only")
            panel.setToolTip("Read-only manifest/report inspection. No MIDI, SysEx, device discovery, or module-memory query.")
            layout = QVBoxLayout()
            self.bank_summary = QLabel("Load a rig project or select a local manifest. This view never reads the module.")
            self.bank_summary.setWordWrap(True)
            layout.addWidget(self.bank_summary)
            self.bank_action_status = QLabel("Bank actions are local: selecting or auditioning a WAV never sends MIDI or SysEx.")
            self.bank_action_status.setWordWrap(True)
            layout.addWidget(self.bank_action_status)
            self.manifest = QLineEdit()
            manifest_button = QPushButton("Select manifest…"); manifest_button.clicked.connect(self.select_manifest)
            row = QHBoxLayout(); row.addWidget(QLabel("Manifest:")); row.addWidget(self.manifest); row.addWidget(manifest_button)
            layout.addLayout(row)
            self.reports = QLineEdit(); self.reports.setReadOnly(True)
            reports_button = QPushButton("Select reports…"); reports_button.clicked.connect(self.select_reports)
            row = QHBoxLayout(); row.addWidget(QLabel("Reports:")); row.addWidget(self.reports); row.addWidget(reports_button)
            layout.addLayout(row)
            load = QPushButton("Load 10-slot matrix"); load.clicked.connect(self.load_matrix); layout.addWidget(load)
            self.matrix_table = QTableWidget(10, 13)
            self.matrix_table.setHorizontalHeaderLabels((
                "Slot", "Physical channel", "Sound ID", "NOTE base", "NOTE P", "Source", "Mapping rows",
                "Unique samples", "Encoded blocks", "MEM.LEFT Δ", "Status", "Variations", "Provenance",
            ))
            self.matrix_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.matrix_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.matrix_table.itemSelectionChanged.connect(self.show_layers)
            self.matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.matrix_table.horizontalHeader().setStretchLastSection(True)
            self.layer_table = QTableWidget(0, 12)
            self.layer_table.setHorizontalHeaderLabels(("Mapping row", "Position", "Velocity", "Variation", "Pitch", "RR", "Sample", "WAV", "Resource", "Source", "Status", "Provenance"))
            self.layer_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.layer_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.layer_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.layer_table.horizontalHeader().setStretchLastSection(True)
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
                self._clear_matrix()
                self.bank_action_status.setText("Select a DDrum4 manifest first."); return
            self._clear_matrix(clear_reference=False)
            try:
                matrix = load_kit_matrix(Path(self.manifest.text()), self.report_paths)
            except ValueError as error:
                self.bank_action_status.setText(f"Cannot load bank: {error}")
                QMessageBox.warning(self, "Cannot load DDrum4 matrix", str(error)); return
            self.matrix = matrix
            self._refresh_visual_sound_bank_facts()
            for row, sound in enumerate(matrix.sounds):
                variations = ", ".join(
                    f"V{number}" + (f" · {name}" if name else "")
                    for number, name in sound.variations
                )
                values = (sound.slot, sound.physical_channel, sound.sound_id or "missing", sound.note_base,
                          sound.note_p, sound.source, sound.layer_count, sound.unique_sample_count,
                          sound.encoded_blocks, sound.mem_left_delta_blocks, sound.status, variations, sound.provenance)
                for column, value in enumerate(values): self.matrix_table.setItem(row, column, self._cell(value))
            self.layer_table.setRowCount(0)
            capacity = f"{matrix.capacity_blocks} blocks capacity" if matrix.capacity_blocks is not None else "capacity unknown"
            used = f"{matrix.used_blocks} used" if matrix.used_blocks is not None else "used memory unknown"
            free = f"{matrix.free_blocks} free" if matrix.free_blocks is not None else "free memory unknown"
            identity = matrix.bank_id or Path(self.manifest.text()).stem
            midi = f"MIDI channel {matrix.midi_channel}" if matrix.midi_channel is not None else "MIDI channel unknown"
            local = f"Local control {matrix.local_control}" if matrix.local_control is not None else "Local control unknown"
            self.bank_summary.setText(
                f"Bank: {identity} · {matrix.bank_status or UNKNOWN} · {midi}; {local} · {capacity}; {used}; {free}. "
                "Encoded blocks are declared build facts; MEM.LEFT Δ is shown only when explicitly measured. "
                "A variation is a routing choice, not automatically a copied WAV."
            )
            self.bank_action_status.setText("Loaded selected local manifest and reports. MEM.LEFT Δ remains unknown until explicitly measured.")

        def show_layers(self) -> None:
            if self.matrix is None or self.matrix_table.currentRow() < 0: return
            layers = self.matrix.sound(self.matrix_table.currentRow() + 1).layers
            self.layer_table.setRowCount(len(layers))
            for row, layer in enumerate(layers):
                values = (layer.index, layer.position, layer.velocity,
                          "/".join(str(value) for value in layer.variation) if layer.variation else "not declared",
                          layer.pitch, layer.round_robin, layer.sample, layer.wav, layer.resource_status,
                          layer.source, layer.status, layer.provenance)
                for column, value in enumerate(values): self.layer_table.setItem(row, column, self._cell(value))

        def audition_layer(self) -> None:
            if self.matrix is None or self.matrix_table.currentRow() < 0 or self.layer_table.currentRow() < 0:
                self.bank_action_status.setText("Select a Sound slot and a declared WAV mapping first."); return
            layer: MatrixLayer = self.matrix.sound(self.matrix_table.currentRow() + 1).layers[self.layer_table.currentRow()]
            if layer.wav is None:
                self.bank_action_status.setText("The selected mapping has no declared WAV file."); return
            try:
                result = self.center.audition_wav(layer.wav)
            except (FileNotFoundError, ValueError) as error:
                self.bank_action_status.setText(f"Cannot audition WAV: {error}")
                QMessageBox.warning(self, "Cannot audition WAV", str(error)); return
            self.bank_action_status.setText("Opened selected WAV explicitly in the operating-system player: " + " ".join(result.command))

        def run(self, action: str) -> None:
            if not self.project.text(): self.log.setPlainText("Select a rig project first."); return
            result = self.center.run_rig(action, Path(self.project.text()))
            self.log.setPlainText(" ".join(result.command) + "\n\n" + result.text)

        def compile_project(self) -> None:
            if not self.project.text() or not self.output.text():
                self.log.setPlainText("Select a rig project and an explicit output directory first."); return
            base_dump = Path(self.ddti_base_dump.text().strip()) if self.ddti_base_dump.text().strip() else None
            result = self.center.run_rig(
                "compile", Path(self.project.text()), output=Path(self.output.text()),
                replace=self.replace_compile_output.isChecked(), base_dump=base_dump,
            )
            self.log.setPlainText(" ".join(result.command) + "\n\n" + result.text)

        def select_ddti_base_dump(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select a complete receive-only DDTi configuration dump", "",
                "SysEx dumps (*.syx *.mid *.midi);;All files (*)",
            )
            if filename:
                self.ddti_base_dump.setText(filename)

        def select_ddti_input_layout(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select explicit DDTi Input/Tip/Ring layout", self.ddti_input_layout.text(),
                "YAML/JSON layouts (*.yaml *.yml *.json)",
            )
            if filename:
                self.ddti_input_layout.setText(filename)

        def stage_ddti_from_build(self) -> None:
            """Materialize and diff a DDTi note preset without opening MIDI."""
            base = Path(self.ddti_base_dump.text().strip()) if self.ddti_base_dump.text().strip() else None
            layout = Path(self.ddti_input_layout.text().strip()) if self.ddti_input_layout.text().strip() else None
            build = Path(self.output.text().strip()) if self.output.text().strip() else None
            template = build / "ddti-role-template.yaml" if build is not None else None
            missing = [label for label, path in (("complete DDTi base dump", base), ("DDTi input layout", layout),
                                                  ("compiled ddti-role-template.yaml", template))
                       if path is None or not path.is_file()]
            if missing:
                QMessageBox.warning(self, "Cannot stage DDTi", "Missing: " + ", ".join(missing)); return
            filename, _ = QFileDialog.getSaveFileName(
                self, "Write a new review-only DDTi staged dump", str(build / "ddti-staged.syx"),
                "SysEx dump (*.syx)",
            )
            if not filename:
                return
            staged = Path(filename)
            try:
                result = self.center.run_ddti(
                    "apply-role-preset", base, preset=template, layout=layout, output=staged,
                )
                transcript = " ".join(result.command) + "\n\n" + result.text
                if result.returncode == 0:
                    difference = self.center.run_ddti("diff", base, preset=staged)
                    transcript += "\n\nREVIEWED-OFFLINE DIFF\n" + difference.text
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot stage DDTi", str(error)); return
            self.log.setPlainText(transcript)

        def simulate_chain(self) -> None:
            if not self.project.text() and not self.editor_project.text():
                self.log.setPlainText("Select a rig project first."); return
            if not self.sim_source.text():
                self.log.setPlainText("Enter a declared source module for the simulation."); return
            try:
                simulator = self.current_simulator()
                simulator.set_state(scene=self.sim_scene.text() or None)
                result = simulator.simulate_pad(self.sim_source.text(), self.sim_note.value(), self.sim_velocity.value())
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot simulate drum chain", str(error)); return
            self.log.setPlainText(result.render_text())

        def simulate_control(self) -> None:
            if not self.project.text() and not self.editor_project.text():
                self.log.setPlainText("Select a rig project first."); return
            try:
                simulator = self.current_simulator()
                result = simulator.simulate_logical_control(
                    self.sim_control_source.text().strip(), self.sim_control_channel.value(),
                    self.sim_control_type.text().strip(), self.sim_control_data1.value(), self.sim_control_value.value(),
                )
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot simulate logical control", str(error)); return
            self.log.setPlainText(result.render_text())

        def simulate_expression(self) -> None:
            if not self.project.text() and not self.editor_project.text():
                self.log.setPlainText("Select a rig project first."); return
            try:
                simulator = self.current_simulator()
                simulator.set_state(scene=self.sim_scene.text() or None)
                result = simulator.simulate_expression(
                    self.sim_source.text().strip(), self.sim_expression_type.text().strip(),
                    self.sim_expression_data1.value(), self.sim_expression_value.value(),
                )
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot simulate expression", str(error)); return
            self.log.setPlainText(result.render_text())

        def run_offline_diagnostic(self) -> None:
            if not self.project.text() and not self.editor_project.text():
                self.log.setPlainText("Select a rig project first."); return
            try:
                report = self.current_simulator().run_offline_diagnostic()
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot run offline diagnostic", str(error)); return
            self.log.setPlainText(report.render_text())

        def current_simulator(self) -> RigSimulator:
            path = self._selected_simulator_project_path()
            if self._active_simulator is None or self._active_simulator_path != path:
                self._active_simulator = RigSimulator.from_path(path)
                self._active_simulator_path = path
            return self._active_simulator

        def _selected_simulator_project_path(self) -> Path:
            """Return exactly one saved source of truth for compile and simulate.

            The former UI let the legacy rig selector and the editor selector
            point at different YAML files.  That made a clean simulator trace
            potentially describe a different kit from the editor.  A saved
            editor buffer is therefore required when it is the selected
            project, and divergent selectors are rejected instead of guessed.
            """
            editor_text = self.editor_project.text().strip()
            project_text = self.project.text().strip()
            if not editor_text and not project_text:
                raise SimulationError("select a rig project first")
            editor_path = Path(editor_text).resolve() if editor_text else None
            project_path = Path(project_text).resolve() if project_text else None
            if editor_path is not None and project_path is not None and editor_path != project_path:
                raise SimulationError("editor project and simulator project differ; load one saved project before simulating")
            path = editor_path or project_path
            assert path is not None
            if not path.is_file():
                raise SimulationError(f"rig project does not exist: {path}")
            if editor_path == path and self.project_document.toPlainText() != path.read_text(encoding="utf-8"):
                raise SimulationError("the kit editor has unsaved changes; save it before loading the simulator")
            return path

        def reset_simulator(self) -> None:
            self._invalidate_simulator_workspace()
            self.log.setPlainText("Simulator state reset to the project defaults. No MIDI was sent.")

        def _invalidate_simulator_workspace(self) -> None:
            """Discard every cached/offline view after a saved project change.

            The compiler reads the project file, never the Advanced-YAML text
            buffer. Clearing all derived simulator data here prevents a same
            path save from being presented as if it still used old routes.
            """
            self._active_simulator = None
            self._active_simulator_path = None
            self._studio_rows = []
            self._studio_events.clear()
            if hasattr(self, "virtual_kit_table"):
                self.virtual_kit_table.setRowCount(0)
                self.virtual_kit_log.setRowCount(0)
                for card in self.studio_cards.values():
                    card.setPlainText("Reload the saved rig project to simulate it.")
                self.studio_route_summary.setText("Project changed. Reload the saved project before inspecting routes.")
                self.virtual_kit_status.setText("Project changed. Reload the virtual kit from the saved file.")
                self.studio_project_identity.setText("No active saved rig project. Save and reload before simulation.")

        def load_simulator_pads(self) -> None:
            try:
                simulator = self.current_simulator()
                source = self.sim_source.text().strip() or next(iter(simulator.project.sources))
                if source not in simulator.project.sources:
                    raise SimulationError(f"unknown source module {source!r}")
                self.sim_source.setText(source)
                while self.sim_pad_grid.count():
                    item = self.sim_pad_grid.takeAt(0)
                    if item.widget() is not None:
                        item.widget().deleteLater()
                decoders = [decoder for decoder in simulator.project.source_decoders
                            if decoder.source == source and decoder.message_type == "note"]
                for index, decoder in enumerate(decoders):
                    note = decoder.match["note"]
                    button = QPushButton(f"{decoder.physical}\nraw note {note}")
                    button.setToolTip("Offline hit at the current velocity; the complete route is shown in the log.")
                    button.clicked.connect(lambda _=False, hit_note=note: self.simulate_virtual_pad(hit_note))
                    self.sim_pad_grid.addWidget(button, index // 4, index % 4)
                self.sim_pad_group.setTitle(f"Virtual pads — {source}, {len(decoders)} declared exact-note inputs")
                self.log.setPlainText("Virtual pads loaded. Click one to trace its complete route; no MIDI is emitted.")
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot load virtual pads", str(error))

        def simulate_virtual_pad(self, note: int) -> None:
            self.sim_note.setValue(note)
            self.simulate_chain()

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
    app.setStyleSheet("""
        QMainWindow, QWidget { background: #0b1013; color: #d8e3e7; font-family: "Segoe UI"; font-size: 12px; }
        QLabel#workspaceTitle { color: #eff8fb; font-size: 22px; font-weight: 750; padding: 4px 0; }
        QLabel#projectIdentity { color: #7faeb8; background: #0d171b; border: 1px solid #28434c; border-radius: 4px; padding: 6px; }
        QLabel#signalFlow { color: #8de85b; font-size: 13px; font-weight: 750; letter-spacing: 1px; background: #101a1e; border: 1px solid #274036; border-radius: 5px; padding: 9px; }
        QLabel#routeSummary { color: #b9d9df; background: #0e171b; border-left: 3px solid #54c9dc; padding: 9px; }
        QTabWidget::pane, QGroupBox { border: 1px solid #263940; border-radius: 7px; margin-top: 10px; }
        QGroupBox { color: #8eea57; font-weight: 700; padding: 9px; background: #0e161a; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QGroupBox#rawStage { border-color: #357f53; color: #85e7aa; }
        QGroupBox#ddrumStage { border-color: #bf853c; color: #ffbc59; }
        QGroupBox#sd3Stage { border-color: #a6912e; color: #f0d84b; }
        QGroupBox#drumgizmoStage { border-color: #7760ab; color: #c4a3ff; }
        QPushButton#padTrigger { min-width: 28px; padding: 3px 6px; color: #8eea57; border-color: #357f53; }
        QTabBar::tab { background: #121d22; color: #9eb3ba; padding: 9px 14px; border: 1px solid #263940; }
        QTabBar::tab:selected { background: #1a3138; color: #91ec57; }
        QPushButton { background: #15262d; border: 1px solid #3b6976; border-radius: 5px; padding: 7px 11px; color: #e1f3f6; font-weight: 600; }
        QPushButton:hover { background: #21414b; border-color: #68d6e5; }
        QPushButton:pressed { background: #101b20; }
        QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget { background: #080d10; border: 1px solid #2b4149; border-radius: 4px; color: #e4eef1; selection-background-color: #1f5868; }
        QTextEdit { padding: 4px; }
        QHeaderView::section { background: #16252b; color: #a9c6ce; border: none; border-right: 1px solid #29414a; padding: 6px; font-weight: 700; }
        QTableWidget::item { padding: 3px; border-bottom: 1px solid #142126; }
        QTableWidget::item:alternate { background: #0c1519; }
        QTableWidget::item:selected { background: #214f5d; color: white; }
        QScrollBar:vertical { background: #0b1013; width: 10px; } QScrollBar::handle:vertical { background: #345762; border-radius: 4px; min-height: 22px; }
    """)
    window = Window(); window.resize(1580, 930); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch())
