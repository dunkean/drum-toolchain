"""Optional PySide6 offline DDTi note editor.

It edits a staged dump in memory and can save that staged file.  The prominent
write control is disabled because no hardware-safe DDTi writer exists yet.
"""
from __future__ import annotations

from pathlib import Path

from .models import DDTiConfiguration, decode_configuration, encode_configuration
from .protocol import decode_file


def launch(dump_path: Path) -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
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
            layout.addWidget(QLabel("Kit 0 note map — staged offline; hardware Write is disabled"))
            self.table = QTableWidget(10, 5)
            self.table.setHorizontalHeaderLabels(("Input", "Tip note", "Tip channel (raw+1)", "Ring note", "Ring channel (raw+1)"))
            layout.addWidget(self.table)
            buttons = QHBoxLayout()
            save = QPushButton("Save staged file")
            save.clicked.connect(self.save_file)
            buttons.addWidget(save)
            write = QPushButton("Write to DDTi (disabled)")
            write.setEnabled(False)
            buttons.addWidget(write)
            layout.addLayout(buttons)
            self.setCentralWidget(root)
            self.refresh()

        def refresh(self) -> None:
            self.table.blockSignals(True)
            kit = self.configuration.kits[0]
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
            self.configuration = self.configuration.with_note(0, input_number, zone, value)

        def save_file(self) -> None:
            destination, _ = QFileDialog.getSaveFileName(self, "Save staged DDTi SysEx", str(self.source.with_stem(self.source.stem + "-staged")), "SysEx (*.syx)")
            if not destination:
                return
            path = Path(destination)
            if path.exists():
                QMessageBox.warning(self, "Refused", "Choose a new filename; existing dump files are never overwritten.")
                return
            path.write_bytes(encode_configuration(self.configuration))
            QMessageBox.information(self, "Saved", f"Staged file saved locally:\n{path}\n\nIt was not sent to the DDTi.")

    application = QApplication.instance() or QApplication([])
    editor = Editor(dump_path)
    editor.resize(800, 430)
    editor.show()
    return application.exec()
