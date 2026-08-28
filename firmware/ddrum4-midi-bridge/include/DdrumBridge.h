#pragma once

#include <stddef.h>
#include <stdint.h>

#ifndef PROGMEM
#define PROGMEM
#endif

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

// A route can append these fixed events after its primary translated note.
// Channel zero means "use BridgeConfig::outputChannel".  `useValue` replaces
// data2 with the mapped hit velocity (or pressure for aftertouch).
struct RouteOutput {
  MidiEvent event;
  bool useValue;
};

// The DIN output role is deliberately explicit.  Hardware THRU always carries
// the original input stream independently of this mode.
enum class BridgeMode : uint8_t {
  // Apply the generated nested routing contract for DDrum4 Local-OFF play.
  Nested,
  // Return the original event without nested mapping.
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
  const RouteOutput* extraOutputs = nullptr;
  uint8_t extraOutputCount = 0;
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
  bool enabled = true;
};

// DDrum4 does not consume a continuous pedal controller for the resident
// r15 sounds.  Instead the last observed CC4 value selects a Note-P position
// when the bow or edge is struck.  Zone zero is closed and the last zone is
// open, regardless of the electrical polarity of the pedal values.
struct HihatQuantizedConfig {
  uint8_t sourceChannel;
  uint8_t inputCc;
  uint8_t inputClosed;
  uint8_t inputOpen;
  bool enabled = false;
};

struct HihatHitRoute {
  uint8_t inputChannel;
  uint8_t inputNote;
  uint8_t zoneCount;
  // Upper normalized (0..127) boundary for every zone except the final one.
  // Only the first zoneCount - 1 values are read and must be strictly rising.
  uint8_t upperBoundaries[7];
  uint8_t outputNotes[8];
};

enum class EchoGuardMode : uint8_t {
  Disabled,
  // Only for a physically declared second-DDrum renderer return path.
  DualDdrum,
};

struct EchoGuardConfig {
  // Echo suppression is deliberately only available for a declared
  // dual-DDrum return path. It is not a general MIDI de-duplicator.
  EchoGuardMode mode = EchoGuardMode::Disabled;
  // Zero accepts echoes only in the same processing tick.  This is the safe
  // default for an immediate DIN return path.
  uint16_t windowMs = 0;
  // The channel on which the second DDrum is known to return Arduino output.
  // Zero disables the guard even when enabled is true.
  uint8_t returnChannel = 0;
};

// A fixed, generated state table may replace the normal route for one source
// note.  0xff is a wildcard; all other fields must match LogicalState.
struct StateRoute {
  uint8_t inputChannel;
  uint8_t inputNote;
  uint8_t scene;
  uint8_t vp1;
  uint8_t vp2;
  uint8_t vp3;
  uint8_t vp4;
  uint8_t outputNote;
  uint8_t inputVelocityMin;
  uint8_t inputVelocityMax;
  uint8_t outputVelocityMin;
  uint8_t outputVelocityMax;
};

struct LogicalState {
  uint8_t scene;
  uint8_t vp1;
  uint8_t vp2;
  uint8_t vp3;
  uint8_t vp4;
};

// CH14/15 carry Scene and VP commands. The CC addresses are generated from
// rig-project/v1 instead of being assumed to be 0..3 on every controller.
// 0xff disables a VP slot when a project has fewer than four variables.
struct LogicalControlConfig {
  uint8_t vp1Cc = 0;
  uint8_t vp2Cc = 1;
  uint8_t vp3Cc = 2;
  uint8_t vp4Cc = 3;
  // Program Change on the reserved logical channels is an index into the
  // declared Scene array. It must never create a state which has no route.
  uint8_t sceneCount = 1;
};

// Native DDrum4 state messages are decoded separately from the stable CH14/15
// protocol. Target zero selects Scene; one through four select VP values.
enum class NativeControlType : uint8_t { ProgramChange, ControlChange, NoteOn };
struct NativeControlRoute {
  uint8_t sourceChannel;
  NativeControlType type;
  // Exact incoming Program/CC/note value. A native message can never copy an
  // arbitrary value into Scene/VP state.
  uint8_t address;
  uint8_t target;
  uint8_t value;
};

