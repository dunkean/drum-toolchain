#include "DdrumBridge.h"

#if defined(ARDUINO_ARCH_AVR)
#include <avr/pgmspace.h>
#endif

DdrumBridge::DdrumBridge(const BridgeConfig& config) : config_(config), logicalState_(config.initialState),
    lastHihatCc_(config.hihatQuantized.inputClosed) {
  configValid_ = validConfig();
  if (!configValid_) ++invalidConfigurations_;
}

void DdrumBridge::setMode(BridgeMode mode) {
  mode_ = mode;
}

const NoteRoute* DdrumBridge::findNoteRoute(uint8_t inputChannel, uint8_t inputNote) const {
  // State routes are generated fixed tables, not learned routing state.
  for (size_t i = 0; i < config_.stateRouteCount; ++i) {
    StateRoute state = readStateRoute(i);
    if (state.inputChannel == inputChannel && state.inputNote == inputNote &&
        (state.scene == 0xff || state.scene == logicalState_.scene) &&
        (state.vp1 == 0xff || state.vp1 == logicalState_.vp1) &&
        (state.vp2 == 0xff || state.vp2 == logicalState_.vp2) &&
        (state.vp3 == 0xff || state.vp3 == logicalState_.vp3) &&
        (state.vp4 == 0xff || state.vp4 == logicalState_.vp4)) {
      stateRouteBuffer_ = {state.inputChannel, state.inputNote, state.outputNote,
                           state.inputVelocityMin, state.inputVelocityMax,
                           state.outputVelocityMin, state.outputVelocityMax};
      return &stateRouteBuffer_;
    }
  }
  if (config_.noteRouteIndex && inputChannel >= 1 && inputChannel <= 16) {
    int16_t index = config_.noteRouteIndex[(size_t)(inputChannel - 1) * 128U + inputNote];
    if (index >= 0 && (size_t)index < config_.noteRouteCount) return &config_.noteRoutes[index];
    return nullptr;
  }
  for (size_t i = 0; i < config_.noteRouteCount; ++i) {
    const NoteRoute& route = config_.noteRoutes[i];
    if (route.inputChannel == inputChannel && route.inputNote == inputNote) {
      return &route;
    }
  }
  return nullptr;
}

StateRoute DdrumBridge::readStateRoute(size_t index) const {
#if defined(ARDUINO_ARCH_AVR)
  StateRoute result{};
  const uint8_t* source = reinterpret_cast<const uint8_t*>(config_.stateRoutes) + index * sizeof(StateRoute);
  uint8_t* destination = reinterpret_cast<uint8_t*>(&result);
  for (size_t byte = 0; byte < sizeof(StateRoute); ++byte) destination[byte] = pgm_read_byte(source + byte);
  return result;
#else
  return config_.stateRoutes[index];
#endif
}

NativeControlRoute DdrumBridge::readNativeControl(size_t index) const {
#if defined(ARDUINO_ARCH_AVR)
  NativeControlRoute result{};
  const uint8_t* source = reinterpret_cast<const uint8_t*>(config_.nativeControls) + index * sizeof(NativeControlRoute);
  uint8_t* destination = reinterpret_cast<uint8_t*>(&result);
  for (size_t byte = 0; byte < sizeof(NativeControlRoute); ++byte) destination[byte] = pgm_read_byte(source + byte);
  return result;
#else
  return config_.nativeControls[index];
#endif
}

HihatHitRoute DdrumBridge::readHihatHitRoute(size_t index) const {
#if defined(ARDUINO_ARCH_AVR)
  HihatHitRoute result{};
  const uint8_t* source = reinterpret_cast<const uint8_t*>(config_.hihatHitRoutes) + index * sizeof(HihatHitRoute);
  uint8_t* destination = reinterpret_cast<uint8_t*>(&result);
  for (size_t byte = 0; byte < sizeof(HihatHitRoute); ++byte) destination[byte] = pgm_read_byte(source + byte);
  return result;
#else
  return config_.hihatHitRoutes[index];
#endif
}

