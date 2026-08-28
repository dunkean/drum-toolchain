#include <Arduino.h>
#include <unity.h>
#include "DdrumBridge.h"

uint32_t millis() { return 0; }
void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t, uint8_t) {}
void setUp() {}
void tearDown() {}

static const NoteRoute routes[] = {
    {11, 42, 91, 1, 127, 1, 127}, // ZG H-12 bow -> ddrum HHAT position 2
    {11, 46, 94, 1, 127, 1, 127}, // edge -> position 5
    {11, 44, 90, 1, 127, 1, 127}, // chick -> position 1
    {11, 21, 93, 1, 127, 1, 127}, // splash -> position 4
    {10, 36, 60, 1, 127, 13, 24}, // electronic pad B -> layer velocity window B
    {12, 17, 17, 1, 127, 1, 127}, // Local-OFF DDrum4 CYMB2 diagnostic pad
};
static const uint8_t programChannels[] = {10, 11, 12};
static const PressureRoute pressureRoutes[] = {{12, 17}};

static const BridgeConfig config = [] {
  BridgeConfig result = {
      10, programChannels, sizeof(programChannels) / sizeof(programChannels[0]),
      {11, 4, 4, 0, 127, 0, 127, false},
      routes, sizeof(routes) / sizeof(routes[0]), true,
  };
  result.pressureRoutes = pressureRoutes;
  result.pressureRouteCount = sizeof(pressureRoutes) / sizeof(pressureRoutes[0]);
  return result;
}();

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

void test_disabled_hihat_does_not_claim_cc4() {
  static const BridgeConfig noHihat = {
      10, programChannels, 3, {0, 0, 0, 0, 0, 0, 0, false, false}, routes,
      sizeof(routes) / sizeof(routes[0]), false,
  };
  DdrumBridge bridge(noHihat);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ControlChange, 11, 4, 64}, &output, 1));
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
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOn, 10, 36, 100}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::PolyAftertouch, 10, 36, 47}, &output, 1));
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

void test_logical_controls_update_reserved_channel_state() {
  static const BridgeConfig sceneConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes,
      sizeof(routes) / sizeof(routes[0]), true, nullptr,
      {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, nullptr, 0,
      {0, 1, 2, 3, 9},
  };
  DdrumBridge bridge(sceneConfig);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ProgramChange, 14, 8, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ControlChange, 15, 3, 5}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(8, bridge.logicalState().scene);
  TEST_ASSERT_EQUAL_UINT8(5, bridge.logicalState().vp4);
}

void test_out_of_range_logical_program_is_dropped_without_changing_scene() {
  DdrumBridge bridge(config);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ProgramChange, 15, 1, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, bridge.logicalState().scene);
  TEST_ASSERT_EQUAL_UINT32(1, bridge.ignoredMessages());
}

void test_logical_controls_use_the_generated_cc_addresses() {
  static const BridgeConfig remapped = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes,
      sizeof(routes) / sizeof(routes[0]), false, nullptr,
      {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, nullptr, 0,
      {20, 21, 22, 23},
  };
  DdrumBridge bridge(remapped);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ControlChange, 14, 22, 7}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(7, bridge.logicalState().vp3);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ControlChange, 14, 2, 9}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(7, bridge.logicalState().vp3);
}

void test_native_controls_update_state_without_rendering_a_hit() {
  static const NativeControlRoute nativeControls[] = {
      {12, NativeControlType::ProgramChange, 3, 0, 1},
      {12, NativeControlType::ControlChange, 74, 1, 9},
      {12, NativeControlType::NoteOn, 52, 2, 11},
  };
  static const BridgeConfig nativeConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes,
      sizeof(routes) / sizeof(routes[0]), false, nullptr,
      {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, nullptr, 0,
      {20, 21, 22, 23, 2}, nativeControls, 3,
  };
  DdrumBridge bridge(nativeConfig);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ProgramChange, 12, 3, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(1, bridge.logicalState().scene);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ControlChange, 12, 74, 9}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(9, bridge.logicalState().vp1);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOn, 12, 52, 11}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(11, bridge.logicalState().vp2);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOn, 12, 52, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(11, bridge.logicalState().vp2);
}

