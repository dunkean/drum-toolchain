#include <Arduino.h>
#include <unity.h>

#include <vector>

#include "MidiDinAdapter.h"

uint32_t millis() { return 0; }
void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t, uint8_t) {}
void setUp() {}
void tearDown() {}

namespace {

class FakeMidiStream : public HardwareSerial {
 public:
  void feed(std::initializer_list<uint8_t> bytes) {
    input.insert(input.end(), bytes.begin(), bytes.end());
  }

  int available() override { return static_cast<int>(input.size() - readIndex); }
  int read() override { return input[readIndex++]; }
  int availableForWrite() override { return writeCapacity; }
  size_t write(uint8_t byte) override {
    output.push_back(byte);
    return 1;
  }

  std::vector<uint8_t> input;
  std::vector<uint8_t> output;
  size_t readIndex = 0;
  int writeCapacity = 64;
};

const NoteRoute routes[] = {
    {11, 42, 91, 1, 127, 1, 127},
};
const uint8_t programChannels[] = {11};
const BridgeConfig config = {
    10, programChannels, 1,
    {11, 4, 4, 0, 127, 0, 127, false},
    routes, 1, true,
};

void assertOutput(const FakeMidiStream& stream, std::initializer_list<uint8_t> expected) {
  TEST_ASSERT_EQUAL_UINT32(expected.size(), stream.output.size());
  size_t index = 0;
  for (uint8_t byte : expected) TEST_ASSERT_EQUAL_UINT8(byte, stream.output[index++]);
}

void test_sysex_interleaved_cannot_complete_stale_note_or_create_false_hit() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});

  // The old parser treated 100 after F7 as data2 for the stale 0x9A/42.
  stream.feed({0x9A, 42, 0xF0, 0x7D, 0x01, 0xF8, 0x55, 0xF7, 100});
  adapter.poll();

  assertOutput(stream, {});
}

void test_running_status_requires_new_channel_status_after_sysex() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});

  stream.feed({0x9A, 42, 0xF0, 0x01, 0xF7, 100, 0x9A, 42, 100, 42, 101});
  adapter.poll();

  // Explicit status starts the first hit; channel running status then remains
  // valid for the second hit in the same channel-message stream.
  assertOutput(stream, {0x99, 91, 100, 0x99, 91, 101});
}

void test_system_common_cancels_running_status_but_channel_routes_remain_valid() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});

  // F1 plus its data must not finish the partial Note On. A later CC4 and PC
  // prove that normal channel messages remain available after System Common.
  stream.feed({0x9A, 42, 0xF1, 0x7F, 100, 0xBA, 4, 64, 0xCA, 7});
  adapter.poll();

  assertOutput(stream, {0xB9, 4, 64, 0xC9, 7});
}

void test_realtime_interleaving_preserves_channel_running_status() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});

  stream.feed({0x9A, 42, 100, 0xF8, 42, 101});
  adapter.poll();

  assertOutput(stream, {0x99, 91, 100, 0x99, 91, 101});
}

void test_channel_status_recovers_from_unterminated_sysex_without_stale_data() {
  FakeMidiStream stream;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});

  // A channel status is an unambiguous recovery point after malformed input.
  // Neither the payload byte nor the old partial message may become a hit.
  stream.feed({0x9A, 42, 0xF0, 0x7D, 0x01, 0x9A, 42, 102});
  adapter.poll();

  assertOutput(stream, {0x99, 91, 102});
}

void test_uart_overflow_drops_a_whole_message_and_is_counted() {
  FakeMidiStream stream;
  stream.writeCapacity = 2;
  DdrumBridge bridge(config);
  MidiDinAdapter adapter(stream, bridge, {0, 0});

  stream.feed({0x9A, 42, 100});
  adapter.poll();

  assertOutput(stream, {});
  TEST_ASSERT_EQUAL_UINT32(1, adapter.uartOverflows());
}

}  // namespace

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_sysex_interleaved_cannot_complete_stale_note_or_create_false_hit);
  RUN_TEST(test_running_status_requires_new_channel_status_after_sysex);
  RUN_TEST(test_system_common_cancels_running_status_but_channel_routes_remain_valid);
  RUN_TEST(test_realtime_interleaving_preserves_channel_running_status);
  RUN_TEST(test_channel_status_recovers_from_unterminated_sysex_without_stale_data);
  RUN_TEST(test_uart_overflow_drops_a_whole_message_and_is_counted);
  return UNITY_END();
}
