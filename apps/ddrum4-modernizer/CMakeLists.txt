cmake_minimum_required(VERSION 3.22)
project(ddrum4_converter VERSION 0.1.0 LANGUAGES C CXX)

option(DDRUM4_BUILD_APP "Build the JUCE desktop application" ON)
option(DDRUM4_BUILD_TESTS "Build unit tests" ON)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
FetchContent_Declare(yaml-cpp GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git GIT_TAG 0.8.0 GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(yaml-cpp)

add_library(ddrum4_core
  src/core/Converter.cpp
  src/config/ProfileLoader.cpp
)
target_include_directories(ddrum4_core PUBLIC src)
target_link_libraries(ddrum4_core PUBLIC yaml-cpp::yaml-cpp)
target_compile_features(ddrum4_core PUBLIC cxx_std_23)

add_executable(ddrum4ctl src/cli/main.cpp)
target_link_libraries(ddrum4ctl PRIVATE ddrum4_core)

if(DDRUM4_BUILD_APP)
  FetchContent_Declare(JUCE GIT_REPOSITORY https://github.com/juce-framework/JUCE.git GIT_TAG 8.0.12 GIT_SHALLOW TRUE)
  FetchContent_MakeAvailable(JUCE)
  juce_add_gui_app(ddrum4_converter PRODUCT_NAME "ddrum4 Converter")
  target_sources(ddrum4_converter PRIVATE src/app/Main.cpp)
  target_link_libraries(ddrum4_converter PRIVATE ddrum4_core juce::juce_gui_extra juce::juce_audio_devices)
  target_compile_definitions(ddrum4_converter PRIVATE
    JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_APPLICATION_NAME_STRING="$<TARGET_PROPERTY:ddrum4_converter,JUCE_PRODUCT_NAME>"
    JUCE_APPLICATION_VERSION_STRING="${PROJECT_VERSION}")
  add_custom_command(TARGET ddrum4_converter POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_SOURCE_DIR}/config $<TARGET_FILE_DIR:ddrum4_converter>/config)
endif()

if(DDRUM4_BUILD_TESTS)
  enable_testing()
  add_executable(ddrum4_core_tests tests/ConverterTests.cpp)
  target_link_libraries(ddrum4_core_tests PRIVATE ddrum4_core)
  add_test(NAME ddrum4_core_tests COMMAND ddrum4_core_tests)
endif()
