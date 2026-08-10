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

void test_note_and_note_off() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::NoteOn, 11, 42, 99}, &output, 1) == 1, "mapped NoteOn missing");
  require(output.channel == 10 && output.data1 == 91 && output.data2 == 99, "mapped NoteOn differs");
  require(bridge.process({MidiEventType::NoteOff, 11, 42, 0}, &output, 1) == 1, "mapped NoteOff missing");
  require(output.data1 == 91 && output.data2 == 0, "mapped NoteOff differs");
}

void test_cc_and_unknown_message_policy() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  require(bridge.process({MidiEventType::ControlChange, 11, 4, 64}, &output, 1) == 1, "CC4 missing");
  require(output.type == MidiEventType::ControlChange && output.data1 == 4, "CC4 mapping differs");
  require(bridge.process({MidiEventType::ControlChange, 11, 4, 64}, &output, 1) == 0, "duplicate CC4 not filtered");
  require(bridge.duplicateCcMessages() == 1, "duplicate CC count differs");
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

void test_immediate_ddrum4_echo_is_suppressed() {
  DdrumBridge bridge(config);
  MidiEvent output{};
  const MidiEvent hit = {MidiEventType::NoteOn, 12, 17, 93};
  require(bridge.process(hit, &output, 1) == 1, "DDrum4 source note missing");
  require(bridge.process(output, &output, 1) == 0, "DDrum4 echo was not suppressed");
  require(bridge.suppressedEchoMessages() == 1, "suppressed echo count differs");
}

void test_out_of_order_echo_does_not_block_later_echo() {
  DdrumBridge bridge(config);
  MidiEvent first{};
  MidiEvent second{};
  require(bridge.process({MidiEventType::NoteOn, 12, 17, 70}, &first, 1) == 1, "first source note missing");
  require(bridge.process({MidiEventType::NoteOn, 12, 17, 100}, &second, 1) == 1, "second source note missing");
  require(bridge.process(second, &second, 1) == 0, "out-of-order later echo was not suppressed");
  require(bridge.process(first, &first, 1) == 0, "out-of-order first echo was not suppressed");
}

}  // namespace

int main() {
  try {
    test_note_and_note_off();
    test_cc_and_unknown_message_policy();
    test_velocity_window();
    test_third_source_program_change_is_relayed();
    test_immediate_ddrum4_echo_is_suppressed();
    test_out_of_order_echo_does_not_block_later_echo();
    std::cout << "firmware bridge core tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "firmware bridge core test failure: " << error.what() << '\n';
    return 1;
  }
}
