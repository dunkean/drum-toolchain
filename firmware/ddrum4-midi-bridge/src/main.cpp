#include <Arduino.h>
#include "DdrumBridge.h"
#include "generated_mapping.h"
#include "MidiDinAdapter.h"

static_assert(!HIHAT_NOTE_P_SUPPORTED && !HIHAT_THREE_ZONE_SUPPORTED,
              "unvalidated hi-hat Note-P/three-zone policies must stay disabled");

#ifndef ROUTER_USE_SD
#define ROUTER_USE_SD 0
#endif
#ifndef ROUTER_DEBUG
#define ROUTER_DEBUG 0
#endif
#ifndef ROUTER_TX_SELF_TEST
#define ROUTER_TX_SELF_TEST 0
#endif
#ifndef ROUTER_MODE_CONTROL_CHANNEL
#define ROUTER_MODE_CONTROL_CHANNEL 16
#endif
#ifndef ROUTER_MODE_CONTROL_CC
#define ROUTER_MODE_CONTROL_CC 119
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
  RELAY_PROGRAM_CHANNELS,
  RELAY_PROGRAM_CHANNEL_COUNT,
  HIHAT_CC4,
  NOTE_ROUTES,
  NOTE_ROUTE_COUNT,
  false, // POC: never select a DDrum4 kit from incoming MIDI
  nullptr, {EchoGuardMode::Disabled, 0, 0}, INITIAL_LOGICAL_STATE,
  STATE_ROUTES, STATE_ROUTE_COUNT,
  LOGICAL_CONTROLS,
  NATIVE_CONTROLS, NATIVE_CONTROL_COUNT,
  STATE_ACTIONS, STATE_ACTION_COUNT,
};
DdrumBridge bridge(BRIDGE_CONFIG);
// CC119 on channel 16 selects nested / PC-clean / bypass without a cable swap.
// The values are 0..41=NESTED, 42..83=SILENT, 84..127=BYPASS.
MidiDinAdapter midi(MIDI_PORT, bridge,
                    {ROUTER_MODE_CONTROL_CHANNEL, ROUTER_MODE_CONTROL_CC});

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
