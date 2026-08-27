// Safe checked-in fallback. It deliberately contains no playable routes.
// A live, verified rig-project is required before this file may be replaced by
// generate_mapping.py --project-mapping. Never flash a SIM_* profile.
#pragma once
#include "DdrumBridge.h"

constexpr uint8_t DDRUM_OUTPUT_CHANNEL = 12;
constexpr const uint8_t* RELAY_PROGRAM_CHANNELS = nullptr;
constexpr size_t RELAY_PROGRAM_CHANNEL_COUNT = 0;
constexpr const NoteRoute* NOTE_ROUTES = nullptr;
constexpr size_t NOTE_ROUTE_COUNT = 0;
constexpr const StateRoute* STATE_ROUTES = nullptr;
constexpr size_t STATE_ROUTE_COUNT = 0;
constexpr const NativeControlRoute* NATIVE_CONTROLS = nullptr;
constexpr size_t NATIVE_CONTROL_COUNT = 0;
constexpr const DdrumStateAction* STATE_ACTIONS = nullptr;
constexpr size_t STATE_ACTION_COUNT = 0;
constexpr LogicalControlConfig LOGICAL_CONTROLS = {255, 255, 255, 255, 1};
constexpr LogicalState INITIAL_LOGICAL_STATE = {0, 0, 0, 0, 0};
constexpr HihatDirectCc4Config HIHAT_CC4 = {0, 0, 0, 0, 0, 0, 0, false, false};
constexpr bool HIHAT_NOTE_P_SUPPORTED = false;
constexpr bool HIHAT_THREE_ZONE_SUPPORTED = false;
