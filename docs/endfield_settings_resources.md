# 终末地设置资源：离线导入与溯源契约

## 边界

`tools/prepare_endfield_settings.py` 只消费**显式指定**的 EndfieldStudio
`original --raw --metadata` 本地导出和一个字体文件。不搜索或读取安装的游戏，不打开
manifest 中的 bundle 路径，不修改配置、导出源、用户数据或现有资源包。
UnityPy 仅为离线工具依赖，函数解码时才加载；客户端运行时不需要安装 UnityPy。
原版资源不因本工具源码而获得再分发许可。

目标目录必须不存在（空目录、文件、符号链接也不接受）。请先导入新的临时目录，
核对 manifest 后由主线程整合；不要对现有 `assets/endfield_settings` 原地运行。

## 严格匹配与完整性

- 对象身份为 `(source_path, serialized_file, path_id)`，不以 `parent_asset_path`
  作为唯一键。同一 prefab 可同时包含多个 Texture2D/Sprite。
- 重复输入根、重复对象身份（即使出现在不同根且内容相同）均报错，不能通过输入顺序决定取舍。
- 11 个 NAMES 纹理按名称要求唯一；各自 Sprite 在同一 bundle/CAB/parent 的候选中，
  按实际 `m_RD.texture` PPtr 关联并要求唯一，不依赖 Sprite 的索引名称。
- 9 个角色按 SPRITES 中 PathID 要求唯一；跨 CAB 的 PathID 冲突也拒绝。
  再通过真实 PPtr 解析 Texture2D。本地引用包含 bundle/CAB 身份；外部引用按 metadata
  的 externals 解析并要求唯一。缺失角色报错，**没有**静默矢量降级或同名替代。
- 消费的对象均校验导出状态、非空 raw/metadata、raw 与 source_size 一致、metadata
  身份与类型一致、LittleEndian 和非空原始 type tree；解码使用各行所属的输入根。
- 此版本固定 GameSettingPanel 的 785 个及 Fullwidth GameSettingItemCellV2 的
  26 个 RectTransform；各 prefab 分别要求同一 CAB、完整五组几何向量、GameObject
  原始输入和组件反向引用存在、单根层级、父子双向一致、无重复子节点、无环且全部连通。
- 5 条 AnimationClip 要求唯一、原始名称匹配、60Hz、曲线/关键帧完整、绑定不重复、
  时间严格递增且值有限。版本基线为：

  | clip | FloatCurves | 总关键帧 |
  | --- | ---: | ---: |
  | gamesetting_in | 7 | 13 |
  | gamesetting_out | 7 | 14 |
  | gamesetting_change | 1 | 2 |
  | common_toggle_to_left01 | 24 | 48 |
  | common_toggle_to_right01 | 25 | 49 |

- PNG 验证签名、IHDR 尺寸、chunk 长度/CRC 和 IEND；字体验证 sfnt 头和表目录边界。
  Sprite 的 rect、border、pixels-per-unit 校验有限值与几何范围。
- raw/metadata/output 路径只允许位于该导出根内的相对文件，拒绝绝对路径、`..`、
  Windows drive/UNC/ADS 和逃逸根目录的符号链接/junction。

这些计数是当前原版资源的**版本契约**，不是通用 Unity 导入规则。原版版本变化时应
先审阅新导出再修改基线，不能降低计数以绕过不完整输入。hash 提供完整性审计，
不等同于发行方签名或对未知导出来源的真实性认证。

## PROVENANCE schema 2

保持原有 `prefab`、`sprites`、`files`、`vector_adaptations` 字段。
`files` 精确列出 20 个 PNG、`source_layout.json`、`defaultfont_cn.ttf` 的 SHA-256；
不包含 manifest 本身（避免自引用）。`vector_adaptations` 必为空。

`sprites[filename]` 示例：

```json
{
  "rect": {"x": 1.0, "y": 1.0, "width": 116.0, "height": 96.0},
  "border": {"x": 57.0, "y": 0.0, "z": 57.0, "w": 0.0},
  "pixels_per_unit": 100.0
}
```

这三个字段逐值来自原始 Sprite 的 `m_Rect`、`m_Border`、`m_PixelsToUnits`，
涵盖所有角色和 NAMES 关联 Sprite。**PNG 始终是完整 Texture2D 的原始字节，未裁切、
缩放、重新编码或调色**。`texture_size` 另外记录完整 PNG 的 `[宽, 高]`，不是裁切尺寸。

- `rect` 使用 Unity **左下角**原点，单位为纹理像素。使用左上角原点图像 API 时，
  对应 `left=x, top=texture_height-y-height, width=width, height=height`。
  runtime 应在 preload 时按此 rect **只裁切一次**，然后对裁切结果做 9-slice。
- `border` 顺序为 `x=左, y=下, z=右, w=上`，数值是原始 Sprite 像素，不能按完整
  Texture2D 尺寸推算，也不能把 y/w 当作上/下。目标缩放由 runtime 决定。
- `pixels_per_unit` 不被导入器应用缩放，也不被归一化；保留原始值。
- `pivot` / `offset` 保留原始 Sprite 向量。
- `render_data` 保留存在的 `m_RD.textureRect`、`textureRectOffset`、`atlasRectOffset`、
  `settingsRaw`、`downscaleMultiplier`。其中 textureRect 可能包含 tight mesh 的小数，
  **不是**当前 preload 裁切应使用的 m_Rect 替代品。
