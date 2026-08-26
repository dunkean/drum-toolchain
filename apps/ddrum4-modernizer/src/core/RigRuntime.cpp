#include "core/RigRuntime.h"
#include <algorithm>

namespace ddrum4 {
RigRuntime::RigRuntime(const RuntimeProfile& profile) : profile_(profile) {
  uint64_t initial=profile.defaultScene;
  for(size_t i=0;i<profile.variables.size() && i<6;++i) initial|=static_cast<uint64_t>(profile.variables[i].defaultValue)<<(16+i*8);
  state_.store(initial,std::memory_order_relaxed);
}
int RigRuntime::endpointSourceIndex(std::string_view endpoint, uint8_t channel) const noexcept {
  const auto count=std::min(profile_.sources.size(),maxSources);
  for(size_t i=0;i<count;++i) if(profile_.sources[i].endpoint==endpoint && profile_.sources[i].channel==channel) return static_cast<int>(i);
  return -1;
}
int RigRuntime::sourceIndex(std::string_view id) const noexcept {
  const auto count=std::min(profile_.sources.size(),maxSources);
  for (size_t i=0; i<count; ++i) if (profile_.sources[i].id == id) return static_cast<int>(i);
  return -1;
}
bool RigRuntime::duplicate(uint16_t source, const MidiEvent& input) noexcept {
  const auto& src=profile_.sources[source];
  const auto slot=static_cast<size_t>((input.channel * 17u + input.data1) % seen_.size());
  auto& prior=seen_[slot];
  const bool same=prior.valid && prior.type==input.type && prior.channel==input.channel && prior.data1==input.data1 && prior.data2==input.data2;
  const bool recent=same && input.timestampUs>=prior.timestamp && input.timestampUs-prior.timestamp<=profile_.dedupWindowUs;
  // Identical hits on a single physical connection are valid.  Suppress only
  // measured cross-port copies from an explicitly DUAL connection profile.
  const bool priorSourceValid=prior.source<profile_.sources.size() && prior.source<maxSources;
  const bool crossSource=recent && priorSourceValid && prior.source!=source && src.deduplicateDinCopies &&
    src.connection==RuntimeConnection::Dual && profile_.sources[prior.source].connection==RuntimeConnection::Dual;
  prior={source,input.type,input.channel,input.data1,input.data2,input.timestampUs,true};
  if (crossSource) { duplicates_.fetch_add(1, std::memory_order_relaxed); return true; }
  return false;
}
void RigRuntime::remember(uint16_t source, const MidiEvent& input, const RuntimeRenderer& renderer) noexcept {
  auto& queue=(*active_)[source][input.channel-1][input.data1];
  if(queue.size==queue.entries.size()) { queue.head=static_cast<uint8_t>((queue.head+1)%queue.entries.size()); --queue.size; ++queue.discardedOffs; }
  queue.entries[(queue.head+queue.size)%queue.entries.size()]={renderer.channel,renderer.note}; ++queue.size;
}
bool RigRuntime::recall(uint16_t source, const MidiEvent& input, Active& active) noexcept {
  auto& queue=(*active_)[source][input.channel-1][input.data1];
  if(queue.discardedOffs) { --queue.discardedOffs; return false; }
  if(!queue.size) return false;
  active=queue.entries[queue.head]; queue.head=static_cast<uint8_t>((queue.head+1)%queue.entries.size()); --queue.size; return true;
}
uint8_t RigRuntime::stateVariable(uint64_t state, size_t index) const noexcept { return index<6 ? static_cast<uint8_t>(state>>(16+index*8)) : 0; }
uint8_t RigRuntime::variable(size_t index) const noexcept { return stateVariable(state_.load(std::memory_order_acquire),index); }
void RigRuntime::setStateVariable(size_t index,uint8_t value) noexcept { if(index>=6) return; const auto shift=16+index*8; const auto mask=uint64_t{0xff}<<shift; auto current=state_.load(std::memory_order_relaxed); do { const auto next=(current&~mask)|(static_cast<uint64_t>(value)<<shift); if(state_.compare_exchange_weak(current,next,std::memory_order_release,std::memory_order_relaxed)) return; } while(true); }
bool RigRuntime::selectScene(uint16_t scene) noexcept {
  if (scene>=profile_.scenes.size()) return false;
  auto current=state_.load(std::memory_order_relaxed);
  do {
    const auto next=(current&~uint64_t{0xffff})|scene;
    if (state_.compare_exchange_weak(current,next,std::memory_order_release,std::memory_order_relaxed)) return true;
  } while(true);
}
bool RigRuntime::setVariableValue(size_t index,uint8_t value) noexcept {
  if (index>=profile_.variables.size() || index>=6) return false;
  setStateVariable(index,value);
  return true;
}
RuntimeHealth RigRuntime::health() const noexcept { return {received_.load(),decoded_.load(),rendered_.load(),ignored_.load(),duplicates_.load(),echoes_.load(),controls_.load()}; }
void RigRuntime::clearLedger() noexcept { for(auto& source:*active_) for(auto& channel:source) for(auto& queue:channel) queue={}; }
size_t RigRuntime::process(std::string_view sourceId, const MidiEvent& input, std::array<MidiEvent, maxOutputEvents>& output) noexcept {
  received_.fetch_add(1, std::memory_order_relaxed);
  const auto source=sourceIndex(sourceId);
  if (source<0 || input.channel<1 || input.channel>16 || input.data1>127 || input.data2>127) { ignore(); return 0; }
  if (duplicate(static_cast<uint16_t>(source), input)) return 0;
  // CH14/15 are the canonical logical-control bus, never physical pads.
  if (input.channel==14 || input.channel==15) {
    if (input.type==MidiType::ProgramChange && input.data1<profile_.scenes.size()) { auto current=state_.load(std::memory_order_relaxed); do { const auto next=(current&~uint64_t{0xffff})|input.data1; if(state_.compare_exchange_weak(current,next,std::memory_order_release,std::memory_order_relaxed)) break; } while(true); controls_.fetch_add(1, std::memory_order_relaxed); return 0; }
    if (input.type==MidiType::ControlChange) for(size_t i=0;i<profile_.variables.size() && i<6;++i) if(profile_.variables[i].cc==input.data1) { setStateVariable(i,input.data2); controls_.fetch_add(1,std::memory_order_relaxed); return 0; }
    // The logical bus is never a physical MIDI input, including unknown CCs,
    // note messages and aftertouch.
    ignore(); return 0;
  }
  for (const auto& control : profile_.nativeControls) {
    if ((control.source>=0 && control.source!=source) || control.channel!=input.channel) continue;
    const bool matches=(control.type==NativeControlType::ProgramChange && input.type==MidiType::ProgramChange && control.address==input.data1) ||
      (control.type==NativeControlType::ControlChange && input.type==MidiType::ControlChange && control.address==input.data1 && control.value==input.data2) ||
      (control.type==NativeControlType::NoteOn && isNoteOn(input) && input.data2!=0 && control.address==input.data1);
    if (!matches) continue;
    const uint8_t value=control.value;
    if (control.target==0) {
      if (!selectScene(value)) { ignore(); return 0; }
    } else if (!setVariableValue(static_cast<size_t>(control.target-1),value)) {
      ignore(); return 0;
    }
    controls_.fetch_add(1,std::memory_order_relaxed);
    return 0;
  }
  if (isNoteOff(input)) { Active active; if(!recall(static_cast<uint16_t>(source),input,active)) { ignore(); return 0; } output[0]={MidiType::NoteOff,active.channel,active.note,0,input.timestampUs}; rendered_.fetch_add(1,std::memory_order_relaxed); return 1; }
  const RuntimeDecoder* decoder=nullptr;
  for(const auto& d:profile_.decoders) {
    if(d.source!=static_cast<uint16_t>(source) || input.channel!=profile_.sources[d.source].channel) continue;
    const bool match=(d.matcher==PhysicalMatcher::Note && isNoteOn(input) && input.data1==d.first) ||
      (d.matcher==PhysicalMatcher::NoteRange && isNoteOn(input) && input.data1>=d.first && input.data1<=d.last) ||
      (d.matcher==PhysicalMatcher::ControlChange && input.type==MidiType::ControlChange && input.data1==d.first) ||
      (d.matcher==PhysicalMatcher::PolyAftertouch && input.type==MidiType::PolyAftertouch && (d.first==255 || input.data1==d.first));
    if(match) { decoder=&d; break; }
  }
  if(!decoder) { ignore(); return 0; }
  decoded_.fetch_add(1,std::memory_order_relaxed);
  const auto state=state_.load(std::memory_order_acquire); const auto activeScene=static_cast<uint16_t>(state);
  const RuntimeRoute* route=nullptr; for(const auto& r:profile_.routes) { if(r.scene!=activeScene || r.physical!=decoder->physical) continue; bool match=true; for(uint8_t i=0;i<r.predicateCount;++i) if(stateVariable(state,r.predicates[i].variable)!=r.predicates[i].value) {match=false;break;} if(match) { route=&r; break; } }
  if(!route) { ignore(); return 0; }
  const RuntimeRenderer* renderer=nullptr; for(const auto& r:profile_.renderers) if(r.logical==route->logical) { renderer=&r; break; }
  if(!renderer) { ignore(); return 0; }
  size_t count=0;
  // DrumGizmo's standard MIDI map is note based.  Do not invent a CC or
  // aftertouch convention for hihat/choke behavior that a kit has not proven.
  if(profile_.rendererTarget==RuntimeRendererTarget::DrumGizmo &&
     (input.type==MidiType::ControlChange || input.type==MidiType::PolyAftertouch)) { ignore(); return 0; }
  if(profile_.rendererTarget==RuntimeRendererTarget::Sd3 && decoder->position && renderer->positionCc<=127) {
    const uint8_t position=decoder->last==decoder->first ? input.data2 : static_cast<uint8_t>(((unsigned)(input.data1-decoder->first)*127u)/(decoder->last-decoder->first));
    output[count++]={MidiType::ControlChange,renderer->channel,renderer->positionCc,position,input.timestampUs};
  }
  const auto value=input.data2;
  if(input.type==MidiType::ControlChange) output[count++]={MidiType::ControlChange,renderer->channel,renderer->controller<=127?renderer->controller:renderer->note,value,input.timestampUs};
  else if(input.type==MidiType::PolyAftertouch) output[count++]={MidiType::PolyAftertouch,renderer->channel,renderer->note,value,input.timestampUs};
  else { remember(static_cast<uint16_t>(source),input,*renderer); output[count++]={MidiType::NoteOn,renderer->channel,renderer->note,value,input.timestampUs}; }
  rendered_.fetch_add(count,std::memory_order_relaxed); return count;
}
size_t RigRuntime::processEndpoint(std::string_view endpoint,const MidiEvent& input,std::array<MidiEvent,maxOutputEvents>& output) noexcept { auto source=endpointSourceIndex(endpoint,input.channel); if(source<0 && (input.channel==14||input.channel==15)) for(size_t i=0;i<profile_.sources.size();++i) if(profile_.sources[i].endpoint==endpoint) { source=static_cast<int>(i); break; } if(source<0) { received_.fetch_add(1,std::memory_order_relaxed); ignore(); return 0; } return process(profile_.sources[static_cast<size_t>(source)].id,input,output); }
}
