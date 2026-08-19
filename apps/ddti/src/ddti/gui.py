"""Optional PySide6 offline DDTi note editor.

It edits a staged dump in memory and can save that staged file.  The prominent
write control is disabled because no hardware-safe DDTi writer exists yet.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import DDTiConfiguration, decode_configuration, encode_configuration
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
            self.setWindowTitle(f"DDTi offline editor — {source.name}")
            root = QWidget(self)
            layout = QVBoxLayout(root)
            layout.addWidget(QLabel("Confirmed MIDI notes only — staged offline; hardware Write is disabled"))
            kit_row = QHBoxLayout()
            kit_row.addWidget(QLabel("Kit:"))
            self.kit_selector = QComboBox()
            for kit in self.configuration.kits:
                self.kit_selector.addItem(f"Kit {kit.number + 1}", kit.number)
            self.kit_selector.currentIndexChanged.connect(self.refresh)
            kit_row.addWidget(self.kit_selector)
            kit_row.addStretch()
            layout.addLayout(kit_row)
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
            import_preset = QPushButton("Import note preset")
            import_preset.clicked.connect(self.import_preset)
            buttons.addWidget(import_preset)
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
            path.write_text(json.dumps(self.configuration.to_note_preset(), indent=2) + "\n", encoding="utf-8")
            QMessageBox.information(self, "Saved", f"Portable note preset saved locally:\n{path}\n\nIt was not sent to the DDTi.")

        def import_preset(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Import DDTi note preset", "", "JSON (*.json)")
            if not filename:
                return
            try:
                document = json.loads(Path(filename).read_text(encoding="utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("preset root must be an object")
                self.configuration = self.configuration.with_note_preset(document)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                QMessageBox.warning(self, "Preset not imported", str(error))
                return
            self.refresh()
            QMessageBox.information(self, "Imported", "Notes staged in memory only. Export a new SysEx file to retain them.")

    application = QApplication.instance() or QApplication([])
    editor = Editor(dump_path)
    editor.resize(900, 470)
    editor.show()
    return application.exec()
