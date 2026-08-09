#pragma once

#include <Arduino.h>
#include "DdrumBridge.h"

// Small DIN MIDI 1.0 framing layer for the Uno's sole UART. It only decodes
// the message classes accepted by DdrumBridge; other traffic is ignored.
class MidiDinAdapter {
 public:
  MidiDinAdapter(Stream& port, DdrumBridge& bridge) : port_(port), bridge_(bridge) {}
  void begin();
  void poll();

 private:
  Stream& port_;
  DdrumBridge& bridge_;
  uint8_t runningStatus_ = 0;
  uint8_t data_[2] = {0, 0};
  uint8_t count_ = 0;
  uint32_t ledUntil_ = 0;
  void receive(uint8_t byte);
  void dispatch(uint8_t status, uint8_t data1, uint8_t data2);
  void emit(const MidiEvent& event);
  static uint8_t dataLength(uint8_t status);
};
