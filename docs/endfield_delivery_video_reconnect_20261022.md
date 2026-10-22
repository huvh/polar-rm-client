# Esc 跨电脑交付与图传断流恢复（2026-10-22）

## Esc：代码和运行资源是两个交付物

后续交付更新：维护者已要求将完整运行包纳入 Git，当前 main 的
`assets/endfield_pack` 包含全部菜单必需文件。正常拉取无需再私下迁移；下面保留
原故障原因、路径优先级及私有覆盖包的迁移办法。此前验证报告保持当时快照。

截图中的 `native_renderer/BUILD_MANIFEST.json` 不存在，表示另一台电脑没有完整
运行包。菜单源码已在 main；但 `user_data/` 被忽略，拉取源码不会复制作者的资源。
不能靠新建空 JSON、更换菜单或关闭效果解决。

新增 `RuntimePaths.endfield_menu_pack`，在窗口装配时选择：

1. 有 `CURRENT.json` 或旧版 `BUILD_MANIFEST.json` 的显式本地包：
   `user_data/endfield_pack/`。损坏的本地清单保留诊断，不静默覆盖。
2. 否则使用只读随附包：源码的 `assets/endfield_pack/`；便携版的
   `resources/assets/endfield_pack/`。空的本地目录不会遮蔽随附包。

启动语音、启动画面等可选导入仍单独保留在用户目录，不复制个人配置或游戏安装树。
菜单渲染器、动画、镜头、材质和场地网格不改造；不在 paint/tick 下载、扫描或复制资源。

### 私有跨电脑迁移

在已经完整准备且校验通过的机器上，运行：

```powershell
$AppPy = (Resolve-Path .venv/Scripts/python.exe).Path
& $AppPy tools/prepare_endfield_pack.py export `
    --pack user_data/endfield_pack --out tmp_menu_transfer/assets/endfield_pack
& $AppPy tools/prepare_endfield_pack.py check --pack tmp_menu_transfer/assets/endfield_pack
```

把导出的整个 `assets/endfield_pack/` 复制到另一台电脑客户端根目录的 `assets/`
下面。便携版复制到 `resources/assets/` 下面。必须保留整个目录层级，不只复制 DLL
或清单；关闭客户端后操作，完成后重启。从源码启动时可再次执行：

```powershell
& $AppPy tools/prepare_endfield_pack.py check --pack assets/endfield_pack
& $AppPy tools/verify_endfield_desktop.py --out tmp_menu_desktop --cycles 3
```

第二条不再注入测试包，直接验证真实窗口的默认路径选择、独立临时用户目录和原生菜单。
它仍使用惰性设备/mock 出口，不认证真车。

导出仅复制清单声明且验证过的文件；不覆盖目标、不更改源包。编译器的本机安装路径
从导出清单移除。原始编译源 SHA 保留，另记录仅统一 CRLF/LF 的 C++ 源身份，
避免同一 Git 源码因 `core.autocrlf` 不同在另一台电脑误报不匹配；真正改源码仍拒绝。
资源目录应逐字节迁移，`.gitattributes` 对该路径关闭换行转换。

私有迁移/导出不是第三方素材公开再分发授权。公开素材提交需另外确认，完整来源和
许可证必须保留；本地运行包与本轮测试截图不可作为个人数据全量上传的借口。
从原始固定输入构建的完整说明仍见 [资源准备](ENDFIELD_PACK_SETUP.md)。

## 图传：先退休旧所有者，再建立新代际

- 原 UDP 接收端一直绑定第一次发送端的 IP/端口。转发器重新启动通常更换源端口，
  旧接收代际将其全部拒绝；接收线程遇到 socket 错误退出也缺少选中源恢复调度。
- 现在仅在选中且要求启动的 UDP 源上维护连接：已接收的合法流中断超过 2 秒后，
  异步清理旧 socket、分片和解码状态，以 0.5–5 秒退避重新监听。
- 新发送端只在全新接收代际选取。绝不把两个发送端的同 ID 分片拼接；迟到的旧回调
  不能发布到新代际。未收到过流的监听不因空闲不断重启。
- 原生 `0x0310` 长时间无进展后，重启的发送序号不能永远被视为旧包。2 秒无接受
  进展后重建连续性基线，并丢弃旧参数集，等待新的 SPS/PPS 与 IDR。
  正常实时流中的重复、倒序分块仍丢弃。
- 原有原生资源关闭失败/未确认的所有权保留，自动恢复不得旁路显式清理重试界面。
  场景切换、Hero Native 独占和关闭阶段不会重新唤醒旧 UDP 源。
- 视频恢复不恢复驾驶授权、不自动 Arm，不改变 wire 格式或发送机器人控制命令。

UDP 仍不提供密码学身份认证。选中源断流后新代际允许重新选择第一个合法发送端，
这不是在旧 socket 内静默合并两台发送器；应继续使用隔离网络和可信转发器。

### 独立真实解码回归

```powershell
& $AppPy tools/verify_video_reconnect.py --ffmpeg <本机ffmpeg.exe> --out tmp_video_reconnect
```

使用已有内置 H.264/HEVC GOP、真实回环 UDP 和持续 FFmpeg 管道，断流后换源端口、
序号归零，再检查新鲜画面、stdin 持续开启和退出清理。它不替代真实图传接收机、
裁判 MQTT、现场无线链路或固件认证。测量值与完整回归结果保留在本轮报告中。
