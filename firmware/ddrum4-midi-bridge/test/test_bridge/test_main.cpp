#include <unity.h>
#include "DdrumBridge.h"

static const NoteRoute routes[] = {
    {11, 42, 91, 1, 127, 1, 127}, // ZG H-12 bow -> ddrum HHAT position 2
    {11, 46, 94, 1, 127, 1, 127}, // edge -> position 5
    {11, 44, 90, 1, 127, 1, 127}, // chick -> position 1
    {11, 21, 93, 1, 127, 1, 127}, // splash -> position 4
    {10, 36, 60, 1, 127, 13, 24}, // electronic pad B -> layer velocity window B
    {12, 17, 17, 1, 127, 1, 127}, // Local-OFF DDrum4 CYMB2 diagnostic pad
};
static const uint8_t programChannels[] = {10, 11, 12};

static const BridgeConfig config = {
    10, programChannels, sizeof(programChannels) / sizeof(programChannels[0]),
    {11, 4, 4, 0, 127, 0, 127, false},
    routes, sizeof(routes) / sizeof(routes[0]), true,
};

void test_zeitgeist_bow_maps_to_hihat_position_2() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOn, 11, 42, 99}, &output, 1));
  TEST_ASSERT_EQUAL(MidiEventType::NoteOn, output.type);
  TEST_ASSERT_EQUAL_UINT8(10, output.channel);
  TEST_ASSERT_EQUAL_UINT8(91, output.data1);
  TEST_ASSERT_EQUAL_UINT8(99, output.data2);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOff, 11, 42, 0}, &output, 1));
}

void test_hihat_direct_cc4_is_scaled_without_arduino_filtering() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::ControlChange, 11, 4, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, output.data2);
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::ControlChange, 11, 4, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::ControlChange, 11, 4, 127}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(127, output.data2);
}

void test_unmapped_events_are_not_blindly_forwarded() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOn, 10, 38, 127}, &output, 1));
  TEST_ASSERT_EQUAL_UINT32(1, bridge.ignoredMessages());
}

void test_pad_can_select_a_velocity_window_inside_one_sound() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOn, 10, 36, 64}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(60, output.data1);
  TEST_ASSERT_EQUAL_UINT8(19, output.data2); // midpoint of 13..24
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOff, 10, 36, 0}, &output, 1));
}

void test_declared_third_source_can_change_kit() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::ProgramChange, 12, 7, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(10, output.channel);
  TEST_ASSERT_EQUAL_UINT8(7, output.data1);
}

void test_pc_clean_silent_mode_never_emits() {
  DdrumBridge bridge(config);
  MidiEvent output;
  bridge.setMode(BridgeMode::Silent);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOn, 12, 17, 93}, &output, 1));
  TEST_ASSERT_EQUAL(BridgeMode::Silent, bridge.mode());
}

void test_bypass_returns_raw_event() {
  DdrumBridge bridge(config);
  MidiEvent output;
  const MidiEvent hit = {MidiEventType::PolyAftertouch, 12, 17, 47};
  bridge.setMode(BridgeMode::Bypass);
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process(hit, &output, 1));
  TEST_ASSERT_EQUAL(MidiEventType::PolyAftertouch, output.type);
  TEST_ASSERT_EQUAL_UINT8(12, output.channel);
  TEST_ASSERT_EQUAL_UINT8(17, output.data1);
  TEST_ASSERT_EQUAL_UINT8(47, output.data2);
}

void test_ddrum_one_shot_policy_drops_note_off_but_keeps_aftertouch() {
  DdrumBridge bridge(config);
  MidiEvent output;

  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOn, 12, 17, 127}, &output, 1));
  TEST_ASSERT_EQUAL(MidiEventType::NoteOn, output.type);
  TEST_ASSERT_EQUAL_UINT8(17, output.data1);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOff, 12, 17, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::PolyAftertouch, 12, 17, 47}, &output, 1));
  TEST_ASSERT_EQUAL(MidiEventType::PolyAftertouch, output.type);
  TEST_ASSERT_EQUAL_UINT8(47, output.data2);
}

void test_bypass_preserves_release_wire_semantics() {
  DdrumBridge bridge(config);
  MidiEvent output;
  bridge.setMode(BridgeMode::Bypass);

  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOn, 12, 17, 0}, &output, 1));
  TEST_ASSERT_EQUAL(MidiEventType::NoteOn, output.type);
  TEST_ASSERT_EQUAL_UINT8(12, output.channel);
  TEST_ASSERT_EQUAL_UINT8(17, output.data1);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_zeitgeist_bow_maps_to_hihat_position_2);
  RUN_TEST(test_hihat_direct_cc4_is_scaled_without_arduino_filtering);
  RUN_TEST(test_unmapped_events_are_not_blindly_forwarded);
  RUN_TEST(test_pad_can_select_a_velocity_window_inside_one_sound);
  RUN_TEST(test_declared_third_source_can_change_kit);
  RUN_TEST(test_pc_clean_silent_mode_never_emits);
  RUN_TEST(test_bypass_returns_raw_event);
  RUN_TEST(test_ddrum_one_shot_policy_drops_note_off_but_keeps_aftertouch);
  RUN_TEST(test_bypass_preserves_release_wire_semantics);
  return UNITY_END();
}
