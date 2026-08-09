#include "config/ProfileLoader.h"
#include <yaml-cpp/yaml.h>
#include <algorithm>
#include <set>
#include <stdexcept>

namespace ddrum4 {
namespace {
[[noreturn]] void invalid(const std::string& message) { throw std::runtime_error("Invalid profile: " + message); }
uint8_t midiValue(const YAML::Node& n, const char* label = "MIDI value") { const int v=n.as<int>(); if(v<0||v>127) invalid(std::string(label)+" must be 0..127"); return static_cast<uint8_t>(v); }
uint8_t midi(const YAML::Node& n, const char* key, uint8_t fallback=0) { return n[key] ? midiValue(n[key], key) : fallback; }
uint8_t channel(const YAML::Node& n, const char* key, uint8_t fallback) { const int v=n[key] ? n[key].as<int>() : fallback; if(v<1||v>16) invalid(std::string(key)+" must be 1..16"); return static_cast<uint8_t>(v); }
RouteType routeType(const YAML::Node& t) {
  const auto kind=t["type"].as<std::string>();
  if(kind=="note_map") return RouteType::NoteMap;
  if(kind=="positional_note_to_cc") return RouteType::Positional;
  if(kind=="hihat_continuous") return RouteType::HihatContinuous;
  if(kind=="hihat_discrete") return RouteType::HihatDiscrete;
  invalid("unsupported transform type: "+kind);
}
NoteOffPolicy noteOff(const YAML::Node& t, NoteOffPolicy fallback=NoteOffPolicy::Forward) {
  if(!t["note_off"]) return fallback; const auto value=t["note_off"].as<std::string>();
  if(value=="forward") return NoteOffPolicy::Forward;
  if(value=="suppress") return NoteOffPolicy::Suppress;
  invalid("note_off must be forward or suppress");
}
void applyMatch(Route& r, const YAML::Node& m) {
  if(m["type"] && m["type"].as<std::string>() != "note" && m["type"].as<std::string>() != "note_range") invalid("match.type must be note or note_range");
  r.inputChannel=channel(m,"channel",r.inputChannel);
  if(m["first_note"]) r.firstNote=midi(m,"first_note"); else if(m["note"]) r.firstNote=midi(m,"note");
  if(m["count"]) r.count=midi(m,"count");
}
void applyTransform(Route& r, const YAML::Node& t, bool base) {
  if(t["type"]) r.type=routeType(t);
  if(t["destination_channel"]) r.destinationChannel=channel(t,"destination_channel",r.destinationChannel);
  if(t["destination_note"]) r.destinationNote=midi(t,"destination_note");
  if(t["position_cc"]) r.positionCc=midi(t,"position_cc");
  if(t["output_cc"]) r.positionCc=midi(t,"output_cc");
  if(t["input_cc"]) r.inputCc=midi(t,"input_cc");
  if(t["closed_value"]) r.closedCc=midi(t,"closed_value");
  if(t["open_value"]) r.openCc=midi(t,"open_value");
  r.noteOff=noteOff(t,r.noteOff);
  if(t["cc_values"]) { const auto values=t["cc_values"]; if(!values.IsSequence()) invalid("cc_values must be a sequence"); if(values.size()>r.ccValues.size()) invalid("cc_values supports at most 8 positions"); for(size_t i=0;i<values.size();++i) r.ccValues[i]=midiValue(values[i]); }
  if(base && !t["destination_note"]) invalid("route transform.destination_note is required");
}
Route parseRoute(const YAML::Node& n,uint8_t input,uint8_t output) {
  if(!n["id"]||!n["match"]||!n["transform"]) invalid("each route needs id, match and transform");
  Route r; r.id=n["id"].as<std::string>(); if(r.id.empty()) invalid("route id may not be empty"); r.inputChannel=input; r.destinationChannel=output;
  applyMatch(r,n["match"]); applyTransform(r,n["transform"],true); return r;
}
void validateRoute(const Route& r, const std::string& kit) {
  if(r.count==0 || r.count>8 || static_cast<unsigned>(r.firstNote)+r.count>128) invalid("invalid note range in kit "+kit);
  if(r.type==RouteType::Positional || r.type==RouteType::HihatDiscrete) { if(r.count!=1&&r.count!=2&&r.count!=4&&r.count!=8) invalid("positional/discrete hi-hat count must be 1, 2, 4 or 8"); for(uint8_t i=1;i<r.count;++i) if(r.ccValues[i]<r.ccValues[i-1]) invalid("cc_values must be monotonic"); }
}
}

Profile loadProfile(const std::filesystem::path& path) {
  const auto root=YAML::LoadFile(path.string());
  if(!root.IsMap() || !root["schema_version"] || root["schema_version"].as<int>()!=1) invalid("schema_version: 1 is required");
  if(!root["profile"]||!root["input"]||!root["output"]||!root["routes"]||!root["virtual_kits"]) invalid("profile, input, output, routes and virtual_kits are required");
  Profile p; p.name=root["profile"].as<std::string>(); const auto in=root["input"],out=root["output"];
  p.inputPortMatch=in["port_match"] ? in["port_match"].as<std::string>() : ""; p.inputChannel=channel(in,"channel",10);
  p.endpoint=out["endpoint"] ? out["endpoint"].as<std::string>() : "ddrum_converted"; p.backend=out["backend"] ? out["backend"].as<std::string>() : "auto"; p.outputChannel=channel(out,"channel",10);
  std::vector<Route> base; for(const auto& node:root["routes"]) base.push_back(parseRoute(node,p.inputChannel,p.outputChannel));
  for(const auto& node:root["virtual_kits"]) {
    Kit kit; kit.id=node["id"].as<std::string>(); kit.label=node["label"]?node["label"].as<std::string>():kit.id; kit.outputChannel=p.outputChannel; kit.routes=base;
    if(node["output_override"]&&node["output_override"]["channel"]) { kit.outputChannel=channel(node["output_override"],"channel",p.outputChannel); for(auto& route:kit.routes) route.destinationChannel=kit.outputChannel; }
    if(node["route_overrides"]) for(const auto& overrideNode:node["route_overrides"]) { const auto id=overrideNode["route"].as<std::string>(); auto it=std::find_if(kit.routes.begin(),kit.routes.end(),[&](const Route& r){return r.id==id;}); if(it==kit.routes.end()) invalid("unknown route override: "+id); if(overrideNode["match"]) applyMatch(*it,overrideNode["match"]); if(overrideNode["transform"]) applyTransform(*it,overrideNode["transform"],false); }
    p.kits.push_back(std::move(kit));
  }
  if(const auto pm=root["program_manager"]) { p.programManagerEnabled=pm["enabled"] ? pm["enabled"].as<bool>() : true; if(pm["source"]) p.programSourceChannel=channel(pm["source"],"channel",p.inputChannel); p.forwardProgramChange=pm["forward_program_change"]?pm["forward_program_change"].as<bool>():false; if(pm["unknown_program"]) { const auto policy=pm["unknown_program"].as<std::string>(); if(policy=="ignore_and_monitor") p.unknownProgram=UnknownProgramPolicy::IgnoreAndMonitor; else if(policy=="forward") p.unknownProgram=UnknownProgramPolicy::Forward; else if(policy=="drop") p.unknownProgram=UnknownProgramPolicy::Drop; else invalid("unknown_program must be ignore_and_monitor, forward or drop"); }
    if(pm["initial_kit"]) { const auto id=pm["initial_kit"].as<std::string>(); auto it=std::find_if(p.kits.begin(),p.kits.end(),[&](const Kit& k){return k.id==id;}); if(it==p.kits.end()) invalid("unknown initial_kit: "+id); p.initialKitIndex=static_cast<size_t>(it-p.kits.begin()); }
    if(pm["bindings"]) for(const auto& b:pm["bindings"]) { const auto id=b["kit"].as<std::string>(); auto it=std::find_if(p.kits.begin(),p.kits.end(),[&](const Kit& k){return k.id==id;}); if(it==p.kits.end()) invalid("unknown program kit: "+id); p.programs.push_back({midi(b,"program"),static_cast<size_t>(it-p.kits.begin())}); }
  }
  if(const auto policies=root["policies"]) { if(policies["realtime"]) { const auto value=policies["realtime"].as<std::string>(); if(value=="pass") p.passRealtime=true; else if(value=="drop") p.passRealtime=false; else invalid("policies.realtime must be pass or drop"); } if(policies["cc"]&&policies["cc"]["allow"]) { p.allowedCcs.clear(); for(const auto& cc:policies["cc"]["allow"]) p.allowedCcs.push_back(midiValue(cc)); } }
  validateProfile(p); return p;
}
void validateProfile(const Profile& p) {
  if(p.name.empty()||p.kits.empty()) invalid("profile needs a name and at least one virtual kit"); if(p.initialKitIndex>=p.kits.size()) invalid("initial kit index is invalid");
  std::set<std::string> kitIds; std::set<uint8_t> programs;
  for(const auto& b:p.programs) { if(b.kitIndex>=p.kits.size()) invalid("program has invalid kit"); if(!programs.insert(b.program).second) invalid("duplicate program binding"); }
  for(const auto& kit:p.kits) { if(kit.id.empty()||!kitIds.insert(kit.id).second) invalid("virtual kit ids must be unique"); std::set<std::string> ids; std::set<std::pair<uint8_t,uint8_t>> notes; std::set<std::pair<uint8_t,uint8_t>> positionCcs; for(const auto& r:kit.routes) { if(!ids.insert(r.id).second) invalid("route ids must be unique in kit "+kit.id); validateRoute(r,kit.id); if(r.type==RouteType::Positional&&!positionCcs.insert({r.destinationChannel,r.positionCc}).second) invalid("two positional routes share a position CC in kit "+kit.id); for(uint8_t n=0;n<r.count;++n) if(!notes.insert({r.inputChannel,static_cast<uint8_t>(r.firstNote+n)}).second) invalid("ambiguous route in kit "+kit.id); } }
}
}
