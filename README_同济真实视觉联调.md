# 同济真实自瞄联调

同济侧负责识别装甲板，POLAR-RM 负责显示、交互和控制 mock。控制链路默认只缓存建议 yaw/pitch，绝不发送云台、串口或发射指令。

## 四种视觉来源

- `Local`：默认。客户端独占电脑摄像头，并将同一张 BGR 帧交给后台 `LocalAlignedVision`。它直接加载 `同济自瞄/sp_vision_25/assets/yolov5.xml/.bin`，按同济 YOLOv5 的 letterbox、四点和 NMS 规则检测，不走 UDP、不抢第二个摄像头。
- `Tongji`：客户端监听 UDP `0.0.0.0:9871`，接收外部同济 C++ 或桌面 runner 发送的 `rm.vision.tongji.v1` JSON。
- `Auto`：优先外部同济 UDP 包，外部源超时后回退 Local。
- `Mock`：仅用于检查 HUD/ClickGUI，绝不冒充真实检测。

`TongjiVisionBridge -> Vision Source` 可在客户端切换上述来源；同一模块还提供 UDP 端口、超时、本地模型设备和外部设备显示设置。`ArmorAutoAim` 只消费统一视觉快照。

## 本地同帧检测

正常启动请双击唯一的 `启动.bat`。它会先显示场景和比赛模式选择；进入主 HUD 后，客户端才会打开摄像头并按 `TongjiVisionBridge -> Vision Source` 启动视觉链路。

需要从命令行直接进入本地同帧检测时：

```bat
set POLAR_AUTOSTART=1
set POLAR_VISION_SOURCE=Local
.venv\Scripts\python.exe main.py
```

客户端会独占摄像头，后台线程只保留最新一帧进行 OpenVINO 推理。检测完成后返回 `VisionSnapshot` 给 UI，因此视频、ESP 和检测坐标来自同一帧尺度，不会出现外部进程单独开摄像头造成的画面错位。

本地模式提供真实装甲四点、颜色、编号、置信度与锁定目标。它不包含同济 C++ 的 PnP/EKF 多装甲预测，因此不会伪造 `Armor3DESP` 预测面。

## 外部 UDP 同济

UDP JSON 协议为 `rm.vision.tongji.v1`，默认端口 `9871`。核心包结构：

```json
{
  "protocol": "rm.vision.tongji.v1",
  "frame_w": 1280,
  "frame_h": 720,
  "primary": {"name": "three", "color": "blue", "points": [[0,0],[1,0],[1,1],[0,1]], "locked": true},
  "armors": [],
  "gimbal": {"yaw_rad": 0.0, "pitch_rad": 0.0},
  "command": {"control": true, "fire": false, "yaw_rad": 0.0, "pitch_rad": 0.0}
}
```

客户端会校验协议、归一化四点与方框、缩放到当前视频画面，再交给 `ArmorAutoAim`、`RobotOverlay` 与 `Armor3DESP`。`GimbalCommandBridge` 会把 `control` 和 `fire` 强制置为 `false`，仅保留 HUD 建议读数。

桌面 runner 可手动执行 `tools/tongji_desktop_runner.py --source 0 --port 9871`。它单独使用摄像头并向 `127.0.0.1:9871` 发布，用于双进程 UDP 联调；日常电脑摄像头对齐测试优先用 `Local`。

## 真机 C++ 预测 ESP

外部同济 C++ 侧可把 `Target::armor_xyza_list()`、`Solver::reproject_armor()` 的多装甲预测以 `predicted: true` 连同真实 `depth_m` 填进 `armors`。客户端的 `Wireframe3D / PolarOutline2D / Prediction Rack` 会绘制真实检测四点、深度淡化预测面和 Aim Face。

当没有有效标定、结果超时或外部桥接断开时，客户端只显示检测或离线状态，不显示可信预测，也不会回退成 mock 框。
