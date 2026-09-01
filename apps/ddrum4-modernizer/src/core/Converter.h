#pragma once
#include "core/Profile.h"
#include <array>
#include <atomic>
#include <optional>

namespace ddrum4 {
class Converter {
 public:
  // Also bounds the app's shared output queue used by the richer rig runtime.
  static constexpr size_t maxOutputEvents = 8;
  explicit Converter(const Profile& profile);
  void selectKit(size_t kitIndex, const char* origin = "UI") noexcept;
  void clearLedger() noexcept;
  size_t activeKit() const noexcept { return activeKit_.load(std::memory_order_relaxed); }
  const char* lastProgramOrigin() const noexcept;
  size_t process(const MidiEvent& input, std::array<MidiEvent, maxOutputEvents>& output) noexcept;
  uint64_t ignored() const noexcept { return ignored_.load(std::memory_order_relaxed); }
  uint64_t ledgerOverflows() const noexcept { return ledgerOverflows_.load(std::memory_order_relaxed); }
 private:
  struct Active { uint8_t destinationChannel{}; uint8_t destinationNote{}; NoteOffPolicy off{}; };
  struct ActiveQueue { std::array<Active, 16> entries{}; uint8_t head{}; uint8_t size{}; uint16_t discardedOffs{}; };
  struct CompiledKit { std::array<const Route*,16*128> note{}; std::array<const Route*,16*128> hihatCc{}; };
  const Profile& profile_; std::vector<CompiledKit> compiled_; std::array<int16_t,128> programKits_{}; std::array<bool,128> allowedCcs_{}; std::atomic<size_t> activeKit_{0}; std::array<std::array<ActiveQueue,128>,16> active_{};
  std::atomic<uint8_t> lastOrigin_{0}; std::atomic<uint64_t> ignored_{0}; std::atomic<uint64_t> ledgerOverflows_{0};
  const Route* findRoute(const MidiEvent&, size_t kitIndex) const noexcept;
  std::optional<Active> remember(const MidiEvent&, const Route&) noexcept;
};
}
