#include <Arduino.h>
#include "DdrumBridge.h"
#include "generated_mapping.h"
#include "MidiDinAdapter.h"

#ifndef ROUTER_USE_SD
#define ROUTER_USE_SD 0
#endif
#ifndef ROUTER_DEBUG
#define ROUTER_DEBUG 0
#endif
#ifndef ROUTER_TX_SELF_TEST
#define ROUTER_TX_SELF_TEST 0
#endif

#if ROUTER_USE_SD
#include <SPI.h>
#include <SD.h>
#ifndef ROUTER_SD_CS
#define ROUTER_SD_CS 10
#endif
#endif

// Select the UART wired to the MIDI shield. On Uno this is Serial (pins 0/1).
// On Mega use Serial1 and keep Serial available through USB for diagnostics.
#if defined(ARDUINO_AVR_MEGA2560)
#define MIDI_PORT Serial1
#else
#define MIDI_PORT Serial
#endif

const BridgeConfig BRIDGE_CONFIG = {
  DDRUM_OUTPUT_CHANNEL,
  DDTI_INPUT_CHANNEL,
  EDRUMIN_INPUT_CHANNEL,
  HIHAT_CC4,
  NOTE_ROUTES,
  NOTE_ROUTE_COUNT,
  true, // Program Change from either source -> selected ddrum4 kit
};
DdrumBridge bridge(BRIDGE_CONFIG);
MidiDinAdapter midi(MIDI_PORT, bridge);

void setup() {
#if ROUTER_DEBUG
  Serial.begin(115200);
  Serial.println(F("MIDI router boot"));
#endif
  MIDI_PORT.begin(31250);
  midi.begin();
}

void loop() {
  midi.poll();
#if ROUTER_TX_SELF_TEST
  // Diagnostic profile only. A MIDI monitor on Arduino OUT should receive
  // channel-10 note 38 every two seconds, proving the TX/shield output path.
  static uint32_t nextTest = 1000;
  if ((int32_t)(millis() - nextTest) >= 0) {
    MIDI_PORT.write((uint8_t)0x99);
    MIDI_PORT.write((uint8_t)38);
    MIDI_PORT.write((uint8_t)100);
    delay(100);
    MIDI_PORT.write((uint8_t)0x89);
    MIDI_PORT.write((uint8_t)38);
    MIDI_PORT.write((uint8_t)0);
    nextTest += 2000;
  }
#endif
}
