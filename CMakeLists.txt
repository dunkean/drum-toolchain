cmake_minimum_required(VERSION 3.22)
project(drum_toolchain LANGUAGES C CXX)

option(DRUM_TOOLCHAIN_BUILD_MODERNIZER "Build the ddrum4 MIDI modernizer" ON)

if(DRUM_TOOLCHAIN_BUILD_MODERNIZER)
  add_subdirectory(apps/ddrum4-modernizer)
endif()
