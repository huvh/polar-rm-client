// Diagnostic host for the original, unchanged EndfieldHUD material renderer.
// No game process, desktop capture, services, controls or foreign UI is opened.
#include "core/watch_runtime_input.hpp"
#include "native/source_graphics.hpp"
#include "native/source_scene.hpp"
#include "native/watch_presentation.hpp"
#include "native/renderer.hpp"
#include <windows.h>
#include <d3d11.h>
#include <wrl/client.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <cmath>

namespace fs = std::filesystem;
namespace gpu = endfield::native;
namespace source = endfield::core::source;
using Microsoft::WRL::ComPtr;

// The material-only host does not link the unrelated desktop/UI renderer.
gpu::RendererError::RendererError(std::string operation, std::int32_t code)
    : std::runtime_error(std::move(operation) + " (HRESULT " + std::to_string(code) + ")"), code_(code) {}

void checked(HRESULT result, const char* message) {
    if (FAILED(result)) throw gpu::RendererError(message, result);
}

int main(int argc, char** argv) {
    try {
        if (argc != 7) throw std::invalid_argument("Usage: native_probe runtime-root compiled-scene width height seconds new-output.rgba");
        const auto root = fs::absolute(argv[1]), compiled = fs::absolute(argv[2]), destination = fs::absolute(argv[6]);
        const auto width = std::stoul(argv[3]), height = std::stoul(argv[4]);
        const auto seconds = std::stod(argv[5]);
        if (width < 320 || width > 4096 || height < 240 || height > 2160 || !std::isfinite(seconds) || seconds < 0 || seconds > 60)
            throw std::invalid_argument("Invalid bounded source viewport/time");
        if (fs::exists(destination)) throw std::invalid_argument("Choose new evidence output; refusing overwrite");
        source::WatchRuntimeInput input(root);
        gpu::SourceScene materials(gpu::CompiledSourceScene{compiled,{}});
        if (materials.provenance().packetSHA256 != input.sourceManifestSHA256())
            throw std::invalid_argument("Runtime and shader scene have different source provenance");
        source::SourceWatchFrameBuilder builder(input.scene(), input.document(), input.resources(), input.desktopSettings());
        source::WatchAnimation animation(input.scene(), input.library());
        source::ButtonAnimation buttons(input.scene(), input.library(), input.animators(), input.controllerTransitions());
        source::SelectableColor tints(input.scene(), input.document());
        const auto camera = input.camera().frame({double(width), double(height)});
        auto pose = animation.pose(seconds, seconds, {}, camera.layout.canvasSize);
        buttons.apply(pose, seconds);
        const auto& frame = builder.build(pose, camera.worldRoot, 1, nullptr, tints.colors(seconds));
        for (const auto& diagnostic : frame.diagnostics) std::cerr << diagnostic << '\n';
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> context;
        D3D_FEATURE_LEVEL level;
        checked(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            nullptr, 0, D3D11_SDK_VERSION, &device, &level, &context), "Create owned source-material device");
        gpu::SourceGraphics graphics(device.Get(), context.Get());
        materials.upload(graphics);
        gpu::WatchMaterialPresentation presentation(materials);
        gpu::SourceFrameParameters parameters;
        parameters.width = width; parameters.height = height;
        parameters.camera = input.camera().gpu(camera); parameters.timeSeconds = float(seconds);
        presentation.update(frame, parameters);
        materials.flush(graphics);
        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = width; desc.Height = height; desc.MipLevels = desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM; desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT; desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
        ComPtr<ID3D11Texture2D> target;
        checked(device->CreateTexture2D(&desc, nullptr, &target), "Create owned source target");
        graphics.renderTo(target.Get(), width, height);
        desc.Usage = D3D11_USAGE_STAGING; desc.BindFlags = 0; desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Texture2D> staging;
        checked(device->CreateTexture2D(&desc, nullptr, &staging), "Create bounded readback");
        context->CopyResource(staging.Get(), target.Get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        checked(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped), "Read original material result");
        std::ofstream out(destination, std::ios::binary);
        for (unsigned row = 0; row < height; ++row)
            out.write(static_cast<const char*>(mapped.pData) + row * mapped.RowPitch, width * 4);
        context->Unmap(staging.Get(), 0);
        if (!out) throw std::runtime_error("Could not write source material evidence");
        std::cout << "ORIGINAL MATERIALS RENDERED: " << frame.batches.size() << " batches; "
            << graphics.stats().draws << " passes; native labels/RM integration not certified\n";
        return frame.diagnostics.empty() ? 0 : 2;
    } catch (const std::exception& error) {std::cerr << error.what() << '\n'; return 1;}
}
