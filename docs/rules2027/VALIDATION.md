# 2027 适配验证记录 — 2026-10-25

## 结论

规则/年度隔离的软件回归可交付；**NOT READY FOR REAL MATCH**。
没有设备连接，没有实际运动/开火，没有生成现场PASS或比赛授权。
这是定向scope，既不是整个产品所有测试全绿，也不是2027官方wire已打通。

工作树：`C:/Users/lulu/Desktop/claude/openzenuicodexver/polar-rules-2027`。
分支：`feat/rules-2027-20261025`；基线：`a6c489344fa59bdaaac1bd6a600a3bd13a2e8b11`。
执行器：主仓库现有 `.venv/Scripts/python.exe`，UTF-8模式，未安装新依赖。

## 1. 当前生产代码的79套定向回归

完整机器报告：`tmp_rule_2027/regression5.json`；逐套日志：`tmp_rule_2027/regression5_logs/`。
run_id：`721b8625fd974ec682c95539b39e817e`。

| 状态 | 套数 |
|---|---:|
| PASS | 77 |
| INCOMPLETE | 2 |
| FAIL | 0 |
| SKIP（整套） | 0 |

unittest原始摘要共911项，包含2项skip；另有472条显式断言计数，不混加成“独立测试总数”。
范围包含协议199断言、DT7 112断言、年度门、A5/MQTT最终写、生命周期与急停、配置/迁移/草稿、
经济原有冻结oracle、顶栏/MC融合、启动、Hero、设置全屏/滚动/主窗口关闭、终末地主题和CJK。

两个不完整项没有包装成PASS，aggregate按设计返回NO-GO/exit 1：

1. `polar_link_test`：缺队内 `CRC8_CRC16.py` 参考实现，三方CRC对拍未执行；其余断言执行。
2. `test_endfield_settings_import`：41项摘要中2项跳过——本机进程无文件符号链接创建能力；
   未显式配置真实离线导出/字体路径。合成导入器测试执行，不代表真实游戏全资源导入验收。

源稳定性：880个声明范围输入，起止指纹均为
`6f39c4b19c424757076c7c854063c875a2b4611c92a4a8ab8d41c14322691f58`，PASS。
范围与限制以报告为准，不包括所有外部依赖/素材，也不能检测中间改动后恢复原字节。

第一、二轮发现的fixture契约缺失、旧AST oracle需要显式接纳的新年度边界、诊断汉化遗漏已修复。
未重录或覆盖旧冻结JSON：catalog只显式增加Season及基线已有的终末地介绍文本；
economy只显式审查新增年度guard/context对应的精确AST摘要，原2026行为场景oracle保留。

## 2. 最终年度专项：85项全部执行通过

`tmp_rule_2027/final_rules.json`：5套PASS，0 SKIP/INCOMPLETE/FAIL。

| 新测试文件 | unittest项数 |
|---|---:|
| test_rmul2027_evidence | 12 |
| test_rmuc2027_evidence | 7 |
| test_rule_season_backend_gate | 38 |
| test_rules_2027_runtime | 19 |
| test_rules_2027_frontend | 9 |

该次源起止指纹均为
`29d9ad2339f7bdba37726482349c7c2b6ae277f65426f0751dd8a6d38aec8052`，880文件，PASS。
与79套执行之间**仅加强了独立桌面探针**：固定其Qt DPR并断言真实framebuffer尺寸，
生产源码及79套测试源码没有改动。区别不是一次隐藏的产品修复；最终探针另已实际运行。

## 3. Windows真实OpenGL

最终报告：`tmp_rule_2027/desktop4/report.json`，PASS。
Qt DPR显式固定1.0，仅影响该隔离子进程，不改变系统缩放。不是多DPI认证。
前期探针只记请求尺寸，在多显示器/DPR切换时存在OS限幅；最终版本改为检查实际尺寸，
不把“传入了1280×720”当作“渲染了1280×720”。

| 目标 | 实际widget | 实际原生framebuffer | 三赛制入口/返回无重叠 |
|---|---|---|---|
| 1280×720 | 1280×720 | 1280×720 | PASS |
| 1600×900 | 1600×900 | 1600×900 | PASS |
| 1920×1080 | 1920×1080 | 1920×1080 | PASS |
| 2560×1440 | 2560×1440 | 2560×1440 | PASS |

真实生产窗口、临时用户目录、inert MQTT/串口/图传启动器：
2027三模式/正式图示、未标定坐标禁投影、旧Hero入口受阻、只读经济卡、规则初始值、
2026回切不Arm、设置页打开及窗口清理均执行。真实发布消息为0。
截图在同目录，已人工检查。发现的Mock Robot0/能量框经绘制边界隔离后复查；
真实Local/外部视觉路径保留，不重做荧光白或玻璃材质。

这不验证相机、射频图传、正式裁判身份、真车控制、其他显卡/DPR或持续帧率P95。
截图角落瞬时FPS不作为性能达标证据。

## 4. 其他检查与保护

- `compileall`：PASS；`git diff --check`：PASS。
- `audit_settings.py --max-orphans 21`：exit 0；未扩大既有21项预算。
- 主工作区及终末地UI工作区未改动；没有切换/合并main或推送。
- 用户主仓库 `configs/default.json` 仍为
  `67efb7a5cc0eae8d3e25868a6dd8ee219c73cc2fe85c85176da6d21d59f13475`。
- 未修改/暂存该配置、`_pdf_extract.txt` 或现场证据。未改shader/玻璃材质资源。
- 三个本轮子代理均已结束并关闭。

## 5. 仍阻塞实战的事项

正式2027通信定义/黄金样本、四处阵地与装配/首发认可/新空中系统状态、后勤导致的
新视频限制等运行语义仍需官方wire及实机对拍；正式战术坐标仍未标定。
0x5A/DT7/PRM1不能靠规则年份推断固件兼容。旧2026签字不迁移成2027授权。
真车、裁判、图传、断链/归零/物理急停、完整时长soak及双人签字未执行。
这些缺口必须保留，不能以这份桌面报告替代。
