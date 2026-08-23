#include "MidiDinAdapter.h"

void MidiDinAdapter::begin() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
}

uint8_t MidiDinAdapter::dataLength(uint8_t status) {
  uint8_t type = status >> 4;
  return (type == 0xC || type == 0xD) ? 1 : (type >= 0x8 && type <= 0xE ? 2 : 0);
}

BridgeMode MidiDinAdapter::modeFromControlValue(uint8_t value) {
  // One CC selects the only three DIN-OUT roles. The ranges make the command
  // robust with faders, switches and PC scene automation:
  // 0..41=NESTED, 42..83=SILENT, 84..127=BYPASS.
  if (value < 42) return BridgeMode::Nested;
  if (value < 84) return BridgeMode::Silent;
  return BridgeMode::Bypass;
}

void MidiDinAdapter::poll() {
  while (port_.available()) receive((uint8_t)port_.read());
  if (ledUntil_ && (int32_t)(millis() - ledUntil_) >= 0) {
    digitalWrite(LED_BUILTIN, LOW);
    ledUntil_ = 0;
  }
}

void MidiDinAdapter::clearMessageState() {
  // MIDI 1.0 cancels channel-message running status at every SysEx or System
  // Common boundary. Keeping it would let later data bytes complete a stale
  // Note On and create a false hit.
  runningStatus_ = 0;
  count_ = 0;
}

void MidiDinAdapter::receive(uint8_t byte) {
  // Real-Time bytes can occur anywhere, including in SysEx, and do not alter
  // running status. They are intentionally not routed by this bridge.
  if (byte >= 0xF8) return;

  if (byte == 0xF0) {
    clearMessageState();
    inSysEx_ = true;
    return;
  }

  if (inSysEx_) {
    if (byte == 0xF7) {
      inSysEx_ = false;
      clearMessageState();
      return;
    }
    if (!(byte & 0x80)) return; // SysEx payload is never channel data.
    // A malformed SysEx must not hide a following valid channel status.
    inSysEx_ = false;
  }

  // System Common (including a stray EOX) also cancels running status. Their
  // data bytes are ignored because runningStatus_ is now zero.
  if (byte >= 0xF0) {
    clearMessageState();
    return;
  }

  if (byte & 0x80) { runningStatus_ = byte; count_ = 0; return; }
  if (!runningStatus_) return;
  uint8_t wanted = dataLength(runningStatus_);
  if (!wanted || count_ >= wanted) return;
  data_[count_++] = byte;
  if (count_ == wanted) {
    dispatch(runningStatus_, data_[0], wanted == 2 ? data_[1] : 0);
    count_ = 0; // preserve running status
  }
}

void MidiDinAdapter::dispatch(uint8_t status, uint8_t data1, uint8_t data2) {
  MidiEvent input;
  input.channel = (status & 0x0F) + 1;
  input.data1 = data1;
  input.data2 = data2;
  switch (status >> 4) {
    case 0x8: input.type = MidiEventType::NoteOff; break;
    case 0x9: input.type = MidiEventType::NoteOn; break;
    case 0xA: input.type = MidiEventType::PolyAftertouch; break;
    case 0xB: input.type = MidiEventType::ControlChange; break;
    case 0xC: input.type = MidiEventType::ProgramChange; break;
    default: return;
  }
  if (input.type == MidiEventType::ControlChange && modeControl_.channel &&
      input.channel == modeControl_.channel && input.data1 == modeControl_.control) {
    // This control is bridge-local: hardware THRU still carries the original
    // event to the PC, but Arduino OUT never sends it to the DDrum4.
    bridge_.setMode(modeFromControlValue(input.data2));
    return;
  }
  MidiEvent output[DdrumBridge::MAX_OUTPUT_EVENTS];
  size_t count = bridge_.process(input, output, DdrumBridge::MAX_OUTPUT_EVENTS, millis());
  for (size_t i = 0; i < count; ++i) emit(output[i]);
}

void MidiDinAdapter::emit(const MidiEvent& event) {
  uint8_t status;
  switch (event.type) {
    case MidiEventType::NoteOn: status = 0x90; break;
    case MidiEventType::NoteOff: status = 0x80; break;
    case MidiEventType::ControlChange: status = 0xB0; break;
    case MidiEventType::PolyAftertouch: status = 0xA0; break;
    case MidiEventType::ProgramChange: status = 0xC0; break;
  }
  const uint8_t bytes = event.type == MidiEventType::ProgramChange ? 2 : 3;
  // Stream::availableForWrite is supplied by Arduino's UART streams. Refuse a
  // whole MIDI event when the bounded UART buffer cannot hold it, rather than
  // writing a truncated wire message.
  if (port_.availableForWrite() < bytes) {
    ++uartOverflows_;
    return;
  }
  port_.write(status | (event.channel - 1));
  port_.write(event.data1);
  if (event.type != MidiEventType::ProgramChange) port_.write(event.data2);
  digitalWrite(LED_BUILTIN, HIGH);
  ledUntil_ = millis() + 4;
}
