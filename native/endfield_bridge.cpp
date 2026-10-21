// Retained source UI adapter. The original renderer/session remain unchanged.
// This host owns one render thread and a nonactivating child visual. It never
// publishes robot commands, captures the desktop, installs fonts or runs a game.
#include "core/watch_runtime_input.hpp"
#include "core/source_desktop_chrome.hpp"
#include "app/source_watch_session.hpp"
#include "native/renderer.hpp"
#include "native/source_graphics.hpp"
#include "native/source_scene.hpp"
#include "native/watch_content.hpp"
#include "native/watch_presentation.hpp"
#include "native/chrome_presentation.hpp"
#include <windows.h>
#include <windowsx.h>
#include <atomic>
#include <thread>
#include <mutex>
#include <deque>
#include <map>
#include <memory>
#include <fstream>
#include <cmath>
#include <algorithm>
#include <cstdio>
#include <cstring>

namespace fs=std::filesystem;
namespace src=endfield::core::source;
namespace gpu=endfield::native;
namespace core=endfield::core;
using Json=ehud::data::Json;
using endfield::app::SourceWatchSession;
namespace {
double clockNow(){static const double f=[](){LARGE_INTEGER v;QueryPerformanceFrequency(&v);return double(v.QuadPart);}();LARGE_INTEGER v;QueryPerformanceCounter(&v);return v.QuadPart/f;}
struct Event{int kind{};double x{},y{},value{};};
struct Shared {
    HWND parent{};fs::path root;bool offscreen{};
    std::atomic<bool> stop{},wanted{},paused{};
    std::atomic<int> status{},phase{},action{}; // status 0 loading,1 ready,-1 fault,2 retired
    std::atomic<std::uint64_t> requestEpoch{},closedEpoch{};
    std::atomic<unsigned> width{1280},height{720};
    std::atomic<std::uint64_t> frames{},textures{},meshes{};
    std::atomic<double> lastMS{};
    std::atomic<int> hoverCode{};std::atomic<std::uint64_t> hoverChanges{};
    std::mutex mutex;std::deque<Event> events;std::string error,context,capture;
    std::atomic<int> captureState{};
    int probeCode{},probeReady{};std::array<double,4> probeRect{};
    void push(Event e){std::lock_guard lock(mutex);if(e.kind==1&&!events.empty()&&events.back().kind==1)events.back()=e;else if(events.size()<64)events.push_back(e);else events.clear();}
};
std::mutex registryMutex;std::map<std::uint64_t,std::shared_ptr<Shared>> registry;std::atomic<std::uint64_t> sequence{1};
std::shared_ptr<Shared> get(std::uint64_t id){std::lock_guard lock(registryMutex);const auto i=registry.find(id);return i==registry.end()?nullptr:i->second;}
std::atomic<unsigned> live{};

struct Action {const char* target;const char* en;const char* zh;int code;};
constexpr Action actions[]{
    {"system","Settings","系统设置",2},{"display","Display","显示设置",6},{"hotkeys","Key bindings","快捷键",5},{"about","Changelog","更新日志",7},
    {"storage","Inventory","模块背包",10},{"activityMonitor","Match readiness","比赛就绪",12},
    {"notes","ClickGUI","功能列表",11},{"fileShelf","Economy","经济补给",8},{"clipboard","Tactical map","战术地图",9},
    {"archive","HUD","战斗界面",13},{"mediaAssembly","Hero deployment","英雄部署",14},{"minigame","Minecraft HUD","MC 战斗界面",15},
    {"nowPlaying","Audio","声音设置",16},{"volume","Audio","声音设置",16},{"projection","Camera","图传画面",17},
    {"reader","Changelog","更新日志",7},{"calendar","Match timer","比赛计时",18},{"eventLog","Messages","比赛消息",19},
    {"map","Tactical map","战术地图",9},{"workMode","Scenario","运行场景",20},{"power","Readiness","就绪检查",12},
    {"profile","Readiness","就绪检查",12},{"account","Scenario","运行场景",20},
    {"addApp","Return to startup","返回启动页",3}};

std::string flat(std::string value){for(auto& c:value)if(c=='\n'||c=='\r'||c=='\t')c=' ';return value;}

void replaceText(Json& value,const std::map<std::string,std::string,std::less<>>& replacements){
    if(value.isObject()){
        if(value["text"].isObject()&&value["text"]["string"].isString()){
            const auto i=replacements.find(flat(value["text"]["string"].string()));
            if(i!=replacements.end()){value["text"]["string"]=i->second;value["text"]["runs"]=Json::Array{};}
        }
        auto children=value["children"].array();for(auto& c:children)replaceText(c,replacements);if(value.contains("children"))value["children"]=std::move(children);
    }
}
void localize(Json& frame,bool chinese){
    std::map<std::string,std::string,std::less<>> replacements;
    auto navigation=frame["nativeNavigation"].array();
    for(auto& row:navigation){
        for(const auto& a:actions)if(row["target"].string()==a.target){
            replacements[row["title"].string()]=chinese?a.zh:a.en;row["title"]=chinese?a.zh:a.en;break;
        }
    }
    frame["nativeNavigation"]=std::move(navigation);
    replacements["Endministrator"]="POLAR-RM";replacements["60"]="RM";
    replacements["UID: 1000000000"]=chinese?"选手端 · UI":"OPERATOR · UI";
    replacements["Authority"]="CONTROL";replacements["MAX"]="UI ONLY";
    replaceText(frame["nativeLayers"],replacements);
}

class Host;
LRESULT CALLBACK windowProc(HWND window,UINT message,WPARAM w,LPARAM l);
class Host {
public:
    std::shared_ptr<Shared> shared;HWND window{};
    src::WatchRuntimeInput input;gpu::SourceScene materials;
    gpu::Renderer renderer;gpu::LayerRasterizer raster;
    gpu::LayerScene layers,chromeLayers;
    src::WatchAnimation animation;
    std::unique_ptr<src::NativeLabelPlan> labelPlan;
    std::unique_ptr<gpu::WatchLabelPresentation> labels;
    std::unique_ptr<gpu::WatchContentCatalog> catalog;
    std::unique_ptr<gpu::NativeWatchContent> content;
    std::unique_ptr<SourceWatchSession> session;
    std::unique_ptr<src::DesktopChromeProjectionPlan> chromePlan;
    std::unique_ptr<gpu::NativeChromePresentation> chrome;
    gpu::WatchMaterialPresentation presentation;
    Json top,bottom,chromeSource;
    gpu::LayerRasterOptions options;
    std::vector<gpu::DrawObject> draws;
    std::vector<gpu::WatchButtonAvailability> available;
    std::map<std::uint64_t,int> actionCodes;
    std::string appliedContext,mode="RMUC7v7",mapMode;bool chinese{},shown{},lastWanted{},confirm{};
    double opened{},closed{},lastClock{-1};unsigned width{},height{};int selected{};
    bool hasMap{};core::Matrix4 modelToLocal;gpu::DrawObject mapDraw;
    std::string observedHover;std::optional<core::Point> pointer;bool trackingMouse{};
    Host(std::shared_ptr<Shared> s):shared(std::move(s)),input(shared->root/"resources/shell/runtime-input"),
        materials(gpu::CompiledSourceScene{shared->root/"resources/shell/catalog.ehscene",{}}),
        raster(shared->root/"fonts"),layers(raster),chromeLayers(raster),animation(input.scene(),input.library()),presentation(materials){
        if(materials.provenance().packetSHA256!=input.sourceManifestSHA256())throw std::runtime_error("Native source provenance differs");
        try { width=shared->width;height=shared->height;
        WNDCLASSW c{};c.lpfnWndProc=windowProc;c.hInstance=GetModuleHandleW(nullptr);c.lpszClassName=L"PolarEndfieldSourceVisual";
        if(!RegisterClassW(&c)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)throw std::runtime_error("Cannot register source visual");
        window=CreateWindowExW(WS_EX_NOREDIRECTIONBITMAP|WS_EX_NOACTIVATE|WS_EX_NOPARENTNOTIFY,
            c.lpszClassName,L"POLAR original source UI",shared->offscreen?WS_POPUP:WS_CHILD,0,0,width,height,shared->parent,nullptr,c.hInstance,this);
        if(!window)throw std::runtime_error("Cannot create source visual");
        renderer.initialize(window,width,height,{gpu::Driver::hardware,shared->root/"resources/shell/hud.hlsl",
            shared->offscreen?gpu::RenderTarget::offscreenForTests:gpu::RenderTarget::composition});
        options.assetRoot=input.assetRoot();options.pixelsPerPoint=2;
        rebuild(false);materials.upload(renderer.sourceGraphics());
        // Background stays in the client's existing GPU compositor. No desktop
        // capture, alternate glass shader or framebuffer readback is installed.
        renderer.setCamera(gpu::layerViewportProjection(width,height));
        shared->status=1;
        }catch(...){renderer.reset();if(window){DestroyWindow(window);window=nullptr;}throw;}
    }
    ~Host(){session.reset();content.reset();labels.reset();chrome.reset();renderer.reset();if(window)DestroyWindow(window);}
    void rebuild(bool zh){
        chinese=zh;top=input.nativeTop();bottom=input.nativeBottom();chromeSource=input.chrome();localize(top,chinese);localize(bottom,chinese);
        std::map<std::string,std::string,std::less<>> title{{"ENDFIELDHUD","POLAR-RM"},{"ENDFIELD HUD","POLAR-RM"}};
        replaceText(chromeSource["header"],title);
        content.reset();labels.reset();catalog.reset();session.reset();chrome.reset();chromePlan.reset();labelPlan.reset();
        layers.load(top["nativeLayers"],options);
        auto bindings=src::nativeLabelBindingsFromExport(input.scene(),input.nativeButtons(),top["nativeLayers"],top["nativeProfileBindings"]);
        labelPlan=std::make_unique<src::NativeLabelPlan>(input.scene(),std::move(bindings));
        labels=std::make_unique<gpu::WatchLabelPresentation>(*labelPlan,layers);
        std::array snapshots{gpu::WatchContentSnapshot{&top,1},gpu::WatchContentSnapshot{&bottom,0}};
        catalog=std::make_unique<gpu::WatchContentCatalog>(input.scene(),input.document(),labelPlan->bindings(),snapshots);
        session=std::make_unique<SourceWatchSession>(input.scene(),input.document(),input.library(),input.camera(),input.resources(),input.animators(),input.controllerTransitions(),input.profile(),input.desktopSettings());
        const auto& nav=catalog->navigation();endfield::app::WatchSessionNavigation navigation{nav.fixedActions,nav.rightActions,nav.managedButtons};
        if(input.profile())if(const auto action=catalog->actionForTarget("profile"))navigation.fixedActions[input.profile()->rootID]=*action;
        for(const auto& n:input.scene().nodes())if(input.document().component("UIButton",n.id)&&
            (n.name=="QuitBtn"||n.path.ends_with("/FullScreenCloseBtn")||n.path.ends_with("/CloseButtonNode/Btn_BackNode")))navigation.fixedActions[n.id]=n.name=="QuitBtn"?10002:10001;
        session->setNavigation(std::move(navigation),clockNow());
        content=std::make_unique<gpu::NativeWatchContent>(*catalog,layers,options);
        actionCodes.clear();actionCodes[10001]=1;actionCodes[10002]=4;
        for(const auto& e:catalog->entries())for(const auto& a:actions)if(e.target==a.target)actionCodes[e.action]=a.code;
        auto empty=top["nativeLayers"];empty["children"]=Json::Array{};
        chromeLayers.load(gpu::NativeChromePresentation::combinedReferenceRoot(empty,chromeSource),options);
        chromePlan=std::make_unique<src::DesktopChromeProjectionPlan>(input.scene(),input.camera(),animation,src::DesktopChromeBindings::fromJson(chromeSource["bindings"]));
        chrome=std::make_unique<gpu::NativeChromePresentation>(*chromePlan,chromeLayers,chromeSource,options);
        layers.uploadResources(renderer);chromeLayers.uploadResources(renderer);
        available.clear();for(const auto& id:labelPlan->buttonIDs())available.push_back({id,true,false});lastClock=-1;
    }
    void context(){
        std::string next;{std::lock_guard lock(shared->mutex);next=shared->context;}
        if(next==appliedContext||next.empty())return;
        const auto value=Json::parse(next,4096);const bool zh=value["chinese"].isBool()&&value["chinese"].boolean();
        if(zh!=chinese){const bool was=shown;rebuild(zh);if(was){session->open(clockNow(),0);session->setInputEnabled(true,clockNow());}}
        const auto proposed=value["mode"].isString()?value["mode"].string():"RMUC7v7";
        if(proposed!="RMUC7v7"&&proposed!="RMUL3v3"&&proposed!="RMUL1v1")throw std::invalid_argument("Unknown RM field mode");
        mode=proposed;appliedContext=std::move(next);
    }
    template<class T>void read(std::ifstream& f,T& value){f.read(reinterpret_cast<char*>(&value),sizeof(value));if(!f)throw std::runtime_error("Truncated field mesh");}
    void loadMap(){
        if(mapMode==mode)return;hasMap=false;mapMode=mode;
        std::ifstream file(shared->root.parent_path()/"maps"/(mode+".efmesh"),std::ios::binary);
        if(!file)throw std::runtime_error("Prepared official RM mesh missing: "+mode);
        char magic[8];file.read(magic,8);if(std::string_view(magic,8)!="PRMESH01")throw std::runtime_error("Invalid RM mesh format");
        std::uint32_t vertices,indices;read(file,vertices);read(file,indices);
        if(vertices>360000||indices>360000||indices%3)throw std::runtime_error("RM mesh exceeds budget");
        for(auto& x:modelToLocal.values)read(file,x);
        std::vector<gpu::Vertex> v(vertices);std::vector<std::uint32_t> i(indices);
        file.read(reinterpret_cast<char*>(v.data()),v.size()*sizeof(gpu::Vertex));file.read(reinterpret_cast<char*>(i.data()),i.size()*4);
        if(!file||file.peek()!=EOF||!modelToLocal.finite())throw std::runtime_error("Invalid RM mesh payload");
        renderer.setMesh("polar.field",1+static_cast<unsigned>(mode=="RMUL3v3"?1:mode=="RMUL1v1"?2:0),{v,i});
        mapDraw.sourceID="polar.field";mapDraw.meshID="polar.field";mapDraw.opacity=1;hasMap=true;
    }
    void activate(std::uint64_t id){const auto i=actionCodes.find(id);if(i!=actionCodes.end())shared->action=i->second;}
    void observeHover(){
        const auto hovered=session->hovered();const auto id=hovered.value_or(std::string_view{});
        if(id==observedHover)return;
        observedHover=id;++shared->hoverChanges;int code=hovered?-1:0;
        if(hovered){const auto action=session->actions().find(std::string(id));
            if(action!=session->actions().end()){const auto found=actionCodes.find(action->second);if(found!=actionCodes.end())code=found->second;}}
        shared->hoverCode=code;
    }
    void event(Event e,double now){
        // Pointer position is retained input, not a one-frame event. A real
        // leave clears it; modal blocking suppresses interaction, not tracking.
        if(e.kind==6){pointer.reset();session->pointerMove(std::nullopt,now);return;}
        if(e.kind>=1&&e.kind<=4)pointer=core::Point{e.x,e.y};
        if(shared->paused||!lastWanted)return;
        const core::Point p{e.x,e.y};
        if(e.kind==1)session->pointerMove(p,now);
        else if(e.kind==2)session->pointerDown(p,now);
        else if(e.kind==3){if(const auto result=session->pointerUp(p,now))activate(result->action);}
        else if(e.kind==4){session->pointerMove(p,now);session->wheel(p,e.value,3,now);}
        else if(e.kind==5){
            if(e.value==0){shared->action=1;return;}
            std::vector<std::string> ids;for(const auto& [id,a]:session->actions())if(actionCodes.contains(a)&&session->buttonFrame(std::array{id}))ids.push_back(id);
            if(ids.empty())return;
            if(e.value==1||e.value==-1){selected=(selected+(e.value>0?1:-1)+int(ids.size()))%int(ids.size());const std::array one{ids[selected]};if(const auto r=session->buttonFrame(one)){pointer=core::Point{r->x+r->width/2,r->y+r->height/2};session->pointerMove(pointer,now);}}
            else if(e.value==2){if(const auto r=session->activate(ids[selected],now))activate(r->action);}
        }
    }
    void step(double now){
        context();
        const auto w=shared->width.load(),h=shared->height.load();
        if(w!=width||h!=height){width=w;height=h;SetWindowPos(window,HWND_TOP,0,0,w,h,SWP_NOACTIVATE);renderer.resize(w,h);renderer.setCamera(gpu::layerViewportProjection(w,h));}
        bool want;std::uint64_t epoch;
        {std::lock_guard lock(shared->mutex);want=shared->wanted;epoch=shared->requestEpoch;}
        // Reversals wait for the authored finite clip to reach its endpoint;
        // never jump from an intermediate entrance to a fully-open exit pose.
        const bool transitioning=session->phase()==core::VisibilityPhase::opening||session->phase()==core::VisibilityPhase::closing;
        if(want!=lastWanted&&!transitioning){lastWanted=want;selected=0;shared->action=0;
            if(want){loadMap();opened=now;session->open(now,0);session->setInputEnabled(true,now);if(!shared->offscreen)ShowWindow(window,SW_SHOWNOACTIVATE);shown=true;}
            else{closed=now;session->close(now);session->setInputEnabled(false,now);}}
        if(want&&mapMode!=mode)loadMap();
        session->setEnvironment({{double(width),double(height)},shown,true,true,shared->paused,
            want&&!shared->paused?pointer:std::nullopt},now);
        session->setInputEnabled(want&&!shared->paused,now);
        std::deque<Event> events;{std::lock_guard lock(shared->mutex);events.swap(shared->events);}for(auto e:events){event(e,now);observeHover();}
        const auto* frame=session->sample(now);
        observeHover();
        if(!frame||!frame->sourceFrame){if(shown){ShowWindow(window,SW_HIDE);renderer.releaseFrameTargets();shown=false;pointer.reset();}shared->phase=0;if(!want)shared->closedEpoch=epoch;return;}
        shared->phase=want?1:2;
        if(content->update(session->actions()))layers.uploadResources(renderer);
        for(auto& item:available){const auto action=session->actions().find(std::string(item.buttonID));item.enabled=action!=session->actions().end()||input.profile()&&input.profile()->rootID==item.buttonID;
            item.expandFileShelfCaption=false;}
        labels->update(*frame->sourceFrame,frame->camera,{0,0,double(width),double(height)},available);
        // Explicit owned-target diagnostic/accessibility query only. No
        // per-frame hit-map allocation or scene serialization in normal use.
        int probe;{std::lock_guard lock(shared->mutex);probe=shared->probeCode;}
        if(probe){for(const auto& [id,action]:session->actions()){
            const auto code=actionCodes.find(action);if(code!=actionCodes.end()&&code->second==probe){
                if(const auto r=session->buttonFrame(std::array{id})){
                    std::lock_guard lock(shared->mutex);shared->probeRect={r->x,r->y,r->width,r->height};shared->probeReady=probe;shared->probeCode=0;
                }break;}}}
        src::DesktopChromeSettings settings;settings.viewport={0,0,double(width),double(height)};settings.module=core::Module::map;
        settings.contentScale=src::desktopContentScale(input.camera(),settings.viewport);
        const float opacity=float(src::DesktopChromeTiming::opacity(want,now-(want?opened:closed)));
        if(int(now)!=int(lastClock)){SYSTEMTIME t;GetLocalTime(&t);char time[32],date[32];snprintf(time,sizeof(time),"%02u:%02u:%02u",t.wHour,t.wMinute,t.wSecond);snprintf(date,sizeof(date),"%04u / %02u / %02u",t.wYear,t.wMonth,t.wDay);
            gpu::DesktopChromeContent text;text.reading=src::DesktopClockReading{time,date};text.localizedClose=chinese?"返回战斗":"Return to combat";
            if(chrome->setContent(text))chromeLayers.uploadResources(renderer);lastClock=now;}
        chrome->update(*frame->sourceFrame,frame->camera,settings,opacity);
        draws.clear();
        if(hasMap&&chromePlan->projection().center&&chromePlan->projection().status){
            const auto layout=src::DesktopChromeLayout::make(settings,*chromePlan->projection().center,*chromePlan->projection().status);
            mapDraw.world=layout.moduleLocalToScreen*modelToLocal;mapDraw.opacity=opacity;
            mapDraw.masks={gpu::PlaneMask{src::inverseSourceMatrix(layout.moduleLocalToScreen),{0,0,440,440},220}};
            draws.push_back(mapDraw);
        }
        const auto append=[&](auto values){draws.insert(draws.end(),values.begin(),values.end());};append(layers.prepareDraws());append(chromeLayers.prepareDraws());
        renderer.setDrawList(draws);
        gpu::SourceFrameParameters params;params.camera=frame->gpuCamera;params.width=width;params.height=height;params.timeSeconds=frame->shaderTime;
        presentation.update(*frame->sourceFrame,params);materials.flush(renderer.sourceGraphics());
        renderer.draw(!shared->offscreen);
        std::string capture;{std::lock_guard lock(shared->mutex);capture.swap(shared->capture);}
        if(!capture.empty()){
            try{const auto path=fs::u8path(capture);if(fs::exists(path))throw std::runtime_error("Capture output exists");
                if(!shared->offscreen)renderer.draw(false);
                const auto pixels=renderer.readback();std::ofstream file(path,std::ios::binary);
                for(unsigned row=0;row<height;++row)file.write(reinterpret_cast<const char*>(pixels.pixels.data())+row*pixels.rowBytes,width*4);
                if(!file)throw std::runtime_error("Capture write failed");shared->captureState=1;
            }catch(const std::exception& e){std::lock_guard lock(shared->mutex);shared->error=e.what();shared->captureState=-1;}
        }
        const auto stats=renderer.stats();shared->textures=stats.textures;shared->meshes=stats.meshes;++shared->frames;
    }
};
LRESULT CALLBACK windowProc(HWND w,UINT m,WPARAM a,LPARAM b){
    auto* host=reinterpret_cast<Host*>(GetWindowLongPtrW(w,GWLP_USERDATA));
    if(m==WM_NCCREATE){host=static_cast<Host*>(reinterpret_cast<CREATESTRUCTW*>(b)->lpCreateParams);SetWindowLongPtrW(w,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(host));}
    if(m==WM_MOUSEACTIVATE)return MA_NOACTIVATE;
    if(host){const double x=GET_X_LPARAM(b),y=GET_Y_LPARAM(b);
        if(m==WM_MOUSEMOVE){
            if(!host->trackingMouse){TRACKMOUSEEVENT tracking{sizeof(TRACKMOUSEEVENT),TME_LEAVE,w,0};host->trackingMouse=TrackMouseEvent(&tracking)!=0;}
            host->shared->push({1,x,y,0});
        }
        else if(m==WM_MOUSELEAVE){host->trackingMouse=false;host->shared->push({6,0,0,0});}
        else if(m==WM_LBUTTONDOWN){SetCapture(w);host->shared->push({2,x,y,0});}
        else if(m==WM_LBUTTONUP){ReleaseCapture();host->shared->push({3,x,y,0});}
        else if(m==WM_MOUSEWHEEL){POINT p{LONG(x),LONG(y)};ScreenToClient(w,&p);host->shared->push({4,double(p.x),double(p.y),GET_WHEEL_DELTA_WPARAM(a)/120.});}
    }
    return DefWindowProcW(w,m,a,b);
}
void run(std::shared_ptr<Shared> s){
    ++live;const HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    try{{Host host(s);while(!s->stop){MSG msg;while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}
        const double begin=clockNow();host.step(begin);s->lastMS=(clockNow()-begin)*1000;
        MsgWaitForMultipleObjectsEx(0,nullptr,s->phase?1:25,QS_ALLINPUT,MWMO_INPUTAVAILABLE);}}}
    catch(const std::exception& e){{std::lock_guard lock(s->mutex);s->error=e.what();}s->status=-1;s->phase=0;}
    if(SUCCEEDED(com))CoUninitialize();if(s->status!=-1)s->status=2;--live;
}
}
#define API extern "C" __declspec(dllexport)
API std::uint64_t pe_create(std::uintptr_t parent,const char* root,unsigned width,unsigned height,int offscreen){
    try{if(!root||width<320||height<240||width>8192||height>8192||std::uint64_t(width)*height>16*1024*1024)return 0;
        auto s=std::make_shared<Shared>();s->parent=reinterpret_cast<HWND>(parent);s->root=fs::u8path(root);s->width=width;s->height=height;s->offscreen=offscreen!=0;
        const auto id=sequence++;{std::lock_guard lock(registryMutex);registry[id]=s;}std::thread(run,s).detach();return id;}catch(...){return 0;}}
