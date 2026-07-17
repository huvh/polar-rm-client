# 第三方实现参考

## AndroidLiquidGlass-kmp

- 本项目的 GPU 液态玻璃镜片参考了本地 `AndroidLiquidGlass-kmp` 的镜片数学结构，包括圆角 SDF、窄边折射带、圆形折射曲线和边缘色差思路。
- POLAR-RM 使用 PySide6/OpenGL 重新实现，没有嵌入 Compose 运行时。
- 上游许可证：Apache License 2.0。

## DynamicIsland-System-for-mc-hacked-client

- 灵动岛参考其目标宽高平滑、内容裁剪和 EaseOutExpo 时序，在 POLAR-RM 中重新实现。
- 未迁移 Minecraft 功能或品牌素材。

## OpenZen 与 TestClient

- ModuleList 与 ClickGUI 仅迁移界面结构、布局规则和动效语言，RM 模块及业务逻辑由 POLAR-RM 自身实现。
