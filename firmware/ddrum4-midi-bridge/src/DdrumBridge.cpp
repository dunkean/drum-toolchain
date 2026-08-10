#include "DdrumBridge.h"

DdrumBridge::DdrumBridge(const BridgeConfig& config) : config_(config) {}

void DdrumBridge::setMode(BridgeMode mode) {
  // A mode change must never leave stale expectations that could consume the
  // first genuine strike in the new mode.  It emits no MIDI and never creates
  // an artificial note-off.
  mode_ = mode;
  expectedEchoCount_ = 0;
  hasLastHihatCc_ = false;
}

bool DdrumBridge::consumeExpectedEcho(const MidiEvent& input) {
  if (!expectedEchoCount_) return false;
  for (size_t i = 0; i < expectedEchoCount_; ++i) {
    const MidiEvent& expected = expectedEchoes_[i];
    if (input.type != expected.type || input.channel != expected.channel ||
        input.data1 != expected.data1 || input.data2 != expected.data2) {
      continue;
    }
    for (size_t remaining = i + 1; remaining < expectedEchoCount_; ++remaining) {
      expectedEchoes_[remaining - 1] = expectedEchoes_[remaining];
    }
    --expectedEchoCount_;
    ++suppressedEchoMessages_;
    return true;
  }
  return false;
}

void DdrumBridge::rememberExpectedEcho(const MidiEvent& output) {
  if (expectedEchoCount_ == kEchoGuardCapacity) {
    for (size_t i = 1; i < expectedEchoCount_; ++i) {
      expectedEchoes_[i - 1] = expectedEchoes_[i];
    }
    --expectedEchoCount_;
  }
  expectedEchoes_[expectedEchoCount_++] = output;
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
  if (config_.suppressReturnEcho && consumeExpectedEcho(input)) return 0;

  if (mode_ == BridgeMode::Silent) return 0;

  if (mode_ == BridgeMode::Bypass) {
    *output = input;
    if (config_.suppressReturnEcho) rememberExpectedEcho(*output);
    return 1;
  }

  // The direct CC4 engine is deliberately handled before note routing. CC4 is
  // recognised by ddrum4; quantisation is an explicit future fallback only.
  const HihatDirectCc4Config& h = config_.hihat;
  if (input.type == MidiEventType::ControlChange && input.channel == h.sourceChannel &&
      input.data1 == h.inputCc) {
    uint8_t mapped = mapHihatCc(input.data2);
    if (hasLastHihatCc_ && mapped == lastHihatCc_) {
      ++duplicateCcMessages_;
      return 0;
    }
    hasLastHihatCc_ = true;
    lastHihatCc_ = mapped;
    *output = {MidiEventType::ControlChange, config_.outputChannel, h.outputCc, mapped};
    if (config_.suppressReturnEcho) rememberExpectedEcho(*output);
    return 1;
  }

  if (input.type == MidiEventType::ProgramChange && config_.relayProgramChange) {
    for (size_t i = 0; i < config_.relayProgramChannelCount; ++i) {
      if (input.channel == config_.relayProgramChannels[i]) {
        *output = {MidiEventType::ProgramChange, config_.outputChannel, input.data1, 0};
        if (config_.suppressReturnEcho) rememberExpectedEcho(*output);
        return 1;
      }
    }
  }

  if (input.type != MidiEventType::NoteOn && input.type != MidiEventType::NoteOff &&
      input.type != MidiEventType::PolyAftertouch) {
    ++ignoredMessages_;
    return 0;
  }

  const NoteRoute* route = findNoteRoute(input.channel, input.data1);
  // Static manifest routes make Note On and Note Off deterministically resolve
  // to the same output note without a 16 x 128 active-note RAM table. Dynamic
  // routing modes will add a deliberately bounded active-note cache later.
  if (!route) {
    ++ignoredMessages_;
    return 0;
  }
  uint8_t value = input.data2;
  if (input.type == MidiEventType::NoteOn && input.data2 != 0) value = mapVelocity(*route, input.data2);
  *output = {input.type, config_.outputChannel, route->outputNote, value};
  if (config_.suppressReturnEcho) rememberExpectedEcho(*output);
  return 1;
}
