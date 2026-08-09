#include <unity.h>
#include "DdrumBridge.h"

static const NoteRoute routes[] = {
    {11, 42, 91, 1, 127, 1, 127}, // ZG H-12 bow -> ddrum HHAT position 2
    {11, 46, 94, 1, 127, 1, 127}, // edge -> position 5
    {11, 44, 90, 1, 127, 1, 127}, // chick -> position 1
    {11, 21, 93, 1, 127, 1, 127}, // splash -> position 4
    {10, 36, 60, 1, 127, 13, 24}, // electronic pad B -> layer velocity window B
};

static const BridgeConfig config = {
    10, 10, 11,
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
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOff, 11, 42, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(91, output.data1);
}

void test_hihat_direct_cc4_is_scaled_and_duplicate_is_dropped() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::ControlChange, 11, 4, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, output.data2);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ControlChange, 11, 4, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(1, bridge.duplicateCcMessages());
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
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOff, 10, 36, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, output.data2);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_zeitgeist_bow_maps_to_hihat_position_2);
  RUN_TEST(test_hihat_direct_cc4_is_scaled_and_duplicate_is_dropped);
  RUN_TEST(test_unmapped_events_are_not_blindly_forwarded);
  RUN_TEST(test_pad_can_select_a_velocity_window_inside_one_sound);
  return UNITY_END();
}
