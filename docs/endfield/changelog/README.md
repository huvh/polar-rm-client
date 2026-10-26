# 原版公告页更新日志

游戏本体 `WebviewConfig/BulletinConfig.bin` 的 `targets.game.entry` 指向
`https://ef-webview.hypergryph.com/page/game_bulletin`。本次直接核对本机配置后，保存其官方静态页面资源，
并逐字节取用本机游戏 `sdkresources/font` 中的 HarmonyOS Sans SC / Latin Medium、Bold 四个 WOFF2。
没有使用 Wiki 字体，也没有按截图手绘公告控件。

页面保留原版三页签、日期列表、选中展开、正文、滚动、悬停和 CSS 动画。1920×1080 下，
原公告框边界为 `(92, 68, 1736, 900)`，与参考图一致；根页面淡入仍为原 `opacity .3s ease`。
原脚本中的数据访问端口 `var bt=It` 显式替换为本地只读日志接口，界面组件与样式不另写一套。
顶部文字适配为“更新日志／功能变更／使用说明”；正文为终端本地记录。

Qt 的 `ChangelogDialog` 管理模态、关闭与 F12 急停，沿用打开前锁定控制、打开前后清空输入的流程。
页面使用内存浏览器配置，不使用游戏登录态、Cookie 或客户端账户数据。浏览器仅允许读取公告资源包内部文件，
禁止远程请求和包外本地文件。原页面字体地址、图片、脚本与声音全部改为本地资源，运行不依赖游戏、网络或解包工具。

源码资源位于 `rm_client/ui/endfield/changelog/assets`；发布脚本复制到
`resources/assets/endfield/changelog`。PySide6 的 WebEngine 与主 HUD 共用 Qt 全局 OpenGL 上下文，
Qt/PyInstaller 的 WebEngine hook 负责浏览器子进程与运行库。此轮未构建完整 EXE。

`PROVENANCE.json` 保存每个官方资源的 URL、原始摘要和本地适配摘要。离线重建：

```powershell
python tools/endfield/changelog/prepare.py --source <已保存的官方静态页面目录> --fonts <游戏/sdkresources/font> --out <新资源目录>
python tools/endfield/changelog/check_assets.py --asset-root rm_client/ui/endfield/changelog/assets
python tests/endfield/test_original_changelog.py
python tests/endfield/test_endfield_changelog.py
```

原始静态目录结构应保留页面实际使用的版本化文件名及 `assets/img`、`assets/audio` 路径。
准备工具仅转换本地资源地址、明确的数据端口与页签文案；若数据端口变化即报错，避免静默套用错误版本。
游戏与官方资源版权归 HYPERGRYPH，来源边界见根目录 `THIRD_PARTY_NOTICES.md`。

## Esc 子页面往返修复

更新日志作为 Esc 的子模态打开，不再走“原生菜单退场 → 战斗 HUD → 独立功能”的通用路由。
日志动作先排入 Qt 事件队列，退出当前 tick 后打开，期间原生 Esc 场景、背景和菜单位置保持不变；
关闭日志直接回到现有菜单，不重新播放 Esc 入场。模态期间丢弃残留原生动作，防止旧点击重放。

日志窗口在本地正文、字体和浏览器两次绘制回调完成前保持透明；加载失败返回原菜单，
已关闭页面的迟到回调不能重新显示窗口。原版页面 CSS 动画、字体和组件不变。

`python tools/endfield/changelog/verify_handoff.py --out <新证据目录>`
在真实 Windows 主窗口、原生 Esc 和本地公告页之间连续往返六次，交替用 Esc 和关闭按钮退出。
加 `--fullscreen` 检查全屏，加 `--cancel-loading --rounds 2` 检查页面加载中退出。
记录每次采样的主窗口 HWND、原生菜单请求、阶段、日志就绪状态和窗口透明度。

原先仅检查原生渲染纹理，无法检出“状态打开、纹理正常但实际屏幕缺少菜单”的问题。
WebEngine 首次创建原生窗口时会沿父链改变主 OpenGL 窗口的原生属性，替换其 HWND，
而 Esc 的 DirectComposition 目标仍绑定旧 HWND。公告窗口现在先设置
`WA_DontCreateNativeAncestors`，再创建自己的原生窗口，阻止这个传播；同时接入已有全屏保护，
退出后使主画面缓存失效并请求重绘。保留原生菜单会话、滚动位置和动画，不重启菜单渲染器。
当前公告模态还通过 Qt 事件过滤器消费 Esc，页面脚本尚未就绪或窗口仍透明时也能关闭，
避免 WebEngine 吞掉早期按键；过滤器随模态结束移除。

验收额外检查整个往返期间主 HWND 不变，并读取最终屏幕上的客户区，比较退出前后左侧按钮的
明亮像素覆盖，缺失菜单时立即失败。按 HWND 抓图也可能漏掉 DirectComposition 图层，
因此实际屏幕验收使用屏幕坐标区域，原生纹理截图仅作为辅助证据。

本次[实测报告](../../evidence/changelog-return-20261025/verification.json)保存全屏、窗口模式及
加载中退出的像素检查和 HWND 记录；另附[修复前](../../evidence/changelog-return-20261025/before.png)
与[修复后](../../evidence/changelog-return-20261025/after.png)的最终屏幕区域。
