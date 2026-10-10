# POLAR-RM 现场候选版

便携包是 **现场候选版**，不是自动认证的比赛就绪版本。每次启动均为
`LOCKED`。只有同一构建、机器人和固件哈希的动态证据在 24 小时内有效，
完成技术测试、操作员与安全负责人双人签字后，才可在本次进程中人工
`MATCH_ARMED`。断线超过 2 秒、切换场景、窗口失焦或重启都会重新锁定。

PRM1 `kind=1` 自瞄和 `kind=2` 小陀螺独立授权；核心 KMC 通过不会解锁它们。
回放工具没有发布接口，现场日志不记录视频画面。

必须通过 `START-POLAR-RM.bat` 启动。启动器先执行清单、关键资源、内置
FFmpeg 持续解码、目录写入、UDP 端口和 Qt/OpenGL 预检；失败报告写入
`user_data/logs/startup-preflight.json`，失败时不会进入客户端。只读回放可用：

```bat
POLAR-RM.exe --replay-field-log user_data\logs --replay-output field_evidence\replay-summary.json
```

回放模式在构造任何后端或上行传输对象之前结束。

没有真车、正式裁判系统、正式图传发射端、物理急停测试、完整比赛时长
soak 和双人签字时，结论必须保持 `NOT READY FOR REAL MATCH`。