uint8_t DdrumBridge::hihatZone(const HihatHitRoute& route) const {
  const HihatQuantizedConfig& h = config_.hihatQuantized;
  const int16_t span = static_cast<int16_t>(h.inputOpen) - static_cast<int16_t>(h.inputClosed);
  int16_t normalized = span
      ? ((static_cast<int16_t>(lastHihatCc_) - static_cast<int16_t>(h.inputClosed)) * 127 + span / 2) / span
      : 0;
  if (normalized < 0) normalized = 0;
  if (normalized > 127) normalized = 127;
  for (uint8_t zone = 0; zone + 1 < route.zoneCount; ++zone)
    if (normalized <= route.upperBoundaries[zone]) return zone;
  return route.zoneCount - 1;
}

const NoteRoute* DdrumBridge::findHihatRoute(uint8_t inputChannel, uint8_t inputNote) const {
  if (!config_.hihatQuantized.enabled) return nullptr;
  for (size_t index = 0; index < config_.hihatHitRouteCount; ++index) {
    HihatHitRoute route = readHihatHitRoute(index);
    if (route.inputChannel != inputChannel || route.inputNote != inputNote) continue;
    hihatRouteBuffer_ = {route.inputChannel, route.inputNote, route.outputNotes[hihatZone(route)], 1, 127, 1, 127};
    return &hihatRouteBuffer_;
  }
  return nullptr;
}

DdrumStateAction DdrumBridge::readStateAction(size_t index) const {
#if defined(ARDUINO_ARCH_AVR)
  DdrumStateAction result{};
  const uint8_t* source = reinterpret_cast<const uint8_t*>(config_.stateActions) + index * sizeof(DdrumStateAction);
  uint8_t* destination = reinterpret_cast<uint8_t*>(&result);
  for (size_t byte = 0; byte < sizeof(DdrumStateAction); ++byte) destination[byte] = pgm_read_byte(source + byte);
  return result;
#else
  return config_.stateActions[index];
#endif
}

const NoteRoute* DdrumBridge::findLedgerRoute(uint8_t inputChannel, uint8_t inputNote, uint32_t nowMs) {
  for (size_t i = 0; i < HIT_LEDGER_CAPACITY; ++i) {
    HitLedgerEntry& entry = hitLedger_[i];
    if (entry.active && (int32_t)(nowMs - entry.expiresAt) > 0) entry.active = false;
    // rememberPrimaryHit updates an existing source key in place, so at most
    // one live entry can match. Avoid ordering sequence numbers across their
    // uint32_t wrap point.
    if (entry.active && entry.channel == inputChannel && entry.note == inputNote)
      return &entry.route;
  }
  return nullptr;
}

void DdrumBridge::rememberPrimaryHit(uint8_t inputChannel, uint8_t inputNote, const NoteRoute* route, uint32_t nowMs) {
  size_t target = 0;
  uint32_t greatestAge = 0;
  bool replacementSelected = false;
  for (size_t i = 0; i < HIT_LEDGER_CAPACITY; ++i) {
    if (hitLedger_[i].active && hitLedger_[i].channel == inputChannel && hitLedger_[i].note == inputNote) {
      target = i;
      replacementSelected = true;
      break;
    }
    if (!hitLedger_[i].active) {
      target = i;
      replacementSelected = true;
      break;
    }
    // Unsigned subtraction gives a stable age across sequence wrap as long as
    // live entries are less than 2^31 hits apart (the ledger expires in 250ms).
    uint32_t age = hitSequence_ - hitLedger_[i].sequence;
    if (!replacementSelected || age > greatestAge) {
      greatestAge = age;
      target = i;
      replacementSelected = true;
    }
  }
  hitLedger_[target] = {inputChannel, inputNote, *route, ++hitSequence_, nowMs + HIT_LEDGER_WINDOW_MS, true};
}

