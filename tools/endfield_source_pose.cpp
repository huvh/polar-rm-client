// Source-fidelity probe, linked to the pinned MIT EndfieldHUD core unchanged.
// This exports original camera/layout/animation transforms. It is NOT a UI
// renderer and must not be used as evidence of pixel/shader equivalence.
#include "core/source_animation.hpp"
#include "core/source_camera.hpp"
#include "core/source_layout.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <cmath>

using ehud::data::Json;
namespace src = endfield::core::source;
namespace core = endfield::core;
namespace fs = std::filesystem;

Json read(const fs::path& path) {
    if (!fs::is_regular_file(path) || fs::file_size(path) > 64 * 1024 * 1024)
        throw std::runtime_error("Missing or excessive reference JSON");
    std::ifstream stream(path, std::ios::binary);
    std::string bytes((std::istreambuf_iterator<char>(stream)), {});
    return Json::parse(bytes, 64 * 1024 * 1024);
}

int main(int argc, char** argv) {
    try {
        if (argc != 6) throw std::runtime_error("Usage: source_pose WatchSource width height entrance-time output.json");
        const fs::path root = fs::absolute(argv[1]);
        const double width = std::stod(argv[2]), height = std::stod(argv[3]), time = std::stod(argv[4]);
        if (!std::isfinite(width) || !std::isfinite(height) || !std::isfinite(time) || width <= 0 || height <= 0)
            throw std::runtime_error("Invalid source frame parameters");
        const auto scene = src::SceneDefinition::fromJson(read(root / "Scene/scene.json"));
        const auto library = src::Library::fromJson(read(root / "Scene/clips.json"));
        const src::SourceCamera camera(read(root / "Scene/runtime-root-camera.json"));
        const auto frame = camera.frame({width, height});
        const auto pose = src::WatchAnimation(scene, library).pose(time, {}, {}, frame.layout.canvasSize);
        const auto nodes = src::SourceLayout(scene).resolve({}, pose.transforms);
        const auto viewProjection = frame.projection * frame.view;
        Json::Array output;
        for (const auto& node : nodes) {
            Json::Array matrix, quad;
            for (const auto value : (frame.worldRoot * node.worldMatrix).values) matrix.emplace_back(value);
            if (node.rect) {
                const auto m = viewProjection * frame.worldRoot * node.worldMatrix;
                for (const auto& point : node.rect->corners()) {
                    double v[4]{};
                    for (unsigned r = 0; r < 4; ++r)
                        v[r] = m.values[r] * point[0] + m.values[4+r] * point[1] + m.values[8+r] * point[2] + m.values[12+r];
                    if (v[3] == 0) {quad.emplace_back(nullptr); continue;}
                    quad.emplace_back(Json::Array{(v[0]/v[3]+1)*width/2, (1-v[1]/v[3])*height/2, v[2]/v[3]});
                }
            }
            Json::Object properties;
            if (const auto p = pose.properties.find(node.node->id); p != pose.properties.end())
                for (const auto& [key, value] : p->second) properties.emplace(key, value);
            output.emplace_back(Json::Object{{"id",node.node->id}, {"path",node.node->path},
                {"active",node.activeInHierarchy}, {"world",std::move(matrix)},
                {"quad",std::move(quad)}, {"properties",std::move(properties)}});
        }
        Json result(Json::Object{{"format","POLAR.Endfield.SourcePose"}, {"schema",1},
            {"referenceCommit","cdbd4f573c8fa3b9c2048fa3d1b089e69196537b"},
            {"scope","original source transform/curve probe; not a rendered or fully mounted frame"},
            {"viewport",Json::Array{width,height}}, {"entranceTime",time}, {"nodes",std::move(output)}});
        const auto destination = fs::absolute(argv[5]);
        if (fs::exists(destination)) throw std::runtime_error("Refusing to replace existing source evidence");
        std::ofstream out(destination, std::ios::binary);
        out << result.encode(32 * 1024 * 1024);
        if (!out) throw std::runtime_error("Could not write source pose evidence");
        std::cout << "SOURCE POSE EXPORTED: " << nodes.size() << " original nodes; not pixel acceptance\n";
        return 0;
    } catch (const std::exception& error) {std::cerr << error.what() << '\n'; return 1;}
}
