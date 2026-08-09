#pragma once

#include <stddef.h>
#include <stdint.h>

// All channel values in this core are human/MIDI values 1..16, not 0..15.
enum class MidiEventType : uint8_t {
  NoteOff,
  NoteOn,
  ControlChange,
  PolyAftertouch,
  ProgramChange,
};

struct MidiEvent {
  MidiEventType type;
  uint8_t channel;
  uint8_t data1;
  uint8_t data2;
};

struct NoteRoute {
  uint8_t inputChannel;
  uint8_t inputNote;
  uint8_t outputNote;
  // NoteOn velocity is mapped linearly from the input interval to the output
  // interval.  This lets several source pads select deterministic velocity
  // windows (and therefore different ddrum4 layers) inside one sound.
  uint8_t inputVelocityMin;
  uint8_t inputVelocityMax;
  uint8_t outputVelocityMin;
  uint8_t outputVelocityMax;
};

struct HihatDirectCc4Config {
  uint8_t sourceChannel;
  uint8_t inputCc;
  uint8_t outputCc;
  uint8_t inputClosed;
  uint8_t inputOpen;
  uint8_t outputClosed;
  uint8_t outputOpen;
  bool invert;
};

struct BridgeConfig {
  uint8_t outputChannel;
  uint8_t ddtiChannel;
  uint8_t edruminChannel;
  HihatDirectCc4Config hihat;
  const NoteRoute* noteRoutes;
  size_t noteRouteCount;
  bool relayProgramChange;
};

// Pure, allocation-free routing core. It has no Arduino dependency so tests can
// run natively. An event may produce zero or one event in the current MVP.
class DdrumBridge {
 public:
  explicit DdrumBridge(const BridgeConfig& config);
  size_t process(const MidiEvent& input, MidiEvent* output, size_t capacity);
  uint32_t ignoredMessages() const { return ignoredMessages_; }
  uint32_t duplicateCcMessages() const { return duplicateCcMessages_; }

 private:
  BridgeConfig config_;
  bool hasLastHihatCc_ = false;
  uint8_t lastHihatCc_ = 0;
  uint32_t ignoredMessages_ = 0;
  uint32_t duplicateCcMessages_ = 0;

  const NoteRoute* findNoteRoute(uint8_t inputChannel, uint8_t inputNote) const;
  uint8_t mapVelocity(const NoteRoute& route, uint8_t velocity) const;
  uint8_t mapHihatCc(uint8_t value) const;
};
