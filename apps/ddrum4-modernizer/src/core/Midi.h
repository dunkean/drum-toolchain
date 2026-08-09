#pragma once
#include <cstdint>

namespace ddrum4 {
enum class MidiType : uint8_t { NoteOff, NoteOn, ControlChange, PolyAftertouch, ProgramChange, Realtime };
struct MidiEvent { MidiType type{}; uint8_t channel{}; uint8_t data1{}; uint8_t data2{}; uint64_t timestampUs{}; };
inline bool isNoteOn(const MidiEvent& e) { return e.type == MidiType::NoteOn && e.data2 != 0; }
inline bool isNoteOff(const MidiEvent& e) { return e.type == MidiType::NoteOff || (e.type == MidiType::NoteOn && e.data2 == 0); }
}