bool DdrumBridge::validConfig() const {
  if (config_.outputChannel < 1 || config_.outputChannel > 16) return false;
  if (!config_.logicalControls.sceneCount || config_.initialState.scene >= config_.logicalControls.sceneCount) return false;
  if (config_.noteRouteCount && !config_.noteRoutes) return false;
  if (config_.relayProgramChannelCount && !config_.relayProgramChannels) return false;
  if (config_.stateRouteCount && !config_.stateRoutes) return false;
  if (config_.nativeControlCount && !config_.nativeControls) return false;
  if (config_.stateActionCount && !config_.stateActions) return false;
  if (config_.hihatQuantized.enabled && (!config_.hihatHitRouteCount || !config_.hihatHitRoutes)) return false;
  if (config_.echoGuard.mode != EchoGuardMode::Disabled &&
      config_.echoGuard.mode != EchoGuardMode::DualDdrum) return false;
  if (config_.echoGuard.mode == EchoGuardMode::DualDdrum &&
      (config_.echoGuard.returnChannel < 1 || config_.echoGuard.returnChannel > 16)) return false;
  const HihatDirectCc4Config& h = config_.hihat;
  if (h.enabled && (h.sourceChannel < 1 || h.sourceChannel > 16 || h.inputCc > 127 || h.outputCc > 127 ||
      h.inputClosed == h.inputOpen || h.inputClosed > 127 || h.inputOpen > 127 ||
      h.outputClosed > 127 || h.outputOpen > 127)) return false;
  const HihatQuantizedConfig& q = config_.hihatQuantized;
  if (q.enabled && (h.enabled || q.sourceChannel < 1 || q.sourceChannel > 16 || q.inputCc > 127 ||
      q.inputClosed == q.inputOpen)) return false;
  for (size_t i = 0; i < config_.hihatHitRouteCount; ++i) {
    HihatHitRoute route = readHihatHitRoute(i);
    if (!q.enabled || route.inputChannel != q.sourceChannel || route.inputNote > 127 ||
        route.zoneCount < 1 || route.zoneCount > 8) return false;
    for (uint8_t zone = 0; zone < route.zoneCount; ++zone) {
      if (route.outputNotes[zone] > 127) return false;
      if (zone >= 2 && route.upperBoundaries[zone - 1] <= route.upperBoundaries[zone - 2]) return false;
    }
    for (size_t otherIndex = i + 1; otherIndex < config_.hihatHitRouteCount; ++otherIndex) {
      HihatHitRoute other = readHihatHitRoute(otherIndex);
      if (route.inputChannel == other.inputChannel && route.inputNote == other.inputNote) return false;
    }
  }
  for (size_t i = 0; i < config_.relayProgramChannelCount; ++i)
    if (config_.relayProgramChannels[i] < 1 || config_.relayProgramChannels[i] > 16) return false;
  for (size_t i = 0; i < config_.noteRouteCount; ++i) {
    const NoteRoute& route = config_.noteRoutes[i];
    if (route.inputChannel < 1 || route.inputChannel > 16 || route.inputNote > 127 || route.outputNote > 127 ||
        route.inputVelocityMin > 127 || route.inputVelocityMax > 127 || route.outputVelocityMin > 127 || route.outputVelocityMax > 127 || route.extraOutputCount >= MAX_OUTPUT_EVENTS ||
        (route.extraOutputCount && !route.extraOutputs)) return false;
    for (size_t output = 0; output < route.extraOutputCount; ++output) {
      const MidiEvent& event = route.extraOutputs[output].event;
      if ((uint8_t)event.type > (uint8_t)MidiEventType::ProgramChange || event.channel > 16 ||
          event.data1 > 127 || event.data2 > 127) return false;
    }
  }
  for (size_t i = 0; i < config_.stateRouteCount; ++i) {
    StateRoute state = readStateRoute(i);
    if (state.inputChannel < 1 || state.inputChannel > 16 || state.inputNote > 127 ||
        state.outputNote > 127 || state.inputVelocityMin > 127 || state.inputVelocityMax > 127 ||
        state.outputVelocityMin > 127 || state.outputVelocityMax > 127 ||
        (state.scene != 0xff && state.scene >= config_.logicalControls.sceneCount) ||
        (state.vp1 != 0xff && state.vp1 > 127) ||
        (state.vp2 != 0xff && state.vp2 > 127) ||
        (state.vp3 != 0xff && state.vp3 > 127) ||
        (state.vp4 != 0xff && state.vp4 > 127)) return false;
  }
  for (size_t i = 0; i < config_.nativeControlCount; ++i) {
    NativeControlRoute control = readNativeControl(i);
    if (control.sourceChannel < 1 || control.sourceChannel > 16 || control.address > 127 || control.target > 4 || control.value > 127 ||
        (control.type != NativeControlType::ProgramChange && control.type != NativeControlType::ControlChange && control.type != NativeControlType::NoteOn)) return false;
    if (control.target == 0 && control.value >= config_.logicalControls.sceneCount) return false;
    for (size_t j = i + 1; j < config_.nativeControlCount; ++j) {
      NativeControlRoute other = readNativeControl(j);
      if (control.sourceChannel == other.sourceChannel && control.type == other.type && control.address == other.address) return false;
    }
  }
  for (size_t i = 0; i < config_.stateActionCount; ++i) {
    const DdrumStateAction action = readStateAction(i);
    if (action.scene >= config_.logicalControls.sceneCount || !action.event.channel || action.event.channel > 16 ||
        (uint8_t)action.event.type > (uint8_t)MidiEventType::ProgramChange || action.event.data1 > 127 || action.event.data2 > 127) return false;
  }
  const uint8_t controls[] = {config_.logicalControls.vp1Cc, config_.logicalControls.vp2Cc,
                              config_.logicalControls.vp3Cc, config_.logicalControls.vp4Cc};
  for (size_t i = 0; i < sizeof(controls); ++i) {
    if (controls[i] > 127 && controls[i] != 0xff) return false;
    for (size_t j = i + 1; j < sizeof(controls); ++j)
      if (controls[i] != 0xff && controls[i] == controls[j]) return false;
  }
  if (config_.noteRouteIndex) {
    for (size_t i = 0; i < 16U * 128U; ++i) {
      int16_t index = config_.noteRouteIndex[i];
      if (index < -1 || (index >= 0 && (size_t)index >= config_.noteRouteCount)) return false;
      if (index >= 0) {
        const NoteRoute& route = config_.noteRoutes[index];
        if (route.inputChannel != i / 128U + 1U || route.inputNote != i % 128U) return false;
      }
    }
  }
  return true;
}