void test_unmapped_native_program_cannot_create_an_invalid_scene() {
  static const NativeControlRoute nativeControls[] = {
      {12, NativeControlType::ProgramChange, 0, 0, 0},
  };
  static const BridgeConfig nativeConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes,
      sizeof(routes) / sizeof(routes[0]), false, nullptr,
      {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, nullptr, 0,
      {20, 21, 22, 23}, nativeControls, 1,
  };
  DdrumBridge bridge(nativeConfig);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ProgramChange, 12, 100, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, bridge.logicalState().scene);
}

void test_state_actions_respect_virtual_palette_predicates_and_native_changes_do_not_echo() {
  static const DdrumStateAction actions[] = {
      {0, 7, 255, 255, 255, {MidiEventType::ProgramChange, 12, 9, 0}},
  };
  static const NativeControlRoute nativeControls[] = {
      {12, NativeControlType::ProgramChange, 1, 0, 0},
  };
  static const BridgeConfig stateConfig = {
      12, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes,
      sizeof(routes) / sizeof(routes[0]), false, nullptr,
      {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0}, nullptr, 0,
      {20, 255, 255, 255}, nativeControls, 1, actions, 1,
  };
  DdrumBridge bridge(stateConfig);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::ControlChange, 15, 20, 7}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(9, output.data1);
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::ProgramChange, 12, 1, 0}, &output, 1));
  TEST_ASSERT_EQUAL_UINT8(0, bridge.logicalState().scene);
}

void test_route_emits_bounded_note_and_cc() {
  static const RouteOutput sideEffects[] = {
      {{MidiEventType::ControlChange, 0, 74, 0}, true},
  };
  static const NoteRoute multiRoutes[] = {
      {11, 42, 91, 1, 127, 1, 127, sideEffects, 1},
  };
  static const BridgeConfig multiConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, multiRoutes, 1,
      false, nullptr, {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(multiConfig);
  MidiEvent output[DdrumBridge::MAX_OUTPUT_EVENTS];
  TEST_ASSERT_EQUAL_UINT8(2, bridge.process({MidiEventType::NoteOn, 11, 42, 73}, output,
                                             DdrumBridge::MAX_OUTPUT_EVENTS));
  TEST_ASSERT_EQUAL(MidiEventType::NoteOn, output[0].type);
  TEST_ASSERT_EQUAL(MidiEventType::ControlChange, output[1].type);
  TEST_ASSERT_EQUAL_UINT8(74, output[1].data1);
  TEST_ASSERT_EQUAL_UINT8(73, output[1].data2);
}

void test_guard_drops_only_emitted_future_echo() {
  static const BridgeConfig guarded = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false}, routes,
      sizeof(routes) / sizeof(routes[0]), true, nullptr, {EchoGuardMode::DualDdrum, 10, 10}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(guarded);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process({MidiEventType::NoteOn, 10, 91, 100}, &output, 1, 100));
  TEST_ASSERT_EQUAL_UINT32(0, bridge.expectedEchoes());
  TEST_ASSERT_EQUAL_UINT8(1, bridge.process({MidiEventType::NoteOn, 11, 42, 100}, &output, 1, 100));
  TEST_ASSERT_EQUAL_UINT8(0, bridge.process(output, &output, 1, 105));
  TEST_ASSERT_EQUAL_UINT32(1, bridge.expectedEchoes());
}

