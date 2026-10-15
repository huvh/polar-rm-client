# 击杀音效与预设选择修复

## 保留原始资产

`assets/kill_fx/gd656/` 的 264 个资源与上游
[MinecraftGD656/gd656killicon](https://github.com/MinecraftGD656/gd656killicon/tree/9d4d074199b631e5b567dfac32fe41f9434da6f3)
逐个 Git blob 一致；未替换、重新绘制或生成新音效。声音仍使用原始 OGG 内容。

## 修复内容

- Jello 预设弹层有独立、限位的滚动区域，滚轮和触控板均可到达最后一项。选项命中范围严格裁剪，滚动不会穿透到底层设置或控制输入；长列表不会把自己的标题滚出窗口。
- Card 的 ASSIST / DESTROY_VEHICLE 原来拼出不存在的音效文件名，现在和上游一样回落到 Card 普通击杀声。
- 原来的预加载只接受 WAV，但击杀库是 OGG，实际没有预加载。现在用现有 FFmpeg 在单个后台线程解码为 PCM WAV，并由 QSoundEffect 在 Ready 后播放。原始采样率、声道、音量保留，不加增益或混音处理。
- 仅使用便携包 `bin/ffmpeg.exe`；源码运行可使用已有 `POLAR_FFMPEG` / PATH。没有运行时下载或安装。缓存存于可写用户数据目录，键包含原始内容、解码器版本与编码设置；临时文件原子替换、进程超时、任务和缓存上限避免无限增长。
- 没有解码器或解码失败时仍可回退 Qt 媒体后端，每次事件只选一个播放路径。没有音频设备及异步媒体错误会明确记录，不再静默丢失。静音不会触发解码或播放；冷启动排队的过期提示不会很久后突然响起。
- 大尺寸原图缩小到实际 HUD 尺寸时使用缓存的离散高质量缩小层，并局部启用平滑纹理变换，保留原动画和尺寸。缓存考虑设备 DPR，不为每一帧/每个动画小数尺寸重复缩放。

## 验证与边界

运行：

```
python tests/test_kill_selector_regressions.py
python tests/test_kill_audio_regressions.py
python tests/test_kill_asset_filtering.py
python tests/hud_batch16_killfx_test.py
```

选择器测试使用真正的离屏 Qt 几何和滚轮事件；音频回归使用真实 Qt 信号/后台工作队列，但模拟音频输出，确保不驱动设备；图像测试使用真实 Qt 光栅绘制，覆盖 DPR、缓存复用和细节保留。

此外，原始 Card 普通击杀及默认击杀 OGG 均实际解码到非静音的 48 kHz 双声道 PCM，第二次命中缓存。未验证用户 Windows 音频设备、系统音量或驱动，也未在此环境验证 OpenGL 最终显示；不能据此断言用户机器的无声问题只有一个根因。首次启动选定预设会后台准备 PCM，FFmpeg 不可用时可从日志识别回退原因。
