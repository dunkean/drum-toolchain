#include "DdrumBridge.h"

#include <cstdint>
#include <iostream>
#include <stdexcept>

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

  require(bridge.process({MidiEventType::NoteOn, 12, 17, 127}, &output, 1) == 1,
          "one-shot NoteOn missing");
  require(bridge.process({MidiEventType::NoteOff, 12, 17, 0}, &output, 1) == 0,
          "one-shot NoteOff was forwarded");
  require(bridge.process({MidiEventType::PolyAftertouch, 12, 17, 47}, &output, 1) == 1,
          "one-shot aftertouch was filtered");
  require(output.type == MidiEventType::PolyAftertouch && output.data2 == 47,
          "one-shot aftertouch differs");

  bridge.setMode(BridgeMode::Bypass);
  require(bridge.process({MidiEventType::NoteOn, 12, 17, 0}, &output, 1) == 1,
          "bypass release marker was filtered");
  require(output.type == MidiEventType::NoteOn && output.channel == 12 && output.data1 == 17 && output.data2 == 0,
          "bypass release marker differs");
}

}  // namespace

int main() {
  try {
    test_note_and_release_policy();
    test_cc_and_unknown_message_policy();
    test_velocity_window();
    test_third_source_program_change_is_relayed();
    test_ddrum_one_shot_policy();
    std::cout << "firmware bridge core tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "firmware bridge core test failure: " << error.what() << '\n';
    return 1;
  }
}
