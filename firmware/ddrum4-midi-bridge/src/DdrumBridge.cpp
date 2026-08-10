#include "DdrumBridge.h"

DdrumBridge::DdrumBridge(const BridgeConfig& config) : config_(config) {}

void DdrumBridge::setMode(BridgeMode mode) {
  mode_ = mode;
}

const NoteRoute* DdrumBridge::findNoteRoute(uint8_t inputChannel, uint8_t inputNote) const {
  for (size_t i = 0; i < config_.noteRouteCount; ++i) {
    const NoteRoute& route = config_.noteRoutes[i];
    if (route.inputChannel == inputChannel && route.inputNote == inputNote) {
      return &route;
    }
  }
  return nullptr;
}

uint8_t DdrumBridge::mapVelocity(const NoteRoute& route, uint8_t velocity) const {
  if (velocity == 0) return 0;
  uint8_t low = route.inputVelocityMin < route.inputVelocityMax ? route.inputVelocityMin : route.inputVelocityMax;
  uint8_t high = route.inputVelocityMin < route.inputVelocityMax ? route.inputVelocityMax : route.inputVelocityMin;
  if (velocity < low) velocity = low;
  if (velocity > high) velocity = high;
  uint16_t inputRange = high - low;
  uint16_t normalized = inputRange ? ((uint16_t)(velocity - low) * 127U + inputRange / 2U) / inputRange : 0;
  if (route.inputVelocityMin > route.inputVelocityMax) normalized = 127U - normalized;
  uint16_t outputRange = route.outputVelocityMax >= route.outputVelocityMin
      ? route.outputVelocityMax - route.outputVelocityMin
      : route.outputVelocityMin - route.outputVelocityMax;
  uint16_t mapped = (normalized * outputRange + 63U) / 127U;
  return route.outputVelocityMax >= route.outputVelocityMin
      ? route.outputVelocityMin + mapped : route.outputVelocityMin - mapped;
}

uint8_t DdrumBridge::mapHihatCc(uint8_t value) const {
  const HihatDirectCc4Config& h = config_.hihat;
  uint8_t low = h.inputClosed < h.inputOpen ? h.inputClosed : h.inputOpen;
  uint8_t high = h.inputClosed < h.inputOpen ? h.inputOpen : h.inputClosed;
  if (value < low) value = low;
  if (value > high) value = high;
  uint16_t range = high - low;
  uint16_t normalized = range ? ((uint16_t)(value - low) * 127U + range / 2U) / range : 0;
  if (h.inputClosed > h.inputOpen) normalized = 127U - normalized;
  if (h.invert) normalized = 127U - normalized;
  uint16_t outputRange = h.outputOpen >= h.outputClosed
      ? h.outputOpen - h.outputClosed : h.outputClosed - h.outputOpen;
  uint16_t mapped = (normalized * outputRange + 63U) / 127U;
  return h.outputOpen >= h.outputClosed ? h.outputClosed + mapped : h.outputClosed - mapped;
}

size_t DdrumBridge::process(const MidiEvent& input, MidiEvent* output, size_t capacity, uint32_t) {
  if (!capacity) return 0;

  if (mode_ == BridgeMode::Silent) return 0;

  if (mode_ == BridgeMode::Bypass) {
    *output = input;
    return 1;
  }

  // The direct CC4 engine is deliberately handled before note routing. CC4 is
  // recognised by ddrum4; quantisation is an explicit future fallback only.
  const HihatDirectCc4Config& h = config_.hihat;
  if (input.type == MidiEventType::ControlChange && input.channel == h.sourceChannel &&
      input.data1 == h.inputCc) {
    uint8_t mapped = mapHihatCc(input.data2);
    *output = {MidiEventType::ControlChange, config_.outputChannel, h.outputCc, mapped};
    return 1;
  }

  if (input.type == MidiEventType::ProgramChange && config_.relayProgramChange) {
    for (size_t i = 0; i < config_.relayProgramChannelCount; ++i) {
      if (input.channel == config_.relayProgramChannels[i]) {
        *output = {MidiEventType::ProgramChange, config_.outputChannel, input.data1, 0};
        return 1;
      }
    }
  }

  // DDrum4 sends release as 0x90 with velocity zero and does not recognise
  // MIDI Note Off. Its one-shot renderer therefore receives no release event.
  if ((input.type == MidiEventType::NoteOn && input.data2 == 0) ||
      input.type == MidiEventType::NoteOff) {
    ++ignoredMessages_;
    return 0;
  }

  if (input.type != MidiEventType::NoteOn && input.type != MidiEventType::PolyAftertouch) {
    ++ignoredMessages_;
    return 0;
  }

  const NoteRoute* route = findNoteRoute(input.channel, input.data1);
  // Static manifest routes make Note On and polyphonic aftertouch
  // deterministically resolve to the same output note without an active-note
  // RAM table. Dynamic routing modes will add one only when needed.
  if (!route) {
    ++ignoredMessages_;
    return 0;
  }
  uint8_t value = input.data2;
  if (input.type == MidiEventType::NoteOn) value = mapVelocity(*route, input.data2);
  *output = {input.type, config_.outputChannel, route->outputNote, value};
  return 1;
}
