#pragma once
#include "core/Profile.h"
#include "core/RigRuntime.h"
#include <filesystem>
namespace ddrum4 {
Profile loadProfile(const std::filesystem::path& path); void validateProfile(const Profile& profile);
// Loads the offline artifact emitted by rig-compiler.  Planned/unresolved
// artifacts are intentionally rejected before any MIDI transport is involved.
RuntimeProfile loadRuntimeProfile(const std::filesystem::path& path,
                                  RuntimeRendererTarget target = RuntimeRendererTarget::Sd3);
void validateRuntimeProfile(const RuntimeProfile& profile);
}
