#pragma once
#include "core/Profile.h"
#include <filesystem>
namespace ddrum4 { Profile loadProfile(const std::filesystem::path& path); void validateProfile(const Profile& profile); }
