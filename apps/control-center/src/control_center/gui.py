"""Optional PySide front end for offline, operator-selected workflows.

The DDrum4 matrix is a selected-file viewer. It has no MIDI, SysEx,
device-discovery, or module-memory operations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import yaml

from .ddrum4_matrix import Ddrum4KitMatrix, MatrixLayer, UNKNOWN, load_kit_matrix
from .service import ControlCenter
from .simulator import RigSimulator, SimulationError
from .virtual_kit import build_virtual_kit
from .campaign import (CaptureRow, Sd3CaptureCampaign, STARTER_ROWS,
                       METALCORE_ELECTRONIC_V1_ADDITIONS)


def launch() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtCore import QProcess
        from PySide6.QtGui import QTextCursor
        from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog,
                                       QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                                       QHeaderView, QMainWindow, QMessageBox, QPushButton,
                                       QSplitter, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
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
            self._studio_events: list[dict[str, object]] = []
            self._studio_variable_controls: dict[str, QSpinBox] = {}
            self._studio_state_syncing = False
            self.report_paths: list[Path] = []
            self.campaign_directory: Path | None = None
            self.campaign_process: QProcess | None = None
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
            self.visual_sounds = QTableWidget(0, 4)
            self.visual_sounds.setHorizontalHeaderLabels(("Logical sound", "DDrum4 note / NOTE P", "SD3 note", "DrumGizmo note"))
            self.visual_sounds.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_sounds.itemChanged.connect(lambda _: self._sync_visual_project("sounds"))
            editor_tabs.addTab(self.visual_sounds, "Sounds and renderer map")
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
            editor_tabs.addTab(self.visual_actions, "DDrum4 kit / palette actions")
            self.visual_sources = QTableWidget(0, 4)
            self.visual_sources.setHorizontalHeaderLabels(("Module", "Endpoint", "Raw channel", "Primary input"))
            self.visual_sources.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.visual_sources.itemChanged.connect(lambda _: self._sync_visual_project("sources"))
            editor_tabs.addTab(self.visual_sources, "Modules and MIDI map")
            self.project_document = QTextEdit(); self.project_document.setAcceptRichText(False)
            self.project_document.setPlaceholderText("Advanced YAML source.")
            editor_tabs.addTab(self.project_document, "Advanced YAML")
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
            if clear_reference:
                self.report_paths = []
                self.manifest.clear()
                self.reports.clear()

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
                values = [logical]
                for renderer in ("ddrum4", "sd3", "drumgizmo"):
                    value = renderers.get(renderer, {}).get(logical, {}) if isinstance(renderers.get(renderer), dict) else {}
                    values.append(value.get("note", "—") if isinstance(value, dict) else "—")
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
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
                    for action in actions:
                        if isinstance(action, dict): action_rows.append((scene, action.get("type", "—"), action.get("channel", "—"), action.get("program", "—"), action.get("status", "—"), action.get("description", "")))
            self.visual_actions.setRowCount(len(action_rows))
            for row, values in enumerate(action_rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column < 2:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_actions.setItem(row, column, item)
            sources = document.get("sources", {})
            source_rows = [(name, item.get("endpoint", "—"), item.get("channel", "—"), item.get("primary", "—")) for name, item in sources.items() if isinstance(item, dict)]
            self.visual_sources.setRowCount(len(source_rows))
            for row, values in enumerate(source_rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.visual_sources.setItem(row, column, item)

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
                        for column, renderer in enumerate(("ddrum4", "sd3", "drumgizmo"), start=1):
                            item = self.visual_sounds.item(row, column)
                            if item is None or item.text().strip() == "—":
                                continue
                            document["renderers"][renderer][logical]["note"] = int(item.text())
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
                self.editor_status.setText("Table edit applied to Advanced YAML. Validate before saving.")
            except (TypeError, ValueError, KeyError) as error:
                self._visual_project_syncing = True
                self._populate_visual_project_tables(yaml.safe_load(self.project_document.toPlainText()))
                self._visual_project_syncing = False
                self.editor_status.setText(f"Table edit rejected: {error}")

        def _selected_visual_scene(self) -> str:
            row = self.visual_routes.currentRow()
            if row < 0 or self.visual_routes.item(row, 0) is None:
                document = yaml.safe_load(self.project_document.toPlainText())
                if not isinstance(document, dict):
                    raise ValueError("Advanced YAML is not a project mapping")
                return str(document["state"]["defaults"]["scene"])
            return self.visual_routes.item(row, 0).text()

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
            trigger.clicked.connect(self.trigger_virtual_kit_pad)
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
            left_layout.addWidget(QLabel("Pads / articulations — double-click a row to trigger it at the displayed velocity. Raw input notes remain visible for all declared modules."))
            self.virtual_kit_table = QTableWidget(0, 8)
            self.virtual_kit_table.setHorizontalHeaderLabels((
                "Pad / articulation", "eDRUMin", "DDTi", "DDrum4", "Logical sound", "DDrum4 bank", "SD3", "DrumGizmo",
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
                self._rebuild_studio_variable_controls(simulator)
                self._refresh_studio_expression_choices(simulator)
                self._load_project_bank_reference(self._active_simulator_path or Path(), simulator.project.raw)
                self.refresh_virtual_kit_workspace()
                self.virtual_kit_status.setText("Virtual kit loaded from the same validated rig project as the compiler.")
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot load virtual kit", str(error))

        def _studio_scene_changed(self, scene: str) -> None:
            if not scene:
                return
            try:
                self.current_simulator().set_state(scene=scene)
                self.refresh_virtual_kit_workspace()
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
            for name in simulator.project.variables:
                label = QLabel(name.upper() + ":")
                control = QSpinBox(); control.setRange(0, 127); control.setValue(simulator.state[name]); control.setPrefix("V ")
                control.setToolTip(f"Offline value for {name}. It is applied to the logical route matrix.")
                control.valueChanged.connect(lambda value, variable=name: self._studio_variable_changed(variable, value))
                self.studio_variable_controls[name] = control
                self.studio_variable_layout.addWidget(label); self.studio_variable_layout.addWidget(control)
            self.studio_variable_layout.addStretch(1)

        def _studio_variable_changed(self, variable: str, value: int) -> None:
            if self._studio_state_syncing:
                return
            try:
                self.current_simulator().set_state(values={variable: value})
                self.refresh_virtual_kit_workspace()
                self.virtual_kit_status.setText(f"Offline palette state: {variable}={value}.")
            except (OSError, ValueError, SimulationError) as error:
                self.virtual_kit_status.setText(f"Virtual-palette change rejected: {error}")

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
                    control.setValue(simulator.state[name])
            finally:
                self._studio_state_syncing = False
            self._studio_rows = build_virtual_kit(simulator)
            self.virtual_kit_table.setRowCount(len(self._studio_rows))
            for row, kit_row in enumerate(self._studio_rows):
                logical = kit_row.logical_sound or "MISSING"
                ddrum_text = (f"S{kit_row.ddrum4_slot} {kit_row.ddrum4_sound_id} · P{kit_row.ddrum4_note_p} · "
                              f"C{simulator.project.ddrum4_output_channel} N{kit_row.ddrum4_note}"
                              if kit_row.ddrum4_note is not None and kit_row.ddrum4_sound_id else
                              (f"C{simulator.project.ddrum4_output_channel} · note {kit_row.ddrum4_note}" if kit_row.ddrum4_note is not None else "MISSING"))
                sd3_text = f"C{kit_row.sd3_channel} · note {kit_row.sd3_note}" if kit_row.sd3_note is not None else "MISSING"
                gizmo_text = (f"{kit_row.drumgizmo_instrument} / {kit_row.drumgizmo_articulation} · note {kit_row.drumgizmo_note}"
                              if kit_row.drumgizmo_note is not None and kit_row.drumgizmo_instrument and kit_row.drumgizmo_articulation else "MISSING")
                values = (kit_row.physical, kit_row.raw_notes.get("edrumin", "—"), kit_row.raw_notes.get("ddti", "—"),
                          kit_row.raw_notes.get("ddrum4", "—"), logical, ddrum_text, sd3_text, gizmo_text)
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column != 0:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if value == "MISSING":
                        item.setBackground(Qt.GlobalColor.darkRed)
                    self.virtual_kit_table.setItem(row, column, item)
            self.virtual_kit_table.resizeColumnsToContents()
            if self.virtual_kit_table.rowCount() and self.virtual_kit_table.currentRow() < 0:
                self.virtual_kit_table.selectRow(0)

        def trigger_virtual_kit_pad(self) -> None:
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
                result = simulator.simulate_pad(source, kit_row.raw_notes[source], self.studio_velocity.value())
            except (OSError, ValueError, SimulationError) as error:
                QMessageBox.warning(self, "Cannot trigger virtual pad", str(error)); return
            by_stage = {step.stage: step for step in result.steps}
            self.studio_cards["Raw input"].setPlainText(self._format_studio_card(by_stage, ("raw MIDI", "source profile", "logical state", "logical sound")))
            self.studio_cards["Arduino → DDrum4"].setPlainText(self._format_studio_card(by_stage, ("Arduino DDrum4 renderer", "DDrum4 audio", "DDrum4 echo guard")))
            self.studio_cards["SD3 reference"].setPlainText(self._format_studio_card(by_stage, ("SD3 renderer", "SD3 audio")))
            self.studio_cards["DrumGizmo"].setPlainText(self._format_studio_card(by_stage, ("DrumGizmo renderer", "DrumGizmo audio")))
            self.studio_route_summary.setText(
                f"{result.physical}  →  {result.logical_target}  |  source {result.source}, velocity {result.velocity}  |  "
                "all destinations shown are declared by the saved project"
            )
            self._append_virtual_kit_event(result)
            self.virtual_kit_status.setText(f"Offline route verified: {result.physical} → {result.logical_target}. No MIDI or audio was emitted.")

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
            self.studio_cards["SD3 reference"].setPlainText(self._format_studio_card(by_stage, ("SD3 renderer", "SD3 audio")))
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
            ddrum = self.current_simulator().project.renderers["ddrum4"][result.logical_target]
            sd3 = self.current_simulator().project.renderers["sd3"][result.logical_target]
            gizmo = self.current_simulator().project.renderers["drumgizmo"][result.logical_target]
            row = self.virtual_kit_log.rowCount(); self.virtual_kit_log.insertRow(row)
            values = (datetime.now().strftime("%H:%M:%S.%f")[:-3], "Note On", result.source, result.physical,
                      result.logical_target, result.velocity, f"C{self.current_simulator().project.ddrum4_output_channel} N{ddrum['note']}",
                      f"C{sd3.get('channel', 10)} N{sd3['note']}", f"{gizmo['instrument']}/{gizmo['articulation']} · N{gizmo['note']}")
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
            self.layer_table = QTableWidget(0, 11)
            self.layer_table.setHorizontalHeaderLabels(("Layer", "Position", "Velocity", "Variation", "Pitch", "RR", "WAV", "Resource", "Source", "Status", "Provenance"))
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
                self._clear_matrix()
                self.log.setPlainText("Select a DDrum4 manifest first."); return
            self._clear_matrix(clear_reference=False)
            try:
                matrix = load_kit_matrix(Path(self.manifest.text()), self.report_paths)
            except ValueError as error:
                QMessageBox.warning(self, "Cannot load DDrum4 matrix", str(error)); return
            self.matrix = matrix
            for row, sound in enumerate(matrix.sounds):
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
                values = (layer.index, layer.position, layer.velocity,
                          "/".join(str(value) for value in layer.variation) if layer.variation else None,
                          layer.pitch, layer.round_robin, layer.wav, layer.resource_status,
                          layer.source, layer.status, layer.provenance)
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
            path_text = self.project.text().strip() or self.editor_project.text().strip()
            if not path_text:
                raise SimulationError("select a rig project first")
            path = Path(path_text).resolve()
            if self._active_simulator is None or self._active_simulator_path != path:
                self._active_simulator = RigSimulator.from_path(path)
                self._active_simulator_path = path
            return self._active_simulator

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
        QMainWindow, QWidget { background: #0b1013; color: #d8e3e7; font-size: 12px; }
        QLabel#workspaceTitle { color: #eff8fb; font-size: 22px; font-weight: 750; padding: 4px 0; }
        QLabel#signalFlow { color: #8de85b; font-size: 13px; font-weight: 750; letter-spacing: 1px; background: #101a1e; border: 1px solid #274036; border-radius: 5px; padding: 9px; }
        QLabel#routeSummary { color: #b9d9df; background: #0e171b; border-left: 3px solid #54c9dc; padding: 9px; }
        QTabWidget::pane, QGroupBox { border: 1px solid #263940; border-radius: 7px; margin-top: 10px; }
        QGroupBox { color: #8eea57; font-weight: 700; padding: 9px; background: #0e161a; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QGroupBox#rawStage { border-color: #357f53; color: #85e7aa; }
        QGroupBox#ddrumStage { border-color: #bf853c; color: #ffbc59; }
        QGroupBox#sd3Stage { border-color: #a6912e; color: #f0d84b; }
        QGroupBox#drumgizmoStage { border-color: #7760ab; color: #c4a3ff; }
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
