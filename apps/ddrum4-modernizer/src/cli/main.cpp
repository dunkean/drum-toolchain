#include "config/ProfileLoader.h"
#include "core/Converter.h"
#include <array>
#include <chrono>
#include <iostream>

using namespace ddrum4;
int main(int argc, char** argv) {
  if (argc < 3) { std::cerr << "Usage: ddrum4ctl <validate|programs|list|benchmark> <profile.yaml>\n"; return 2; }
  try {
    const auto profile = loadProfile(argv[2]);
    if (std::string_view(argv[1]) == "validate") { std::cout << "OK " << profile.name << " — " << profile.kits.size() << " virtual kits\n"; return 0; }
    if (std::string_view(argv[1]) == "programs") { for (const auto& b : profile.programs) std::cout << "PC " << int(b.program) << " -> " << profile.kits[b.kitIndex].label << "\n"; return 0; }
    if (std::string_view(argv[1]) == "list") { std::cout << "Input match: " << profile.inputPortMatch << "\nOutput endpoint: " << profile.endpoint << " (" << profile.backend << ")\n"; for (const auto& kit : profile.kits) std::cout << kit.id << "\t" << kit.label << "\tch " << int(kit.outputChannel) << "\n"; return 0; }
    if (std::string_view(argv[1]) == "benchmark") { Converter converter{profile}; std::array<MidiEvent,Converter::maxOutputEvents> out{}; constexpr int iterations=1'000'000; const auto start=std::chrono::steady_clock::now(); size_t events=0; for(int i=0;i<iterations;++i) events+=converter.process({MidiType::NoteOn,profile.inputChannel,40,100,static_cast<uint64_t>(i)},out); const auto elapsed=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count(); std::cout << iterations << " Note On, " << events << " MIDI OUT, " << elapsed/iterations << " us/event\n"; return 0; }
    std::cerr << "Unknown command\n"; return 2;
  } catch (const std::exception& error) { std::cerr << "Profile error: " << error.what() << "\n"; return 1; }
}
