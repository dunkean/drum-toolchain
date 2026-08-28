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

namespace {
uint16_t runtimeSource(RuntimeProfile& profile, const YAML::Node& source) {
  const auto id=source["id"].as<std::string>();
  const auto endpoint=source["endpoint"] ? source["endpoint"].as<std::string>() : id; const auto sourceChannel=channel(source,"channel",1);
  const auto primary=source["primary"] && source["primary"].as<std::string>()=="usb"; const auto profileId=source["connection_profile"] ? source["connection_profile"].as<std::string>() : "";
  for(size_t i=0;i<profile.sources.size();++i) if(profile.sources[i].id==id) { const auto& existing=profile.sources[i]; if(existing.endpoint!=endpoint||existing.channel!=sourceChannel||existing.primary!=primary||existing.connectionProfile!=profileId) invalid("runtime source "+id+" is inconsistent across records"); return static_cast<uint16_t>(i); }
  RuntimeSource value; value.id=id; value.endpoint=endpoint; value.connectionProfile=profileId; value.channel=sourceChannel; value.primary=primary;
  if(source["deduplicate_din_copies"]) value.deduplicateDinCopies=source["deduplicate_din_copies"].as<bool>();
  if(!profileId.empty() && profileId.find("DUAL")!=std::string::npos) value.connection=RuntimeConnection::Dual;
  profile.sources.push_back(std::move(value)); return static_cast<uint16_t>(profile.sources.size()-1);
}
PhysicalMatcher runtimeMatcher(const std::string& value) {
  if(value=="note") return PhysicalMatcher::Note; if(value=="note_range") return PhysicalMatcher::NoteRange;
  if(value=="cc") return PhysicalMatcher::ControlChange; if(value=="poly_aftertouch") return PhysicalMatcher::PolyAftertouch;
  invalid("unsupported runtime matcher: "+value);
}
uint16_t sceneIndex(RuntimeProfile& profile, const std::string& scene) {
  auto it=std::find(profile.scenes.begin(),profile.scenes.end(),scene);
  if(it==profile.scenes.end()) { profile.scenes.push_back(scene); return static_cast<uint16_t>(profile.scenes.size()-1); }
  return static_cast<uint16_t>(it-profile.scenes.begin());
}
const char* runtimeRendererName(RuntimeRendererTarget target) {
  return target==RuntimeRendererTarget::DrumGizmo ? "drumgizmo" : "sd3";
}
NativeControlType runtimeNativeControlType(const std::string& value) {
  if(value=="program_change") return NativeControlType::ProgramChange;
  if(value=="cc") return NativeControlType::ControlChange;
  if(value=="note") return NativeControlType::NoteOn;
  invalid("unsupported native control type: "+value);
}
}