size_t DdrumBridge::emitStateActions(MidiEvent* output, size_t capacity, uint32_t nowMs) {
  size_t count = 0;
  for (size_t index = 0; index < config_.stateActionCount; ++index) {
    const DdrumStateAction action = readStateAction(index);
    if (action.scene != logicalState_.scene ||
        (action.vp1 != 0xff && action.vp1 != logicalState_.vp1) ||
        (action.vp2 != 0xff && action.vp2 != logicalState_.vp2) ||
        (action.vp3 != 0xff && action.vp3 != logicalState_.vp3) ||
        (action.vp4 != 0xff && action.vp4 != logicalState_.vp4) || !action.event.channel) continue;
    if (count == capacity) { ++outputOverflows_; break; }
    output[count++] = action.event;
    rememberOutput(action.event, nowMs);
  }
  return count;
}

bool DdrumBridge::isLogicalControl(const MidiEvent& input) {
  if (input.channel != 14 && input.channel != 15) return false;
  if (input.type == MidiEventType::ProgramChange) {
    logicalState_.scene = input.data1;
    return true;
  }
  if (input.type != MidiEventType::ControlChange) return false;
  const uint8_t controls[] = {config_.logicalControls.vp1Cc, config_.logicalControls.vp2Cc,
                              config_.logicalControls.vp3Cc, config_.logicalControls.vp4Cc};
  for (uint8_t index = 0; index < sizeof(controls); ++index) {
    if (controls[index] == 0xff || input.data1 != controls[index]) continue;
    switch (index) {
      case 0: logicalState_.vp1 = input.data2; break;
      case 1: logicalState_.vp2 = input.data2; break;
      case 2: logicalState_.vp3 = input.data2; break;
      default: logicalState_.vp4 = input.data2; break;
    }
    return true;
  }
  return false;
}

