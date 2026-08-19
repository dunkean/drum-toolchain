"""PySide6 desktop editor for the legacy 2016 ddrum DDTi."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import Event

from .capture import CaptureCancelled, capture_dump
from .diff import diff_ddti_bytes, render_diff
from .models import CONFIGURATION_PRESET_FORMAT, DDTiConfiguration, VELOCITY_CURVE_LABELS, decode_configuration
from .mappings import apply_role_template
from .monitor import observe_messages
from .presets import load_document, write_document
from .protocol import decode_dump, decode_file
from .state import DDTiStateStore
from .transfer import build_safe_write_plan, send_safe_configuration


_STYLE = """
QMainWindow, QWidget { background: #11151c; color: #e8edf5; font-size: 13px; }
QFrame#hero { background: #18202b; border: 1px solid #293546; border-radius: 12px; }
QLabel#title { font-size: 24px; font-weight: 700; color: #ffffff; }
QLabel#subtitle { color: #9dacbf; }
QLabel#statusGood { color: #56d6a3; font-weight: 600; }
QLabel#statusChanged { color: #ffca6a; font-weight: 600; }
QLabel#lastHit { font-size: 20px; font-weight: 700; color: #ffffff; padding: 12px; }
QListWidget, QTableWidget, QTabWidget::pane, QGroupBox { background: #161c25; border: 1px solid #293546; border-radius: 8px; }
QListWidget::item { padding: 9px 12px; border-radius: 5px; }
QListWidget::item:selected { background: #2364d2; color: white; }
QHeaderView::section { background: #202a38; color: #cdd7e6; padding: 8px; border: 0; }
QTabBar::tab { background: #18202b; padding: 10px 18px; margin-right: 3px; border-radius: 6px; }
QTabBar::tab:selected { background: #2364d2; color: white; }
QSpinBox, QComboBox { background: #202936; border: 1px solid #344359; border-radius: 6px; padding: 5px 8px; }
QSpinBox:focus, QComboBox:focus { border: 1px solid #4d8dff; }
QPushButton { background: #253246; border: 1px solid #34465f; border-radius: 7px; padding: 8px 13px; }
QPushButton:hover { background: #30415a; }
QPushButton#primary { background: #246bdb; border-color: #3880ee; font-weight: 600; }
QPushButton#primary:hover { background: #2f7aea; }
QGroupBox { margin-top: 10px; padding: 14px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #aebbd0; }
QStatusBar { color: #8fa0b7; }
"""


def _decode_complete_configuration(path: Path) -> DDTiConfiguration:
    configuration = decode_configuration(decode_file(path))
    if len(configuration.kits) != 21 or len(configuration.global_trigger_records) != 21:
        raise ValueError("un dump DDTi complet doit contenir 21 kits et 21 réglages globaux")
    return configuration


def _midi_note_label(note: object) -> str:
    if type(note) is not int or not 0 <= note <= 127:
        return "—"
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{note} ({names[note % 12]}{note // 12 - 1})"


def launch(dump_path: Path | None = None) -> int:
    try:
        from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
        from PySide6.QtWidgets import (
            QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
            QHeaderView, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton,
            QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
            QVBoxLayout, QWidget,
        )
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("install the 'ddti[gui]' extra to run the PySide6 editor") from error

    class CaptureWorker(QObject):
        completed = Signal(object)
        failed = Signal(str)
        cancelled = Signal()

        def __init__(self, stem: Path) -> None:
            super().__init__()
            self.stem = stem
            self.cancel_event = Event()

        def cancel(self) -> None:
            self.cancel_event.set()

        @Slot()
        def run(self) -> None:
            try:
                self.completed.emit(
                    capture_dump(
                        "TriggerIO",
                        self.stem,
                        seconds=180,
                        idle_seconds=5,
                        cancelled=self.cancel_event.is_set,
                    )
                )
            except CaptureCancelled:
                self.cancelled.emit()
            except Exception as error:  # pragma: no cover - hardware/runtime path
                self.failed.emit(str(error))

    class MidiMonitorWorker(QObject):
        message = Signal(object)
        stopped = Signal()
        failed = Signal(str)

        def __init__(self) -> None:
            super().__init__()
            self.cancel_event = Event()

        def cancel(self) -> None:
            self.cancel_event.set()

        @Slot()
        def run(self) -> None:
            try:
                observe_messages(
                    "TriggerIO",
                    self.message.emit,
                    cancelled=self.cancel_event.is_set,
                )
            except Exception as error:  # pragma: no cover - hardware/runtime path
                self.failed.emit(str(error))
            else:
                self.stopped.emit()

    class Editor(QMainWindow):
        def __init__(self, source: Path | None) -> None:
            super().__init__()
            self.state_store = DDTiStateStore.default()
            self._refreshing = False
            self.capture_thread = None
            self.capture_worker = None
            self.monitor_thread = None
            self.monitor_worker = None
            self.monitor_records: list[dict[str, object]] = []
            self._close_confirmed = False
            self._close_after_capture = False
            self._close_after_monitor = False
            self._startup_warning: str | None = None
            if source is None:
                if not self.state_store.exists():
                    raise ValueError("no dump supplied and no last-known DDTi state exists")
                self.configuration = self.state_store.load()
                self.source_label = str(self.state_store.syx_path)
            else:
                self.configuration = _decode_complete_configuration(source)
                self.source_label = str(source)
                try:
                    self.state_store.save(self.configuration.raw, source=str(source), reason="opened verified dump")
                except OSError as error:
                    self._startup_warning = str(error)
            self.source_raw = self.configuration.raw
            self.setWindowTitle("DDTi Editor — configuration complète")
            self.setMinimumSize(1100, 700)
            self._build_ui()
            self.refresh_all()
            if self._startup_warning:
                QTimer.singleShot(
                    0,
                    lambda: QMessageBox.warning(
                        self,
                        "Cache local indisponible",
                        "Le dump est ouvert, mais le dernier état connu n’a pas pu être mémorisé.\n\n"
                        + self._startup_warning,
                    ),
                )

        def _build_ui(self) -> None:
            root = QWidget(self)
            outer = QVBoxLayout(root)
            outer.setContentsMargins(18, 18, 18, 12)
            outer.setSpacing(12)
            hero = QFrame()
            hero.setObjectName("hero")
            hero_layout = QVBoxLayout(hero)
            title = QLabel("DDTi Editor")
            title.setObjectName("title")
            hero_layout.addWidget(title)
            subtitle = QLabel("21 kits • 20 zones • réglages globaux • envoi SysEx contrôlé")
            subtitle.setObjectName("subtitle")
            hero_layout.addWidget(subtitle)
            status_row = QHBoxLayout()
            self.device_status = QLabel("● TriggerIO — vérifié au moment de l’envoi")
            self.device_status.setObjectName("statusGood")
            status_row.addWidget(self.device_status)
            status_row.addStretch()
            self.change_status = QLabel()
            status_row.addWidget(self.change_status)
            hero_layout.addLayout(status_row)
            outer.addWidget(hero)
            splitter = QSplitter()
            self.kit_list = QListWidget()
            self.kit_list.setMaximumWidth(190)
            for kit in self.configuration.kits:
                self.kit_list.addItem(f"Kit {kit.number + 1:02d}")
            self.kit_list.currentRowChanged.connect(self.refresh_kit)
            splitter.addWidget(self.kit_list)
            self.tabs = QTabWidget()
            self.tabs.addTab(self._build_kit_tab(), "Kit & routage MIDI")
            self.tabs.addTab(self._build_trigger_tab(), "Réponse des triggers")
            self.tabs.addTab(self._build_monitor_tab(), "Test MIDI en direct")
            splitter.addWidget(self.tabs)
            splitter.setStretchFactor(1, 1)
            outer.addWidget(splitter, 1)
            actions = QHBoxLayout()
            self.action_buttons: list[QPushButton] = []
            for text, callback in (
                ("Synchroniser", self.synchronize_from_ddti),
                ("Ouvrir un dump", self.open_dump),
                ("Importer une config", self.import_preset),
                ("Mapping GM/SD3", self.apply_role_preset),
                ("Exporter la config", self.export_configuration_preset),
                ("Exporter SysEx", self.export_sysex),
                ("Voir les changements", self.review_staged_diff),
                ("Annuler", self.discard_changes),
            ):
                button = QPushButton(text)
                button.clicked.connect(callback)
                actions.addWidget(button)
                self.action_buttons.append(button)
                if text == "Synchroniser":
                    self.synchronize_button = button
            actions.addStretch()
            write = QPushButton("Envoyer au DDTi")
            write.setObjectName("primary")
            write.clicked.connect(self.write_to_ddti)
            actions.addWidget(write)
            self.write_button = write
            outer.addLayout(actions)
            self.setCentralWidget(root)
            self.statusBar().showMessage(f"Source : {self.source_label}")
            self.kit_list.setCurrentRow(0)

        def _build_kit_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            top = QHBoxLayout()
            top.addWidget(QLabel("Program Change"))
            self.program_change = QSpinBox()
            self.program_change.setRange(-1, 127)
            self.program_change.setSpecialValueText("---")
            self.program_change.valueChanged.connect(self.set_program_change)
            top.addWidget(self.program_change)
            top.addStretch()
            layout.addLayout(top)
            self.mapping_table = QTableWidget(10, 5)
            self.mapping_table.setHorizontalHeaderLabels(("Entrée", "Tip canal", "Tip note", "Ring canal", "Ring note"))
            self.mapping_table.verticalHeader().setVisible(False)
            self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            layout.addWidget(self.mapping_table, 1)
            hi_hat_group = QGroupBox("Hi-hat — valeurs propres au kit")
            hi_hat_layout = QHBoxLayout(hi_hat_group)
            self.hi_hat_spins: dict[str, QSpinBox] = {}
            for field, label, minimum, maximum in (
                ("pedal_channel", "Canal pédale", 1, 16),
                ("pedal_note", "Note pédale", 0, 127),
                ("closed_note", "Note fermée Input 3", 0, 127),
            ):
                hi_hat_layout.addWidget(QLabel(label))
                spin = QSpinBox()
                spin.setRange(minimum, maximum)
                spin.valueChanged.connect(lambda value, name=field: self.set_hi_hat(name, value))
                self.hi_hat_spins[field] = spin
                hi_hat_layout.addWidget(spin)
            hi_hat_layout.addStretch()
            layout.addWidget(hi_hat_group)
            return tab

        def _build_trigger_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            row = QHBoxLayout()
            row.addWidget(QLabel("Zone globale"))
            self.trigger_selector = QComboBox()
            for record in self.configuration.global_trigger_records:
                self.trigger_selector.addItem(record.label, record.index)
            self.trigger_selector.currentIndexChanged.connect(self.refresh_trigger)
            row.addWidget(self.trigger_selector)
            row.addStretch()
            layout.addLayout(row)
            group = QGroupBox("Réponse et filtrage")
            form = QFormLayout(group)
            self.trigger_spins: dict[str, QSpinBox] = {}
            for field, label in (
                ("gain", "Gain"),
                ("threshold", "Threshold"),
                ("xtalk", "X-Talk / calibration brute"),
                ("retrigger", "Retrigger (ms)"),
            ):
                spin = QSpinBox()
                spin.setRange(0, 127)
                spin.valueChanged.connect(lambda value, name=field: self.set_global_trigger(name, value))
                self.trigger_spins[field] = spin
                form.addRow(label, spin)
            self.curve = QComboBox()
            for value, label in VELOCITY_CURVE_LABELS.items():
                self.curve.addItem(f"{label}  (code {value})", value)
            self.curve.currentIndexChanged.connect(self.set_velocity_curve)
            form.insertRow(1, "Velocity Curve", self.curve)
            self.trigger_type_raw = QSpinBox()
            self.trigger_type_raw.setRange(0, 127)
            self.trigger_type_raw.setReadOnly(True)
            self.trigger_type_raw.setToolTip("Visible mais verrouillé jusqu’à la validation du dernier octet sur ce DDTi 2016.")
            form.addRow("Dernier octet (brut, verrouillé)", self.trigger_type_raw)
            layout.addWidget(group)
            note = QLabel(
                "Ces réglages sont globaux pour les 21 kits. Sur la pédale hi-hat, X-Talk contient la calibration. "
                "Types documentés : PP1–PP5, SS, PS, SP, SUS, AS ; HH1–HH7 sont auto-détectés. "
                "Leur encodage SysEx reste verrouillé jusqu’au test matériel."
            )
            note.setWordWrap(True)
            note.setObjectName("subtitle")
            layout.addWidget(note)
            layout.addStretch()
            return tab

        def _build_monitor_tab(self) -> QWidget:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            controls = QHBoxLayout()
            self.monitor_button = QPushButton("Démarrer l’écoute")
            self.monitor_button.setObjectName("primary")
            self.monitor_button.clicked.connect(self.toggle_midi_monitor)
            controls.addWidget(self.monitor_button)
            clear = QPushButton("Effacer")
            clear.clicked.connect(self.clear_midi_monitor)
            controls.addWidget(clear)
            export = QPushButton("Exporter JSONL")
            export.clicked.connect(self.export_midi_monitor)
            controls.addWidget(export)
            controls.addStretch()
            self.monitor_count = QLabel("0 message")
            controls.addWidget(self.monitor_count)
            layout.addLayout(controls)
            self.last_hit = QLabel("Frappe un pad pour vérifier sa note et sa vélocité")
            self.last_hit.setObjectName("lastHit")
            self.last_hit.setWordWrap(True)
            layout.addWidget(self.last_hit)
            self.monitor_table = QTableWidget(0, 6)
            self.monitor_table.setHorizontalHeaderLabels(
                ("Heure", "Message", "Canal", "Note", "Vélocité", "Contrôle / valeur")
            )
            self.monitor_table.verticalHeader().setVisible(False)
            self.monitor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.monitor_table.setEditTriggers(QTableWidget.NoEditTriggers)
            layout.addWidget(self.monitor_table, 1)
            help_text = QLabel(
                "Lecture seule : ce test n’envoie rien au DDTi. Les Note On montrent immédiatement le canal, "
                "la note musicale et la vélocité ; les messages de pédale et Program Change restent visibles dans le tableau."
            )
            help_text.setWordWrap(True)
            help_text.setObjectName("subtitle")
            layout.addWidget(help_text)
            return tab

        def selected_kit(self) -> int:
            return max(0, self.kit_list.currentRow())

        def selected_record(self) -> int:
            value = self.trigger_selector.currentData()
            return 0 if value is None else int(value)

        def _spin(self, minimum: int, maximum: int, value: int, callback) -> QSpinBox:
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setValue(value)
            spin.valueChanged.connect(callback)
            return spin

        def refresh_all(self) -> None:
            self._refreshing = True
            self.refresh_kit()
            self.refresh_trigger()
            self._refreshing = False
            self.refresh_status()

        def refresh_kit(self, _row: int | None = None) -> None:
            if not hasattr(self, "mapping_table"):
                return
            self._refreshing = True
            kit = self.configuration.kits[self.selected_kit()]
            self.program_change.blockSignals(True)
            self.program_change.setValue(-1 if kit.program_change is None else kit.program_change)
            self.program_change.blockSignals(False)
            for row, input_ in enumerate(kit.inputs):
                number = QTableWidgetItem(str(input_.number))
                number.setTextAlignment(Qt.AlignCenter)
                number.setFlags(number.flags() & ~Qt.ItemIsEditable)
                self.mapping_table.setItem(row, 0, number)
                self.mapping_table.setCellWidget(row, 1, self._spin(1, 16, input_.tip.channel, lambda value, n=input_.number: self.set_zone(n, "tip", "channel", value)))
                self.mapping_table.setCellWidget(row, 2, self._spin(0, 127, input_.tip.note, lambda value, n=input_.number: self.set_zone(n, "tip", "note", value)))
                self.mapping_table.setCellWidget(row, 3, self._spin(1, 16, input_.ring.channel, lambda value, n=input_.number: self.set_zone(n, "ring", "channel", value)))
                self.mapping_table.setCellWidget(row, 4, self._spin(0, 127, input_.ring.note, lambda value, n=input_.number: self.set_zone(n, "ring", "note", value)))
            for field, spin in self.hi_hat_spins.items():
                spin.blockSignals(True)
                spin.setValue(getattr(kit.hi_hat, field))
                spin.blockSignals(False)
            self._refreshing = False
            self.refresh_status()

        def refresh_trigger(self, _index: int | None = None) -> None:
            if not hasattr(self, "trigger_selector") or not self.configuration.global_trigger_records:
                return
            self._refreshing = True
            record = self.configuration.global_trigger_records[self.selected_record()]
            for field, spin in self.trigger_spins.items():
                spin.blockSignals(True)
                if field == "xtalk":
                    spin.setMaximum(127 if record.index == 20 else max(7, record.settings[field]))
                spin.setValue(record.settings[field])
                spin.blockSignals(False)
            self.curve.blockSignals(True)
            curve_value = record.settings["velocity_curve"]
            curve_index = self.curve.findData(curve_value)
            if curve_index < 0:
                self.curve.addItem(f"Code brut non documenté {curve_value}", curve_value)
                curve_index = self.curve.findData(curve_value)
            self.curve.setCurrentIndex(curve_index)
            self.curve.blockSignals(False)
            self.trigger_type_raw.setValue(record.trigger_type_raw)
            self._refreshing = False
            self.refresh_status()

        def refresh_status(self) -> None:
            if not hasattr(self, "change_status"):
                return
            count = len(diff_ddti_bytes(self.source_raw, self.configuration.raw))
            self.change_status.setText("Aucun changement" if count == 0 else f"{count} octet(s) modifié(s)")
            self.change_status.setObjectName("statusGood" if count == 0 else "statusChanged")
            self.change_status.style().unpolish(self.change_status)
            self.change_status.style().polish(self.change_status)

        def _has_staged_changes(self) -> bool:
            return self.configuration.raw != self.source_raw

        def _monitor_is_active(self) -> bool:
            return self.monitor_thread is not None and self.monitor_thread.isRunning()

        def toggle_midi_monitor(self) -> None:
            if self._monitor_is_active():
                self.monitor_worker.cancel()
                self.monitor_button.setEnabled(False)
                self.monitor_button.setText("Arrêt…")
                return
            if self.capture_thread is not None and self.capture_thread.isRunning():
                self.statusBar().showMessage("Arrête d’abord la synchronisation DDTi.")
                return
            self.monitor_thread = QThread(self)
            self.monitor_worker = MidiMonitorWorker()
            self.monitor_worker.moveToThread(self.monitor_thread)
            self.monitor_thread.started.connect(self.monitor_worker.run)
            self.monitor_worker.message.connect(self._midi_message_received)
            self.monitor_worker.stopped.connect(self.monitor_thread.quit)
            self.monitor_worker.failed.connect(self._midi_monitor_failed)
            self.monitor_worker.failed.connect(self.monitor_thread.quit)
            self.monitor_thread.finished.connect(self.monitor_worker.deleteLater)
            self.monitor_thread.finished.connect(self.monitor_thread.deleteLater)
            self.monitor_thread.finished.connect(self._midi_monitor_finished)
            self.monitor_button.setText("Arrêter l’écoute")
            self.synchronize_button.setEnabled(False)
            self.device_status.setText("● Test MIDI en écoute — lecture seule")
            self.monitor_thread.start()

        @Slot(object)
        def _midi_message_received(self, record: dict[str, object]) -> None:
            self.monitor_records.append(dict(record))
            if len(self.monitor_records) > 500:
                self.monitor_records.pop(0)
            if self.monitor_table.rowCount() >= 500:
                self.monitor_table.removeRow(0)
            row = self.monitor_table.rowCount()
            self.monitor_table.insertRow(row)
            timestamp = str(record.get("timestamp_utc", ""))
            control = ""
            if "control" in record:
                control = f"CC {record['control']} = {record.get('value', '—')}"
            elif "program" in record:
                control = f"Programme {record['program']}"
            elif "pitch" in record:
                control = f"Pitch {record['pitch']}"
            values = (
                timestamp[11:23] if len(timestamp) >= 23 else timestamp,
                record.get("message_type", "—"),
                record.get("channel", "—"),
                _midi_note_label(record.get("note")),
                record.get("velocity", "—"),
                control or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.monitor_table.setItem(row, column, item)
            self.monitor_table.scrollToBottom()
            count = int(self.monitor_count.property("messageCount") or 0) + 1
            self.monitor_count.setProperty("messageCount", count)
            self.monitor_count.setText(f"{count} message{'s' if count != 1 else ''}")
            if record.get("message_type") == "note_on" and int(record.get("velocity", 0) or 0) > 0:
                self.last_hit.setText(
                    f"Canal {record.get('channel', '—')}  ·  Note {_midi_note_label(record.get('note'))}  ·  "
                    f"Vélocité {record.get('velocity', '—')}"
                )

        def clear_midi_monitor(self) -> None:
            self.monitor_records.clear()
            self.monitor_table.setRowCount(0)
            self.monitor_count.setProperty("messageCount", 0)
            self.monitor_count.setText("0 message")
            self.last_hit.setText("Frappe un pad pour vérifier sa note et sa vélocité")

        def export_midi_monitor(self) -> None:
            if not self.monitor_records:
                QMessageBox.information(self, "Journal MIDI vide", "Aucun message MIDI n’a encore été reçu.")
                return
            path = self.choose_new_path(
                "Exporter le test MIDI",
                Path("ddti-midi-test.jsonl"),
                "Journal JSON Lines (*.jsonl)",
            )
            if path is None:
                return
            try:
                path.write_text(
                    "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in self.monitor_records),
                    encoding="utf-8",
                )
            except OSError as error:
                QMessageBox.warning(self, "Export impossible", str(error))
                return
            self.statusBar().showMessage(f"Journal MIDI exporté : {path}")

        @Slot(str)
        def _midi_monitor_failed(self, message: str) -> None:
            self.device_status.setText("● Test MIDI indisponible")
            if not self._close_after_monitor:
                QMessageBox.warning(self, "Test MIDI impossible", message)

        @Slot()
        def _midi_monitor_finished(self) -> None:
            self.monitor_thread = None
            self.monitor_worker = None
            self.monitor_button.setEnabled(True)
            self.monitor_button.setText("Démarrer l’écoute")
            self.synchronize_button.setEnabled(True)
            if not self._close_after_monitor:
                self.device_status.setText("● Test MIDI arrêté")
            if self._close_after_monitor:
                self._close_after_monitor = False
                QTimer.singleShot(0, self.close)

        def _save_last_known(self, raw: bytes, *, source: str, reason: str) -> Path | None:
            try:
                return self.state_store.save(raw, source=source, reason=reason)
            except OSError as error:
                QMessageBox.warning(
                    self,
                    "Cache local indisponible",
                    "L’état de travail reste ouvert, mais il n’a pas pu être mémorisé.\n\n" + str(error),
                )
                return None

        def set_zone(self, input_number: int, zone: str, field: str, value: int) -> None:
            if self._refreshing:
                return
            self.configuration = self.configuration.with_zone(self.selected_kit(), input_number, zone, **{field: value})
            self.refresh_status()

        def set_hi_hat(self, field: str, value: int) -> None:
            if self._refreshing:
                return
            self.configuration = self.configuration.with_hi_hat_kit_settings(self.selected_kit(), **{field: value})
            self.refresh_status()

        def set_program_change(self, value: int) -> None:
            if self._refreshing:
                return
            self.configuration = self.configuration.with_program_change(self.selected_kit(), None if value == -1 else value)
            self.refresh_status()

        def set_global_trigger(self, field: str, value: int) -> None:
            if self._refreshing:
                return
            self.configuration = self.configuration.with_global_trigger_settings(self.selected_record(), {field: value})
            self.refresh_status()

        def set_velocity_curve(self, index: int) -> None:
            if self._refreshing or index < 0:
                return
            self.set_global_trigger("velocity_curve", int(self.curve.itemData(index)))

        def choose_new_path(self, title: str, suggestion: Path, file_filter: str) -> Path | None:
            destination, _ = QFileDialog.getSaveFileName(self, title, str(suggestion), file_filter)
            if not destination:
                return None
            path = Path(destination)
            if path.exists():
                QMessageBox.warning(self, "Fichier existant", "Choisis un nouveau nom : aucun fichier n’est écrasé.")
                return None
            return path

        def open_dump(self) -> None:
            if self._has_staged_changes():
                answer = QMessageBox.question(
                    self,
                    "Remplacer les changements ?",
                    "Ouvrir un autre dump abandonnera les changements non envoyés. Continuer ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            filename, _ = QFileDialog.getOpenFileName(self, "Ouvrir un dump DDTi", "", "SysEx (*.syx)")
            if not filename:
                return
            try:
                configuration = _decode_complete_configuration(Path(filename))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Dump refusé", str(error))
                return
            self.configuration = configuration
            self.source_raw = configuration.raw
            self.source_label = filename
            self._save_last_known(configuration.raw, source=filename, reason="opened verified dump")
            self.refresh_all()
            self.statusBar().showMessage(f"Source : {filename}")

        def synchronize_from_ddti(self) -> None:
            if self._monitor_is_active():
                self.statusBar().showMessage("Arrête d’abord le test MIDI en direct.")
                return
            if self.capture_thread is not None and self.capture_thread.isRunning():
                self.capture_worker.cancel()
                self.synchronize_button.setEnabled(False)
                self.device_status.setText("● Annulation de l’écoute…")
                return
            if self._has_staged_changes():
                answer = QMessageBox.question(
                    self,
                    "Remplacer les changements ?",
                    "La synchronisation remplacera les changements non envoyés. Continuer ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            answer = QMessageBox.information(
                self,
                "Synchronisation DDTi",
                "Après avoir fermé ce message, appuie sur FUNCTION ↑ + VALUE ↑ sur le DDTi.\n\n"
                "L’application écoutera pendant trois minutes et remplacera l’état de travail uniquement après un dump complet de 42 trames.",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok,
            )
            if answer != QMessageBox.Ok:
                return
            capture_directory = self.state_store.directory / "captures"
            stem = capture_directory / f"sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            self.capture_thread = QThread(self)
            self.capture_worker = CaptureWorker(stem)
            self.capture_worker.moveToThread(self.capture_thread)
            self.capture_thread.started.connect(self.capture_worker.run)
            self.capture_worker.completed.connect(self._synchronization_complete)
            self.capture_worker.failed.connect(self._synchronization_failed)
            self.capture_worker.cancelled.connect(self._synchronization_cancelled)
            self.capture_worker.completed.connect(self.capture_thread.quit)
            self.capture_worker.failed.connect(self.capture_thread.quit)
            self.capture_worker.cancelled.connect(self.capture_thread.quit)
            self.capture_thread.finished.connect(self.capture_worker.deleteLater)
            self.capture_thread.finished.connect(self.capture_thread.deleteLater)
            self.device_status.setText("● Écoute du dump DDTi…")
            self.synchronize_button.setText("Annuler l’écoute")
            self._set_capture_active(True)
            self.capture_thread.finished.connect(self._synchronization_finished)
            self.capture_thread.start()

        def _set_capture_active(self, active: bool) -> None:
            for button in self.action_buttons:
                if button is not self.synchronize_button:
                    button.setEnabled(not active)
            self.write_button.setEnabled(not active)
            self.kit_list.setEnabled(not active)
            self.tabs.setEnabled(not active)
            if not active:
                self.synchronize_button.setEnabled(True)
                self.synchronize_button.setText("Synchroniser")

        @Slot()
        def _synchronization_finished(self) -> None:
            self._set_capture_active(False)
            self.capture_thread = None
            self.capture_worker = None
            if self._close_after_capture:
                self._close_after_capture = False
                QTimer.singleShot(0, self.close)

        @Slot(object)
        def _synchronization_complete(self, result) -> None:
            try:
                configuration = _decode_complete_configuration(result.syx_path)
            except (OSError, ValueError) as error:
                self._synchronization_failed(str(error))
                return
            self.configuration = configuration
            self.source_raw = configuration.raw
            self.source_label = str(result.syx_path)
            self._save_last_known(
                configuration.raw,
                source=self.source_label,
                reason="complete panel synchronization",
            )
            self.refresh_all()
            self.device_status.setText("● Synchronisé — 42 trames reçues")
            self.statusBar().showMessage(f"Source : {self.source_label}")

        @Slot(str)
        def _synchronization_failed(self, message: str) -> None:
            self.device_status.setText("● Synchronisation échouée")
            if not self._close_after_capture:
                QMessageBox.warning(self, "Synchronisation échouée", message)

        @Slot()
        def _synchronization_cancelled(self) -> None:
            self.device_status.setText("● Synchronisation annulée")

        def import_preset(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Importer une configuration", "", "Configuration (*.yaml *.yml *.json)")
            if not filename:
                return
            try:
                document = load_document(Path(filename))
                if document.get("format") != CONFIGURATION_PRESET_FORMAT:
                    raise ValueError(f"format attendu : {CONFIGURATION_PRESET_FORMAT}")
                self.configuration = self.configuration.with_configuration_preset(document)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Import refusé", str(error))
                return
            self.refresh_all()

        def apply_role_preset(self) -> None:
            template_name, _ = QFileDialog.getOpenFileName(self, "Choisir le mapping GM/SD3", "", "Preset (*.yaml *.yml *.json)")
            if not template_name:
                return
            layout_name, _ = QFileDialog.getOpenFileName(self, "Choisir le câblage DDTi", "", "Câblage (*.yaml *.yml *.json)")
            if not layout_name:
                return
            try:
                self.configuration = apply_role_template(
                    self.configuration,
                    load_document(Path(template_name)),
                    load_document(Path(layout_name)),
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Mapping refusé", str(error))
                return
            self.refresh_all()

        def export_configuration_preset(self) -> None:
            path = self.choose_new_path("Exporter la configuration", Path("ddti-config.yaml"), "YAML (*.yaml *.yml);;JSON (*.json)")
            if path is not None:
                try:
                    write_document(path, self.configuration.to_configuration_preset(name=path.stem))
                except (OSError, ValueError) as error:
                    QMessageBox.warning(self, "Export impossible", str(error))
                    return
                self.statusBar().showMessage(f"Configuration exportée : {path}")

        def export_sysex(self) -> None:
            path = self.choose_new_path("Exporter le SysEx", Path("ddti-staged.syx"), "SysEx (*.syx)")
            if path is not None:
                try:
                    path.write_bytes(self.configuration.raw)
                except OSError as error:
                    QMessageBox.warning(self, "Export impossible", str(error))
                    return
                self.statusBar().showMessage(f"SysEx exporté : {path}")

        def review_staged_diff(self) -> None:
            differences = diff_ddti_bytes(self.source_raw, self.configuration.raw)
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Changements en attente")
            dialog.setText(f"{len(differences)} octet(s) modifié(s). Rien n’a encore été envoyé.")
            dialog.setDetailedText(render_diff(differences))
            dialog.exec()

        def discard_changes(self) -> None:
            if not self._has_staged_changes():
                return
            answer = QMessageBox.question(
                self,
                "Annuler les changements",
                "Abandonner tous les changements non envoyés ?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            self.configuration = decode_configuration(decode_dump(self.source_raw))
            self.refresh_all()

        def write_to_ddti(self) -> None:
            try:
                plan = build_safe_write_plan(self.source_raw, self.configuration.raw)
            except (ValueError, RuntimeError) as error:
                QMessageBox.warning(self, "Envoi refusé", str(error))
                return
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Confirmer l’envoi DDTi")
            dialog.setIcon(QMessageBox.Warning)
            dialog.setText(f"Envoyer 42 trames et {len(plan.differences)} changement(s) validé(s) ?\n\nSHA-256 : {plan.sha256}\n\nLe dernier état connu sera sauvegardé automatiquement.")
            dialog.setDetailedText(render_diff(plan.differences))
            dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            dialog.setDefaultButton(QMessageBox.No)
            if dialog.exec() != QMessageBox.Yes:
                return
            try:
                self.state_store.save(
                    self.source_raw,
                    source=self.source_label,
                    reason="pre-write persistence check",
                )
            except OSError as error:
                QMessageBox.warning(
                    self,
                    "Envoi refusé",
                    f"L’état de sécurité local ne peut pas être écrit. Aucun octet n’a été envoyé.\n\n{error}",
                )
                return
            try:
                result = send_safe_configuration(self.source_raw, self.configuration.raw, "TriggerIO", expected_sha256=plan.sha256, confirmation="I_AUTHORIZE_DDTI_CONFIRMED_FIELDS", inter_message_ms=50)
            except (ValueError, RuntimeError) as error:
                QMessageBox.warning(self, "Échec de l’envoi", str(error))
                return
            self.source_raw = plan.raw
            self.configuration = decode_configuration(plan.transfer.dump)
            try:
                saved = self.state_store.save(
                    plan.raw,
                    source=self.source_label,
                    reason="successful confirmed-fields write",
                )
            except OSError as error:
                self.refresh_all()
                self.device_status.setText("● Envoyé — cache local à resynchroniser")
                QMessageBox.critical(
                    self,
                    "DDTi envoyé, cache non sauvegardé",
                    "Le DDTi a bien reçu la configuration, mais le cache local n’a pas pu être mis à jour. "
                    f"Garde l’application ouverte et resynchronise avant de la fermer.\n\n{error}",
                )
                return
            self.refresh_all()
            QMessageBox.information(self, "Configuration envoyée", f"{result.packet_count} trames envoyées vers {result.output_port}.\nÉtat local : {saved}\nSHA-256 : {result.sha256}")

        def closeEvent(self, event) -> None:
            capture_active = self.capture_thread is not None and self.capture_thread.isRunning()
            monitor_active = self._monitor_is_active()
            if not self._close_confirmed and (capture_active or monitor_active or self._has_staged_changes()):
                details = []
                if capture_active:
                    details.append("l’écoute DDTi en cours sera annulée")
                if monitor_active:
                    details.append("le test MIDI en direct sera arrêté")
                if self._has_staged_changes():
                    details.append("les changements non envoyés seront perdus")
                answer = QMessageBox.question(
                    self,
                    "Fermer DDTi Editor ?",
                    "Fermer maintenant : " + " et ".join(details) + ". Continuer ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
                self._close_confirmed = True
            if capture_active:
                self._close_after_capture = True
                self.capture_worker.cancel()
                self.synchronize_button.setEnabled(False)
                self.device_status.setText("● Annulation avant fermeture…")
                event.ignore()
                return
            if monitor_active:
                self._close_after_monitor = True
                self.monitor_worker.cancel()
                self.monitor_button.setEnabled(False)
                self.device_status.setText("● Arrêt du test avant fermeture…")
                event.ignore()
                return
            event.accept()

    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(_STYLE)
    editor = Editor(dump_path)
    editor.resize(1240, 780)
    editor.show()
    return application.exec()