RuntimeProfile loadRuntimeProfile(const std::filesystem::path& path, RuntimeRendererTarget target) {
  const auto root=YAML::LoadFile(path.string());
  if(!root.IsMap() || !root["format"] || root["format"].as<std::string>()!="rig-runtime-profile/v1") invalid("format rig-runtime-profile/v1 is required");
  const auto rendererName=runtimeRendererName(target);
  const auto status=root["status"] ? root["status"].as<std::string>() : "planned";
  if(root["target_status"] && root["target_status"][rendererName]) {
    if(root["target_status"][rendererName].as<std::string>()!="ready")
      invalid("runtime profile is unresolved/planned for the selected renderer");
  } else if(status!="ready") {
    invalid("runtime profile is unresolved/planned");
  }
  const auto records=root["records"] ? root["records"] : root["routes"];
  if(!records || !records.IsSequence() || records.size()==0) invalid("runtime profile needs records");
  RuntimeProfile result; result.rendererTarget=target;
  if(root["source_sha256"]) result.sourceSha256=root["source_sha256"].as<std::string>();
  if(root["control_bus"] && !root["control_bus"].IsNull()) {
    const auto bus=root["control_bus"];
    if(!bus.IsMap() || !bus["endpoint"] || !bus["channel"] || !bus["status"])
      invalid("runtime control_bus is incomplete");
    result.controlBusEndpoint=bus["endpoint"].as<std::string>();
    result.controlBusChannel=channel(bus,"channel",15);
    if(result.controlBusChannel!=14 && result.controlBusChannel!=15)
      invalid("runtime control_bus must use channel 14 or 15");
    const auto status=bus["status"].as<std::string>();
    const auto live=root["deployment"] && root["deployment"].as<std::string>()=="live";
    const auto hardwareIo=root["hardware_io"] ? root["hardware_io"].as<std::string>() : "disabled";
    result.controlBusEnabled=live && status=="user-confirmed" && hardwareIo=="logical-control-only";
  }
  if(root["state"] && root["state"]["scenes"]) for(const auto& s:root["state"]["scenes"]) sceneIndex(result,s.as<std::string>());
  if(root["state"] && root["state"]["defaults"] && root["state"]["defaults"]["scene"]) result.defaultScene=sceneIndex(result,root["state"]["defaults"]["scene"].as<std::string>());
  if(root["policies"] && root["policies"]["echo"]) result.echoMeasuredOnly=root["policies"]["echo"].as<std::string>()=="measured_only";
  if(root["logical_control_protocol"]) for(const auto& item:root["logical_control_protocol"]) {
    const auto name=item.first.as<std::string>(); const auto control=item.second;
    if(name!="scene" && control["type"] && control["type"].as<std::string>()=="cc") {
      uint8_t defaultValue=0;
      if(root["state"] && root["state"]["defaults"] && root["state"]["defaults"][name]) defaultValue=midiValue(root["state"]["defaults"][name]);
      result.variables.push_back({name,midi(control,"cc"),defaultValue});
    }
  }
  for(const auto& record:records) {
    if(!record["source"]||!record["match"]||!record["emit"]||!record["scene"]||!record["physical"]||!record["logical_target"]||!record["renderers"]||!record["renderers"][rendererName]) invalid(std::string("runtime record is incomplete for ")+rendererName);
    const auto source=runtimeSource(result,record["source"]); const auto match=record["match"]; const auto emit=record["emit"];
    const auto matcherName=match["type"].as<std::string>();
    RuntimeDecoder decoder; decoder.source=source; decoder.matcher=runtimeMatcher(matcherName); decoder.physical=record["physical"].as<std::string>();
    if(decoder.matcher==PhysicalMatcher::NoteRange) { const auto range=match["note_range"]; if(!range||range.size()!=2) invalid("runtime note_range needs two values"); decoder.first=midiValue(range[0]); decoder.last=midiValue(range[1]); }
    else if(decoder.matcher==PhysicalMatcher::PolyAftertouch) { decoder.first=match["note"]?midi(match,"note"):255; decoder.last=decoder.first; }
    else { const char* key=decoder.matcher==PhysicalMatcher::ControlChange?"cc":"note"; decoder.first=midi(match,key); decoder.last=decoder.first; }
    if(decoder.first!=255 && decoder.last<decoder.first) invalid("runtime note range is descending");
    if(emit["expressions"]) for(const auto& expression:emit["expressions"]) { const auto value=expression.as<std::string>(); decoder.velocity|=value=="velocity"; decoder.position|=value=="position"; }
    if(decoder.position && (decoder.matcher!=PhysicalMatcher::NoteRange || decoder.first==decoder.last))
      invalid("runtime positional decoder requires a non-empty measured note range");
    bool decoderExists=false; for(const auto& existing:result.decoders) if(existing.source==decoder.source&&existing.matcher==decoder.matcher&&existing.first==decoder.first&&existing.last==decoder.last&&existing.physical==decoder.physical) decoderExists=true;
    if(!decoderExists) result.decoders.push_back(std::move(decoder));
    const auto scene=sceneIndex(result,record["scene"].as<std::string>()); const auto physical=record["physical"].as<std::string>(); const auto logical=record["logical_target"].as<std::string>();
    RuntimeRoute route; route.scene=scene; route.physical=physical; route.logical=logical; const auto predicates=record["state_predicates"] ? record["state_predicates"] : record["predicates"]; if(predicates) { if(!predicates.IsMap()) invalid("state predicates must be a map"); for(const auto& predicate:predicates) { if(route.predicateCount>=route.predicates.size()) invalid("too many state predicates"); const auto name=predicate.first.as<std::string>(); auto it=std::find_if(result.variables.begin(),result.variables.end(),[&](const RuntimeControl& c){return c.name==name;}); if(it==result.variables.end()) invalid("unknown state predicate "+name); route.predicates[route.predicateCount++]={static_cast<uint8_t>(it-result.variables.begin()),midiValue(predicate.second)}; } std::sort(route.predicates.begin(),route.predicates.begin()+route.predicateCount,[](const RuntimePredicate& left,const RuntimePredicate& right){return left.variable<right.variable;}); }
    // Expressions are state for an active or following hit, not independent
    // logical sounds. Keeping them out of the route table lets CC4 share
    // `hh.bow` and pressure share a raw cymbal Note decoder safely.
    if(!(matcherName=="poly_aftertouch" || (target==RuntimeRendererTarget::DrumGizmo && matcherName=="cc"))) {
      bool routeExists=false; for(const auto& item:result.routes) { if(item.scene!=route.scene||item.physical!=route.physical||item.logical!=route.logical||item.predicateCount!=route.predicateCount) continue; bool same=true; for(uint8_t i=0;i<route.predicateCount;++i) if(item.predicates[i].variable!=route.predicates[i].variable||item.predicates[i].value!=route.predicates[i].value) {same=false;break;} if(same) routeExists=true; }
      if(!routeExists) result.routes.push_back(std::move(route));
    }
    const auto targetRenderer=record["renderers"][rendererName]; if(!targetRenderer["note"]&&!targetRenderer["cc"]) invalid(std::string("runtime ")+rendererName+" renderer needs note or cc"); RuntimeRenderer renderer; renderer.logical=logical; renderer.note=targetRenderer["note"]?midi(targetRenderer,"note"):0; renderer.channel=channel(targetRenderer,"channel",10); if(targetRenderer["position_cc"]) renderer.positionCc=midi(targetRenderer,"position_cc"); if(targetRenderer["cc"]) renderer.controller=midi(targetRenderer,"cc");
    if(matcherName=="cc" || matcherName=="poly_aftertouch") {
      if(matcherName=="poly_aftertouch") {
        if(target!=RuntimeRendererTarget::Sd3) invalid("runtime pressure expression is unsupported for the selected renderer");
        bool accepted=false;
        const auto expressions=emit["expressions"];
        if(expressions && root["expression_routing"]) for(const auto& expression:expressions) {
          if(expression.as<std::string>()!="pressure") continue;
          for(const auto& candidate:root["expression_routing"]) {
            if(!candidate["source"]||!candidate["physical"]||!candidate["expression"]||
               candidate["source"].as<std::string>()!=record["source"]["id"].as<std::string>() ||
               candidate["physical"].as<std::string>()!=physical || candidate["expression"].as<std::string>()!="pressure") continue;
            if(!candidate["correlation"] || candidate["correlation"].as<std::string>()!="source_channel_note")
              invalid("runtime pressure expression requires correlation: source_channel_note");
            const auto expressionTarget=candidate["targets"] ? candidate["targets"]["sd3"] : YAML::Node{};
            const auto event=expressionTarget ? expressionTarget["event"] : YAML::Node{};
            if(!expressionTarget||!event||!expressionTarget["status"]||!event["type"]||!event["note_from"])
              invalid("runtime pressure expression route is incomplete");
            const auto status=expressionTarget["status"].as<std::string>();
            if((status!="measured"&&status!="user-confirmed") || event["type"].as<std::string>()!="poly_aftertouch" ||
               event["note_from"].as<std::string>()!="active_rendered_hit")
              invalid("runtime pressure expression route is not a reviewed active-hit aftertouch route");
            bool foundPrimary=false;
            for(const auto& primary:result.decoders) {
              if(primary.source!=source || primary.physical!=physical ||
                 (primary.matcher!=PhysicalMatcher::Note && primary.matcher!=PhysicalMatcher::NoteRange)) continue;
              foundPrimary=true;
              const auto existing=std::find_if(result.pressureExpressions.begin(),result.pressureExpressions.end(),
                                               [&primary](const RuntimePressureExpression& item){ return item.source==primary.source && item.inputFirst==primary.first && item.inputLast==primary.last; });
              if(existing==result.pressureExpressions.end()) result.pressureExpressions.push_back({source,primary.first,primary.last});
            }
            if(!foundPrimary) invalid("runtime pressure expression has no primary Note decoder for its physical event");
            accepted=true;
          }
        }
        if(!accepted) invalid("runtime pressure decoder has no measured expression-routing/v1 target");
      } else {
      bool accepted=false;
      const auto expressions=emit["expressions"];
      if(expressions && root["expression_routing"]) for(const auto& expression:expressions) {
        if(expression.as<std::string>()!="openness") continue;
        for(const auto& candidate:root["expression_routing"]) {
          if(!candidate["source"]||!candidate["physical"]||!candidate["expression"]||
             candidate["source"].as<std::string>()!=record["source"]["id"].as<std::string>() ||
             candidate["physical"].as<std::string>()!=physical || candidate["expression"].as<std::string>()!="openness") continue;
          if(!candidate["correlation"] || candidate["correlation"].as<std::string>()!="none")
            invalid("runtime openness expression route requires correlation: none");
          const auto expressionTarget=candidate["targets"] ? candidate["targets"][rendererName] : YAML::Node{};
          const auto event=expressionTarget ? expressionTarget["event"] : YAML::Node{};
          if(!expressionTarget||!event||!expressionTarget["status"]||!event["type"])
            invalid("runtime expression route is incomplete");
          const auto expressionStatus=expressionTarget["status"].as<std::string>();
          if((expressionStatus!="measured"&&expressionStatus!="user-confirmed"))
            invalid("runtime expression route is not reviewed");
          if(target==RuntimeRendererTarget::Sd3) {
            if(!event["transform"]||!event["channel"]||!event["cc"] || event["type"].as<std::string>()!="cc" || event["transform"].as<std::string>()!="passthrough")
              invalid("runtime expression route is not a reviewed passthrough CC");
            if(renderer.channel!=channel(event,"channel",10)||renderer.controller!=midi(event,"cc"))
              invalid("runtime expression route differs from its SD3 renderer address");
          } else {
            if(event["type"].as<std::string>()!="quantized_note" || !event["input_closed"] || !event["input_open"] || !event["articulations"])
              invalid("runtime DrumGizmo hi-hat route is incomplete");
            RuntimeHihatQuantization quantization;
            quantization.source=source; quantization.controller=decoder.first;
            quantization.inputClosed=midi(event,"input_closed"); quantization.inputOpen=midi(event,"input_open");
            if(quantization.inputClosed==quantization.inputOpen) invalid("runtime DrumGizmo hi-hat endpoints must differ");
            for(const auto& item:event["articulations"]) {
              if(!item["physical"]||!item["notes"]||!item["upper_boundaries"]) invalid("runtime DrumGizmo hi-hat zone is incomplete");
              RuntimeHihatZone zone; zone.physical=item["physical"].as<std::string>();
              const auto notes=item["notes"]; const auto boundaries=item["upper_boundaries"];
              if(notes.size()<1||notes.size()>zone.notes.size()||boundaries.size()+1!=notes.size()) invalid("runtime DrumGizmo hi-hat zone count is invalid");
              zone.count=static_cast<uint8_t>(notes.size());
              for(size_t index=0;index<notes.size();++index) zone.notes[index]=midiValue(notes[index]);
              zone.baseNote=zone.notes[0];
              for(size_t index=0;index<boundaries.size();++index) { zone.upperBoundaries[index]=midiValue(boundaries[index]); if(zone.upperBoundaries[index]>=127 || (index&&zone.upperBoundaries[index]<=zone.upperBoundaries[index-1])) invalid("runtime DrumGizmo hi-hat boundaries are invalid"); }
              for(const auto& existing:quantization.zones) if(existing.physical==zone.physical) invalid("runtime DrumGizmo hi-hat physical zone is duplicated");
              quantization.zones.push_back(std::move(zone));
            }
            if(result.hihatQuantization) {
              const auto& existing=*result.hihatQuantization;
              if(existing.source!=quantization.source || existing.controller!=quantization.controller || existing.inputClosed!=quantization.inputClosed || existing.inputOpen!=quantization.inputOpen || existing.zones.size()!=quantization.zones.size()) invalid("runtime DrumGizmo hi-hat expression is inconsistent");
            } else result.hihatQuantization=std::make_unique<RuntimeHihatQuantization>(std::move(quantization));
          }
          accepted=true;
        }
      }
      if(!accepted) invalid("runtime expression decoder has no measured expression-routing/v1 target");
      }
    }
    bool renderExists=false; for(const auto& item:result.renderers) if(item.logical==renderer.logical) { renderExists=true; if(item.note!=renderer.note||item.channel!=renderer.channel||item.positionCc!=renderer.positionCc||item.controller!=renderer.controller) invalid(std::string("logical sound has inconsistent ")+rendererName+" renderers"); } if(!renderExists) result.renderers.push_back(std::move(renderer));
  }
  if(root["native_control_map"]) for(const auto& item:root["native_control_map"]) {
    const auto name=item.first.as<std::string>(); const auto native=item.second;
    if(!native["decode_to"]||!native["channel"]||!native["type"]||!native["value"]) invalid("native control "+name+" is incomplete");
    RuntimeNativeControl control; control.channel=channel(native,"channel",1); control.type=runtimeNativeControlType(native["type"].as<std::string>());
    const auto target=native["decode_to"].as<std::string>();
    if(target=="scene") control.target=0;
    else { auto variable=std::find_if(result.variables.begin(),result.variables.end(),[&](const RuntimeControl& value){return value.name==target;}); if(variable==result.variables.end()) invalid("native control "+name+" has unknown state target"); control.target=static_cast<uint8_t>(variable-result.variables.begin()+1); }
    if(native["source"]) { const auto sourceId=native["source"].as<std::string>(); auto source=std::find_if(result.sources.begin(),result.sources.end(),[&](const RuntimeSource& value){return value.id==sourceId;}); if(source==result.sources.end()) invalid("native control "+name+" has unknown source"); if(source->channel!=control.channel) invalid("native control "+name+" channel differs from source"); control.source=static_cast<int16_t>(source-result.sources.begin()); }
    if(control.type==NativeControlType::ProgramChange) { if(!native["program"]) invalid("native Program Change control needs program"); control.address=midi(native,"program"); }
    if(control.type==NativeControlType::ControlChange) { if(!native["cc"]) invalid("native CC control needs cc"); control.address=midi(native,"cc"); }
    if(control.type==NativeControlType::NoteOn) { if(!native["note"]) invalid("native note control needs note"); control.address=midi(native,"note"); }
    control.value=midi(native,"value");
    for(const auto& existing:result.nativeControls) if(existing.channel==control.channel&&existing.type==control.type&&existing.address==control.address&&(existing.source<0||control.source<0||existing.source==control.source)) invalid("duplicate native runtime control");
    result.nativeControls.push_back(control);
  }
  if(root["connection_profiles"] && root["connection_profiles"].IsMap()) for(auto& source:result.sources) { const auto policy=root["connection_profiles"][source.connectionProfile]; if(policy && policy["deduplicate_din_copies"]) source.deduplicateDinCopies=policy["deduplicate_din_copies"].as<bool>(); }
  std::stable_sort(result.routes.begin(),result.routes.end(),[](const RuntimeRoute& left,const RuntimeRoute& right){ if(left.scene!=right.scene) return left.scene<right.scene; if(left.physical!=right.physical) return left.physical<right.physical; return left.predicateCount>right.predicateCount; });
  validateRuntimeProfile(result); return result;
}
void validateRuntimeProfile(const RuntimeProfile& profile) {
  if(profile.sources.empty()||profile.sources.size()>8||profile.scenes.empty()||profile.scenes.size()>128||profile.decoders.empty()||profile.routes.empty()||profile.renderers.empty()) invalid("runtime profile has no complete pipeline, exceeds eight MIDI sources, or exceeds 128 scenes");
  if(profile.defaultScene>=profile.scenes.size()) invalid("runtime default scene is invalid");
  if(profile.variables.size()>4) invalid("runtime profile supports at most 4 atomic state variables");
  std::set<std::pair<std::string,uint8_t>> endpointChannels;
  for(const auto& source:profile.sources) { if(source.id.empty()||source.endpoint.empty()) invalid("runtime source id and endpoint may not be empty"); if(!endpointChannels.insert({source.endpoint,source.channel}).second) invalid("runtime sources sharing an endpoint must use distinct channels"); }
  for(const auto& decoder:profile.decoders) if(decoder.source>=profile.sources.size()||decoder.physical.empty()) invalid("runtime decoder is invalid");
  if(profile.hihatQuantization) {
    const auto& quantization=*profile.hihatQuantization;
    if(quantization.source>=profile.sources.size() || quantization.zones.empty()) invalid("runtime DrumGizmo hi-hat quantization is invalid");
    bool controllerDecoder=false;
    for(const auto& decoder:profile.decoders) if(decoder.source==quantization.source && decoder.matcher==PhysicalMatcher::ControlChange && decoder.first==quantization.controller) controllerDecoder=true;
    if(!controllerDecoder) invalid("runtime DrumGizmo hi-hat quantization has no CC decoder");
    for(const auto& zone:quantization.zones) {
      if(zone.physical.empty() || zone.count==0 || zone.count>zone.notes.size()) invalid("runtime DrumGizmo hi-hat zone is invalid");
      bool noteDecoder=false;
      for(const auto& decoder:profile.decoders) if(decoder.source==quantization.source && decoder.physical==zone.physical && (decoder.matcher==PhysicalMatcher::Note || decoder.matcher==PhysicalMatcher::NoteRange)) noteDecoder=true;
      if(!noteDecoder) invalid("runtime DrumGizmo hi-hat zone has no note decoder");
      for(uint8_t index=1;index<zone.count;++index) if(zone.upperBoundaries[index-1]>=127 || (index>1 && zone.upperBoundaries[index-1]<=zone.upperBoundaries[index-2])) invalid("runtime DrumGizmo hi-hat boundaries are invalid");
    }
  }
  for(const auto& route:profile.routes) if(route.scene>=profile.scenes.size()||route.physical.empty()||route.logical.empty()) invalid("runtime route is invalid");
  for(size_t i=0;i<profile.routes.size();++i) {
    const auto& route=profile.routes[i]; size_t fallbackCount=0;
    for(const auto& candidate:profile.routes) if(candidate.scene==route.scene&&candidate.physical==route.physical&&candidate.predicateCount==0) ++fallbackCount;
    if(fallbackCount!=1) invalid("runtime scene/physical route group needs exactly one fallback");
    if(route.predicateCount==0) continue;
    for(size_t j=i+1;j<profile.routes.size();++j) {
      const auto& other=profile.routes[j]; if(other.scene!=route.scene||other.physical!=route.physical||other.predicateCount==0) continue;
      bool overlaps=true;
      for(uint8_t left=0;left<route.predicateCount;++left) for(uint8_t right=0;right<other.predicateCount;++right) if(route.predicates[left].variable==other.predicates[right].variable&&route.predicates[left].value!=other.predicates[right].value) overlaps=false;
      if(overlaps) invalid("runtime scene/physical route predicates overlap");
    }
  }
}
}
