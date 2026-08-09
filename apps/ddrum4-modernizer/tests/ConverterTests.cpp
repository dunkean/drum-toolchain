#include "core/Converter.h"
#include "config/ProfileLoader.h"
#include <cassert>
#include <iostream>
using namespace ddrum4;

int main() {
  Route snare{"snare", RouteType::Positional, 10, 40, 8, 6, 10, 16};
  Route rim{"rim", RouteType::NoteMap, 10, 48, 1, 40, 10};
  Profile p; p.name="test"; p.endpoint="out"; p.inputChannel=10; p.outputChannel=10;
  p.kits={{"core", "Core", 10, {snare, rim}}, {"metal", "Metal", 10, {Route{"snare", RouteType::Positional, 10, 40, 8, 14, 10, 16}, rim}}};
  p.programs={{0,0},{1,1}};
  Converter converter{p}; std::array<MidiEvent, Converter::maxOutputEvents> out{};
  auto count=converter.process({MidiType::NoteOn,10,43,99,100},out); assert(count==2); assert(out[0].type==MidiType::ControlChange && out[0].data2==54); assert(out[1].data1==6 && out[1].data2==99);
  assert(converter.process({MidiType::ProgramChange,10,1,0,101},out)==0 && converter.activeKit()==1);
  count=converter.process({MidiType::NoteOn,10,43,88,102},out); assert(count==2 && out[1].data1==14);
  count=converter.process({MidiType::NoteOff,10,43,0,103},out); assert(count==1 && out[0].data1==6); // pre-PC hit retains its route
  count=converter.process({MidiType::NoteOff,10,43,0,104},out); assert(count==1 && out[0].data1==14);
  count=converter.process({MidiType::ControlChange,10,4,64,104},out); assert(count==1 && out[0].data1==4);
  count=converter.process({MidiType::ControlChange,10,7,64,105},out); assert(count==0);
  Route continuous{"hat_cc",RouteType::HihatContinuous,10,70,1,42,10,4}; continuous.inputCc=4; continuous.closedCc=10; continuous.openCc=110;
  Route discrete{"hat_notes",RouteType::HihatDiscrete,10,72,2,42,10,4}; discrete.ccValues={0,127,0,0,0,0,0,0};
  Profile hat; hat.name="hat"; hat.kits={{"hat","Hat",10,{continuous,discrete}}}; Converter hats{hat};
  count=hats.process({MidiType::ControlChange,10,4,64,106},out); assert(count==1 && out[0].data1==4 && out[0].data2>=59 && out[0].data2<=61);
  count=hats.process({MidiType::NoteOn,10,73,90,107},out); assert(count==2 && out[0].data1==4 && out[0].data2==127 && out[1].data1==42);
  Converter overflow{p}; assert(overflow.process({MidiType::NoteOn,10,40,100,0},out)==2); assert(overflow.process({MidiType::ProgramChange,10,1,0,1},out)==0); for(int i=0;i<15;++i) assert(overflow.process({MidiType::NoteOn,10,40,100,static_cast<uint64_t>(i+2)},out)==2);
  count=overflow.process({MidiType::NoteOn,10,40,100,200},out); assert(count==3 && out[0].type==MidiType::NoteOff && out[0].data1==6 && overflow.ledgerOverflows()==1);
  assert(overflow.process({MidiType::NoteOff,10,40,0,201},out)==0); // consumes the real Off of the evicted Core hit
  count=overflow.process({MidiType::NoteOff,10,40,0,202},out); assert(count==1 && out[0].data1==14); // next FIFO hit remains Metal
  const auto loaded=loadProfile("../config/ddrum4-template.yaml"); assert(loaded.initialKitIndex==0 && loaded.programSourceChannel==10 && loaded.kits.size()==3);
  std::cout << "converter tests passed\n";
}