bool DdrumBridge::isNativeControl(const MidiEvent& input) {
  for (size_t i = 0; i < config_.nativeControlCount; ++i) {
    const NativeControlRoute control = readNativeControl(i);
    if (control.sourceChannel != input.channel) continue;
    const bool matches = (control.type == NativeControlType::ProgramChange && input.type == MidiEventType::ProgramChange && control.address == input.data1) ||
        (control.type == NativeControlType::ControlChange && input.type == MidiEventType::ControlChange && control.address == input.data1 && control.value == input.data2) ||
        (control.type == NativeControlType::NoteOn && input.type == MidiEventType::NoteOn && input.data2 != 0 && control.address == input.data1);
    if (!matches) continue;
    const uint8_t value = control.value;
    switch (control.target) {
      case 0: logicalState_.scene = value; break;
      case 1: logicalState_.vp1 = value; break;
      case 2: logicalState_.vp2 = value; break;
      case 3: logicalState_.vp3 = value; break;
      default: logicalState_.vp4 = value; break;
    }
    return true;
  }
  return false;
}

bool DdrumBridge::isExpectedEcho(const MidiEvent& input, uint32_t nowMs) {
  if (config_.echoGuard.mode != EchoGuardMode::DualDdrum ||
      input.channel != config_.echoGuard.returnChannel) return false;
  while (echoCount_) {
    EchoEntry& entry = echoes_[echoHead_];
    if ((int32_t)(nowMs - entry.expiresAt) <= 0) break;
    entry.active = false;
    echoHead_ = (uint8_t)((echoHead_ + 1U) % ECHO_CAPACITY);
    --echoCount_;
  }
  if (!echoCount_) return false;
  EchoEntry& entry = echoes_[echoHead_];
  const MidiEvent& event = entry.event;
  if (event.type != input.type || event.channel != input.channel ||
      event.data1 != input.data1 || event.data2 != input.data2) return false;
  entry.active = false; // only the earliest causal return can consume a token
  echoHead_ = (uint8_t)((echoHead_ + 1U) % ECHO_CAPACITY);
  --echoCount_;
  ++expectedEchoes_;
  return true;
}

