# Jello UI 按功能资源包

本目录持有所有 24 个既有 Jello UI 图片、字体和短音效，不新增、重绘、转码或
改变它们的字节。`JELLO_RESOURCES.json` 记录功能归属、迁移前路径、大小和
SHA-256；所有资源保持与迁移基准 `5bb0ec2` 相同。

| 功能目录 | 材料 | 现有消费者 |
| --- | --- | --- |
| `clickgui/assets` | Options 图标 | ClickGUI、GPU 预热 |
| `widgets/assets` | 勾选图片 | 设置行、Qt 复选框 |
| `scrolling/assets` | 上下滚动端帽 | 设置页/模块列表滚动 |
| `shadows/assets` | 8 个边角阴影 | ClickGUI、弹窗、键位画布 |
| `hud/assets` | HUD 阴影 | 模块列表、HUD 快照 |
| `typography/assets` | Helvetica Light/Medium、Regular | 所有 Jello 文字、键位画布 |
| `audio/assets` | 8 个原 UI MP3 | 原开关、点击、连接、错误等事件 |

键盘/绑定兼容画布的键帽由原代码绘制，没有独立位图资源；继续共享字体、
阴影和控件材料，不伪造“原版键盘图片”。生产 Endfield 独立键盘资源不属于
本包。`jello_clickgui.py`、`jello_widgets.py`、`jello_keybinds.py`、
`jello_scroll.py`、`jello_locale.py` 保留现有兼容入口和算法，不改视觉/时间线。

## 统一解析与发布

- `RuntimePaths.jello_pack`：源码为本目录；便携版为
  `resources/assets/jello`。不依赖工作目录，不去用户游戏目录搜索。
- `resources.JelloResources`：图片/字体/音效按用途定位。旧的显式
  `assets/jello` renderer 构造参数仍可解析到相邻新包；任意缺失目录仍为缺失。
- 现有 `jello/activate.mp3` 等音效事件 ID 不变，私有 `custom/...` 声音不动。
- `tools/jello/pack.py check --pack ...` 完整性检查；`stage --source ...
  --destination ...` 仅复制清单中的材料到新的发布目录，拒绝覆盖非空目录。
- 发布脚本在冻结前校验、在便携包中再次校验；不会把 Python 源码、缓存或
  `user_data` 混入资源目录。只有结构被重组，没有重复保留旧资源树。

第三方声明仍见项目 `THIRD_PARTY_NOTICES.md`。路径迁移不改变素材所有权。
