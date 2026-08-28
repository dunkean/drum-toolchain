#include <juce_gui_extra/juce_gui_extra.h>
#include <juce_audio_devices/juce_audio_devices.h>
#include "config/ProfileLoader.h"
#include "core/Converter.h"
#include "core/RigRuntime.h"
#include <atomic>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <thread>
#include <vector>
#if defined(_WIN32)
#include <windows.h>
#endif

namespace {
using namespace ddrum4;
struct MonitorLine { MidiEvent event{}; std::array<MidiEvent, Converter::maxOutputEvents> output{}; uint8_t outputCount{}; };
class MonitorQueue {
 public:
  void push(const MidiEvent& event, const std::array<MidiEvent, Converter::maxOutputEvents>& output, size_t outputCount) noexcept { const auto write=w_.load(std::memory_order_relaxed), next=(write+1)%slots; if(next==r_.load(std::memory_order_acquire)) { dropped_.fetch_add(1,std::memory_order_relaxed); return; } q_[write]={event,output,static_cast<uint8_t>(outputCount)}; w_.store(next,std::memory_order_release); }
  bool pop(MonitorLine& value) noexcept { const auto read=r_.load(std::memory_order_relaxed); if(read==w_.load(std::memory_order_acquire)) return false; value=q_[read]; r_.store((read+1)%slots,std::memory_order_release); return true; }
  uint64_t dropped() const noexcept { return dropped_.load(std::memory_order_relaxed); }
 private: static constexpr uint32_t slots=512; std::array<MonitorLine,slots> q_{}; std::atomic<uint32_t>w_{0},r_{0}; std::atomic<uint64_t>dropped_{0};
};
struct QueuedInput { MidiEvent event{}; uint8_t source{}; };
// Bounded MPSC queue: MIDI callbacks only claim a preallocated slot and copy
// bytes.  Conversion and all MIDI output run later on the message thread.
class InputQueue {
 public:
  static constexpr uint32_t slots=1024;
  InputQueue() { for(uint32_t i=0;i<slots;++i) q_[i].sequence.store(i,std::memory_order_relaxed); }
  bool push(const QueuedInput& value) noexcept { uint32_t pos=write_.load(std::memory_order_relaxed); for(;;) { auto& cell=q_[pos%slots]; const auto seq=cell.sequence.load(std::memory_order_acquire); const auto diff=static_cast<int32_t>(seq-pos); if(diff==0) { if(write_.compare_exchange_weak(pos,pos+1,std::memory_order_relaxed)) { cell.value=value; cell.sequence.store(pos+1,std::memory_order_release); return true; } } else if(diff<0) return false; else pos=write_.load(std::memory_order_relaxed); } }
  bool pop(QueuedInput& value) noexcept { auto& cell=q_[read_%slots]; if(cell.sequence.load(std::memory_order_acquire)!=read_+1) return false; value=cell.value; cell.sequence.store(read_+slots,std::memory_order_release); ++read_; return true; }
  void reset() noexcept { read_=0; write_.store(0,std::memory_order_relaxed); for(uint32_t i=0;i<slots;++i) q_[i].sequence.store(i,std::memory_order_relaxed); }
 private: struct Cell { std::atomic<uint32_t> sequence{}; QueuedInput value{}; }; std::array<Cell,slots> q_{}; std::atomic<uint32_t> write_{0}; uint32_t read_{};
};
std::filesystem::path findDefaultProfile() {
  const auto nextToApp=std::filesystem::path(juce::File::getSpecialLocation(juce::File::currentExecutableFile).getParentDirectory().getFullPathName().toStdString())/"config/ddrum4-template.yaml";
  if(std::filesystem::exists(nextToApp)) return nextToApp;
  return std::filesystem::current_path()/"config/ddrum4-template.yaml";
}
uint64_t nowMicroseconds() noexcept { const auto ticks=juce::Time::getHighResolutionTicks(); const auto rate=juce::Time::getHighResolutionTicksPerSecond(); return rate>0 ? static_cast<uint64_t>((static_cast<long double>(ticks)*1'000'000.0L)/rate) : 0; }
RuntimeRendererTarget runtimeRendererFromEnvironment() {
  const auto* value=std::getenv("DDRUM4_RENDERER_TARGET");
  if(!value || std::string_view{value}=="sd3") return RuntimeRendererTarget::Sd3;
  if(std::string_view{value}=="drumgizmo") return RuntimeRendererTarget::DrumGizmo;
  throw std::runtime_error("DDRUM4_RENDERER_TARGET must be sd3 or drumgizmo");
}
const char* runtimeRendererLabel(RuntimeRendererTarget target) noexcept {
  return target==RuntimeRendererTarget::DrumGizmo ? "DrumGizmo" : "SD3";
}
class Router final : private juce::MidiInputCallback {
 public:
  Router() { try { rendererTarget_=runtimeRendererFromEnvironment(); if(const auto* runtime=std::getenv("DDRUM4_RUNTIME_PROFILE")) profilePath_=runtime; else profilePath_=findDefaultProfile(); reload(); } catch(const std::exception& e) { error_=e.what(); } }
  ~Router() override { stop(); }
  const Profile* profile() const noexcept { return profile_.get(); }
  Converter* converter() const noexcept { return converter_.get(); }
  RuntimeHealth runtimeHealth() const noexcept { return runtime_ ? runtime_->health() : RuntimeHealth{}; }
  juce::String runtimeSourceHash() const { return runtimeProfile_ ? juce::String(runtimeProfile_->sourceSha256) : juce::String{}; }
  juce::String runtimeRenderer() const { return runtimeRendererLabel(rendererTarget_); }
  uint32_t queueDropped() const noexcept { return queueDropped_.load(std::memory_order_relaxed); }
  const std::filesystem::path& profilePath() const noexcept { return profilePath_; }
  juce::String error() const { return error_; }
  MonitorQueue& monitor() noexcept { return monitor_; }
  bool runtimeMode() const noexcept { return runtime_!=nullptr; }
  const RuntimeProfile* runtimeProfile() const noexcept { return runtimeProfile_.get(); }
  bool selectRuntimeScene(uint16_t scene) noexcept {
    if(!runtime_) return false;
    auto* bus=controlOutput_.load(std::memory_order_acquire);
    if(globalControlConfigured() && !bus) return false;
    if(!runtime_->selectScene(scene)) return false;
    if(bus)
      bus->sendMessageNow(juce::MidiMessage::programChange(runtimeProfile_->controlBusChannel, static_cast<int>(scene)));
    return true;
  }
  bool setRuntimeVariable(size_t index,uint8_t value) noexcept {
    if(!runtime_ || index>=runtimeProfile_->variables.size()) return false;
    auto* bus=controlOutput_.load(std::memory_order_acquire);
    if(globalControlConfigured() && !bus) return false;
    if(!runtime_->setVariableValue(index,value)) return false;
    if(bus)
      bus->sendMessageNow(juce::MidiMessage::controllerEvent(runtimeProfile_->controlBusChannel, runtimeProfile_->variables[index].cc, value));
    return true;
  }
  uint16_t runtimeScene() const noexcept { return runtime_ ? runtime_->scene() : 0; }
  uint8_t runtimeVariable(size_t index) const noexcept { return runtime_ ? runtime_->variable(index) : 0; }
  bool globalControlConfigured() const noexcept { return runtimeProfile_ && runtimeProfile_->controlBusEnabled; }
  bool globalControlOpen() const noexcept { return controlOutput_.load(std::memory_order_acquire)!=nullptr; }
  juce::String globalControlEndpoint() const { return runtimeProfile_ ? juce::String(runtimeProfile_->controlBusEndpoint) : juce::String{}; }
  bool startRuntimeByOutputName(std::string_view requested) {
    if(!runtimeProfile_) { error_="Automatic live start requires a rig runtime profile"; return false; }
    if(requested.empty()) { error_="DDRUM4_RENDERER_OUTPUT is empty"; return false; }
    const auto devices=juce::MidiOutput::getAvailableDevices();
    std::vector<const juce::MidiDeviceInfo*> matches;
    const auto exact=juce::String::fromUTF8(requested.data(),static_cast<int>(requested.size()));
    for(const auto& device:devices)
      if(device.name==exact||device.identifier==exact) matches.push_back(&device);
    if(matches.size()!=1) {
      error_=matches.empty()?"Automatic renderer output not found: "+exact:"Automatic renderer output is ambiguous: "+exact;
      return false;
    }
    start({},matches.front()->identifier);
    return running();
  }
  bool reload() {
    stop();
    try {
      runtime_.reset(); runtimeProfile_.reset(); profile_.reset(); converter_.reset();
      try {
        auto next=std::make_unique<RuntimeProfile>(loadRuntimeProfile(profilePath_,rendererTarget_));
        runtime_=std::make_unique<RigRuntime>(*next); runtimeProfile_=std::move(next);
        error_.clear(); return true;
      } catch(const std::exception& runtimeError) {
        if(rendererTarget_==RuntimeRendererTarget::DrumGizmo) throw;
        const auto message=std::string(runtimeError.what());
        try {
          auto next=std::make_unique<Profile>(loadProfile(profilePath_));
          auto converter=std::make_unique<Converter>(*next);
          profile_=std::move(next); converter_=std::move(converter);
          error_.clear(); return true;
        } catch(const std::exception&) { throw std::runtime_error(message); }
      }
    } catch(const std::exception& e) { error_=e.what(); return false; }
  }
  bool saveAndReload(const juce::String& text) {
    stop(); const auto temp=profilePath_.string()+".tmp";
    try {
      juce::File(temp).replaceWithText(text);
      try { (void)loadRuntimeProfile(temp,rendererTarget_); }
      catch(const std::exception&) {
        if(rendererTarget_==RuntimeRendererTarget::DrumGizmo) throw;
        (void)loadProfile(temp);
      }
      if(!juce::File(profilePath_.string()).replaceWithText(text)) throw std::runtime_error("unable to write profile");
      std::filesystem::remove(temp); return reload();
    } catch(const std::exception& e) {
      std::error_code ec; std::filesystem::remove(temp,ec); error_=e.what(); return false;
    }
  }
  void start(const juce::String& inputId,const juce::String& outputId) {
    stop(); if(!profile_&&!runtimeProfile_){error_="Profile is not loaded";return;} error_.clear();
    const auto endpoint=profile_?profile_->endpoint:"ddrum_runtime";
    outputOwned_=outputId=="__ddrum4_virtual__"?juce::MidiOutput::createNewDevice(endpoint):juce::MidiOutput::openDevice(outputId);
    if(!outputOwned_){error_="Unable to open selected MIDI output";return;}
    const auto devices=juce::MidiInput::getAvailableDevices();
    auto resolveRuntimeInput=[&](const std::string& requested)->const juce::MidiDeviceInfo* {
      const juce::String requestedName(requested);
      std::vector<const juce::MidiDeviceInfo*> matches;
      for(const auto& device:devices)
        if(device.name==requestedName||device.identifier==requestedName) matches.push_back(&device);
      if(matches.size()!=1) {
        error_=matches.empty() ? "Runtime input not found: "+juce::String(requested)
                               : "Runtime input is ambiguous: "+juce::String(requested);
        return nullptr;
      }
      return matches.front();
    };
    if(runtimeProfile_) {
      for(const auto& source:runtimeProfile_->sources) {
        if(std::find(inputEndpoints_.begin(),inputEndpoints_.end(),source.endpoint)!=inputEndpoints_.end()) continue;
        const auto* device=resolveRuntimeInput(source.endpoint);
        if(!device) { stop(); return; }
        auto opened=juce::MidiInput::openDevice(device->identifier,this);
        if(!opened) { error_="Unable to open runtime input"; stop(); return; }
        inputs_.push_back(std::move(opened)); inputEndpoints_.push_back(source.endpoint);
      }
    } else {
      auto opened=juce::MidiInput::openDevice(inputId,this);
      if(opened) { inputs_.push_back(std::move(opened)); inputEndpoints_.push_back("legacy"); }
    }
    if(inputs_.empty()){error_="Unable to open selected MIDI input";stop();return;}
    if(runtimeProfile_ && runtimeProfile_->controlBusEnabled) {
      const auto controlName=juce::String(runtimeProfile_->controlBusEndpoint);
      const auto outputDevices=juce::MidiOutput::getAvailableDevices();
      std::vector<const juce::MidiDeviceInfo*> matches;
      for(const auto& device:outputDevices)
        if(device.name==controlName || device.identifier==controlName) matches.push_back(&device);
      if(matches.size()!=1) { error_=matches.empty()?"Global control output not found: "+controlName:"Global control output is ambiguous: "+controlName; stop(); return; }
      if(matches.front()->identifier==outputId) { error_="Global control output must be distinct from renderer output"; stop(); return; }
      controlOutputOwned_=juce::MidiOutput::openDevice(matches.front()->identifier);
      if(!controlOutputOwned_) { error_="Unable to open global control output"; stop(); return; }
    }
    controlOutput_.store(controlOutputOwned_.get(),std::memory_order_release);
    output_.store(outputOwned_.get(),std::memory_order_release); running_.store(true,std::memory_order_release);
    publishCurrentLogicalState();
    worker_=std::thread([this]{ runWorker(); }); for(auto& input:inputs_) input->start();
  }
  void stop() { running_.store(false,std::memory_order_release); for(auto& input:inputs_) input->stop(); while(callbacks_.load(std::memory_order_acquire)!=0) std::this_thread::yield(); if(worker_.joinable()) worker_.join(); output_.store(nullptr,std::memory_order_release); controlOutput_.store(nullptr,std::memory_order_release); if(converter_) converter_->clearLedger(); if(runtime_) runtime_->clearLedger(); queue_.reset(); inputs_.clear(); inputEndpoints_.clear(); outputOwned_.reset(); controlOutputOwned_.reset(); }
  void panic() { clearLedgerRequested_.store(true,std::memory_order_release); if(auto* out=output_.load(std::memory_order_acquire)) for(int channel=1;channel<=16;++channel) out->sendMessageNow(juce::MidiMessage::allNotesOff(channel)); }
  bool running() const noexcept { return running_.load(std::memory_order_acquire); }
 private:
  std::filesystem::path profilePath_; RuntimeRendererTarget rendererTarget_{RuntimeRendererTarget::Sd3}; std::unique_ptr<Profile> profile_; std::unique_ptr<Converter> converter_; std::unique_ptr<RuntimeProfile> runtimeProfile_; std::unique_ptr<RigRuntime> runtime_; std::vector<std::unique_ptr<juce::MidiInput>> inputs_; std::vector<std::string> inputEndpoints_; std::unique_ptr<juce::MidiOutput> outputOwned_,controlOutputOwned_; std::atomic<juce::MidiOutput*> output_{nullptr},controlOutput_{nullptr}; std::atomic<bool> running_{false}; std::atomic<bool> clearLedgerRequested_{false}; std::atomic<uint32_t> callbacks_{0},queueDropped_{0}; std::thread worker_; juce::String error_; MonitorQueue monitor_; InputQueue queue_;
  void publishCurrentLogicalState() noexcept {
    auto* bus=controlOutput_.load(std::memory_order_acquire);
    if(!bus || !runtime_ || !runtimeProfile_ || !runtimeProfile_->controlBusEnabled) return;
    bus->sendMessageNow(juce::MidiMessage::programChange(runtimeProfile_->controlBusChannel, static_cast<int>(runtime_->scene())));
    for(size_t i=0;i<runtimeProfile_->variables.size();++i)
      bus->sendMessageNow(juce::MidiMessage::controllerEvent(runtimeProfile_->controlBusChannel, runtimeProfile_->variables[i].cc, runtime_->variable(i)));
  }
  void handleIncomingMidiMessage(juce::MidiInput* sender,const juce::MidiMessage& m) override {
    if(!running_.load(std::memory_order_acquire)) return; callbacks_.fetch_add(1,std::memory_order_acq_rel); const struct Guard{std::atomic<uint32_t>& n;~Guard(){n.fetch_sub(1,std::memory_order_release);}} guard{callbacks_};
    if(m.isMidiClock()||m.isMidiStart()||m.isMidiStop()||m.isMidiContinue()||m.isActiveSense()) return;
    MidiEvent input{}; input.channel=static_cast<uint8_t>(m.getChannel()); input.timestampUs=nowMicroseconds();
    if(m.isNoteOn()) input={MidiType::NoteOn,input.channel,static_cast<uint8_t>(m.getNoteNumber()),static_cast<uint8_t>(m.getVelocity()),input.timestampUs}; else if(m.isNoteOff()) input={MidiType::NoteOff,input.channel,static_cast<uint8_t>(m.getNoteNumber()),0,input.timestampUs}; else if(m.isController()) input={MidiType::ControlChange,input.channel,static_cast<uint8_t>(m.getControllerNumber()),static_cast<uint8_t>(m.getControllerValue()),input.timestampUs}; else if(m.isProgramChange()) input={MidiType::ProgramChange,input.channel,static_cast<uint8_t>(m.getProgramChangeNumber()),0,input.timestampUs}; else if(m.isAftertouch()) input={MidiType::PolyAftertouch,input.channel,static_cast<uint8_t>(m.getNoteNumber()),static_cast<uint8_t>(m.getAfterTouchValue()),input.timestampUs}; else return;
    uint8_t source=0; for(size_t i=0;i<inputs_.size();++i) if(inputs_[i].get()==sender) { source=static_cast<uint8_t>(i); break; }
    if(!queue_.push({input,source})) queueDropped_.fetch_add(1,std::memory_order_relaxed);
  }
  void runWorker() noexcept {
#if defined(_WIN32)
    ::SetThreadPriority(::GetCurrentThread(), THREAD_PRIORITY_HIGHEST);
#endif
    while(running_.load(std::memory_order_acquire)) { drainQueue(); std::this_thread::yield(); }
    drainQueue();
  }
  void drainQueue() noexcept { if(clearLedgerRequested_.exchange(false,std::memory_order_acq_rel)) { if(converter_) converter_->clearLedger(); if(runtime_) runtime_->clearLedger(); } QueuedInput queued; while(queue_.pop(queued)) { auto* destination=output_.load(std::memory_order_acquire); if(!destination) return; std::array<MidiEvent,Converter::maxOutputEvents> events{}; size_t n=0; if(runtime_) { std::array<MidiEvent,RigRuntime::maxOutputEvents> runtimeEvents{}; n=runtime_->processEndpoint(inputEndpoints_[queued.source],queued.event,runtimeEvents); for(size_t i=0;i<n;++i) events[i]=runtimeEvents[i]; } else if(converter_) n=converter_->process(queued.event,events); else continue; monitor_.push(queued.event,events,n); for(size_t i=0;i<n;++i) { const auto& e=events[i]; juce::MidiMessage result; switch(e.type){case MidiType::NoteOn:result=juce::MidiMessage::noteOn(e.channel,e.data1,(juce::uint8)e.data2);break;case MidiType::NoteOff:result=juce::MidiMessage::noteOff(e.channel,e.data1);break;case MidiType::ControlChange:result=juce::MidiMessage::controllerEvent(e.channel,e.data1,e.data2);break;case MidiType::PolyAftertouch:result=juce::MidiMessage::aftertouchChange(e.channel,e.data1,e.data2);break;case MidiType::ProgramChange:result=juce::MidiMessage::programChange(e.channel,e.data1);break;default:continue;} destination->sendMessageNow(result); } } }
};

class MainComponent final : public juce::Component, private juce::Timer {
 public:
  MainComponent() {
    setSize(920,620); setWantsKeyboardFocus(true);
    title_.setText("ddrum4 Converter",juce::dontSendNotification); title_.setFont(juce::FontOptions(27.0f,juce::Font::bold)); addAndMakeVisible(title_);
    for(auto* b:{&performance_,&mapping_,&programs_,&monitorTab_}) { addAndMakeVisible(*b); b->setColour(juce::TextButton::buttonColourId,juce::Colour(0xff303640)); }
    performance_.onClick=[this]{showPage(0);};mapping_.onClick=[this]{showPage(1);};programs_.onClick=[this]{showPage(2);};monitorTab_.onClick=[this]{showPage(3);};
    addAndMakeVisible(status_); addAndMakeVisible(input_);addAndMakeVisible(output_);addAndMakeVisible(start_);addAndMakeVisible(panic_);
    start_.onClick=[this]{toggle();};panic_.onClick=[this]{router_.panic();}; for(auto& b:kits_){addAndMakeVisible(b);}
    runtimeStateLabel_.setText("Logical state local to this PC",juce::dontSendNotification); addAndMakeVisible(runtimeStateLabel_);
    addAndMakeVisible(runtimeScene_); runtimeScene_.onChange=[this]{const auto index=runtimeScene_.getSelectedItemIndex(); if(index>=0) router_.selectRuntimeScene(static_cast<uint16_t>(index));};
    for(size_t i=0;i<runtimeVariables_.size();++i) {
      addAndMakeVisible(runtimeVariableLabels_[i]); addAndMakeVisible(runtimeVariables_[i]);
      runtimeVariables_[i].setSliderStyle(juce::Slider::LinearHorizontal); runtimeVariables_[i].setRange(0,127,1); runtimeVariables_[i].setTextBoxStyle(juce::Slider::TextBoxRight,false,50,22);
      runtimeVariables_[i].onValueChange=[this,i]{router_.setRuntimeVariable(i,static_cast<uint8_t>(runtimeVariables_[i].getValue()));};
    }
    refreshPorts(); buildEditor(); showPage(0);
    if(const auto* output=std::getenv("DDRUM4_RENDERER_OUTPUT")) router_.startRuntimeByOutputName(output);
    startTimerHz(20);
  }
  void paint(juce::Graphics& g) override { g.fillAll(juce::Colour(0xff15171b)); g.setColour(juce::Colour(0xff242a31)); g.fillRoundedRectangle(18,100,getWidth()-36,getHeight()-118,10); }
  void resized() override {
    title_.setBounds(24,18,300,42); int x=340; for(auto* b:{&performance_,&mapping_,&programs_,&monitorTab_}){b->setBounds(x,24,90,30);x+=94;}
    status_.setBounds(730,27,170,24); input_.setBounds(35,118,275,32);output_.setBounds(320,118,275,32);start_.setBounds(605,118,105,32);panic_.setBounds(720,118,105,32);
    for(int i=0;i<3;++i) kits_[i].setBounds(38+i*260,180,245,66);
    runtimeStateLabel_.setBounds(38,165,300,24); runtimeScene_.setBounds(38,195,245,28);
    for(size_t i=0;i<runtimeVariables_.size();++i) { runtimeVariableLabels_[i].setBounds(305,190+static_cast<int>(i)*42,180,28); runtimeVariables_[i].setBounds(490,190+static_cast<int>(i)*42,330,28); }
    config_.setBounds(36,165,845,330);apply_.setBounds(36,505,140,32);monitor_.setBounds(36,165,845,350);
    info_.setBounds(36,router_.runtimeMode()?370:265,845,router_.runtimeMode()?180:190);
  }
 private:
  Router router_; juce::Label title_,status_,info_,runtimeStateLabel_; juce::ComboBox input_,output_,runtimeScene_; juce::TextButton start_{"Start"},panic_{"Panic"},performance_{"Performance"},mapping_{"Mapping"},programs_{"Programs"},monitorTab_{"Monitor"},apply_{"Apply YAML"}; std::array<juce::TextButton,3> kits_{}; std::array<juce::Label,4> runtimeVariableLabels_{}; std::array<juce::Slider,4> runtimeVariables_{}; juce::TextEditor config_,monitor_; juce::String runtimeControlsHash_; int page_{};
  void buildEditor(){ config_.setMultiLine(true);config_.setColour(juce::TextEditor::backgroundColourId,juce::Colour(0xff101216));config_.setText(juce::File(router_.profilePath().string()).loadFileAsString(),false);addAndMakeVisible(config_);apply_.onClick=[this]{ if(router_.saveAndReload(config_.getText())) { runtimeControlsHash_.clear(); refreshPorts(); resized(); } refresh(); };addAndMakeVisible(apply_); monitor_.setMultiLine(true);monitor_.setReadOnly(true);monitor_.setColour(juce::TextEditor::backgroundColourId,juce::Colour(0xff101216));addAndMakeVisible(monitor_);addAndMakeVisible(info_); }
  void showPage(int next){page_=next; const bool play=page_==0, edit=page_==1, prog=page_==2, mon=page_==3, runtime=router_.runtimeMode(); input_.setVisible(play);output_.setVisible(play);start_.setVisible(play);panic_.setVisible(play); for(auto& b:kits_)b.setVisible((play||prog)&&!runtime); runtimeStateLabel_.setVisible((play||prog)&&runtime);runtimeScene_.setVisible((play||prog)&&runtime);for(size_t i=0;i<runtimeVariables_.size();++i){runtimeVariableLabels_[i].setVisible((play||prog)&&runtime);runtimeVariables_[i].setVisible((play||prog)&&runtime);}config_.setVisible(edit);apply_.setVisible(edit);monitor_.setVisible(mon);info_.setVisible(play||prog); refresh(); }
  void refreshPorts(){ const auto selectedIn=input_.getText(),selectedOut=output_.getText(); input_.clear();output_.clear();int id=1;for(const auto& d:juce::MidiInput::getAvailableDevices())input_.addItem(d.name,id++);output_.addItem("Create virtual port: "+juce::String(router_.profile()?router_.profile()->endpoint:"ddrum_converted"),1);id=2;for(const auto& d:juce::MidiOutput::getAvailableDevices())output_.addItem(d.name,id++);const auto* p=router_.profile(); auto choose=[](juce::ComboBox& box,const juce::String& old,const std::string& match){for(int i=0;i<box.getNumItems();++i)if(box.getItemText(i)==old||box.getItemText(i).containsIgnoreCase(match)){box.setSelectedItemIndex(i);return;}if(box.getNumItems())box.setSelectedItemIndex(0);};choose(input_,selectedIn,p?p->inputPortMatch:"");choose(output_,selectedOut,p?p->endpoint:""); }
  void toggle(){if(router_.running())router_.stop();else {const auto in=juce::MidiInput::getAvailableDevices(),out=juce::MidiOutput::getAvailableDevices();const int ii=input_.getSelectedItemIndex(),oi=output_.getSelectedItemIndex();if(ii>=0&&ii<(int)in.size()&&oi>=0)router_.start(in[(size_t)ii].identifier,oi==0?"__ddrum4_virtual__":(oi-1<(int)out.size()?out[(size_t)(oi-1)].identifier:juce::String{}));}refresh();}
  void refreshRuntimeControls(){
    const auto* runtime=router_.runtimeProfile();
    if(!runtime) return;
    const bool controlsEnabled=!router_.globalControlConfigured()||router_.globalControlOpen();
    const auto hash=router_.runtimeSourceHash();
    if(hash!=runtimeControlsHash_){
      runtimeScene_.clear(juce::dontSendNotification);
      for(size_t i=0;i<runtime->scenes.size();++i)
        runtimeScene_.addItem(juce::String(runtime->scenes[i]),static_cast<int>(i+1));
      for(size_t i=0;i<runtimeVariables_.size();++i){
        const bool present=i<runtime->variables.size();
        runtimeVariableLabels_[i].setText(present?juce::String(runtime->variables[i].name):"",juce::dontSendNotification);
      }
      runtimeControlsHash_=hash;
    }
    runtimeScene_.setSelectedItemIndex(router_.runtimeScene(),juce::dontSendNotification);
    for(size_t i=0;i<runtimeVariables_.size();++i)
      if(i<runtime->variables.size()) runtimeVariables_[i].setValue(router_.runtimeVariable(i),juce::dontSendNotification);
    runtimeScene_.setEnabled(controlsEnabled);
    for(size_t i=0;i<runtimeVariables_.size();++i){
      const bool present=i<runtime->variables.size();
      runtimeVariableLabels_[i].setEnabled(present&&controlsEnabled);
      runtimeVariables_[i].setEnabled(present&&controlsEnabled);
    }
  }
  void refresh(){const auto* p=router_.profile();const auto* c=router_.converter();const auto active=c?c->activeKit():0;for(size_t i=0;i<kits_.size();++i){juce::String label="—";if(p&&i<p->kits.size()){label=p->kits[i].label;for(const auto& binding:p->programs)if(binding.kitIndex==i){label+="  · PC "+juce::String(binding.program);break;}}kits_[i].setButtonText(label);kits_[i].onClick=[this,i]{if(auto*c=router_.converter())c->selectKit(i,"UI");};kits_[i].setEnabled(p&&i<p->kits.size());}status_.setText(router_.running()?"● CONNECTED":"● STOPPED",juce::dontSendNotification);start_.setButtonText(router_.running()?"Stop":"Start"); juce::String detail=juce::String("Profile: ")+juce::String(router_.profilePath().string())+"\n"; if(router_.runtimeMode()) { refreshRuntimeControls(); const auto h=router_.runtimeHealth(); detail+="Renderer: "+router_.runtimeRenderer()+"\n"; if(router_.globalControlOpen()) detail+="Global control: port open to "+router_.globalControlEndpoint()+"; state published, unverified (logical CH14/15 only).\n"; else if(router_.globalControlConfigured()) detail+="Global control: configured for "+router_.globalControlEndpoint()+"; start required, controls are locked until the port is open.\n"; else detail+="Global control: local only; a user-confirmed live control_bus is required.\n"; detail+=juce::String("Runtime: ")+juce::String((juce::int64)h.received)+" received, "+juce::String((juce::int64)h.rendered)+" rendered, echoes "+juce::String((juce::int64)h.echoes)+", drops "+juce::String(router_.queueDropped()); if(router_.runtimeSourceHash().isNotEmpty()) detail+="\nSource SHA-256: "+router_.runtimeSourceHash(); } else if(p&&c) { detail=juce::String("Active kit: ")+juce::String(p->kits[active].label)+"  · origin: "+c->lastProgramOrigin()+"\n"+detail; } detail+="\n"; detail+=router_.error().isEmpty()?juce::String("Select the source input and renderer output. A live control bus is opened separately only when confirmed."):router_.error(); info_.setText(detail,juce::dontSendNotification); }
  void timerCallback() override {MonitorLine line;bool changed=false;while(router_.monitor().pop(line)){juce::String text="IN ch"+juce::String(line.event.channel)+" d"+juce::String(line.event.data1)+" v"+juce::String(line.event.data2)+"  | OUT ";for(uint8_t i=0;i<line.outputCount;++i){const auto&e=line.output[i];text+="ch"+juce::String(e.channel)+" d"+juce::String(e.data1)+" v"+juce::String(e.data2)+(i+1<line.outputCount?" · ":"");}if(line.outputCount==0)text+="filtered";monitor_.moveCaretToEnd();monitor_.insertTextAtCaret(text+"\n");changed=true;}if(changed&&monitor_.getTotalNumChars()>24000)monitor_.setText(monitor_.getTextInRange({monitor_.getTotalNumChars()-18000,18000}),false);refresh();}
};
class App final:public juce::JUCEApplication{public:const juce::String getApplicationName()override{return "ddrum4 Converter";}const juce::String getApplicationVersion()override{return "0.2.0";}void initialise(const juce::String&)override{window_=std::make_unique<Window>(getApplicationName(),std::make_unique<MainComponent>(),*this);}void shutdown()override{window_.reset();}private:class Window final:public juce::DocumentWindow{public:Window(const juce::String& name,std::unique_ptr<juce::Component> content,App& app):DocumentWindow(name,juce::Colour(0xff15171b),allButtons),app_(app){setUsingNativeTitleBar(true);setContentOwned(content.release(),true);centreWithSize(getWidth(),getHeight());setVisible(true);}void closeButtonPressed()override{app_.systemRequestedQuit();}App&app_;};std::unique_ptr<Window>window_;};
}
START_JUCE_APPLICATION(App)
