# 比赛队伍身份：原位替换 CS 队徽和队名

入口：`ClickGUI → System / 系统 → AllianceProfile / 阵营预设 → 比赛队伍资料 / 校徽`。

- 红、蓝双方各自填写学校、战队名，导入 PNG/JPEG/WebP 校徽。
- 也可导入官方赛事引擎的 `match_info` JSON；同目录的
  `compress_red_team_logo.png` / `compress_blue_team_logo.png` 随之导入。
- 保存后只替换 Tab 计分板原来的 80px 队徽区和下方队名区；分数、行列、
  动画、地图、液态玻璃都不改。校徽保持原色和宽高比，作为分数后的 0.2
  透明度背景。学校在原队名行、战队在原次级文字行；长名称省略，悬停看完整名。
- 显示资料不参与红蓝敌我判断、机器人 ID、战绩、控制授权或协议选择。
  不把示例学校写成默认比赛双方；没设置的队伍继续明确显示红方/蓝方，无校徽。
- 本轮只修改 CS 队徽/队名原位，不新增官方样式顶栏或改变头像、计分板位置。

## 对齐依据及边界

已读取本地官方 `RoboMasterEngine 12.0.0.137_Student.zip` 内：

`RoboMasterEngine_Data/StreamingAssets/RMServer/Server/data/match_info_default.json`
以及相邻的 `Server/format.the.json`。

两者都有 `red_team` / `blue_team`，内部字段包含 `name`、`college_name`、
`college_logo`、`emblem`；该包中的 JSON 是 GB18030，导入同时支持 UTF-8。
名称使用这些实际字段，不根据 score、robot_id 或图片颜色猜测学校。
压缩 PNG 在这个学生包内是红/蓝 RM 测试标，不是截图中两所大学的真实校徽，
不能把测试标冒充真实学校。生产校徽来自操作员选取的当前比赛本地素材。

这是一条**显式本地资料导入**路径，不声称现有 MQTT GameStatus 提供校名/校徽，
不发明裁判协议字段。JSON 里的远程图片 URL 不会联网下载，也不会读取任意绝对
路径；需提供同目录官方压缩图，或单独手动导入图片。不是登录裁判系统后自动
获取当前对阵；换比赛时应由操作员检查/更新双方资料。

## 存储和安全

`user_data/match_teams/teams.json` 原子保存文字和内容哈希文件名，
`user_data/match_teams/logos/` 存储至多 512px 的规范化 PNG。复制这整个目录
可随便携客户端迁移，不依赖最初图片的绝对路径，不改 `configs/default.json`。
图片最多 8MiB / 4MP，禁止 SVG/HTML 执行；绘制只读预加载的 QImage，不在每帧
读盘、解码或联网。缓存键包含双方名字和校徽身份，资料变化后立即重建原位层。

编辑器非系统模态，不启动额外本地事件循环；编辑期间输入不进入战斗控制，
主窗口关闭会先关闭编辑器。取消不提交文字变更；预先复制的图片不取得控制权限。

测试仅为桌面软件离屏检查，不是实际裁判/设备或图传资格证据。
