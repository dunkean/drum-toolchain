"""Browse captured sources and real DDrum4 codec-decoded WAVs.

The UI follows the actual Sound structure: Sound slot, NOTE P position,
Variation and Layer. It never opens MIDI or communicates with a module.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import re
import tempfile
from typing import Any

import numpy as np
from scipy.io import wavfile

from .codec_preview import CodecLayer, CodecPreviewSound, export_codec_preview, load_codec_preview, render_preview
from .ddrum4edit_backend import Ddrum4EditBackend
from .ddrum4ui import discover


@dataclass(frozen=True)
class AuditionEntry:
    instrument: str
    display_name: str
    articulation: str
    logical_target: str
    sound_slot: str
    return_note: int
    note_p: int
    variation: str | None
    velocity: int
    round_robin: int
    raw_file: str
    audio_path: Path

    @property
    def key(self) -> tuple[str, str]:
        return self.instrument, self.articulation


@dataclass(frozen=True)
class UnavailableRoute:
    sound_slot: str
    return_note: int
    note_p: int
    label: str
    reason: str


@dataclass(frozen=True)
class CodecAttachment:
    slot: str
    preview: CodecPreviewSound
    manifest_path: Path
    encoded_blocks: int | None
    encoded_bytes: int | None
    layer_velocities: tuple[int | None, ...] = ()
    layer_sources: tuple[Path | None, ...] = ()
    sample_encoded_bytes: tuple[int | None, ...] = ()
    non_audio_file_bytes: int | None = None
    layer_parameter_bytes: int = 50
    variation_parameter_bytes: int = 20


def _text(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(row: dict[str, Any], name: str, low: int, high: int = 127) -> int:
    value = row.get(name)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _slot_order(slot: str) -> tuple[int, str]:
    match = re.match(r"S(\d{2})\b", slot)
    return (int(match.group(1)), slot) if match else (999, slot)


def _human_bytes(size: int | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in {"B", "KB"} else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _exact_bytes(size: int | None) -> str:
    if size is None:
        return "taille inconnue"
    return f"{_human_bytes(size)} ({size:,} B)".replace(",", " ")


class CaptureAuditionCatalog:
    """Validated and queryable capture package."""

    def __init__(
        self,
        package_directory: Path,
        audio_root: Path,
        entries: tuple[AuditionEntry, ...],
        unavailable_routes: tuple[UnavailableRoute, ...] = (),
        variation_names: dict[str, dict[int, str]] | None = None,
        variation_descriptions: dict[str, dict[int, str]] | None = None,
        variation_models: dict[str, dict[int, dict[str, object]]] | None = None,
        design_slots: tuple[str, ...] = (),
        library_name: str | None = None,
    ) -> None:
        self.package_directory = package_directory
        self.audio_root = audio_root
        self.entries = entries
        self.unavailable_routes = unavailable_routes
        self.variation_names = variation_names or {}
        self.variation_descriptions = variation_descriptions or {}
        self.variation_models = variation_models or {}
        self.library_name = library_name or package_directory.name
        grouped: dict[tuple[str, str], list[AuditionEntry]] = {}
        by_slot: dict[str, list[AuditionEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.key, []).append(entry)
            by_slot.setdefault(entry.sound_slot, []).append(entry)
        self._by_key = {key: tuple(value) for key, value in grouped.items()}
        self._by_slot = {slot: tuple(value) for slot, value in by_slot.items()}
        slots = set(design_slots) | set(by_slot) | {route.sound_slot for route in unavailable_routes}
        self._sound_slots = tuple(sorted(slots, key=_slot_order))

    @classmethod
    def load(cls, package_directory: Path) -> "CaptureAuditionCatalog":
        package_directory = package_directory.resolve()
        try:
            simulation = json.loads((package_directory / "ddrum4-routing-simulation.json").read_text(encoding="utf-8"))
            source_root = simulation["source_audio_root"]
            rows = json.loads((package_directory / "audition" / "catalog.json").read_text(encoding="utf-8"))
            unavailable_rows = simulation.get("unavailable_routes", [])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read DDrum4 capture package: {error}") from error
        if not isinstance(source_root, str) or not source_root or not isinstance(rows, list) or not isinstance(unavailable_rows, list):
            raise ValueError("invalid DDrum4 capture package catalogue")
        audio_root = Path(source_root)
        if not audio_root.is_absolute():
            audio_root = package_directory / audio_root
        entries: list[AuditionEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("capture catalogue entry must be an object")
            try:
                variation = row.get("variation")
                if variation is not None and not isinstance(variation, str):
                    raise ValueError("variation must be a string when present")
                display_name = row.get("display_name", _text(row, "instrument"))
                if not isinstance(display_name, str) or not display_name:
                    raise ValueError("display_name must be a non-empty string when present")
                raw_file = _text(row, "raw_file")
                entries.append(AuditionEntry(
                    _text(row, "instrument"), display_name, _text(row, "articulation"),
                    _text(row, "logical_target"), _text(row, "sound_slot"),
                    _number(row, "return_note", 0), _number(row, "note_p", 1, 8),
                    variation, _number(row, "velocity", 1), _number(row, "round_robin", 1),
                    raw_file, (audio_root / raw_file).resolve(),
                ))
            except ValueError as error:
                raise ValueError(f"invalid capture catalogue entry: {error}") from error
        if not entries:
            raise ValueError("DDrum4 capture package has no audition entries")
        unavailable: list[UnavailableRoute] = []
        for row in unavailable_rows:
            if not isinstance(row, dict):
                raise ValueError("unavailable route must be an object")
            try:
                unavailable.append(UnavailableRoute(
                    _text(row, "sound_slot"), _number(row, "return_note", 0), _number(row, "note_p", 1, 8),
                    f"{_text(row, 'instrument')} / {_text(row, 'articulation')}", _text(row, "reason"),
                ))
            except ValueError as error:
                raise ValueError(f"invalid unavailable DDrum4 route: {error}") from error

        names: dict[str, dict[int, str]] = {}
        descriptions: dict[str, dict[int, str]] = {}
        models: dict[str, dict[int, dict[str, object]]] = {}
        slots: list[str] = []
        design_path = package_directory / "kit-design.json"
        if design_path.is_file():
            try:
                design = json.loads(design_path.read_text(encoding="utf-8"))
                sounds = design.get("sounds", []) if isinstance(design, dict) else []
                for sound in sounds:
                    if not isinstance(sound, dict) or not isinstance(sound.get("slot"), str):
                        continue
                    slot = sound["slot"]
                    slots.append(slot)
                    variations = [item for item in sound.get("variations", []) if isinstance(item, dict)]
                    names[slot] = {
                        item["index"]: item["name"] for item in variations
                        if type(item.get("index")) is int and isinstance(item.get("name"), str)
                    }
                    descriptions[slot] = {
                        item["index"]: item["description"] for item in variations
                        if type(item.get("index")) is int and isinstance(item.get("description"), str)
                    }
                    models[slot] = {
                        item["index"]: dict(item["model"])
                        for item in variations
                        if type(item.get("index")) is int and isinstance(item.get("model"), dict)
                    }
            except (OSError, json.JSONDecodeError):
                pass
        library = simulation.get("library") if isinstance(simulation.get("library"), str) else None
        return cls(
            package_directory, audio_root.resolve(),
            tuple(sorted(entries, key=lambda item: (item.sound_slot, item.note_p, item.instrument, item.articulation, item.velocity, item.round_robin))),
            tuple(sorted(unavailable, key=lambda item: (item.sound_slot, item.note_p, item.label))),
            names, descriptions, models, tuple(slots), library,
        )

    @property
    def keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._by_key))

    @property
    def sound_slots(self) -> tuple[str, ...]:
        return self._sound_slots

    def entries_for(self, key: tuple[str, str]) -> tuple[AuditionEntry, ...]:
        try:
            return self._by_key[key]
        except KeyError as error:
            raise ValueError(f"unknown capture articulation: {key[0]}.{key[1]}") from error

    def entries_for_slot(self, slot: str) -> tuple[AuditionEntry, ...]:
        return self._by_slot.get(slot, ())

    def entries_at(self, slot: str, note_p: int) -> tuple[AuditionEntry, ...]:
        return tuple(entry for entry in self.entries_for_slot(slot) if entry.note_p == note_p)

    def note_positions(self, slot: str) -> tuple[int, ...]:
        values = {entry.note_p for entry in self.entries_for_slot(slot)}
        values.update(route.note_p for route in self.unavailable_routes if route.sound_slot == slot)
        return tuple(sorted(values))

    def velocities_for(self, key: tuple[str, str]) -> tuple[int, ...]:
        return tuple(sorted({entry.velocity for entry in self.entries_for(key)}))

    def round_robins_for(self, key: tuple[str, str], velocity: int) -> tuple[int, ...]:
        return tuple(sorted({entry.round_robin for entry in self.entries_for(key) if entry.velocity == velocity}))

    def resolve(self, key: tuple[str, str], velocity: int, round_robin: int | None = None) -> AuditionEntry:
        if not 1 <= velocity <= 127:
            raise ValueError("velocity must be in 1..127")
        actual = min(self.velocities_for(key), key=lambda value: (abs(value - velocity), -value))
        candidates = [entry for entry in self.entries_for(key) if entry.velocity == actual]
        if round_robin is None:
            return min(candidates, key=lambda entry: entry.round_robin)
        result = next((entry for entry in candidates if entry.round_robin == round_robin), None)
        if result is None:
            values = ", ".join(str(value) for value in self.round_robins_for(key, actual))
            raise ValueError(f"{key[0]}.{key[1]} v{actual:03d} has round robins: {values}")
        return result

    def resolve_position(self, slot: str, note_p: int, velocity: int, round_robin: int) -> AuditionEntry:
        entries = self.entries_at(slot, note_p)
        if not entries:
            raise ValueError(f"{slot} P{note_p} has no captured source")
        key = min({entry.key for entry in entries})
        actual = min({entry.velocity for entry in entries if entry.key == key}, key=lambda value: (abs(value - velocity), -value))
        candidates = [entry for entry in entries if entry.key == key and entry.velocity == actual]
        return next((entry for entry in candidates if entry.round_robin == round_robin), min(candidates, key=lambda item: item.round_robin))


def _load_codec_attachment(
    manifest_path: Path,
    known_slots: tuple[str, ...],
    preferred_slot: str | None = None,
) -> CodecAttachment:
    manifest_path = manifest_path.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {manifest_path}: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("kind") != "ddrum4-codec-preview/v1":
        raise ValueError(f"{manifest_path} is not a DDrum4 codec preview")
    config_name, decoded_name = manifest.get("preview_config"), manifest.get("decoded_directory")
    if not isinstance(config_name, str) or not isinstance(decoded_name, str):
        raise ValueError(f"{manifest_path} has no preview config or decoded directory")
    source_name = manifest.get("source_sound")
    source_sound = Path(source_name) if isinstance(source_name, str) else None
    if source_sound is not None and not source_sound.is_absolute():
        source_sound = manifest_path.parent / source_sound
    layer_directory_name = manifest.get("decoded_layer_directory")
    layer_directory = (
        manifest_path.parent / layer_directory_name
        if isinstance(layer_directory_name, str) and layer_directory_name else None
    )
    preview = load_codec_preview(
        manifest_path.parent / config_name, manifest_path.parent / decoded_name,
        source_sound=source_sound, decoded_layer_directory=layer_directory,
    )
    slot = manifest.get("sound_slot")
    if not isinstance(slot, str) or slot not in known_slots:
        haystack = re.sub(r"[^A-Z0-9]+", " ", f"{manifest_path.parent.name} {preview.sound_name}".upper())
        matches = [candidate for candidate in known_slots if candidate[:3] in haystack]
        if len(matches) != 1:
            matches = [candidate for candidate in known_slots if candidate.split(maxsplit=1)[-1].upper() in haystack]
        if len(matches) == 1:
            slot = matches[0]
        elif preferred_slot in known_slots:
            slot = preferred_slot
        else:
            raise ValueError(f"cannot associate codec preview {preview.sound_name} with a kit Sound")
    blocks = manifest.get("encoded_blocks")
    if blocks is not None and (type(blocks) is not int or blocks < 1):
        raise ValueError(f"{manifest_path} has an invalid encoded block count")
    encoded_bytes = manifest.get("source_sound_bytes")
    if encoded_bytes is not None and (type(encoded_bytes) is not int or encoded_bytes < 1):
        encoded_bytes = None
    if encoded_bytes is None and source_sound is not None and source_sound.is_file():
        encoded_bytes = source_sound.stat().st_size
    layer_velocities: list[int | None] = [None] * 10
    layer_sources: list[Path | None] = [None] * 10
    sample_encoded_bytes: list[int | None] = [None] * 10
    encoded_sizes = manifest.get("sample_encoded_bytes", [])
    if isinstance(encoded_sizes, list):
        for index, value in enumerate(encoded_sizes[:10]):
            if type(value) is int and value >= 0:
                sample_encoded_bytes[index] = value
    kit_layers = manifest.get("kit_layers", [])
    if isinstance(kit_layers, list):
        for item in kit_layers:
            if not isinstance(item, dict) or type(item.get("index")) is not int or not 1 <= item["index"] <= 10:
                continue
            offset = item["index"] - 1
            velocity = item.get("velocity")
            if type(velocity) is int and 1 <= velocity <= 127:
                layer_velocities[offset] = velocity
            source_path = item.get("source_path")
            if isinstance(source_path, str):
                layer_sources[offset] = Path(source_path).resolve()
    return CodecAttachment(
        slot, preview, manifest_path, blocks, encoded_bytes,
        tuple(layer_velocities), tuple(layer_sources), tuple(sample_encoded_bytes),
        manifest.get("non_audio_file_bytes") if type(manifest.get("non_audio_file_bytes")) is int else None,
        manifest.get("layer_parameter_bytes") if type(manifest.get("layer_parameter_bytes")) is int else 50,
        manifest.get("variation_parameter_bytes") if type(manifest.get("variation_parameter_bytes")) is int else 20,
    )


def discover_codec_attachments(catalog: CaptureAuditionCatalog) -> tuple[dict[str, CodecAttachment], tuple[str, ...]]:
    """Find package-owned previews and keep the newest valid preview per Sound."""
    manifests = set((catalog.package_directory / "codec-preview").glob("**/codec-preview.json"))
    attachments: dict[str, CodecAttachment] = {}
    errors: list[str] = []
    for manifest in sorted(manifests, key=lambda path: path.stat().st_mtime):
        try:
            attachment = _load_codec_attachment(manifest, catalog.sound_slots)
        except (OSError, ValueError) as error:
            errors.append(str(error))
        else:
            attachments[attachment.slot] = attachment
    return attachments, tuple(errors)


def active_layers_for_position(preview: CodecPreviewSound, variation: int, note_p: int) -> tuple[CodecLayer, ...]:
    """List all encoded Layers enabled by a Variation at a NOTE P."""
    if variation not in preview.available_variations or not 1 <= note_p <= 8:
        return ()
    row = preview.variations[variation - 1]
    return tuple(
        layer for layer in preview.layers
        if layer.index <= len(row.enabled) and row.enabled[layer.index - 1] and layer.gain_position[note_p - 1] > 0
    )


def encoded_layers(preview: CodecPreviewSound) -> tuple[CodecLayer, ...]:
    """Return Layers that belong to at least one encoded Variation."""
    enabled_indexes = {
        index + 1
        for variation in preview.variations
        for index, enabled in enumerate(variation.enabled)
        if enabled
    }
    return tuple(layer for layer in preview.layers if layer.index in enabled_indexes)


def _layer_variations(preview: CodecPreviewSound, layer: CodecLayer) -> str:
    values = [
        f"V{variation.index}" + ("·RR" if variation.sequenced[layer.index - 1] else "")
        for variation in preview.variations
        if layer.index <= len(variation.enabled) and variation.enabled[layer.index - 1]
    ]
    return ", ".join(values) or "aucune variation"


def _velocity_steps(layer: CodecLayer) -> str:
    values = [index + 1 for index, gain in enumerate(layer.gain_velocity) if gain > 0]
    if not values:
        return "vel —"
    if values == list(range(values[0], values[-1] + 1)):
        return f"vel steps {values[0]}–{values[-1]}"
    return "vel steps " + ",".join(map(str, values))


def prepare_guarded_playback(
    source: Path, output: Path, *, preroll_ms: float = 250.0,
) -> Path:
    """Prepend playback-only silence without changing the encoded waveform.

    QMediaPlayer/Windows can initialise an endpoint during the first few
    milliseconds of a newly selected file. Raw captures hide that startup in
    their long recording preroll; tightly trimmed codec previews do not.
    """
    if preroll_ms < 0:
        raise ValueError("playback preroll cannot be negative")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite guarded playback WAV: {output}")
    rate, samples = wavfile.read(source)
    frames = round(rate * preroll_ms / 1000.0)
    shape = (frames, *samples.shape[1:])
    guarded = np.concatenate((np.zeros(shape, dtype=samples.dtype), samples), axis=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(output, rate, guarded)
    return output


def _qt() -> dict[str, object]:
    try:
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtWidgets import (
            QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
            QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
            QScrollArea, QSizePolicy, QSplitter, QTableWidget,
            QTableWidgetItem, QVBoxLayout, QWidget,
        )
    except ImportError as error:
        raise RuntimeError("the capture audition window requires PySide6; install ddrum4-bank-builder[gui]") from error
    return locals()


def launch(package_directory: Path | None = None) -> int:
    """Open the Sound/layer/variation audition window."""
    qt = _qt()
    QApplication, QMainWindow, QWidget = qt["QApplication"], qt["QMainWindow"], qt["QWidget"]
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel = (
        qt["QVBoxLayout"], qt["QHBoxLayout"], qt["QGridLayout"], qt["QLabel"]
    )
    QPushButton, QLineEdit = qt["QPushButton"], qt["QLineEdit"]
    QTableWidget, QTableWidgetItem = qt["QTableWidget"], qt["QTableWidgetItem"]
    QAbstractItemView, QHeaderView = qt["QAbstractItemView"], qt["QHeaderView"]
    QScrollArea, QSplitter, QFrame, QSizePolicy = qt["QScrollArea"], qt["QSplitter"], qt["QFrame"], qt["QSizePolicy"]
    QFileDialog, QMessageBox = qt["QFileDialog"], qt["QMessageBox"]
    QAudioOutput, QMediaPlayer, QUrl, Qt = qt["QAudioOutput"], qt["QMediaPlayer"], qt["QUrl"], qt["Qt"]

    class AuditionerWindow(QMainWindow):
        def __init__(self, initial_package: Path | None) -> None:
            super().__init__()
            self.catalog: CaptureAuditionCatalog | None = None
            self.attachments: dict[str, CodecAttachment] = {}
            self._visible_slots: list[str] = []
            self._selected_slot: str | None = None
            self._temporary_audio = tempfile.TemporaryDirectory(prefix="ddrum4-auditioner-")
            self._preview_counter = 0
            self._playback_counter = 0
            self._guarded_playback = False
            self._sequence_steps: dict[tuple[str, int, int], int] = {}
            self.setWindowTitle("DDrum4 Sound Dump Browser")
            self.resize(1680, 940)
            self.setMinimumSize(1100, 700)
            self.setStyleSheet("""
                QWidget { background: #11171b; color: #e9edf1; font-family: "Segoe UI"; font-size: 13px; }
                QMainWindow { background: #0d1215; }
                QFrame#topBar, QFrame#sidePanel, QFrame#detailPanel, QFrame#statusBar, QFrame#soundCard {
                    background: #151c20; border: 1px solid #303a40; border-radius: 10px;
                }
                QLabel#brand { font-size: 25px; font-weight: 700; }
                QLabel#metric { background: #101619; border: 1px solid #364149; border-radius: 7px; padding: 9px 13px; }
                QLabel#title { color: #61a9ff; font-size: 25px; font-weight: 700; }
                QLabel#cardTitle { color: #61a9ff; font-size: 17px; font-weight: 650; }
                QLabel#sectionTitle { color: #d5dce2; font-size: 11px; font-weight: 700; letter-spacing: 0.7px; }
                QLabel#layerBadge { background: #20394a; border: 1px solid #3b6884; border-radius: 5px; color: #85c6ff; font-size: 14px; font-weight: 700; padding: 7px 8px; }
                QLabel#variationBadge { background: #183a57; border: 1px solid #397caf; border-radius: 5px; color: #9ed2ff; font-weight: 700; padding: 5px 7px; }
                QLabel#storage { color: #9bd1b7; font-weight: 600; }
                QLabel#muted { color: #aeb8bf; }
                QLabel#danger { color: #ff8f8f; }
                QFrame#section { background: #11181c; border: 1px solid #2c373d; border-radius: 7px; }
                QFrame#layerRow { background: #121a1e; border: 1px solid #29363d; border-radius: 6px; }
                QFrame#layerRow:hover { border-color: #46687a; background: #142027; }
                QLineEdit { background: #0e1418; border: 1px solid #354149; border-radius: 6px; padding: 7px; }
                QPushButton { background: #1b252b; border: 1px solid #46535c; border-radius: 6px; padding: 7px 11px; min-width: 72px; }
                QPushButton:hover { background: #263743; border-color: #61a9ff; }
                QPushButton:disabled { color: #68757d; background: #151c20; border-color: #293238; }
                QPushButton#encoded { color: #70b4ff; }
                QPushButton#primary { background: #173b57; color: #83c5ff; border-color: #397caf; }
                QPushButton#variationPlay { min-width: 104px; }
                QTableWidget { background: #11171b; alternate-background-color: #151d22; border: 0; gridline-color: #293238; }
                QTableWidget::item { padding: 8px; }
                QTableWidget::item:selected { background: #183a57; }
                QHeaderView::section { background: #151d22; border: 0; border-bottom: 1px solid #354149; padding: 7px; font-size: 11px; }
                QScrollArea { border: 0; background: transparent; }
                QSplitter::handle { background: #263038; width: 2px; }
            """)
            self.audio_output = QAudioOutput(self)
            self.audio_output.setVolume(0.9)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio_output)
            self.player.errorOccurred.connect(self._player_error)
            self.player.positionChanged.connect(self._player_position_changed)

            root = QWidget(self)
            self.setCentralWidget(root)
            outer = QVBoxLayout(root)
            outer.setContentsMargins(10, 10, 10, 10)
            outer.setSpacing(10)

            top = QFrame(root); top.setObjectName("topBar")
            top_layout = QHBoxLayout(top)
            brand = QLabel("◫  DDrum4 Sound Dump Browser"); brand.setObjectName("brand")
            top_layout.addWidget(brand); top_layout.addStretch()
            self.bank_metric = QLabel("BANK: —"); self.bank_metric.setObjectName("metric")
            self.sound_metric = QLabel("TOTAL SOUNDS: —"); self.sound_metric.setObjectName("metric")
            self.size_metric = QLabel("ENCODED SIZE: —"); self.size_metric.setObjectName("metric")
            top_layout.addWidget(self.bank_metric); top_layout.addWidget(self.sound_metric); top_layout.addWidget(self.size_metric)
            choose = QPushButton("Ouvrir un package…"); choose.clicked.connect(self.choose_package)
            top_layout.addWidget(choose)
            outer.addWidget(top)

            splitter = QSplitter(Qt.Orientation.Horizontal, root)
            outer.addWidget(splitter, 1)
            side = QFrame(splitter); side.setObjectName("sidePanel")
            side_layout = QVBoxLayout(side)
            self.search = QLineEdit(side); self.search.setPlaceholderText("Rechercher un Sound…")
            self.search.textChanged.connect(self._filter_sounds)
            side_layout.addWidget(self.search)
            self.sound_table = QTableWidget(0, 5, side)
            self.sound_table.setHorizontalHeaderLabels(("SOUND", "TYPE", "POSITIONS", "LAYERS", "ENCODÉ"))
            self.sound_table.verticalHeader().hide()
            self.sound_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.sound_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.sound_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.sound_table.setAlternatingRowColors(True)
            self.sound_table.itemSelectionChanged.connect(self._sound_selection_changed)
            header = self.sound_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for column in range(1, 5):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            side_layout.addWidget(self.sound_table, 1)
            self.showing = QLabel("Aucun Sound"); self.showing.setObjectName("muted")
            side_layout.addWidget(self.showing)

            detail = QFrame(splitter); detail.setObjectName("detailPanel")
            detail_layout = QVBoxLayout(detail)
            detail_header = QHBoxLayout()
            titles = QVBoxLayout()
            self.sound_title = QLabel("Sélectionne un Sound"); self.sound_title.setObjectName("title")
            self.sound_subtitle = QLabel("Sources et WAV encodés apparaîtront ici"); self.sound_subtitle.setObjectName("muted")
            titles.addWidget(self.sound_title); titles.addWidget(self.sound_subtitle)
            detail_header.addLayout(titles, 1)
            import_button = QPushButton("Décoder un Sound encodé…"); import_button.clicked.connect(self.import_codec_preview)
            load_button = QPushButton("Charger un aperçu…"); load_button.clicked.connect(self.load_codec_preview_dialog)
            detail_header.addWidget(import_button); detail_header.addWidget(load_button)
            detail_layout.addLayout(detail_header)

            controls = QHBoxLayout()
            instruction = QLabel("Clique directement une variation ou un Layer : sa vélocité encodée est utilisée automatiquement.")
            instruction.setObjectName("muted")
            controls.addWidget(instruction)
            controls.addStretch()
            stop = QPushButton("■ Stop"); stop.clicked.connect(self.player.stop)
            controls.addWidget(stop)
            detail_layout.addLayout(controls)

            self.card_scroll = QScrollArea(detail)
            self.card_scroll.setWidgetResizable(True)
            self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.card_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.card_host = QWidget(self.card_scroll)
            self.card_layout = QVBoxLayout(self.card_host)
            self.card_layout.setContentsMargins(2, 2, 2, 2)
            self.card_layout.setSpacing(10)
            self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.card_scroll.setWidget(self.card_host)
            detail_layout.addWidget(self.card_scroll, 1)
            splitter.addWidget(side); splitter.addWidget(detail); splitter.setSizes((470, 1180))

            status_frame = QFrame(root); status_frame.setObjectName("statusBar")
            status_layout = QHBoxLayout(status_frame)
            self.status = QLabel("Offline : aucun accès MIDI ou matériel."); self.status.setWordWrap(True)
            status_layout.addWidget(QLabel("ⓘ")); status_layout.addWidget(self.status, 1)
            outer.addWidget(status_frame)
            if initial_package is not None:
                self.load_package(initial_package)

        def choose_package(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Sélectionner ddrum4-routing-simulation.json", "",
                "DDrum4 package (ddrum4-routing-simulation.json)",
            )
            if filename:
                self.load_package(Path(filename).parent)

        def load_package(self, directory: Path) -> None:
            try:
                catalog = CaptureAuditionCatalog.load(directory)
            except ValueError as error:
                QMessageBox.warning(self, "Package invalide", str(error)); return
            self.player.stop()
            self.catalog = catalog
            self.attachments, errors = discover_codec_attachments(catalog)
            self.bank_metric.setText(f"BANK:  {catalog.library_name}")
            self._populate_sound_table()
            self._update_metrics()
            if self.sound_table.rowCount():
                self.sound_table.selectRow(0)
            message = f"{len(catalog.entries)} sources chargées ; {len(self.attachments)} Sound(s) encodé(s) détecté(s)."
            if errors:
                message += f" {len(errors)} aperçu(s) ignoré(s) car invalides ou non associables."
            self.status.setText(message)

        def _populate_sound_table(self) -> None:
            if self.catalog is None:
                return
            current = self._selected_slot
            self._visible_slots = list(self.catalog.sound_slots)
            self.sound_table.setRowCount(len(self._visible_slots))
            for row, slot in enumerate(self._visible_slots):
                attachment = self.attachments.get(slot)
                preview = attachment.preview if attachment else None
                values = (
                    preview.sound_name if preview else slot,
                    slot.split(maxsplit=1)[-1],
                    str(len(self.catalog.note_positions(slot))),
                    str(len(encoded_layers(preview))) if preview else "—",
                    _human_bytes(attachment.encoded_bytes) if attachment else "non encodé",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, slot)
                    self.sound_table.setItem(row, column, item)
                if slot == current:
                    self.sound_table.selectRow(row)
            self._filter_sounds(self.search.text())

        def _filter_sounds(self, query: str) -> None:
            query = query.casefold().strip()
            shown = 0
            for row, slot in enumerate(self._visible_slots):
                attachment = self.attachments.get(slot)
                name = attachment.preview.sound_name if attachment else slot
                visible = not query or query in f"{slot} {name}".casefold()
                self.sound_table.setRowHidden(row, not visible)
                shown += int(visible)
            self.showing.setText(f"{shown} Sound(s) affiché(s) sur {len(self._visible_slots)}")

        def _sound_selection_changed(self) -> None:
            row = self.sound_table.currentRow()
            item = self.sound_table.item(row, 0) if row >= 0 else None
            slot = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if isinstance(slot, str):
                self._selected_slot = slot
                self._rebuild_cards()

        def _clear_cards(self) -> None:
            while self.card_layout.count():
                item = self.card_layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()

        def _position_label(self, slot: str, note_p: int) -> str:
            if self.catalog is None:
                return f"P{note_p}"
            labels = sorted({f"{entry.display_name} / {entry.articulation}" for entry in self.catalog.entries_at(slot, note_p)})
            if labels:
                return " · ".join(labels)
            route = next((item for item in self.catalog.unavailable_routes if item.sound_slot == slot and item.note_p == note_p), None)
            return route.label if route else "Position encodée"

        def _rebuild_cards(self) -> None:
            self._clear_cards()
            if self.catalog is None or self._selected_slot is None:
                return
            slot = self._selected_slot
            attachment = self.attachments.get(slot)
            preview = attachment.preview if attachment else None
            positions_set = set(self.catalog.note_positions(slot)) if preview is None else set()
            if preview is not None:
                positions_set.update(
                    position
                    for layer in encoded_layers(preview)
                    for position, gain in enumerate(layer.gain_position, start=1)
                    if gain > 0
                )
            positions = tuple(sorted(positions_set))
            self.sound_title.setText(preview.sound_name if preview else slot)
            if attachment:
                storage = f"{_human_bytes(attachment.encoded_bytes)} total"
                if attachment.non_audio_file_bytes is not None:
                    storage += f" · en-tête/config {_exact_bytes(attachment.non_audio_file_bytes)}"
                self.sound_subtitle.setText(
                    f"{len(positions)} position(s) · {len(encoded_layers(preview))} layer(s) active(s) · "
                    f"{len(preview.available_variations)} variation(s) encodée(s) · {storage}"
                )
            else:
                self.sound_subtitle.setText(
                    f"{len(positions)} position(s) · {len(self.catalog.entries_for_slot(slot))} capture(s) source · aucun Sound encodé attaché"
                )
            for note_p in positions:
                self.card_layout.addWidget(self._build_position_card(slot, note_p, attachment))
            self.card_layout.addStretch()

        def _build_position_card(
            self, slot: str, note_p: int, attachment: CodecAttachment | None,
        ) -> object:
            card = QFrame(self.card_host); card.setObjectName("soundCard")
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 13, 14, 14)
            layout.setSpacing(9)
            header = QHBoxLayout()
            position_badge = QLabel(f"P{note_p}")
            position_badge.setObjectName("layerBadge")
            position_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(position_badge, 0, Qt.AlignmentFlag.AlignTop)
            title_column = QVBoxLayout()
            title = QLabel(self._position_label(slot, note_p))
            title.setObjectName("cardTitle"); title.setWordWrap(True)
            title_column.addWidget(title)
            entries = self.catalog.entries_at(slot, note_p) if self.catalog else ()
            if entries:
                velocities = sorted({entry.velocity for entry in entries})
                rrs = sorted({entry.round_robin for entry in entries})
                source_info = QLabel(
                    f"Source capturée · {len(velocities)} vélocité(s) : "
                    f"{', '.join(f'v{value:03d}' for value in velocities)} · "
                    f"round robin : {', '.join(map(str, rrs))}"
                )
                source_info.setObjectName("muted")
                source_info.setWordWrap(True)
                title_column.addWidget(source_info)
            else:
                route = next(
                    (item for item in self.catalog.unavailable_routes if item.sound_slot == slot and item.note_p == note_p),
                    None,
                ) if self.catalog else None
                warning = QLabel("⛔ " + (route.reason if route else "Source indisponible"))
                warning.setObjectName("danger"); warning.setWordWrap(True)
                title_column.addWidget(warning)
            header.addLayout(title_column, 1)
            layout.addLayout(header)

            if attachment is None:
                missing = QLabel("Aucun WAV encodé pour ce Sound. Charge ou décode le .mid/.syx avec son .cfg.")
                missing.setObjectName("muted"); missing.setWordWrap(True); layout.addWidget(missing)
                source_button = QPushButton("▶ Écouter la source"); source_button.setEnabled(bool(entries))
                source_button.clicked.connect(lambda _checked=False, s=slot, p=note_p: self.play_source(s, p))
                layout.addWidget(source_button)
                return card

            preview = attachment.preview
            layers = tuple(
                layer for layer in encoded_layers(preview)
                if layer.gain_position[note_p - 1] > 0
            )
            if not layers:
                missing = QLabel("Aucun Layer encodé à cette position.")
                missing.setObjectName("danger"); layout.addWidget(missing)
                return card

            variation_section = QFrame(card); variation_section.setObjectName("section")
            variation_layout = QVBoxLayout(variation_section)
            variation_layout.setContentsMargins(11, 10, 11, 11)
            variation_layout.setSpacing(6)
            variation_label = QLabel("VARIATIONS ENCODÉES")
            variation_label.setObjectName("sectionTitle")
            variation_layout.addWidget(variation_label)
            declared_variations = (
                tuple(sorted(self.catalog.variation_names.get(slot, {})))
                if self.catalog else ()
            )
            variations = declared_variations or preview.available_variations
            for variation in variations:
                active = active_layers_for_position(preview, variation, note_p)
                name = (
                    self.catalog.variation_names.get(slot, {}).get(variation, f"Variation {variation}")
                    if self.catalog else f"Variation {variation}"
                )
                variation_row = QFrame(variation_section); variation_row.setObjectName("layerRow")
                row_layout = QGridLayout(variation_row)
                row_layout.setContentsMargins(8, 7, 8, 7)
                row_layout.setHorizontalSpacing(9)
                row_layout.setVerticalSpacing(2)
                variation_badge = QLabel(f"V{variation}")
                variation_badge.setObjectName("variationBadge")
                variation_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(variation_badge, 0, 0, 2, 1)
                variation_name = QLabel(name)
                variation_name.setStyleSheet("font-weight: 650;")
                variation_name.setWordWrap(True)
                row_layout.addWidget(variation_name, 0, 1)
                description = (
                    self.catalog.variation_descriptions.get(slot, {}).get(variation, "")
                    if self.catalog else ""
                )
                if not active:
                    unavailable = QLabel(
                        f"0 B audio ajouté · config variation {_exact_bytes(attachment.variation_parameter_bytes)} · "
                        f"aucun layer actif à P{note_p}"
                    )
                    unavailable.setObjectName("muted")
                    unavailable.setWordWrap(True)
                    row_layout.addWidget(unavailable, 1, 1)
                    disabled = QPushButton("Indisponible")
                    disabled.setEnabled(False)
                    row_layout.addWidget(disabled, 0, 2, 2, 1)
                    row_layout.setColumnStretch(1, 1)
                    variation_layout.addWidget(variation_row)
                    continue
                pitch = self._variation_pitch(slot, variation, note_p)
                decay = self._variation_number(slot, variation, "decay_percent", 100.0)
                velocities = tuple(sorted({self._layer_velocity(attachment, layer) for layer in active}))
                velocity = max(velocities)
                model_parts = [
                    f"v{velocity:03d}",
                    "layers " + ", ".join(f"L{layer.index:02d}" for layer in active),
                ]
                if pitch != 0.0:
                    model_parts.append(f"pitch {pitch:+.2f} st")
                if decay != 100.0:
                    model_parts.append(f"decay {decay:.0f}%")
                details = QLabel(" · ".join(model_parts))
                details.setObjectName("muted")
                details.setWordWrap(True)
                row_layout.addWidget(details, 1, 1)
                storage = QLabel(
                    f"0 B audio ajouté · config variation {_exact_bytes(attachment.variation_parameter_bytes)}"
                )
                storage.setObjectName("storage")
                storage.setWordWrap(True)
                row_layout.addWidget(storage, 0, 2, 1, 1)
                if description:
                    variation_name.setToolTip(description)
                    details.setToolTip(description)
                button = QPushButton("▶ Écouter")
                button.setObjectName("variationPlay")
                button.clicked.connect(
                    lambda _checked=False, s=slot, p=note_p, v=variation, level=velocity:
                    self.play_variation(s, p, v, level)
                )
                button.setToolTip(f"Écouter V{variation} à la vélocité encodée v{velocity:03d}.")
                row_layout.addWidget(button, 1, 2)
                row_layout.setColumnStretch(1, 1)
                variation_layout.addWidget(variation_row)
            layout.addWidget(variation_section)

            layer_section = QFrame(card); layer_section.setObjectName("section")
            layer_layout = QVBoxLayout(layer_section)
            layer_layout.setContentsMargins(11, 10, 11, 11)
            layer_layout.setSpacing(6)
            layer_label = QLabel(f"LAYERS ENCODÉS · {len(layers)} À CETTE POSITION")
            layer_label.setObjectName("sectionTitle")
            layer_layout.addWidget(layer_label)
            for layer in layers:
                layer_row = QFrame(layer_section); layer_row.setObjectName("layerRow")
                row_layout = QGridLayout(layer_row)
                row_layout.setContentsMargins(8, 8, 8, 8)
                row_layout.setHorizontalSpacing(10)
                row_layout.setVerticalSpacing(3)
                layer_badge = QLabel(f"L{layer.index:02d}")
                layer_badge.setObjectName("layerBadge")
                layer_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(layer_badge, 0, 0, 4, 1)
                sample = preview.samples[layer.sample_index]
                velocity = self._layer_velocity(attachment, layer)
                source_name = preview.sample_file_names[layer.sample_index] or f"sample {layer.sample_index + 1}"
                layer_title = QLabel(f"v{velocity:03d} · Sample S{layer.sample_index + 1:02d}")
                layer_title.setStyleSheet("font-weight: 650;")
                row_layout.addWidget(layer_title, 0, 1)
                source_label = QLabel(Path(source_name).name)
                source_label.setObjectName("muted")
                source_label.setWordWrap(True)
                source_label.setToolTip(source_name)
                row_layout.addWidget(source_label, 1, 1)
                sample_owners = [
                    item.index for item in preview.layers if item.sample_index == layer.sample_index
                ]
                owns_audio = layer.index == min(sample_owners)
                encoded_sample_bytes = (
                    attachment.sample_encoded_bytes[layer.sample_index]
                    if layer.sample_index < len(attachment.sample_encoded_bytes) else None
                )
                if owns_audio:
                    audio_storage = (
                        f"audio encodé {_exact_bytes(encoded_sample_bytes)}"
                        if encoded_sample_bytes is not None else "audio encodé : taille inconnue"
                    )
                else:
                    audio_storage = f"0 B audio ajouté · partage S{layer.sample_index + 1:02d}"
                storage = QLabel(
                    f"{audio_storage} · config Layer {_exact_bytes(attachment.layer_parameter_bytes)} · "
                    f"WAV décodé {_exact_bytes(sample.stat().st_size) if sample is not None and sample.is_file() else 'manquant'}"
                )
                storage.setObjectName("storage"); storage.setWordWrap(True)
                row_layout.addWidget(storage, 2, 1, 1, 2)
                metadata = QLabel(
                    f"{_velocity_steps(layer)} · {_layer_variations(preview, layer)} · "
                    f"DSP : pitch {layer.pitch_semitones:+d}.{layer.pitch_fine_tenths} st · amp {layer.amplitude} · "
                    f"attack {layer.raw_values[30]} · decay {layer.raw_values[32]} · "
                    f"F1 {layer.raw_values[36]}/{layer.raw_values[38]}/Q{layer.raw_values[40]} · "
                    f"F2 {layer.raw_values[42]}/Q{layer.raw_values[44]}"
                )
                metadata.setObjectName("muted"); metadata.setWordWrap(True)
                row_layout.addWidget(metadata, 3, 1, 1, 2)
                buttons = QHBoxLayout()
                buttons.setSpacing(5)
                exact_source = (
                    attachment.layer_sources[layer.index - 1]
                    if layer.index <= len(attachment.layer_sources) else None
                )
                source_button = QPushButton("Source")
                source_button.setEnabled(bool(entries) or bool(exact_source and exact_source.is_file()))
                source_button.clicked.connect(
                    lambda _checked=False, s=slot, p=note_p, layer_index=layer.index,
                    sample_index=layer.sample_index, level=velocity:
                    self.play_source(s, p, layer_index, sample_index, level)
                )
                source_button.setToolTip(f"Écouter la source de L{layer.index:02d} à v{velocity:03d}.")
                encoded_button = QPushButton("▶ Encodé"); encoded_button.setObjectName("encoded")
                encoded_button.setEnabled(sample is not None and sample.is_file())
                encoded_button.clicked.connect(
                    lambda _checked=False, s=slot, layer_index=layer.index: self.play_encoded_layer(s, layer_index)
                )
                encoded_button.setToolTip(f"Écouter le WAV encodé de L{layer.index:02d} (v{velocity:03d}).")
                buttons.addWidget(source_button); buttons.addWidget(encoded_button)
                row_layout.addLayout(buttons, 0, 2, 2, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
                row_layout.setColumnStretch(1, 1)
                layer_layout.addWidget(layer_row)
            layout.addWidget(layer_section)
            return card

        @staticmethod
        def _layer_velocity(attachment: CodecAttachment, layer: CodecLayer) -> int:
            if layer.index <= len(attachment.layer_velocities):
                velocity = attachment.layer_velocities[layer.index - 1]
                if velocity is not None:
                    return velocity
            name = attachment.preview.sample_file_names[layer.sample_index] or ""
            match = re.search(r"(?:^|__)v(\d{3})(?:__|\.)", name)
            return int(match.group(1)) if match else 104

        def _play_path(self, path: Path, description: str, *, guard_startup: bool = False) -> None:
            if not path.is_file():
                QMessageBox.warning(self, "WAV manquant", f"Fichier introuvable :\n{path}"); return
            playable = path
            if guard_startup:
                try:
                    self._playback_counter += 1
                    playable = Path(self._temporary_audio.name) / f"playback-{self._playback_counter:05d}.wav"
                    prepare_guarded_playback(path, playable)
                except (OSError, ValueError) as error:
                    QMessageBox.warning(self, "Préparation de lecture impossible", str(error)); return
            self.player.stop()
            self._guarded_playback = guard_startup
            self.audio_output.setVolume(0.0 if guard_startup else 0.9)
            self.player.setSource(QUrl.fromLocalFile(str(playable.resolve())))
            self.player.play()
            self.status.setText(description)

        def _player_position_changed(self, position_ms: int) -> None:
            # Unmute well before the encoded waveform begins at 250 ms, but
            # only after the multimedia endpoint has actually started.
            if self._guarded_playback and position_ms >= 120:
                self.audio_output.setVolume(0.9)
                self._guarded_playback = False

        def play_source(
            self, slot: str, note_p: int, layer_index: int | None = None,
            sample_index: int | None = None, velocity: int = 104,
        ) -> None:
            if self.catalog is None:
                return
            attachment = self.attachments.get(slot)
            if attachment is not None and sample_index is not None:
                if layer_index is not None and layer_index <= len(attachment.layer_sources):
                    exact_source = attachment.layer_sources[layer_index - 1]
                    if exact_source is not None and exact_source.is_file():
                        self._play_path(
                            exact_source,
                            f"Source exacte : {exact_source.name} · {slot} P{note_p} · vélocité {velocity}.",
                        )
                        return
                declared = attachment.preview.sample_file_names[sample_index]
                if declared and Path(declared).suffix.casefold() in {".wav", ".aif", ".aiff"}:
                    source = Path(declared)
                    candidates = (source,) if source.is_absolute() else (
                        attachment.preview.config_path.parent / source,
                        self.catalog.audio_root / source,
                        self.catalog.audio_root / source.name,
                    )
                    exact = next((path.resolve() for path in candidates if path.is_file()), None)
                    if exact is not None:
                        self._play_path(
                            exact,
                            f"Source déclarée : {exact.name} · {slot} P{note_p} · sample S{sample_index + 1:02d}.",
                        )
                        return
            try:
                entry = self.catalog.resolve_position(slot, note_p, velocity, 1)
            except ValueError as error:
                QMessageBox.warning(self, "Source indisponible", str(error)); return
            self._play_path(
                entry.audio_path,
                f"Source : {entry.raw_file} · {slot} P{note_p} · vélocité {entry.velocity} · RR {entry.round_robin}.",
            )

        def play_encoded_layer(self, slot: str, layer_index: int) -> None:
            attachment = self.attachments.get(slot)
            if attachment is None:
                return
            layer = next((item for item in attachment.preview.layers if item.index == layer_index), None)
            if layer is None:
                return
            path = attachment.preview.layer_samples[layer.index - 1] or attachment.preview.samples[layer.sample_index]
            if path is None:
                QMessageBox.warning(self, "WAV encodé manquant", f"Le sample S{layer.sample_index + 1:02d} n’a pas été extrait."); return
            self._play_path(
                path,
                f"Encodé réel : {path.name} · {attachment.preview.sound_name} · L{layer.index:02d}/S{layer.sample_index + 1:02d}. "
                "Lecture du WAV décodé avec les paramètres DSP du Layer par ddrum4edit.",
                guard_startup=True,
            )

        def play_variation(self, slot: str, note_p: int, variation: int, velocity: int) -> None:
            attachment = self.attachments.get(slot)
            if attachment is None:
                QMessageBox.information(self, "Variation non encodée", f"{slot} n’a pas de Sound encodé attaché."); return
            try:
                self._preview_counter += 1
                sequence_key = (slot, note_p, variation)
                sequence_step = self._sequence_steps.get(sequence_key, 0) + 1
                self._sequence_steps[sequence_key] = sequence_step
                output = Path(self._temporary_audio.name) / f"variation-{self._preview_counter:05d}.wav"
                rendered = render_preview(
                    attachment.preview, output, variation=variation, velocity=velocity,
                    note_p=note_p, round_robin_step=sequence_step,
                    variation_pitch_semitones=self._variation_pitch(slot, variation, note_p),
                    decay_percent=self._variation_number(slot, variation, "decay_percent", 100.0),
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Variation indisponible", str(error)); return
            self._play_path(
                rendered.path,
                f"Variation encodée : {attachment.preview.sound_name} V{variation} P{note_p} v{velocity} · "
                f"layers {', '.join(f'L{index:02d}' for index in rendered.active_layers)} · {rendered.mode}.",
                guard_startup=True,
            )

        def _variation_number(
            self, slot: str, variation: int, key: str, default: float,
        ) -> float:
            if self.catalog is None:
                return default
            value = self.catalog.variation_models.get(slot, {}).get(variation, {}).get(key, default)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default

        def _variation_pitch(self, slot: str, variation: int, note_p: int) -> float:
            if self.catalog is None:
                return 0.0
            model = self.catalog.variation_models.get(slot, {}).get(variation, {})
            specific = model.get(f"p{note_p}_pitch_semitones")
            if isinstance(specific, (int, float)) and not isinstance(specific, bool):
                return float(specific)
            # The S03 design changes Rim B only (P4..P6); Rim A (P1..P3)
            # deliberately remains identical between variations.
            if slot == "S03 RIM" and note_p <= 3:
                return 0.0
            return self._variation_number(slot, variation, "pitch_semitones", 0.0)

        def import_codec_preview(self) -> None:
            if self.catalog is None or self._selected_slot is None:
                QMessageBox.warning(self, "Sound requis", "Charge un package et sélectionne un Sound."); return
            sound_name, _ = QFileDialog.getOpenFileName(self, "Sound DDrum4 encodé", "", "DDrum4 Sound (*.mid *.midi *.syx)")
            if not sound_name:
                return
            config_name, _ = QFileDialog.getOpenFileName(
                self, "Configuration ayant construit ce Sound", str(Path(sound_name).parent), "Configuration ddrum4edit (*.cfg)",
            )
            if not config_name:
                return
            executable = discover().ddrum4edit
            if executable is None:
                QMessageBox.warning(self, "ddrum4edit introuvable", "Installe ou configure ddrum4edit pour décoder le Sound localement."); return
            base = self.catalog.package_directory / "codec-preview"; base.mkdir(exist_ok=True)
            safe_slot = re.sub(r"[^A-Za-z0-9_-]+", "-", self._selected_slot)
            suffix = 1
            while (output := base / f"{safe_slot}-{suffix:02d}").exists():
                suffix += 1
            try:
                self.status.setText("Décodage local du Sound avec ddrum4edit…"); QApplication.processEvents()
                backend = Ddrum4EditBackend(executable)
                export_codec_preview(
                    backend, sound=Path(sound_name), config=Path(config_name), output_directory=output,
                    sound_slot=self._selected_slot,
                )
                attachment = _load_codec_attachment(output / "codec-preview.json", self.catalog.sound_slots)
            except (OSError, RuntimeError, ValueError) as error:
                QMessageBox.warning(self, "Décodage codec impossible", str(error)); return
            self._attach_codec(attachment)
            self.status.setText(f"Sound décodé et attaché à {attachment.slot} dans {output}. Aucun transfert MIDI n’a été effectué.")

        def load_codec_preview_dialog(self) -> None:
            if self.catalog is None or self._selected_slot is None:
                QMessageBox.warning(self, "Sound requis", "Charge un package et sélectionne un Sound."); return
            filename, _ = QFileDialog.getOpenFileName(self, "codec-preview.json", "", "DDrum4 codec preview (codec-preview.json)")
            if not filename:
                return
            try:
                attachment = _load_codec_attachment(Path(filename), self.catalog.sound_slots, self._selected_slot)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Aperçu codec invalide", str(error)); return
            if attachment.slot != self._selected_slot:
                attachment = CodecAttachment(
                    self._selected_slot, attachment.preview, attachment.manifest_path,
                    attachment.encoded_blocks, attachment.encoded_bytes,
                    attachment.layer_velocities, attachment.layer_sources,
                )
            self._attach_codec(attachment)
            self.status.setText(f"{attachment.preview.sound_name} attaché à {attachment.slot}.")

        def _attach_codec(self, attachment: CodecAttachment) -> None:
            self.attachments[attachment.slot] = attachment
            self._populate_sound_table(); self._update_metrics(); self._rebuild_cards()

        def _update_metrics(self) -> None:
            if self.catalog is None:
                return
            self.sound_metric.setText(f"TOTAL SOUNDS:  {len(self.catalog.sound_slots)}  ·  ENCODÉS: {len(self.attachments)}")
            total = sum(item.encoded_bytes or 0 for item in self.attachments.values())
            self.size_metric.setText(f"ENCODED SIZE:  {_human_bytes(total) if self.attachments else '—'}")

        def _player_error(self, _error: object, detail: str) -> None:
            if detail:
                self.status.setText("Erreur de lecture : " + detail)

    app = QApplication.instance() or QApplication([])
    window = AuditionerWindow(package_directory)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Browse captured and encoded DDrum4 WAVs; no MIDI or hardware I/O")
    parser.add_argument("--package", type=Path, help="DDrum4 candidate package directory")
    args = parser.parse_args(argv)
    try:
        return launch(args.package)
    except RuntimeError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
