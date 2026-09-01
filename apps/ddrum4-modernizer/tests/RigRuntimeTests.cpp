#include "core/RigRuntime.h"
#include "config/ProfileLoader.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <filesystem>
#include <iostream>
#include <utility>

using namespace ddrum4;
int main() {
  RuntimeProfile p;
  p.sources={{"edrumin","test","DUAL",1,true,true,RuntimeConnection::Dual},{"ddrum4-din","test-din","DUAL",1,false,true,RuntimeConnection::Dual}};
  p.scenes={"metal","electronic"}; p.defaultScene=0; p.echoMeasuredOnly=true;
  p.decoders={{0,PhysicalMatcher::NoteRange,40,47,"snare.head",true,true}, {0,PhysicalMatcher::ControlChange,4,4,"hat.opening",false,false}, {0,PhysicalMatcher::Note,49,49,"cymbal.choke",false,false}, {0,PhysicalMatcher::PolyAftertouch,49,49,"cymbal.choke",false,false}};
  p.routes={{0,"snare.head","snare.metal"},{1,"snare.head","snare.electronic"},{0,"hat.opening","hat.opening"},{1,"hat.opening","hat.opening"},{0,"cymbal.choke","cymbal.choke"},{1,"cymbal.choke","cymbal.choke"}};
  p.renderers={{"snare.metal",38,10,16},{"snare.electronic",40,10,16},{"hat.opening",46,10,255,46},{"cymbal.choke",49,10,255}};
  p.renderers[1].fixedControllers[0]={4,64}; p.renderers[1].fixedControllerCount=1;
  p.variables={{"vp1",20,9}};
  p.nativeControls={{0,1,NativeControlType::ProgramChange,1,0,1},{0,1,NativeControlType::ControlChange,21,1,66}};
  p.pressureExpressions={{0,49,49}};
  RigRuntime runtime{p}; assert(runtime.variable(0)==9); std::array<MidiEvent,RigRuntime::maxOutputEvents> out{};
  assert(runtime.selectScene(1) && runtime.scene()==1);
  assert(runtime.setVariableValue(0,12) && runtime.variable(0)==12);
  assert(!runtime.selectScene(2) && !runtime.setVariableValue(1,12));
  assert(runtime.selectScene(0));
  // Golden trace: snare position, logical VP control, scene switch, CC4 and choke.
  auto count=runtime.process("edrumin",{MidiType::NoteOn,1,43,100,100},out);
  assert(count==2 && out[0].type==MidiType::ControlChange && out[0].data1==16 && out[0].data2==54 && out[1].data1==38 && out[1].data2==100);
  assert(runtime.process("edrumin",{MidiType::ControlChange,14,20,77,101},out)==0 && runtime.variable(0)==77);
  assert(runtime.process("edrumin",{MidiType::ControlChange,1,21,66,101},out)==0 && runtime.variable(0)==66);
  assert(runtime.process("edrumin",{MidiType::ProgramChange,1,1,0,102},out)==0 && runtime.scene()==1);
  assert(runtime.selectScene(0));
  assert(runtime.process("edrumin",{MidiType::ProgramChange,15,1,0,102},out)==0 && runtime.scene()==1);
  count=runtime.process("edrumin",{MidiType::NoteOn,1,47,90,103},out); assert(count==3 && out[0].data2==127 && out[1].type==MidiType::ControlChange && out[1].data1==4 && out[1].data2==64 && out[2].data1==40);
  count=runtime.process("edrumin",{MidiType::ControlChange,1,4,64,104},out); assert(count==1 && out[0].type==MidiType::ControlChange && out[0].data1==46 && out[0].data2==64);
  count=runtime.process("edrumin",{MidiType::NoteOn,1,49,100,105},out); assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==49);
  count=runtime.process("edrumin",{MidiType::PolyAftertouch,1,49,127,106},out); assert(count==1 && out[0].type==MidiType::PolyAftertouch && out[0].data1==49);
  assert(runtime.process("ddrum4-din",{MidiType::ControlChange,1,4,64,106},out)==0); // same physical CC from a configured DIN copy
  count=runtime.process("edrumin",{MidiType::NoteOff,1,43,0,106},out); assert(count==1 && out[0].type==MidiType::NoteOff && out[0].data1==38);
  // A repeated CC from the same port is a real performance event, not an echo.
  assert(runtime.process("edrumin",{MidiType::ControlChange,1,4,64,20000},out)==1);
  assert(runtime.process("edrumin",{MidiType::ControlChange,1,4,64,20001},out)==1);
  assert(runtime.process("edrumin",{MidiType::NoteOn,14,40,100,108},out)==0); // all logical-bus traffic is swallowed
  const auto h=runtime.health(); assert(h.decoded==7 && h.rendered==11 && h.controls==4 && h.duplicates==1);
  RuntimeProfile oversized;
  for (size_t i=0;i<9;++i)
    oversized.sources.push_back({"source-"+std::to_string(i),"endpoint-"+std::to_string(i),"single",1,true,false,RuntimeConnection::Single});
  oversized.scenes={"default"};
  oversized.decoders={{8,PhysicalMatcher::Note,40,40,"snare",true,false}};
  oversized.routes={{0,"snare","snare"}};
  oversized.renderers={{"snare",38,10,255}};
  RigRuntime sourceBounded{oversized};
  assert(sourceBounded.process("source-8",{MidiType::NoteOn,1,40,100,109},out)==0);
  assert(sourceBounded.processEndpoint("endpoint-8",{MidiType::NoteOn,1,40,100,110},out)==0);
  const auto loaded=loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-ready.yaml");
  assert(loaded.sources.size()==1 && loaded.scenes.size()==2 && loaded.renderers.size()==2 && loaded.routes.size()==3 && loaded.nativeControls.size()==2);
  const auto layered=std::find_if(loaded.renderers.begin(),loaded.renderers.end(),[](const RuntimeRenderer& renderer){return renderer.logical=="snare.metal";});
  assert(layered!=loaded.renderers.end() && layered->layerCount==2 && layered->layers[0]==100 && layered->layers[1]==101);
  RigRuntime loadedRuntime{loaded};
  count=loadedRuntime.process("edrumin",{MidiType::NoteOn,1,40,100,111},out);
  assert(count==3 && out[0].data1==38 && out[1].data1==100 && out[2].data1==101);
  count=loadedRuntime.process("edrumin",{MidiType::NoteOff,1,40,0,111},out);
  assert(count==3 && out[0].type==MidiType::NoteOff && out[0].data1==38 && out[1].data1==100 && out[2].data1==101);
  assert(loadedRuntime.process("edrumin",{MidiType::ControlChange,1,21,1,112},out)==0 && loadedRuntime.variable(0)==1);
  count=loadedRuntime.process("edrumin",{MidiType::NoteOn,1,40,100,112},out);
  assert(count==2 && out[0].type==MidiType::ControlChange && out[0].data1==4 && out[0].data2==64 && out[1].data1==40);
  assert(loadedRuntime.process("edrumin",{MidiType::ProgramChange,1,1,0,112},out)==0 && loadedRuntime.scene()==1);
  assert(loadedRuntime.process("edrumin",{MidiType::ControlChange,14,20,1,112},out)==0);
  count=loadedRuntime.process("edrumin",{MidiType::NoteOn,1,40,100,113},out);
  assert(count==2 && out[0].type==MidiType::ControlChange && out[0].data1==4 && out[0].data2==64 && out[1].data1==40);
  const auto drumgizmo=loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-ready.yaml", RuntimeRendererTarget::DrumGizmo);
  const auto drumgizmoMetal=std::find_if(drumgizmo.renderers.begin(),drumgizmo.renderers.end(),[](const RuntimeRenderer& renderer){return renderer.logical=="snare.metal";});
  assert(drumgizmo.rendererTarget==RuntimeRendererTarget::DrumGizmo && drumgizmoMetal!=drumgizmo.renderers.end() && drumgizmoMetal->note==48);
  RigRuntime drumgizmoRuntime{drumgizmo};
  count=drumgizmoRuntime.process("edrumin",{MidiType::NoteOn,1,40,100,114},out);
  assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==48);
  assert(drumgizmoRuntime.process("edrumin",{MidiType::ControlChange,14,20,1,115},out)==0);
  count=drumgizmoRuntime.process("edrumin",{MidiType::NoteOn,1,40,100,116},out);
  assert(count==1 && out[0].data1==50);
  assert(drumgizmoRuntime.process("edrumin",{MidiType::ControlChange,1,4,64,117},out)==0);
  bool expressionProfileRejected=false;
  try {
    (void)loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-unsafe.yaml");
  } catch(const std::exception&) {
    expressionProfileRejected=true;
  }
  assert(expressionProfileRejected);
  const auto positionSd3=loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-position.yaml");
  RigRuntime positionRuntime{positionSd3};
  count=positionRuntime.process("edrumin",{MidiType::ControlChange,1,16,91,118},out);
  assert(count==1 && out[0].type==MidiType::ControlChange && out[0].channel==10 && out[0].data1==16 && out[0].data2==91);
  const auto expressionSd3=loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-sd3.yaml");
  RigRuntime expressionRuntime{expressionSd3};
  count=expressionRuntime.process("edrumin",{MidiType::ControlChange,1,4,73,118},out);
  assert(count==1 && out[0].type==MidiType::ControlChange && out[0].channel==10 && out[0].data1==4 && out[0].data2==73);
  bool expressionDrumGizmoRejected=false;
  try {
    (void)loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-sd3.yaml", RuntimeRendererTarget::DrumGizmo);
  } catch(const std::exception&) {
    expressionDrumGizmoRejected=true;
  }
  assert(expressionDrumGizmoRejected);
  const auto quantizedDrumGizmo=loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-drumgizmo.yaml", RuntimeRendererTarget::DrumGizmo);
  assert(quantizedDrumGizmo.hihatQuantization && quantizedDrumGizmo.hihatQuantization->zones.size()==2);
  RigRuntime quantizedDrumGizmoRuntime{quantizedDrumGizmo};
  assert(quantizedDrumGizmoRuntime.process("edrumin",{MidiType::ControlChange,1,4,127,119},out)==0);
  count=quantizedDrumGizmoRuntime.process("edrumin",{MidiType::NoteOn,1,42,96,120},out);
  assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==64);
  count=quantizedDrumGizmoRuntime.process("edrumin",{MidiType::NoteOff,1,42,0,121},out);
  assert(count==1 && out[0].type==MidiType::NoteOff && out[0].data1==64);
  assert(quantizedDrumGizmoRuntime.process("edrumin",{MidiType::ControlChange,1,4,0,122},out)==0);
  count=quantizedDrumGizmoRuntime.process("edrumin",{MidiType::NoteOn,1,46,96,123},out);
  assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==75);
  count=quantizedDrumGizmoRuntime.process("edrumin",{MidiType::NoteOff,1,46,0,124},out);
  assert(count==1 && out[0].type==MidiType::NoteOff && out[0].data1==75);
  // Non-full-range calibration catches a one-step boundary mismatch between
  // truncation and the signed rounding used by the Arduino and simulator.
  auto thresholdProfile=loadRuntimeProfile(
    std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-drumgizmo.yaml",
    RuntimeRendererTarget::DrumGizmo);
  thresholdProfile.hihatQuantization->inputClosed=120;
  thresholdProfile.hihatQuantization->inputOpen=20;
  RigRuntime thresholdRuntime{thresholdProfile};
  assert(thresholdRuntime.process("edrumin",{MidiType::ControlChange,1,4,70,124},out)==0);
  count=thresholdRuntime.process("edrumin",{MidiType::NoteOn,1,42,96,124},out);
  assert(count==1 && out[0].data1==74); // 63.5 rounds to 64: next articulation
  assert(thresholdRuntime.process("edrumin",{MidiType::ControlChange,1,4,71,124},out)==0);
  count=thresholdRuntime.process("edrumin",{MidiType::NoteOn,1,42,96,124},out);
  assert(count==1 && out[0].data1==64); // normalized 62: lower articulation
  const auto positionalDrumGizmo=loadRuntimeProfile(
    std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-position-note-range.yaml",
    RuntimeRendererTarget::DrumGizmo);
  assert(positionalDrumGizmo.renderers.size()==1 &&
         positionalDrumGizmo.renderers[0].positionNoteCount==3 &&
         positionalDrumGizmo.renderers[0].positionTargets[0]=="snare2.metalcore_center" &&
         positionalDrumGizmo.renderers[0].positionTargets[1]=="snare2.metalcore" &&
         positionalDrumGizmo.renderers[0].positionTargets[2]=="snare2.metalcore_edge");
  bool mismatchedPositionTargetRejected=false;
  try {
    (void)loadRuntimeProfile(
      std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-position-target-mismatch.yaml",
      RuntimeRendererTarget::DrumGizmo);
  } catch(const std::runtime_error&) {
    mismatchedPositionTargetRejected=true;
  }
  assert(mismatchedPositionTargetRejected);
  RigRuntime positionalDrumGizmoRuntime{positionalDrumGizmo};
  for(const auto& sample:std::array<std::pair<uint8_t,uint8_t>,8>{{
      {8,32},{9,32},{10,32},{11,33},{12,33},{13,33},{14,34},{15,34}}}) {
    count=positionalDrumGizmoRuntime.process("ddrum4",{MidiType::NoteOn,12,sample.first,100,125},out);
    assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==sample.second);
    count=positionalDrumGizmoRuntime.process("ddrum4",{MidiType::NoteOff,12,sample.first,0,126},out);
    assert(count==1 && out[0].type==MidiType::NoteOff && out[0].data1==sample.second);
  }
  const auto pressureProfile=loadRuntimeProfile(std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-pressure.yaml");
  assert(pressureProfile.pressureExpressions.size()==1);
  RigRuntime pressureRuntime{pressureProfile};
  count=pressureRuntime.process("edrumin",{MidiType::NoteOn,1,49,100,125},out);
  assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==83);
  count=pressureRuntime.process("edrumin",{MidiType::PolyAftertouch,1,49,96,126},out);
  assert(count==1 && out[0].type==MidiType::PolyAftertouch && out[0].data1==83 && out[0].data2==96);
  count=pressureRuntime.process("edrumin",{MidiType::NoteOn,1,50,100,126},out);
  assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==84);
  assert(pressureRuntime.process("edrumin",{MidiType::PolyAftertouch,1,50,96,127},out)==0);
  count=pressureRuntime.process("edrumin",{MidiType::NoteOff,1,49,0,127},out);
  assert(count==1 && out[0].type==MidiType::NoteOff && out[0].data1==83);
  assert(pressureRuntime.process("edrumin",{MidiType::PolyAftertouch,1,49,127,128},out)==0);
  const auto drumGizmoPressureProfile=loadRuntimeProfile(
    std::filesystem::path(DDRUM4_TEST_CONFIG_DIR)/"runtime-expression-pressure.yaml",
    RuntimeRendererTarget::DrumGizmo);
  assert(drumGizmoPressureProfile.pressureExpressions.size()==1);
  RigRuntime drumGizmoPressureRuntime{drumGizmoPressureProfile};
  count=drumGizmoPressureRuntime.process("edrumin",{MidiType::NoteOn,1,49,100,129},out);
  assert(count==1 && out[0].type==MidiType::NoteOn && out[0].data1==83);
  count=drumGizmoPressureRuntime.process("edrumin",{MidiType::PolyAftertouch,1,49,127,130},out);
  assert(count==1 && out[0].type==MidiType::PolyAftertouch && out[0].data1==83 && out[0].data2==127);
  std::cout << "rig runtime tests passed\n";
}
