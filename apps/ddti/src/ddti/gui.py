"""Optional PySide6 offline DDTi note editor.

It edits a staged dump in memory and can save that staged file.  The prominent
write control is disabled because no hardware-safe DDTi writer exists yet.
"""
from __future__ import annotations

from pathlib import Path

from .diff import diff_ddti_bytes, render_diff
from .models import CONFIGURATION_PRESET_FORMAT, DDTiConfiguration, decode_configuration, encode_configuration
from .mappings import apply_role_template
from .presets import load_document, write_document
from .protocol import decode_file


def launch(dump_path: Path) -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
    except ImportError as error:  # pragma: no cover - optional desktop dependency
        raise RuntimeError("install the 'ddti[gui]' extra to run the PySide6 editor") from error

    class Editor(QMainWindow):
        def __init__(self, source: Path) -> None:
            super().__init__()
            self.source = source
            self.configuration: DDTiConfiguration = decode_configuration(decode_file(source))
            self.source_raw = self.configuration.raw
            self.setWindowTitle(f"DDTi offline editor — {source.name}")
            root = QWidget(self)
            layout = QVBoxLayout(root)
            layout.addWidget(QLabel("Confirmed MIDI notes and Input 1 Tip Gain — staged offline; hardware Write is disabled"))
            kit_row = QHBoxLayout()
            kit_row.addWidget(QLabel("Kit:"))
            self.kit_selector = QComboBox()
            for kit in self.configuration.kits:
                self.kit_selector.addItem(f"Kit {kit.number + 1}", kit.number)
            self.kit_selector.currentIndexChanged.connect(self.refresh)
            kit_row.addWidget(self.kit_selector)
            kit_row.addStretch()
            layout.addLayout(kit_row)
            gain_row = QHBoxLayout()
            gain_row.addWidget(QLabel("Input 1 Tip Gain (global, confirmed):"))
            self.gain = QSpinBox()
            self.gain.setRange(0, 127)
            if self.configuration.global_trigger_records:
                self.gain.setValue(self.configuration.input_1_tip_gain)
                self.gain.valueChanged.connect(self.set_input_1_tip_gain)
                self.gain.setToolTip("Only the byte location is confirmed; this remains an offline staged edit.")
            else:
                self.gain.setEnabled(False)
                self.gain.setToolTip("The opened dump has no global-trigger record 0.")
            gain_row.addWidget(self.gain)
            gain_row.addStretch()
            layout.addLayout(gain_row)
            self.table = QTableWidget(10, 5)
            self.table.setHorizontalHeaderLabels(("Input", "Tip note", "Tip channel (raw+1)", "Ring note", "Ring channel (raw+1)"))
            layout.addWidget(self.table)
            buttons = QHBoxLayout()
            save = QPushButton("Export staged SysEx")
            save.clicked.connect(self.save_file)
            buttons.addWidget(save)
            export_preset = QPushButton("Export note preset")
            export_preset.clicked.connect(self.export_preset)
            buttons.addWidget(export_preset)
            export_configuration = QPushButton("Export config preset")
            export_configuration.clicked.connect(self.export_configuration_preset)
            buttons.addWidget(export_configuration)
            import_preset = QPushButton("Import config preset")
            import_preset.clicked.connect(self.import_preset)
            buttons.addWidget(import_preset)
            apply_role = QPushButton("Apply GM/SD3 role preset")
            apply_role.clicked.connect(self.apply_role_preset)
            buttons.addWidget(apply_role)
            review = QPushButton("Review staged diff")
            review.clicked.connect(self.review_staged_diff)
            buttons.addWidget(review)
            write = QPushButton("Write to DDTi (disabled)")
            write.setEnabled(False)
            buttons.addWidget(write)
            layout.addLayout(buttons)
            self.setCentralWidget(root)
            self.refresh()

        def selected_kit_number(self) -> int:
            return int(self.kit_selector.currentData())

        def refresh(self, _index: int | None = None) -> None:
            self.table.blockSignals(True)
            if self.configuration.global_trigger_records:
                self.gain.blockSignals(True)
                self.gain.setValue(self.configuration.input_1_tip_gain)
                self.gain.blockSignals(False)
            kit = self.configuration.kits[self.selected_kit_number()]
            for row, input_ in enumerate(kit.inputs):
                number = QTableWidgetItem(str(input_.number))
                number.setFlags(number.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 0, number)
                for column, zone in ((1, input_.tip), (3, input_.ring)):
                    spin = QSpinBox()
                    spin.setRange(0, 127)
                    spin.setValue(zone.note)
                    spin.valueChanged.connect(lambda value, input_number=input_.number, target="tip" if column == 1 else "ring": self.set_note(input_number, target, value))
                    self.table.setCellWidget(row, column, spin)
                for column, zone in ((2, input_.tip), (4, input_.ring)):
                    channel = QTableWidgetItem(str(zone.channel_raw + 1))
                    channel.setFlags(channel.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, column, channel)
            self.table.blockSignals(False)

        def set_note(self, input_number: int, zone: str, value: int) -> None:
            self.configuration = self.configuration.with_note(self.selected_kit_number(), input_number, zone, value)

        def set_input_1_tip_gain(self, value: int) -> None:
            if self.configuration.global_trigger_records:
                self.configuration = self.configuration.with_input_1_tip_gain(value)

        def choose_new_path(self, title: str, suggestion: Path, file_filter: str) -> Path | None:
            destination, _ = QFileDialog.getSaveFileName(self, title, str(suggestion), file_filter)
            if not destination:
                return None
            path = Path(destination)
            if path.exists():
                QMessageBox.warning(self, "Refused", "Choose a new filename; existing files are never overwritten.")
                return None
            return path

        def save_file(self) -> None:
            path = self.choose_new_path("Export staged DDTi SysEx", self.source.with_stem(self.source.stem + "-staged"), "SysEx (*.syx)")
            if path is None:
                return
            path.write_bytes(encode_configuration(self.configuration))
            QMessageBox.information(self, "Saved", f"Staged file saved locally:\n{path}\n\nIt was not sent to the DDTi.")

        def export_preset(self) -> None:
            path = self.choose_new_path("Export DDTi note preset", self.source.with_stem(self.source.stem + "-notes"), "JSON (*.json)")
            if path is None:
                return
            write_document(path, self.configuration.to_note_preset())
            QMessageBox.information(self, "Saved", f"Portable note preset saved locally:\n{path}\n\nIt was not sent to the DDTi.")

        def export_configuration_preset(self) -> None:
            path = self.choose_new_path("Export DDTi configuration preset", self.source.with_stem(self.source.stem + "-config").with_suffix(".yaml"), "YAML (*.yaml *.yml);;JSON (*.json)")
            if path is None:
                return
            try:
                write_document(path, self.configuration.to_configuration_preset(name=self.source.stem))
            except ValueError as error:
                QMessageBox.warning(self, "Preset not exported", str(error))
                return
            QMessageBox.information(self, "Saved", f"Portable configuration preset saved locally:\n{path}\n\nIt was not sent to the DDTi.")

        def import_preset(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Import DDTi preset", "", "Preset (*.yaml *.yml *.json)")
            if not filename:
                return
            try:
                document = load_document(Path(filename))
                if document.get("format") == CONFIGURATION_PRESET_FORMAT:
                    self.configuration = self.configuration.with_configuration_preset(document)
                else:
                    self.configuration = self.configuration.with_note_preset(document)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Preset not imported", str(error))
                return
            self.refresh()
            QMessageBox.information(self, "Imported", "Settings staged in memory only. Export a new SysEx file to retain them.")

        def apply_role_preset(self) -> None:
            template_name, _ = QFileDialog.getOpenFileName(self, "Choose GM/SD3 role template", "", "Preset (*.yaml *.yml *.json)")
            if not template_name:
                return
            layout_name, _ = QFileDialog.getOpenFileName(self, "Choose explicit DDTi input layout", "", "Layout (*.yaml *.yml *.json)")
            if not layout_name:
                return
            try:
                self.configuration = apply_role_template(
                    self.configuration,
                    load_document(Path(template_name)),
                    load_document(Path(layout_name)),
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Role preset not applied", str(error))
                return
            self.refresh()
            QMessageBox.information(self, "Role preset staged", "The named role mapping was applied only to the explicit input/zone bindings. Export a new SysEx file to retain it; nothing was sent to the DDTi.")

        def review_staged_diff(self) -> None:
            differences = diff_ddti_bytes(self.source_raw, encode_configuration(self.configuration))
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Staged DDTi diff")
            dialog.setText(f"{len(differences)} changed byte(s) relative to {self.source.name}.\n\nNothing will be sent to the DDTi.")
            dialog.setDetailedText(render_diff(differences))
            dialog.exec()

    application = QApplication.instance() or QApplication([])
    editor = Editor(dump_path)
    editor.resize(900, 470)
    editor.show()
    return application.exec()
