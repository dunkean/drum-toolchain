#include "DdrumBridge.h"
#include "MidiDinAdapter.h"

#include <cstdint>
#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

const NoteRoute routes[] = {
    {11, 42, 91, 1, 127, 1, 127},
    {11, 46, 94, 1, 127, 1, 127},
    {10, 36, 60, 1, 127, 13, 24},
    {12, 17, 17, 1, 127, 1, 127},
};
const uint8_t programChannels[] = {10, 11, 12};

const BridgeConfig config = {
    10, programChannels, sizeof(programChannels) / sizeof(programChannels[0]),
    {11, 4, 4, 0, 127, 0, 127, false},
    routes, sizeof(routes) / sizeof(routes[0]), true,
};

class FakeMidiStream : public HardwareSerial {
 public:
  void feed(std::initializer_list<uint8_t> bytes) { input.insert(input.end(), bytes.begin(), bytes.end()); }
  int available() override { return static_cast<int>(input.size() - readIndex); }
  int read() override { return input[readIndex++]; }
  size_t write(uint8_t byte) override { output.push_back(byte); return 1; }

  std::vector<uint8_t> input;
  std::vector<uint8_t> output;
  size_t readIndex = 0;
};

void requireOutput(const FakeMidiStream& stream, std::initializer_list<uint8_t> expected,
                   const char* message) {
  require(stream.output.size() == expected.size(), message);
  size_t index = 0;
  for (uint8_t byte : expected) require(stream.output[index++] == byte, message);
}

void test_note_and_release_policy() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 99}, &output, 1) == 1, "mapped NoteOn missing");
  require(output.channel == 10 && output.data1 == 91 && output.data2 == 99, "mapped NoteOn differs");
  require(bridge.process({MidiEventType::NoteOff, 11, 42, 0}, &output, 1) == 0,
          "DDrum4 must not receive an unsupported NoteOff");
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 0}, &output, 1) == 0,
          "DDrum4 release marker must not be relayed");
}

void test_cc_and_unknown_message_policy() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::ControlChange, 11, 4, 64}, &output, 1) == 1, "CC4 missing");
  require(output.type == MidiEventType::ControlChange && output.data1 == 4, "CC4 mapping differs");
  require(bridge.process({MidiEventType::ControlChange, 11, 4, 64}, &output, 1) == 1,
          "CC4 must be passed without an Arduino-side filter");
  require(bridge.process({MidiEventType::NoteOn, 10, 38, 127}, &output, 1) == 0, "unknown NoteOn forwarded");
}

void test_velocity_window() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 10, 36, 64}, &output, 1) == 1, "velocity-window route missing");
  require(output.data1 == 60 && output.data2 == 19, "velocity window differs");
}

void test_third_source_program_change_is_relayed() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::ProgramChange, 12, 7, 0}, &output, 1) == 1,
          "declared third source ProgramChange missing");
  require(output.channel == 10 && output.data1 == 7, "third source ProgramChange differs");
}

void test_ddrum_one_shot_policy() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 12, 17, 127}, &output, 1) == 1, "one-shot NoteOn missing");
  require(bridge.process({MidiEventType::NoteOff, 12, 17, 0}, &output, 1) == 0, "one-shot NoteOff was forwarded");
  require(bridge.process({MidiEventType::PolyAftertouch, 12, 17, 47}, &output, 1) == 1,
          "one-shot aftertouch was filtered");
  require(output.type == MidiEventType::PolyAftertouch && output.data2 == 47, "one-shot aftertouch differs");
  bridge.setMode(BridgeMode::Bypass);
  require(bridge.process({MidiEventType::NoteOn, 12, 17, 0}, &output, 1) == 1,
          "bypass release marker was filtered");
}

void test_sysex_cancels_partial_message_and_running_status() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});
  stream.feed({0x9A, 42, 0xF0, 0x7D, 0x01, 0xF8, 0x55, 0xF7, 100,
               0x9A, 42, 100, 42, 101});
  adapter.poll();
  requireOutput(stream, {0x99, 91, 100, 0x99, 91, 101},
                "SysEx boundary allowed stale data or broke later running status");
}

void test_system_common_cancels_running_status() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});
  stream.feed({0x9A, 42, 0xF1, 0x7F, 100, 0xBA, 4, 64, 0xCA, 7});
  adapter.poll();
  requireOutput(stream, {0xB9, 4, 64, 0xC9, 7}, "System Common did not cancel running status");
}

void test_realtime_preserves_running_status() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});
  stream.feed({0x9A, 42, 100, 0xF8, 42, 101});
  adapter.poll();
  requireOutput(stream, {0x99, 91, 100, 0x99, 91, 101}, "Real-Time byte cleared running status");
}