void DdrumBridge::rememberOutput(const MidiEvent& output, uint32_t nowMs) {
  if (config_.echoGuard.mode != EchoGuardMode::DualDdrum ||
      output.channel != config_.echoGuard.returnChannel) return;
  if (echoCount_ == ECHO_CAPACITY) {
    echoes_[echoHead_].active = false;
    echoHead_ = (uint8_t)((echoHead_ + 1U) % ECHO_CAPACITY);
    --echoCount_;
  }
  uint8_t tail = (uint8_t)((echoHead_ + echoCount_) % ECHO_CAPACITY);
  EchoEntry& entry = echoes_[tail];
  entry.event = output;
  entry.expiresAt = nowMs + config_.echoGuard.windowMs;
  entry.active = true;
  ++echoCount_;
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

size_t DdrumBridge::process(const MidiEvent& input, MidiEvent* output, size_t capacity, uint32_t nowMs) {
  if (!output || !capacity || !configValid_) {
    if (!configValid_) ++invalidConfigurations_;
    else if (!capacity) ++outputOverflows_;
    return 0;
  }

  // MidiDinAdapter can only construct 7-bit channel messages, but this pure
  // core is also called directly by native tools. Validate before looking up
  // the optional 16 * 128 index: an input note above 127 would otherwise read
  // into the next channel row (or beyond the table for channel 16).
  if ((uint8_t)input.type > (uint8_t)MidiEventType::ProgramChange ||
      input.channel < 1 || input.channel > 16 || input.data1 > 127 ||
      input.data2 > 127) {
    ++ignoredMessages_;
    return 0;
  }

  if (isExpectedEcho(input, nowMs)) return 0;

  // Reserved logical Program Changes use scene indexes, not arbitrary MIDI
  // program numbers. Consume an out-of-range command rather than leaving the
  // bridge in a state for which no route or action was generated.
  if ((input.channel == 14 || input.channel == 15) && input.type == MidiEventType::ProgramChange &&
      input.data1 >= config_.logicalControls.sceneCount) {
    ++ignoredMessages_;
    return 0;
  }

  // Logical controls update state and reconcile only declared native output.
  const LogicalState priorState = logicalState_;
  if (isLogicalControl(input)) {
    if (priorState.scene == logicalState_.scene && priorState.vp1 == logicalState_.vp1 &&
        priorState.vp2 == logicalState_.vp2 && priorState.vp3 == logicalState_.vp3 && priorState.vp4 == logicalState_.vp4) return 0;
    return emitStateActions(output, capacity, nowMs);
  }
  // Native DDrum4 changes are observations. Update state but never echo an
  // action back to that same module; PC/logical controls are the sole origin
  // of renderer reconciliation.
  if (isNativeControl(input)) {
    return 0;
  }

  if (mode_ == BridgeMode::Silent) return 0;

  if (mode_ == BridgeMode::Bypass) {
    output[0] = input;
    return 1;
  }

  // A quantized profile retains CC4 state and chooses the DDrum4 Note-P slot
  // on the following bow/edge hit. No controller is emitted to DDrum4.
  const HihatQuantizedConfig& q = config_.hihatQuantized;
  if (q.enabled && input.type == MidiEventType::ControlChange && input.channel == q.sourceChannel &&
      input.data1 == q.inputCc) {
    lastHihatCc_ = input.data2;
    return 0;
  }

  // Legacy/direct controller profiles remain supported for modules that do
  // understand CC4, but cannot be enabled together with Note-P quantization.
  const HihatDirectCc4Config& h = config_.hihat;
  if (h.enabled && input.type == MidiEventType::ControlChange && input.channel == h.sourceChannel &&
      input.data1 == h.inputCc) {
    uint8_t mapped = mapHihatCc(input.data2);
    output[0] = {MidiEventType::ControlChange, config_.outputChannel, h.outputCc, mapped};
    rememberOutput(output[0], nowMs);
    return 1;
  }

  if (input.type == MidiEventType::ProgramChange && config_.relayProgramChange) {
    for (size_t i = 0; i < config_.relayProgramChannelCount; ++i) {
      if (input.channel == config_.relayProgramChannels[i]) {
        output[0] = {MidiEventType::ProgramChange, config_.outputChannel, input.data1, 0};
        rememberOutput(output[0], nowMs);
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

  // Pressure/choke belongs to the latest actual primary hit for this source
  // note; it must not be re-routed through a changed Scene/VP state.
  const NoteRoute* route = nullptr;
  if (input.type == MidiEventType::PolyAftertouch) {
    route = findLedgerRoute(input.channel, input.data1, nowMs);
  } else {
    route = findHihatRoute(input.channel, input.data1);
    if (!route) route = findNoteRoute(input.channel, input.data1);
  }
  if (!route) {
    ++ignoredMessages_;
    return 0;
  }
  uint8_t value = input.data2;
  if (input.type == MidiEventType::NoteOn) value = mapVelocity(*route, input.data2);
  size_t wanted = 1U + route->extraOutputCount;
  if (wanted > MAX_OUTPUT_EVENTS ||
      (route->extraOutputCount && !route->extraOutputs)) {
    ++outputOverflows_;
    return 0;
  }
  output[0] = {input.type, config_.outputChannel, route->outputNote, value};
  if (capacity < wanted) {
    // The primary hit is always first and must not be dropped because an
    // optional side effect cannot fit in the caller's bounded buffer.
    ++outputOverflows_;
    if (input.type == MidiEventType::NoteOn) rememberPrimaryHit(input.channel, input.data1, route, nowMs);
    rememberOutput(output[0], nowMs);
    return 1;
  }
  for (size_t i = 0; i < route->extraOutputCount; ++i) {
    output[i + 1] = route->extraOutputs[i].event;
    if (!output[i + 1].channel) output[i + 1].channel = config_.outputChannel;
    if (route->extraOutputs[i].useValue) output[i + 1].data2 = value;
  }
  if (input.type == MidiEventType::NoteOn) rememberPrimaryHit(input.channel, input.data1, route, nowMs);
  for (size_t i = 0; i < wanted; ++i) rememberOutput(output[i], nowMs);
  return wanted;
}