void test_invalid_note_cannot_cross_an_index_row() {
  static const NoteRoute indexedRoutes[] = {
      {2, 0, 64, 1, 127, 1, 127},
  };
  int16_t routeIndex[16 * 128];
  for (size_t i = 0; i < 16U * 128U; ++i) routeIndex[i] = -1;
  // Row 1/note 0 is exactly where row 0/note 128 would land without the
  // public-input bounds check.
  routeIndex[128] = 0;
  const BridgeConfig indexedConfig = {
      10, programChannels, 3, {11, 4, 4, 0, 127, 0, 127, false},
      indexedRoutes, 1, false, routeIndex,
      {EchoGuardMode::Disabled, 0, 0}, {0, 0, 0, 0, 0},
  };
  DdrumBridge bridge(indexedConfig);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT8(
      0, bridge.process({MidiEventType::NoteOn, 1, 128, 100}, &output, 1));
  TEST_ASSERT_EQUAL_UINT32(1, bridge.ignoredMessages());
}

void test_zero_width_hihat_input_range_rejects_configuration() {
  const BridgeConfig invalidConfig = {
      10, programChannels, 3, {11, 4, 4, 64, 64, 0, 127, false},
      routes, sizeof(routes) / sizeof(routes[0]), true,
  };
  DdrumBridge bridge(invalidConfig);
  MidiEvent output;
  TEST_ASSERT_EQUAL_UINT32(1, bridge.invalidConfigurations());
  TEST_ASSERT_EQUAL_UINT8(
      0, bridge.process({MidiEventType::ControlChange, 11, 4, 64}, &output, 1));
}

void test_zero_output_capacity_is_counted_without_writing() {
  DdrumBridge bridge(config);
  MidiEvent output = {MidiEventType::ProgramChange, 16, 127, 127};
  TEST_ASSERT_EQUAL_UINT8(
      0, bridge.process({MidiEventType::NoteOn, 11, 42, 100}, &output, 0));
  TEST_ASSERT_EQUAL_UINT32(1, bridge.outputOverflows());
  TEST_ASSERT_EQUAL(MidiEventType::ProgramChange, output.type);
  TEST_ASSERT_EQUAL_UINT8(16, output.channel);
  TEST_ASSERT_EQUAL_UINT8(127, output.data1);
  TEST_ASSERT_EQUAL_UINT8(127, output.data2);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_zeitgeist_bow_maps_to_hihat_position_2);
  RUN_TEST(test_hihat_direct_cc4_is_scaled_without_arduino_filtering);
  RUN_TEST(test_disabled_hihat_does_not_claim_cc4);
  RUN_TEST(test_unmapped_events_are_not_blindly_forwarded);
  RUN_TEST(test_pad_can_select_a_velocity_window_inside_one_sound);
  RUN_TEST(test_declared_third_source_can_change_kit);
  RUN_TEST(test_pc_clean_silent_mode_never_emits);
  RUN_TEST(test_bypass_returns_raw_event);
  RUN_TEST(test_ddrum_one_shot_policy_drops_note_off_but_keeps_aftertouch);
  RUN_TEST(test_bypass_preserves_release_wire_semantics);
  RUN_TEST(test_logical_controls_update_reserved_channel_state);
  RUN_TEST(test_out_of_range_logical_program_is_dropped_without_changing_scene);
  RUN_TEST(test_logical_controls_use_the_generated_cc_addresses);
  RUN_TEST(test_native_controls_update_state_without_rendering_a_hit);
  RUN_TEST(test_unmapped_native_program_cannot_create_an_invalid_scene);
  RUN_TEST(test_state_actions_respect_virtual_palette_predicates_and_native_changes_do_not_echo);
  RUN_TEST(test_route_emits_bounded_note_and_cc);
  RUN_TEST(test_guard_drops_only_emitted_future_echo);
  RUN_TEST(test_invalid_note_cannot_cross_an_index_row);
  RUN_TEST(test_zero_width_hihat_input_range_rejects_configuration);
  RUN_TEST(test_zero_output_capacity_is_counted_without_writing);
  return UNITY_END();
}
