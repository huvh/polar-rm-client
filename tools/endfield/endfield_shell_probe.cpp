// Noninteractive, owned-window probe. All presentation algorithms are upstream.
#include "core/watch_runtime_input.hpp"
#include "app/source_watch_session.hpp"
#include "native/renderer.hpp"
#include "native/source_scene.hpp"
#include "native/source_graphics.hpp"
#include "native/watch_presentation.hpp"
#include "native/watch_content.hpp"
#include "native/layer_scene.hpp"
#include "native/layer_raster.hpp"
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <cmath>

namespace fs = std::filesystem;
namespace source = endfield::core::source;
namespace gpu = endfield::native;
using endfield::app::SourceWatchSession;

class OwnedWindow {
public:
    OwnedWindow() {
        WNDCLASSW c{}; c.lpfnWndProc = DefWindowProcW; c.hInstance = GetModuleHandleW(nullptr);
        c.lpszClassName = L"PolarOriginalWatchDiagnostic";
        if (!RegisterClassW(&c)) throw std::runtime_error("Cannot register owned diagnostic window");
        window = CreateWindowExW(WS_EX_NOREDIRECTIONBITMAP | WS_EX_TOOLWINDOW, c.lpszClassName,
            L"POLAR source diagnostic (not client acceptance)", WS_POPUP, 0, 0, 32, 32, nullptr, nullptr, c.hInstance, nullptr);
        if (!window) throw std::runtime_error("Cannot create owned diagnostic window");
    }
    ~OwnedWindow() {if (window) DestroyWindow(window); UnregisterClassW(L"PolarOriginalWatchDiagnostic", GetModuleHandleW(nullptr));}
    HWND window{};
};

int main(int argc, char** argv) {
    try {
        if (argc != 6) throw std::invalid_argument("Usage: shell_probe extracted-upstream-root width height time new-output.bgra");
        const auto root = fs::absolute(argv[1]), output = fs::absolute(argv[5]);
        const auto width = std::stoul(argv[2]), height = std::stoul(argv[3]); const auto time = std::stod(argv[4]);
        if (width < 320 || width > 4096 || height < 240 || height > 2160 || !std::isfinite(time) || time < 0 || time > 60 || fs::exists(output))
            throw std::invalid_argument("Invalid probe parameters or existing output");
        const auto shell = root / "resources/shell";
        source::WatchRuntimeInput input(shell / "runtime-input");
        gpu::SourceScene materials(gpu::CompiledSourceScene{shell / "catalog.ehscene",{}});
        if (materials.provenance().packetSHA256 != input.sourceManifestSHA256()) throw std::runtime_error("Source pin differs");
        if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) throw std::runtime_error("COM init failed");
        // All COM clients are destroyed before balancing the apartment.
        struct Apartment {~Apartment(){CoUninitialize();}} apartment;
        OwnedWindow window;
        gpu::Renderer renderer;
        renderer.initialize(window.window, width, height, {gpu::Driver::hardware,shell / "hud.hlsl",gpu::RenderTarget::offscreenForTests});
        gpu::LayerRasterizer raster(root / "fonts");
        gpu::LayerScene layers(raster); gpu::LayerRasterOptions options; options.assetRoot = input.assetRoot();
        layers.load(input.nativeTop()["nativeLayers"], options);
        layers.upload(renderer);
        auto bindings = source::nativeLabelBindingsFromExport(input.scene(), input.nativeButtons(),
            input.nativeTop()["nativeLayers"], input.nativeTop()["nativeProfileBindings"]);
        source::NativeLabelPlan plan(input.scene(), std::move(bindings));
        gpu::WatchLabelPresentation labels(plan, layers);
        SourceWatchSession session(input.scene(), input.document(), input.library(), input.camera(), input.resources(),
            input.animators(), input.controllerTransitions(), input.profile(), input.desktopSettings());
        const std::array snapshots{gpu::WatchContentSnapshot{&input.nativeTop(),1},gpu::WatchContentSnapshot{&input.nativeBottom(),0}};
        gpu::WatchContentCatalog catalog(input.scene(),input.document(),plan.bindings(),snapshots);
        const auto& navigation = catalog.navigation();
        session.setNavigation({navigation.fixedActions,navigation.rightActions,navigation.managedButtons}, 0);
        gpu::NativeWatchContent content(catalog,layers,options);
        session.setEnvironment({{double(width),double(height)},true,true,true,false,{}},0);
        session.open(0, 0); session.setInputEnabled(true, 0);
        session.sample(0);
        const auto* frame = session.sample(time);
        if (!frame || !frame->sourceFrame) throw std::runtime_error("Source frame is concealed");
        if (content.update(session.actions())) layers.upload(renderer);
        std::vector<gpu::WatchButtonAvailability> availability;
        for (const auto& id : plan.buttonIDs()) {
            const auto action = session.actions().find(id);
            const bool expand = action != session.actions().end() && action->second == catalog.actionForTarget("fileShelf");
            availability.push_back({id,true,expand});
        }
        labels.update(*frame->sourceFrame, frame->camera, {0,0,double(width),double(height)}, availability);
        labels.present(renderer);
        renderer.setCamera(gpu::layerViewportProjection(width,height));
        materials.upload(renderer.sourceGraphics());
        gpu::WatchMaterialPresentation presentation(materials);
        gpu::SourceFrameParameters parameters; parameters.camera = frame->gpuCamera; parameters.width = width;
        parameters.height = height; parameters.timeSeconds = frame->shaderTime;
        presentation.update(*frame->sourceFrame, parameters); materials.flush(renderer.sourceGraphics());
        renderer.draw(false);
        const auto image = renderer.readback();
        std::ofstream stream(output, std::ios::binary);
        for (unsigned row = 0; row < height; ++row)
            stream.write(reinterpret_cast<const char*>(image.pixels.data()) + row * image.rowBytes, width * 4);
        if (!stream) throw std::runtime_error("Cannot write diagnostic pixels");
        if (IsWindowVisible(window.window)) throw std::runtime_error("Diagnostic must remain noninteractive");
        layers.detach(renderer);
        std::cout << "ORIGINAL SHELL RENDERED (no RM integration verdict): " << frame->sourceFrame->batches.size() << " batches\n";
        return 0;
    } catch (const std::exception& e) {std::cerr << e.what() << '\n'; return 1;}
}