- 每张 PNG 保留 `asset`、`bundle`、`sha256`，并新增 `sprite_source` 与 `texture_source`：
  含输入根 ID、索引行号、bundle、CAB、PathID、类型、名称、asset，以及 raw/metadata
  的相对路径、SHA-256、字节数；纹理来源另外记录原 PNG output 的路径/hash/大小。
- `inputs` 记录显式根路径、根 ID、`_index.jsonl` hash 和行数。
- `layout_sources.prefabs[prefab_path].geometry` / `game_objects` 及 `layout_sources.clips`
  记录两个布局及动画原始输入的完整来源。
- `font_source` 记录显式字体路径/hash/大小，不凭已导出字体臆造原始 bundle。
- `completeness` 记录几何/动画/角色计数；`sprite_coordinates` 记录裁切和 border 约定。

### 布局和逻辑参考尺寸

`source_layout.json` 保留顶层 `prefab`、`geometry`、`clips`，其中 `geometry` 仍是原有
GameSettingPanel 的 785 个 RectTransform，避免改变旧消费者对其含义的依赖。
新增 `layouts_by_prefab`，完整路径作 key，各项包含 `geometry`（PathID 作 key，五组
原始 RectTransform 向量）和 `game_object_names`（相同 PathID 对应原 GameObject 名称）：

- `assets/beyond/dynamicassets/gameplay/ui/prefabs/settings/gamesettingpanel.prefab`
- `assets/beyond/dynamicassets/gameplay/ui/prefabs/settings/widgets/gamesettingitemcellv2.prefab`

V2 记录包括根 `GameSettingItemCellV2`、`ItemText`、`ControlNode` 等全部 26 个节点；
名称可能重复，不能把名称当唯一键。m_SizeDelta 可为负（stretch anchors），保留原值，
不能当作最终屏幕上的实际像素尺寸或对其取绝对值。

不再输出未经证实的 `canvas=[1920,1080]`。布局和 manifest 均记录
`logical_reference=[3840,2160]`，其 status 明确这是**展示适配参考，不是已确认的 Unity
Canvas 尺寸**。原 prefab 如 SettingItemControls.x=1920 提供了使用大逻辑宽度的线索，
但不能据此推导最终屏幕缩放。`canvas_scaler.status=runtime_rules_unavailable` 表明尚未
获得 Unity CanvasScaler 的运行时规则；不编造 Scale Mode、Match Width/Height、
reference resolution 或缩放倍率。图标栏和 control 的实际缩放由主 UI 负责。

已核对的原始数据（rect 均为 x=1、y=1；PPU 均为 100）：

| 文件 | rect 宽×高 | border x,y,z,w |
| --- | --- | --- |
| bg_setting_dropdown.png | 80×80 | 28,28,28,28 |
| button_bg.png | 116×96 | 57,0,57,0 |
| toggle_bg.png | 94×78 | 40,0,42,0 |
| toggle_ring.png | 44×44 | 21,21,22,22 |
| row_bg.png | 58×58 | 18,24,26,27 |

## 事务输出

输入验证和所有资源字节/hash 准备完成前不创建输出目录。随后在目标父目录创建
`.目标名.staging-*` 临时目录，写入全部资源和 manifest，逐个回读并核对完整清单及字节。
最后在同一文件系统 rename 发布。解析、写入或 rename 抛出异常时删除本次 staging，
不留下看似完整的目标包；如果其它进程已创建目标，保留对方目标并失败。
硬断电/强制终止不提供清理保证，残留隐藏 staging 不是已发布资源包。

## 单独运行

在当前工作树下运行；不会调用 `verify_all` 或其 aggregate 锁：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
py -m unittest discover -s tests -p test_endfield_settings_import.py -v
```

普通测试使用临时合成输入、mock 解码器和现有包 hash，不需要 UnityPy；覆盖同 parent
多纹理、名称/PathID 歧义、缺失 raw/metadata/prefab/clip、路径逃逸、精确 rect/border/PPU、
输出清单/hash、输入变化和失败回滚。真实导出测试默认跳过，必须显式指定路径：

```powershell
$base = 'C:\Users\lulu\Desktop\claude\openzenuicodexver\rm_custom_client'
$env:ENDFIELD_SETTINGS_EXPORT_BASE = Join-Path $base 'tmp_endfield_work'
$env:ENDFIELD_SETTINGS_FONT = Join-Path $base 'user_data/endfield_pack/boot/defaultfont_cn.ttf'
uv run --no-project --with 'UnityPy==1.25.4' python -m unittest discover -s tests -p test_endfield_settings_import.py -v
```

生成新的临时包（仅工具隔离环境安装 UnityPy，不改客户端依赖）：

```powershell
$work = Join-Path $base 'tmp_endfield_work'
$out = Join-Path $env:TEMP ('endfield-settings-import-' + [guid]::NewGuid().ToString('N'))
$args = @('tools/prepare_endfield_settings.py', '--export-root', (Join-Path $work 'settings_original'),
          '--font', (Join-Path $base 'user_data/endfield_pack/boot/defaultfont_cn.ttf'), '--out', $out,
          '--extra-root', (Join-Path $work 'settings_common_original'))
0..4 | ForEach-Object { $args += @('--extra-root', (Join-Path $work "common_extra_$_")) }
uv run --no-project --with 'UnityPy==1.25.4' python @args
Write-Output $out
```

真实导出 round-trip 要求 20 个 PNG 和字体的 hash 与现有包完全相同，旧顶层 geometry
和 clips 逐值相同，并逐张重新解码原始 Sprite 检查 rect/border/PPU。source_layout.json
因新增 V2 几何和纠正 canvas 表述而改变 hash；仍总计 22 个资源文件。不会覆写现有 assets。