API int pe_status(std::uint64_t id){auto s=get(id);return s?s->status.load():2;}
API int pe_phase(std::uint64_t id){auto s=get(id);if(!s)return 0;const int phase=s->phase.load();return phase?phase:s->requestEpoch!=s->closedEpoch?3:0;}
API int pe_action(std::uint64_t id){auto s=get(id);return s?s->action.exchange(0):0;}
API void pe_visible(std::uint64_t id,int visible){if(auto s=get(id)){std::lock_guard lock(s->mutex);s->wanted=visible!=0;++s->requestEpoch;}}
API void pe_pause(std::uint64_t id,int paused){if(auto s=get(id))s->paused=paused!=0;}
API void pe_resize(std::uint64_t id,unsigned w,unsigned h){if(w>=320&&h>=240&&w<=8192&&h<=8192&&std::uint64_t(w)*h<=16*1024*1024)if(auto s=get(id)){s->width=w;s->height=h;}}
API void pe_input(std::uint64_t id,int kind,double x,double y,double value){if(std::isfinite(x)&&std::isfinite(y)&&std::isfinite(value))if(auto s=get(id))s->push({kind,x,y,value});}
API void pe_context(std::uint64_t id,const char* value){if(!value||strlen(value)>4096)return;if(auto s=get(id)){std::lock_guard lock(s->mutex);s->context=value;}}
API const char* pe_error(std::uint64_t id){static thread_local std::string error;if(auto s=get(id)){std::lock_guard lock(s->mutex);error=s->error;}else error="Native source owner retired";return error.c_str();}
API void pe_stats(std::uint64_t id,double* values){if(!values)return;if(auto s=get(id)){values[0]=double(s->frames);values[1]=s->lastMS;values[2]=double(s->textures);values[3]=double(s->meshes);values[4]=double(live);}}
// Bounded owned-session diagnostic; no scene serialization or framebuffer copy.
API void pe_hover(std::uint64_t id,double* values){if(values)if(auto s=get(id)){values[0]=s->hoverCode;values[1]=double(s->hoverChanges);}}
API void pe_destroy(std::uint64_t id){if(auto s=get(id)){s->stop=true;s->wanted=false;}}
API void pe_release(std::uint64_t id){auto s=get(id);if(!s||s->status==2||s->status==-1){std::lock_guard lock(registryMutex);registry.erase(id);}}
API void pe_capture(std::uint64_t id,const char* path){if(path&&strlen(path)<4096)if(auto s=get(id)){std::lock_guard lock(s->mutex);s->capture=path;s->captureState=0;}}
API int pe_captured(std::uint64_t id){auto s=get(id);return s?s->captureState.load():-1;}
API int pe_button(std::uint64_t id,int code,double* rect){if(!rect||code<1||code>20)return 0;if(auto s=get(id)){std::lock_guard lock(s->mutex);
    if(s->probeReady==code){std::copy(s->probeRect.begin(),s->probeRect.end(),rect);s->probeReady=0;return 1;}s->probeCode=code;}return 0;}