// Scene reconciliation is deliberately limited to short MIDI channel events.
// Vendor SysEx is handled only by a separately reviewed streaming transport.
struct DdrumStateAction {
  uint8_t scene;
  uint8_t vp1;
  uint8_t vp2;
  uint8_t vp3;
  uint8_t vp4;
  MidiEvent event;
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
  // Optional 16 * 128 table of signed route indexes, -1 for no route.
  // Generated M1 mappings may omit it and retain the bounded linear fallback.
  const int16_t* noteRouteIndex = nullptr;
  EchoGuardConfig echoGuard = {EchoGuardMode::Disabled, 0, 0};
  LogicalState initialState = {0, 0, 0, 0, 0};
  const StateRoute* stateRoutes = nullptr;
  size_t stateRouteCount = 0;
  LogicalControlConfig logicalControls = {};
  const NativeControlRoute* nativeControls = nullptr;
  size_t nativeControlCount = 0;
  const DdrumStateAction* stateActions = nullptr;
  size_t stateActionCount = 0;
  HihatQuantizedConfig hihatQuantized = {0, 0, 0, 0, false};
  const HihatHitRoute* hihatHitRoutes = nullptr;
  size_t hihatHitRouteCount = 0;
};

// Pure, allocation-free routing core. It has no Arduino dependency so tests can
// run natively. It never allocates and can emit a primary note plus bounded
// fixed side effects (for example a note plus a state/CC update).
class DdrumBridge {
 public:
  static constexpr size_t MAX_OUTPUT_EVENTS = 5;
  static constexpr const char* BUILD_ID = "ddrum4-midi-bridge-m3";
  explicit DdrumBridge(const BridgeConfig& config);
  size_t process(const MidiEvent& input, MidiEvent* output, size_t capacity, uint32_t nowMs = 0);
  void setMode(BridgeMode mode);
  BridgeMode mode() const { return mode_; }
  uint32_t ignoredMessages() const { return ignoredMessages_; }
  uint32_t expectedEchoes() const { return expectedEchoes_; }
  uint32_t outputOverflows() const { return outputOverflows_; }
  uint32_t invalidConfigurations() const { return invalidConfigurations_; }
  const LogicalState& logicalState() const { return logicalState_; }
  const char* buildId() const { return BUILD_ID; }

 private:
  BridgeConfig config_;
  BridgeMode mode_ = BridgeMode::Nested;
  uint32_t ignoredMessages_ = 0;
  uint32_t expectedEchoes_ = 0;
  uint32_t outputOverflows_ = 0;
  uint32_t invalidConfigurations_ = 0;
  bool configValid_ = false;
  LogicalState logicalState_{};

  struct EchoEntry { MidiEvent event; uint32_t expiresAt; bool active; };
  static constexpr size_t ECHO_CAPACITY = 8;
  EchoEntry echoes_[ECHO_CAPACITY] = {};
  uint8_t echoHead_ = 0;
  uint8_t echoCount_ = 0;

  // The ledger makes pressure/choke follow the actual primary hit route,
  // including a state-selected route. It is bounded so flams never allocate.
  struct HitLedgerEntry { uint8_t channel; uint8_t note; NoteRoute route; uint32_t sequence; uint32_t expiresAt; bool active; };
  static constexpr size_t HIT_LEDGER_CAPACITY = 16;
  static constexpr uint16_t HIT_LEDGER_WINDOW_MS = 250;
  HitLedgerEntry hitLedger_[HIT_LEDGER_CAPACITY] = {};
  uint32_t hitSequence_ = 0;
  // One compact state record is decoded at a time; state tables can therefore
  // live in AVR program memory rather than consuming Uno SRAM.
  mutable NoteRoute stateRouteBuffer_{};
  mutable NoteRoute hihatRouteBuffer_{};
  uint8_t lastHihatCc_ = 0;

  const NoteRoute* findNoteRoute(uint8_t inputChannel, uint8_t inputNote) const;
  StateRoute readStateRoute(size_t index) const;
  HihatHitRoute readHihatHitRoute(size_t index) const;
  const NoteRoute* findHihatRoute(uint8_t inputChannel, uint8_t inputNote) const;
  uint8_t hihatZone(const HihatHitRoute& route) const;
  NativeControlRoute readNativeControl(size_t index) const;
  DdrumStateAction readStateAction(size_t index) const;
  const NoteRoute* findLedgerRoute(uint8_t inputChannel, uint8_t inputNote, uint32_t nowMs);
  void rememberPrimaryHit(uint8_t inputChannel, uint8_t inputNote, const NoteRoute* route, uint32_t nowMs);
  uint8_t mapVelocity(const NoteRoute& route, uint8_t velocity) const;
  uint8_t mapHihatCc(uint8_t value) const;
  bool isLogicalControl(const MidiEvent& input);
  bool isNativeControl(const MidiEvent& input);
  size_t emitStateActions(MidiEvent* output, size_t capacity, uint32_t nowMs);
  bool isExpectedEcho(const MidiEvent& input, uint32_t nowMs);
  void rememberOutput(const MidiEvent& output, uint32_t nowMs);
  bool validConfig() const;
};