void test_logical_controls_are_state_only_on_reserved_channels() {
  const BridgeConfig sceneConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false},
      routes, 4, true, nullptr, {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, nullptr, 0,
      {0, 1, 2, 3, 10},
  };
  DdrumBridge bridge(sceneConfig);
  MidiEvent output{};
  require(bridge.process({MidiEventType::ProgramChange, 14, 9, 0}, &output, 1) == 0,
          "Scene control escaped to renderer");
  require(bridge.process({MidiEventType::ControlChange, 15, 2, 4}, &output, 1) == 0,
          "VP control escaped to renderer");
  require(bridge.logicalState().scene == 9 && bridge.logicalState().vp3 == 4,
          "reserved channel logical state differs");
}

void test_route_can_emit_note_and_cc_without_allocation() {
  const RouteOutput sideEffects[] = {
      {{MidiEventType::ControlChange, 0, 74, 0}, true},
  };
  const NoteRoute multiRoutes[] = {
      {11, 42, 91, 1, 127, 1, 127, sideEffects, 1},
  };
  const BridgeConfig multiConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false},
      multiRoutes, 1, false, nullptr, {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(multiConfig);
  MidiEvent output[DdrumBridge::MAX_OUTPUT_EVENTS]{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 73}, output,
                         DdrumBridge::MAX_OUTPUT_EVENTS) == 2,
          "note plus CC route did not emit both events");
  require(output[0].type == MidiEventType::NoteOn && output[0].data1 == 91 &&
              output[1].type == MidiEventType::ControlChange && output[1].data1 == 74 &&
              output[1].data2 == 73,
          "multi output values differ");
}

void test_echo_guard_consumes_only_future_expected_return() {
  const BridgeConfig guarded = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false},
      routes, 4, true, nullptr, {EchoGuardMode::DualDdrum, 10, 10}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(guarded);
  MidiEvent output{};
  // A matching event before this bridge has emitted it is a real input.
  require(bridge.process({MidiEventType::NoteOn, 10, 91, 100}, &output, 1, 100) == 0 &&
              bridge.expectedEchoes() == 0,
          "future echo was misclassified before it was emitted");
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 100}, &output, 1, 100) == 1,
          "guarded primary hit missing");
  require(bridge.process(output, &output, 1, 105) == 0 && bridge.expectedEchoes() == 1,
          "expected immediate echo was not consumed");
  require(bridge.process({MidiEventType::NoteOn, 10, 91, 100}, &output, 1, 120) == 0 &&
              bridge.expectedEchoes() == 1,
          "expired echo token swallowed later traffic");
}

void test_state_route_and_ledger_keep_the_primary_hit() {
  const StateRoute stateRoutes[] = {
      {11, 42, 9, 0xff, 0xff, 4, 0xff, 101, 1, 127, 1, 127},
      {11, 46, 9, 0xff, 0xff, 4, 0xff, 102, 1, 127, 1, 127},
  };
  const BridgeConfig stateful = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false},
      routes, 4, false, nullptr, {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, stateRoutes, 2,
      {0, 1, 2, 3, 10},
  };
  DdrumBridge bridge(stateful);
  MidiEvent output{};
  bridge.process({MidiEventType::ProgramChange, 14, 9, 0}, &output, 1);
  bridge.process({MidiEventType::ControlChange, 15, 2, 4}, &output, 1);
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 90}, &output, 1) == 1 && output.data1 == 101,
          "Scene/VP state route was not selected");
  require(bridge.process({MidiEventType::NoteOn, 11, 46, 90}, &output, 1) == 1 && output.data1 == 102,
          "second state route was not selected");
  bridge.process({MidiEventType::ProgramChange, 14, 0, 0}, &output, 1);
  require(bridge.process({MidiEventType::PolyAftertouch, 11, 42, 55}, &output, 1) == 1 && output.data1 == 101,
          "aftertouch did not retain actual primary route");
}

void test_flams_replace_only_the_same_source_note_ledger_entry() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 80}, &output, 1) == 1, "first flam hit missing");
  require(bridge.process({MidiEventType::NoteOn, 11, 46, 81}, &output, 1) == 1, "second flam hit missing");
  require(bridge.process({MidiEventType::PolyAftertouch, 11, 42, 50}, &output, 1) == 1 && output.data1 == 91,
          "flam aftertouch was associated with a different source note");
}

void test_ledger_expires_stale_aftertouch() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 80}, &output, 1, 10) == 1,
          "ledger primary hit missing");
  require(bridge.process({MidiEventType::PolyAftertouch, 11, 42, 50}, &output, 1,
                         300) == 0,
          "stale pressure was routed after ledger expiry");
}

void test_malformed_configs_are_inert() {
  const BridgeConfig malformed = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes, 4,
      false, nullptr, {EchoGuardMode::DualDdrum, 10, 0}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(malformed);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 100}, &output, 1) == 0 &&
              bridge.invalidConfigurations() >= 1,
          "malformed echo configuration was not rejected");
}

