# Esc renderer 选择与 Jello 资源封装验证（2026-10-26）

基准：`main@5bb0ec263757be013b9edfd0225c671de6facf1e`。范围仅为本次路径
装配修复、既有 Jello 材料迁移及相关回归，不是整个客户端的验收报告。

## 本次修复

- 生产工厂显式传入 `renderer_pack=paths.endfield_renderer_pack`。
- 源码及便携模式中，DLL 只使用该版本自带包；旧私有包仍提供场景资源，
  启动和语音目录保留。缺失/损坏自带 DLL 时报告错误，不自动执行旧私有 DLL。
- 新增真实工厂回归，包含有效旧/新包共存、源码/便携、坏哈希、缺失自带
  DLL 和私有目录保持原字节。反例确认：漏传参数确实会选择旧 DLL。

## Jello 材料

- 24 个迁移前已有文件（13 图片、3 字体、8 MP3），共 511,795 字节。
- 与基准提交中每个原路径的 Git blob 做逐字节比较，全部相同；清单同时
  保存 SHA-256。不是重新绘制/转码，也没有复制出两份原资源树。
- 按 `clickgui/widgets/scrolling/shadows/hud/typography/audio` 七种功能归档，
  共享路径目录为 `rm_client/ui/jello/resources.py`。
- 源码和便携运行路径、旧 renderer 构造参数、音效事件 ID、私有声音导入
  保持兼容。打包只复制清单中的文件，并校验源/目标；拒绝覆盖非空目标。
- 新测试将原扁平资源与新功能包以同一真实 QPainter 绘制，比较 16 对画面：
  960×540 DPR2、1280×720 DPR1、1600×900 DPR1.5、2560×1440 DPR1；
  中/英文及主页面/HUD 设置页组合全部像素相同。这不是新旧 GPU 帧逐像素认证。

## 本机原生验证

在 Windows 上通过生产菜单工厂创建原生 owner，读取原有私有资源；仅关闭
无关的 boot/feedback 初始化，未启动游戏、输入采集、摄像头或设备链路。

| 项目 | 结果 |
| --- | --- |
| 本机私有 CURRENT | `build_83a5af809b9ccdb1`，保持不变 |
| 实际加载 DLL | `build_65994449a68ffa60` |
| 新 DLL SHA-256 | `c6b65039111cb750bd1d7d1f4cf537cc8fdf4ba8030d38461cd87f8a195704c0` |
| 原生 D3D 自有离屏画面 | 1280×720、2560×1440 均非空 |
| 退出 owner | 正常退役，handle 归零 |
| 私有资源目录 | 运行前后全部文件哈希相同 |

另运行 `gpu_renderer_runtime_smoke --desktop`，真实桌面 OpenGL 下的新 Options
资源路径上传/绘制通过。诊断截图里的“144 FPS”只是既有测试文字，不是性能
测量结果。本轮没有声称完成全应用帧率、跨显卡或另一台电脑的验证。

## 测试报告

机器可读的所选测试结果及基准失败对照见同目录
`evidence/renderer-jello-20261026.json`。Jello 新资源测试 9 项、Esc 工厂测试
3 项均通过。最终所选 45 套中 43 PASS、2 FAIL、0 SKIP、0 INCOMPLETE；
43 套通过的用例数合计 448。资源审计、编译与 PowerShell 发布脚本解析通过。

以下两套既有回归在基准 `main` 上复测也失败，本次没有删除/放宽断言，
不能因此宣布完整回归 PASS：

- `test_endfield_clickgui_theme`：1 个失败，兼容栅格路径会补解码图片。
- `test_endfield_settings_theme`：5 个失败、2 个错误，涉及旧设置主题类型、
  背景/过渡成员、页面结构及资源失败契约，与本次资源地址迁移无关。

另尝试导入传统 `tests/smoke_test.py` 以单独运行更新过资源引用的两个函数；
它在导入不存在的旧 `rm_client.ui.hero_deploy` 时即中止。基准 main 上同样
可复现，两个函数没有实际执行，未计入上述通过数量。没有声称完整 smoke 通过。

## 用户数据保护

没有修改/暂存 `configs/default.json`、`_pdf_extract.txt`、`user_data`，没有
删除旧包或替换游戏安装目录文件。个人 default.json 在操作前后的 SHA-256：
`67efb7a5cc0eae8d3e25868a6dd8ee219c73cc2fe85c85176da6d21d59f13475`。

更新后需要重启客户端才会重新装配 DLL；不会强卸载正在运行的原生代码。
真实比赛 readiness 不因 UI/资源测试而改变。
