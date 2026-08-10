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

// The DIN output role is deliberately explicit.  Hardware THRU always carries
// the original input stream independently of this mode.
enum class BridgeMode : uint8_t {
  // Apply the generated nested routing contract for DDrum4 Local-OFF play.
  Nested,
  // Return the original event to the module. Used with Local-OFF when a
  // transparent return path is wanted; the return-echo guard stays active.
  Bypass,
  // Never emit from Arduino DIN OUT. Used for PC_CLEAN with DDrum4 Local-ON.
  Silent,
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
  // Program changes are only relayed for declared source channels.  Keeping
  // this as a list rather than naming modules here lets the same firmware
  // bridge DDTi, eDRUMin and a Local-OFF ddrum4 without a special code path.
  const uint8_t* relayProgramChannels;
  size_t relayProgramChannelCount;
  HihatDirectCc4Config hihat;
  const NoteRoute* noteRoutes;
  size_t noteRouteCount;
  bool relayProgramChange;
  // Enable only after a trace proves that this particular module/cabling sends
  // a returned copy of Arduino DIN OUT through its MIDI OUT.
  bool suppressReturnEcho;
};

// Pure, allocation-free routing core. It has no Arduino dependency so tests can
// run natively. An event may produce zero or one event in the current MVP.
class DdrumBridge {
 public:
  explicit DdrumBridge(const BridgeConfig& config);
  size_t process(const MidiEvent& input, MidiEvent* output, size_t capacity, uint32_t nowMs = 0);
  void setMode(BridgeMode mode);
  BridgeMode mode() const { return mode_; }
  uint32_t ignoredMessages() const { return ignoredMessages_; }
  uint32_t duplicateCcMessages() const { return duplicateCcMessages_; }
  uint32_t suppressedEchoMessages() const { return suppressedEchoMessages_; }

 private:
  BridgeConfig config_;
  BridgeMode mode_ = BridgeMode::Nested;
  bool hasLastHihatCc_ = false;
  uint8_t lastHihatCc_ = 0;
  uint32_t ignoredMessages_ = 0;
  uint32_t duplicateCcMessages_ = 0;
  // Some DDrum4 configurations retransmit a MIDI-IN event through MIDI OUT.
  // The bridge is normally in that return path, so each emitted event is
  // recorded once and exactly one byte-identical return is consumed.  This is
  // intentionally an exact-event list, not a timer, trigger filter or MIDI
  // interpretation layer.
  static constexpr size_t kEchoGuardCapacity = 64;
  MidiEvent expectedEchoes_[kEchoGuardCapacity]{};
  size_t expectedEchoCount_ = 0;
  uint32_t suppressedEchoMessages_ = 0;

  const NoteRoute* findNoteRoute(uint8_t inputChannel, uint8_t inputNote) const;
  uint8_t mapVelocity(const NoteRoute& route, uint8_t velocity) const;
  uint8_t mapHihatCc(uint8_t value) const;
  bool consumeExpectedEcho(const MidiEvent& input);
  void rememberExpectedEcho(const MidiEvent& output);
};