void test_guard_is_not_generic_and_overflow_keeps_primary_hit() {
  const RouteOutput sideEffects[] = {
      {{MidiEventType::ControlChange, 0, 74, 0}, true},
  };
  const NoteRoute routesWithEffect[] = {
      {11, 42, 91, 1, 127, 1, 127, sideEffects, 1},
  };
  const BridgeConfig noDualGuard = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routesWithEffect, 1,
      false, nullptr, {EchoGuardMode::Disabled, 10, 10}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(noDualGuard);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 90}, &output, 1) == 1 && output.data1 == 91,
          "side-effect overflow dropped the primary hit");
  require(bridge.outputOverflows() == 1, "side-effect overflow was not counted");
  // In Bypass mode raw traffic never creates an echo token.
  bridge.setMode(BridgeMode::Bypass);
  require(bridge.process({MidiEventType::NoteOn, 10, 91, 90}, &output, 1, 1) == 1,
          "disabled dual guard suppressed ordinary MIDI traffic");
}

void test_quantized_hihat_selects_note_p_from_last_cc4() {
  const HihatHitRoute hihatRoutes[] = {
      // Bow closed / loose / quarter / half / open: r15 HHAT_981 positions 1..5.
      {3, 3, 72, 5, {25, 50, 75, 100, 0, 0, 0}, {72, 73, 74, 75, 76, 0, 0, 0}},
      // Edge closed / quarter / half / open: r15 CYMB_981 positions 1..4.
      {3, 4, 40, 4, {31, 63, 95, 0, 0, 0, 0}, {40, 41, 42, 43, 0, 0, 0, 0}},
  };
  const StateRoute acousticScene[] = {
      {3, 3, 0, 0xff, 0xff, 0xff, 0xff, 72, 1, 127, 1, 127},
      {3, 4, 0, 0xff, 0xff, 0xff, 0xff, 40, 1, 127, 1, 127},
  };
  const BridgeConfig quantized = {
      12, programChannels, 3, {0, 0, 0, 0, 0, 0, 0, false, false},
      routes, 4, false, nullptr, {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0},
      acousticScene, 2, {0, 1, 2, 3, 2}, nullptr, 0, nullptr, 0,
      {3, 4, 0, 127, true}, hihatRoutes, 2,
  };
  DdrumBridge bridge(quantized);
  MidiEvent output{};
  require(bridge.process({MidiEventType::ControlChange, 3, 4, 0}, &output, 1) == 0,
          "quantized CC4 must be state only");
  require(bridge.process({MidiEventType::NoteOn, 3, 3, 111}, &output, 1) == 1 && output.data1 == 72,
          "closed bow did not select first Note-P slot");
  require(bridge.process({MidiEventType::ControlChange, 3, 4, 127}, &output, 1) == 0,
          "open quantized CC4 must be state only");
  require(bridge.process({MidiEventType::NoteOn, 3, 3, 112}, &output, 1) == 1 && output.data1 == 76,
          "open bow did not select final Note-P slot");
  require(bridge.process({MidiEventType::NoteOn, 3, 4, 113}, &output, 1) == 1 && output.data1 == 43,
          "open edge did not select its final Note-P slot");

  // Scene/VP owns logical target resolution. A scene which maps the same raw
  // bow to electronic note 50 must not be overwritten by acoustic CC4 slots.
  const StateRoute electronicScene[] = {
      {3, 3, 1, 0xff, 0xff, 0xff, 0xff, 50, 1, 127, 1, 127},
  };
  BridgeConfig sceneQuantized = quantized;
  sceneQuantized.stateRoutes = electronicScene;
  sceneQuantized.stateRouteCount = 1;
  DdrumBridge sceneBridge(sceneQuantized);
  require(sceneBridge.process({MidiEventType::ProgramChange, 14, 1, 0}, &output, 1) == 0,
          "scene change should not emit a renderer hit");
  require(sceneBridge.process({MidiEventType::ControlChange, 3, 4, 0}, &output, 1) == 0,
          "scene CC4 must remain state only");
  require(sceneBridge.process({MidiEventType::NoteOn, 3, 3, 114}, &output, 1) == 1 && output.data1 == 50,
          "quantized hihat bypassed the selected Scene renderer");
}

}  // namespace

uint32_t millis() { return 0; }
void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t, uint8_t) {}

int main() {
  try {
    test_note_and_release_policy();
    test_cc_and_unknown_message_policy();
    test_velocity_window();
    test_third_source_program_change_is_relayed();
    test_ddrum_one_shot_policy();
    test_sysex_cancels_partial_message_and_running_status();
    test_system_common_cancels_running_status();
    test_realtime_preserves_running_status();
    test_logical_controls_are_state_only_on_reserved_channels();
    test_route_can_emit_note_and_cc_without_allocation();
    test_echo_guard_consumes_only_future_expected_return();
    test_state_route_and_ledger_keep_the_primary_hit();
    test_flams_replace_only_the_same_source_note_ledger_entry();
    test_ledger_expires_stale_aftertouch();
    test_malformed_configs_are_inert();
    test_guard_is_not_generic_and_overflow_keeps_primary_hit();
    test_quantized_hihat_selects_note_p_from_last_cc4();
    std::cout << "firmware bridge and MIDI DIN tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "firmware test failure: " << error.what() << '\n';
    return 1;
  }
}
