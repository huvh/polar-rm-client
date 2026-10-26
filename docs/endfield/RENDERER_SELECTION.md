# Esc 旧渲染器覆盖新版：路径职责修复

PR #24 将工厂迁到 `rm_client/ui/endfield/lifecycle.py`，创建菜单时遗漏
`renderer_pack=paths.endfield_renderer_pack`。`EndfieldNativeMenu` 的兼容默认
参数会把素材路径也当作 DLL 路径，因此旧 `user_data/endfield_pack` 的
CURRENT/DLL 可以覆盖发布版。重启依然会选择同一个错误路径。

现在生产工厂明确分离两项：

- `paths.endfield_menu_pack`：继续允许本地场景素材，启动展示及可选语音仍用
  用户自己的 `endfield_pack`。不删除、迁移、覆盖任何本地包。
- `paths.endfield_renderer_pack`：源码/便携版都固定返回该客户端版本随附的
  原生渲染器目录。库仍经原 reference commit、CURRENT 格式及二进制哈希检查。
  随附 DLL 丢失或损坏应显示诊断，不再静默回退到旧用户 DLL。离线开发工具
  仍可显式创建 `EndfieldNativeMenu(pack)`，不改变该兼容接口。

回归 `tests/endfield/test_renderer_pack_priority.py` 使用真实工厂和路径/哈希
验证器，覆盖源码与便携环境、有效旧 CURRENT 与 DLL 并存、资源根路径保留、
坏哈希、缺失随附 DLL。NativeApi 为替身，测试不加载真实 DLL、不启动任何
游戏或设备。另检查私有目录前后字节完全一致。

这修复了路径装配错误，不代表 PR #24 记录的其他回归、原生 GPU/FPS 或现场
链路已全部验收。代码更新后应重启客户端；已加载的 DLL 不在运行时强卸载。
