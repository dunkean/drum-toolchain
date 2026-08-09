#pragma once
#include "core/Midi.h"
#include <array>
#include <string>
#include <vector>

namespace ddrum4 {
enum class RouteType : uint8_t { NoteMap, Positional, HihatContinuous, HihatDiscrete };
enum class NoteOffPolicy : uint8_t { Forward, Suppress };
enum class UnknownProgramPolicy : uint8_t { IgnoreAndMonitor, Forward, Drop };
struct Route {
  std::string id; RouteType type{RouteType::NoteMap}; uint8_t inputChannel{10}; uint8_t firstNote{}; uint8_t count{1};
  uint8_t destinationNote{}; uint8_t destinationChannel{10}; uint8_t positionCc{16};
  uint8_t inputCc{4}; uint8_t closedCc{0}; uint8_t openCc{127};
  std::array<uint8_t, 8> ccValues{0,18,36,54,73,91,109,127}; NoteOffPolicy noteOff{NoteOffPolicy::Forward};
};
struct Kit { std::string id; std::string label; uint8_t outputChannel{10}; std::vector<Route> routes; };
struct ProgramBinding { uint8_t program{}; size_t kitIndex{}; };
struct Profile {
  std::string name; std::string inputPortMatch{"ddrum4"}; std::string endpoint{"ddrum_converted"}; std::string backend{"auto"};
  uint8_t inputChannel{10}; uint8_t outputChannel{10}; std::vector<Kit> kits; std::vector<ProgramBinding> programs;
  bool programManagerEnabled{true}; uint8_t programSourceChannel{10}; size_t initialKitIndex{}; UnknownProgramPolicy unknownProgram{UnknownProgramPolicy::IgnoreAndMonitor};
  bool forwardProgramChange{false}; bool passRealtime{true}; std::vector<uint8_t> allowedCcs{4};
};
}
