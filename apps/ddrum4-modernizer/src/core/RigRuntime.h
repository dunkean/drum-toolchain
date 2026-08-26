#pragma once

#include "core/Midi.h"
#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace ddrum4 {

// The compiled rig profile is deliberately transport agnostic.  A MIDI port
// adapter supplies a source id; this class never opens a device.
enum class PhysicalMatcher : uint8_t { Note, NoteRange, ControlChange, PolyAftertouch };
enum class NativeControlType : uint8_t { ProgramChange, ControlChange, NoteOn };
enum class RuntimeConnection : uint8_t { Single, Dual };
enum class RuntimeRendererTarget : uint8_t { Sd3, DrumGizmo };
struct RuntimeSource { std::string id; std::string endpoint; std::string connectionProfile; uint8_t channel{1}; bool primary{}; bool deduplicateDinCopies{}; RuntimeConnection connection{RuntimeConnection::Single}; };
struct RuntimeDecoder {
  uint16_t source{}; PhysicalMatcher matcher{}; uint8_t first{}; uint8_t last{};
  std::string physical; bool velocity{}; bool position{};
};
struct RuntimeRenderer { std::string logical; uint8_t note{}; uint8_t channel{10}; uint8_t positionCc{255}; uint8_t controller{255}; };
struct RuntimePredicate { uint8_t variable{}; uint8_t value{}; };
struct RuntimeRoute { uint16_t scene{}; std::string physical; std::string logical; std::array<RuntimePredicate, 4> predicates{}; uint8_t predicateCount{}; };
struct RuntimeControl { std::string name; uint8_t cc{}; uint8_t defaultValue{}; };
// Native DDrum4 controls are optional observations of the module's own
// Program/Palette protocol.  Target 0 is Scene; 1..4 address VP variables.
struct RuntimeNativeControl { int16_t source{-1}; uint8_t channel{}; NativeControlType type{}; uint8_t address{}; uint8_t target{}; uint8_t value{}; };
struct RuntimeProfile {
  std::vector<RuntimeSource> sources; std::vector<std::string> scenes;
  std::vector<RuntimeDecoder> decoders; std::vector<RuntimeRoute> routes;
  std::vector<RuntimeRenderer> renderers; std::vector<RuntimeControl> variables; std::vector<RuntimeNativeControl> nativeControls;
  std::string sourceSha256; uint16_t defaultScene{}; bool echoMeasuredOnly{}; uint64_t dedupWindowUs{10000};
  // A PC renderer may publish only logical CH14/15 control to this explicit
  // endpoint. It is off unless the compiled source project is live and the
  // endpoint was user-confirmed.
  std::string controlBusEndpoint; uint8_t controlBusChannel{15}; bool controlBusEnabled{};
  RuntimeRendererTarget rendererTarget{RuntimeRendererTarget::Sd3};
};
struct RuntimeHealth { uint64_t received{}; uint64_t decoded{}; uint64_t rendered{}; uint64_t ignored{}; uint64_t duplicates{}; uint64_t echoes{}; uint64_t controls{}; };

class RigRuntime {
 public:
  static constexpr size_t maxOutputEvents = 3;
  explicit RigRuntime(const RuntimeProfile& profile);
  size_t process(std::string_view sourceId, const MidiEvent& input,
                 std::array<MidiEvent, maxOutputEvents>& output) noexcept;
  size_t processEndpoint(std::string_view endpoint, const MidiEvent& input,
                         std::array<MidiEvent, maxOutputEvents>& output) noexcept;
  // These are deliberately renderer-local controls.  A PC-to-rig broadcast
  // remains an explicit hardware path once the Master Merger is installed.
  bool selectScene(uint16_t scene) noexcept;
  bool setVariableValue(size_t index, uint8_t value) noexcept;
  void clearLedger() noexcept;
  RuntimeHealth health() const noexcept;
  uint16_t scene() const noexcept { return static_cast<uint16_t>(state_.load(std::memory_order_acquire)); }
  uint8_t variable(size_t index) const noexcept;
 private:
  struct Seen { uint16_t source{0xffff}; MidiType type{}; uint8_t channel{}; uint8_t data1{}; uint8_t data2{}; uint64_t timestamp{}; bool valid{}; };
  struct Active { uint8_t channel{}; uint8_t note{}; };
  struct ActiveQueue { std::array<Active, 16> entries{}; uint8_t head{}; uint8_t size{}; uint16_t discardedOffs{}; };
  const RuntimeProfile& profile_; std::atomic<uint64_t> state_{};
  std::array<Seen, 32> seen_{};
  static constexpr size_t maxSources=8;
  using ActiveLedgers = std::array<std::array<std::array<ActiveQueue, 128>, 16>, maxSources>;
  // Keep the sizeable Note-On/Off ledger off the caller stack. A converter
  // owns one runtime for its lifetime; allocating its bounded storage once is
  // safer than making every construction consume several hundred KiB of stack.
  std::unique_ptr<ActiveLedgers> active_{std::make_unique<ActiveLedgers>()};
  std::atomic<uint64_t> received_{}, decoded_{}, rendered_{}, ignored_{}, duplicates_{}, echoes_{}, controls_{};
  int sourceIndex(std::string_view id) const noexcept;
  int endpointSourceIndex(std::string_view endpoint, uint8_t channel) const noexcept;
  bool duplicate(uint16_t source, const MidiEvent& input) noexcept;
  void remember(uint16_t source, const MidiEvent& input, const RuntimeRenderer& renderer) noexcept;
  bool recall(uint16_t source, const MidiEvent& input, Active& active) noexcept;
  uint8_t stateVariable(uint64_t state, size_t index) const noexcept;
  void setStateVariable(size_t index, uint8_t value) noexcept;
  void ignore() noexcept { ignored_.fetch_add(1, std::memory_order_relaxed); }
};
}
