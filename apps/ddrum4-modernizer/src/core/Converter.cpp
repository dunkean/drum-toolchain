#include "core/Converter.h"
#include <algorithm>
#include <string_view>

namespace ddrum4 {
Converter::Converter(const Profile& profile) : profile_(profile), compiled_(profile.kits.size()) {
  programKits_.fill(-1);
  for(const auto& binding:profile_.programs) {
    if (binding.kitIndex < profile_.kits.size())
      programKits_[binding.program]=static_cast<int16_t>(binding.kitIndex);
  }
  for(const auto cc:profile_.allowedCcs) allowedCcs_[cc]=true;
  for(size_t kitIndex=0;kitIndex<profile_.kits.size();++kitIndex) for(const auto& route:profile_.kits[kitIndex].routes) {
    if (route.inputChannel < 1 || route.inputChannel > 16) continue;
    if(route.type==RouteType::HihatContinuous) {
      if (route.inputCc <= 127)
        compiled_[kitIndex].hihatCc[(route.inputChannel-1)*128+route.inputCc]=&route;
      continue;
    }
    const auto routeEnd = std::min<unsigned>(128u, static_cast<unsigned>(route.firstNote) + route.count);
    for(unsigned note=route.firstNote;note<routeEnd;++note)
      compiled_[kitIndex].note[(route.inputChannel-1)*128+note]=&route;
  }
  if (!profile_.kits.empty()) selectKit(std::min(profile_.initialKitIndex, profile_.kits.size() - 1), "startup");
}

void Converter::selectKit(size_t kitIndex, const char* origin) noexcept {
  if (kitIndex < profile_.kits.size()) { activeKit_.store(kitIndex, std::memory_order_release); const std::string_view text{origin}; lastOrigin_.store(text == "PC" ? 2 : text == "keyboard" ? 3 : text == "UI" ? 1 : 0, std::memory_order_release); }
}
const char* Converter::lastProgramOrigin() const noexcept { switch(lastOrigin_.load(std::memory_order_acquire)) { case 1: return "UI"; case 2: return "PC"; case 3: return "keyboard"; default: return "startup"; } }
void Converter::clearLedger() noexcept { for(auto& channel : active_) for(auto& queue : channel) { queue.head=0; queue.size=0; queue.discardedOffs=0; } }

const Route* Converter::findRoute(const MidiEvent& input, size_t kitIndex) const noexcept { return compiled_[kitIndex].note[(input.channel-1)*128+input.data1]; }

std::optional<Converter::Active> Converter::remember(const MidiEvent& input, const Route& route) noexcept {
  auto& queue = active_[input.channel - 1][input.data1];
  std::optional<Active> evicted;
  if (queue.size == queue.entries.size()) { evicted = queue.entries[queue.head]; queue.head = static_cast<uint8_t>((queue.head + 1) % queue.entries.size()); --queue.size; ++queue.discardedOffs; ledgerOverflows_.fetch_add(1, std::memory_order_relaxed); }
  queue.entries[(queue.head + queue.size) % queue.entries.size()] = {route.destinationChannel, route.destinationNote, route.noteOff};
  ++queue.size;
  return evicted;
}

size_t Converter::process(const MidiEvent& input, std::array<MidiEvent, maxOutputEvents>& output) noexcept {
  if (input.type == MidiType::Realtime) { if (profile_.passRealtime) { output[0] = input; return 1; } ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
  if (input.channel < 1 || input.channel > 16) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
  if (input.data1 > 127 || input.data2 > 127) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
  if (input.type == MidiType::ProgramChange) {
    if (input.channel != profile_.programSourceChannel) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
    if (profile_.programManagerEnabled && programKits_[input.data1]>=0) {
      selectKit(static_cast<size_t>(programKits_[input.data1]), "PC");
      if (!profile_.forwardProgramChange) return 0;
      if (profile_.kits.empty()) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
      output[0] = {MidiType::ProgramChange, profile_.kits[activeKit()].outputChannel, input.data1, 0, input.timestampUs}; return 1;
    }
    if (profile_.unknownProgram == UnknownProgramPolicy::Forward || profile_.forwardProgramChange) {
      if (profile_.kits.empty()) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
      output[0] = {MidiType::ProgramChange, profile_.kits[activeKit()].outputChannel, input.data1, 0, input.timestampUs}; return 1;
    }
    ignored_.fetch_add(1, std::memory_order_relaxed); return 0;
  }
  if (input.type == MidiType::ControlChange) {
    if (profile_.kits.empty()) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
    const auto kitIndex=activeKit_.load(std::memory_order_acquire);
    const auto& kit=profile_.kits[kitIndex];
    if(const auto* route=compiled_[kitIndex].hihatCc[(input.channel-1)*128+input.data1]) {
      const auto low=std::min(route->closedCc,route->openCc), high=std::max(route->closedCc,route->openCc);
      const auto mapped=static_cast<uint8_t>(low + (static_cast<unsigned>(input.data2)*(high-low)+63)/127);
      output[0]={MidiType::ControlChange,route->destinationChannel,route->positionCc,mapped,input.timestampUs}; return 1;
    }
    if (!allowedCcs_[input.data1]) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
    output[0] = {MidiType::ControlChange, kit.outputChannel, input.data1, input.data2, input.timestampUs}; return 1;
  }
  if (isNoteOff(input) || input.type == MidiType::PolyAftertouch) {
    auto& queue = active_[input.channel - 1][input.data1];
    if (isNoteOff(input) && queue.discardedOffs != 0) { --queue.discardedOffs; return 0; }
    if (queue.size == 0) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
    const auto index = input.type == MidiType::PolyAftertouch ? static_cast<uint8_t>((queue.head + queue.size - 1) % queue.entries.size()) : queue.head;
    const auto active = queue.entries[index];
    if (input.type == MidiType::PolyAftertouch || active.off == NoteOffPolicy::Forward) {
      output[0] = {input.type == MidiType::NoteOn ? MidiType::NoteOff : input.type, active.destinationChannel, active.destinationNote, input.data2, input.timestampUs};
    }
    const bool emit = input.type == MidiType::PolyAftertouch || active.off == NoteOffPolicy::Forward;
    if (isNoteOff(input)) { queue.head = static_cast<uint8_t>((queue.head + 1) % queue.entries.size()); --queue.size; }
    return emit ? 1 : 0;
  }
  if (!isNoteOn(input) || profile_.kits.empty()) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
  const auto kitIndex=activeKit_.load(std::memory_order_acquire);
  const auto& kit = profile_.kits[kitIndex];
  const auto* route = findRoute(input, kitIndex);
  if (!route) { ignored_.fetch_add(1, std::memory_order_relaxed); return 0; }
  size_t count = 0;
  if (const auto evicted = remember(input, *route); evicted && evicted->off == NoteOffPolicy::Forward)
    output[count++] = {MidiType::NoteOff, evicted->destinationChannel, evicted->destinationNote, 0, input.timestampUs};
  if (route->type == RouteType::Positional || route->type == RouteType::HihatDiscrete) {
    const auto position = static_cast<size_t>(input.data1 - route->firstNote);
    output[count++] = {MidiType::ControlChange, route->destinationChannel, route->positionCc, route->ccValues[position], input.timestampUs};
  }
  output[count++] = {MidiType::NoteOn, route->destinationChannel, route->destinationNote, input.data2, input.timestampUs};
  return count;
}
}
