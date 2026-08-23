# polar_app.py 模块化重构蓝图（REFACTOR_BLUEPRINT）

> 生成方式：基于对 `rm_client/ui/polar_app.py` 的全量符号扫描 + 分段抽样读取，以及全仓 grep 的外部触点分析。
> 所有行号以撰写本文档时的文件快照为准：**16911 行 / ~867KB**。
>
> ⚠️ **行号误差说明**：另一个代理正在并行修改 `draw_official_map` 区域（当前实测该区域新增了
> `_map_fit_cuts_panel_corners` / `_rounded_map_layer` 两个辅助方法，约 +75 行）。本文档中
> **行号 ≤ 10081 的条目不受影响**；**行号 ≥ 10082 的条目按插入后的新快照记录**。若该区域继续被编辑，
> 以 `grep -n "^    def "` 重新定位为准，方法名与分组结论不受影响。

---

## 1. 顶层符号地图

文件只有 **10 个顶层符号**：9 个 class + 1 个 `main()`。全部复杂度集中在 `PolarRMWindow`。

| 行范围 | 符号 | 行数 | 职责 |
|---|---|---|---|
| 1–158 | imports | — | PySide6 + 约 25 个 rm_client 内部模块；其中 22 个来自 `.ui` 同级模块（animation/fonts/clickgui_gpu/jello_clickgui/gpu_frame_compositor/…），说明"渲染件外置、polar_app 装配"是既有架构惯例 |
| 161–166 | `class EconomyScenePhase(str, Enum)` | 6 | 经济工作区场景机四态（CLOSED/OPENING/OPEN/CLOSING）。被 tests/smoke_test.py 直接 import |
| 168–174 | `@dataclass class Hotspot` | 7 | 点击热区（rect/action/payload/button/tooltip），输入域核心数据结构 |
| 177–189 | `@dataclass(frozen) class ModuleListLayout` | 13 | ModuleList 统一逻辑像素安全区布局参数 |
| 191–214 | `class StartupLayerCache` | 24 | 启动页 vignette QImage 有界缓存（key=(w,h)，容量 4） |
| 217–243 | `class FrameScheduler` | 27 | 绝对deadline 的帧请求节流器（high_rate 时按 target_fps，否则 15fps）。被 tests/smoke_test.py 直接 import |
| 246–281 | `class InertialScroll` | 36 | 单调时钟临界阻尼滚动（step_damped_spring，~220ms 收敛）。被 tests/smoke_test.py 直接 import |
| 284–313 | `class VisionViewport(QOpenGLWidget)` | 30 | 战斗视频 GPU 合成子视口（当前 `gpu_viewport_enabled=False`，保留回退 CPU 路径）；paintGL 回调 `owner.draw_synthetic_video_scene` |
| 316–340 | `class PolarHudOverlay(QWidget)` | 25 | 叠在 GPU 战斗底图上的交互/HUD 层；paintEvent 与四个鼠标事件全部转发给 owner（PolarRMWindow） |
| 343–16887 | `class PolarRMWindow(QOpenGLWidget)` | **~16545** | 主窗口。502 个方法（含 2 组重复定义，见 §2.21） |
| 16890–16911 | `def main()` | 22 | QApplication 装配（GL 3.3 Core、双缓冲、swapInterval=1）+ 创建窗口。被 main.py:59 与 rm_client/app.py:655 引用 |

---

## 2. PolarRMWindow 方法域分组

主类 502 个方法按功能域聚类如下。每域给出：代表方法清单（省略号表示同族）、行范围合计、内部耦合评估（共享的 self 状态字段）。

### D0 构造 / 生命周期（~400 行）
- `__init__` (348–702)、`resizeEvent` (968–980)、`initializeGL` (982–995)、`closeEvent` (4836–4855)、`focusOutEvent` (4856–4867)
- 耦合：**最高**。`__init__` 装配约 60 个实例协作对象（registry/state/backend/mqtt/udp/serial/control/vision 全家桶、GPU 渲染器全家桶、全部缓存 dict、动画状态机）并定义了 ~150 个状态字段——这是全文件事实上的"状态 schema"，见 §4。

### D1 主循环 tick 编排（~230 行）
- `on_tick` (704–884)、`_run_tick_stage` (886–911)、`update_backend_readiness` (912–925)、`readiness_video_source` (926–934)
- 耦合：高但结构清晰。on_tick 内部已自文档化地列出 12 个逻辑 stage（backend.tick/apply/readiness、hero.deploy/lob、auto.spin、official.consume/apply、fx.hit_info、vision.sync/events、registry.tick）+ 75Hz 控制 stage + FrameScheduler 帧请求门控。
- 共享状态：`timer/frame_scheduler/render_fps_target/last_frame_time/frame_dt/_last_logic_time/_last_control_tick_time` 及几乎所有域的状态。

### D2 GPU 帧编排 / FBO 层管理（~1900 行）
- `paintGL` (997–1041)、`_jello_gpu_fonts` (1043)、`_jello_module_text_pages` (1061)、`prewarm_jello_module_resources` (1108)、`prewarm_gpu_clickgui_resources` (1140–1338)、`paint_direct_gpu_background` (1484–1556)、`_paint_gpu_frame_cached` (1557–1959，403 行，帧编排核心)、`paint_gpu_control_backdrop` (1960–2035)、`paint_gpu_frame` (2036–2143，注意：函数体首行即 return，2040 起为死代码)、`paint_gpu_startup_interaction_layer` (2145)、`module_list_animation_in_flight` (2175)、`_should_defer_hud_static_rebuild` (2187)、`gpu_static_ui_key` (2208)、`paint_gpu_background` (2251–2431)、`tune_render_rate` (2432–2470)、`draw_startup_gpu_background` (4754)、`draw_hud_gpu_background` (4798)、`draw_gui_cached_layer` (16612)、`invalidate_gui_cache` (16646)、`get_gui_scale_for_bounds` (16649)
- 耦合：高。共享 `gpu_compositor(GpuFrameCompositor)/clickgui_gpu/startup_gpu/hud_video_gpu/gui_cache/frame_scheduler` 及全部 `_gpu_*_key` 失效键、`_gpu_frame_recording/_gpu_motion_layer_ready/_gpu_warm_pending`。
- 特征：分层 FBO 编排（background → control backdrop → vision → static overlay(仅 key 变化重建) → dynamic → target → present），失败时回退 `paint_overlay(None, force_economy_compat=True)`。

### D3 CPU 覆盖层总入口（~330 行）
- `paint_overlay` (2471–2557)、`menu_overlay_active` (2626)、`economy_stage_active` (2635)、`combat_hud_preset` (2652)、`minecraft_hud_active` (2656)、`paint_hud_motion_overlay` (2664–2797)、`paint_priority_interaction_layer` (2798–2828)
- 耦合：**枢纽级**——paint_overlay 是所有 CPU 绘制域的分发器，按 startup_step/economy_phase/gui_visible/tactical map 等状态调用 D4/D5/D6/D10/D11/D12/D13 的 draw_*。拆分任何绘制域都不动它，但它必须最后迁。

### D4 startup 场景渲染（~1700 行）
- `paint_gpu_startup` (1339)、`begin_/finish_startup_page_transition` (1400–1430)、`build_gpu_startup_transition` (1431–1483)、`draw_startup_page_content/_transition` (2558–2625)、`startup_needs_high_rate` (4826)、`draw_startup_background` (5845)、`draw_particle_grid_background` (5879)、`draw_startup_screen` (5959)、`draw_robot_profile_screen` (6012)、`draw_match_mode_screen` (6036)、`draw_startup_scene_launcher` (6087)、`draw_startup_match_launcher` (6138)、`draw_liquid_startup_scene/match_launcher` (6191–6285)、liquid 控件族 `liquid_menu_layout/startup_stagger_value/mix_color/startup_menu_accent(startup_glass_settings/draw_liquid_glass_panel/draw_legacy_glass_panel/draw_liquid_icon/draw_liquid_menu_header/draw_liquid_main_button/draw_liquid_bottom_bar` (6286–6584)、壁纸选择器 `set_wallpaper_picker_visible/draw_wallpaper_picker/draw_wallpaper_card/draw_image_cover(static)/draw_liquid_small_action_button` (6585–6777)、`draw_liquid_status_panel/draw_startup_icon_card/draw_startup_card_shadow` (6778–6911)、`startup_scenario_meta/startup_match_meta/reset_startup_page_animation` (6912–7003，含重复定义)、`handle_startup_key` (16080)、`apply_scenario` (16131)
- 耦合：中低。主要读 `home_visible/startup_step/startup_transition_*/startup_wallpaper/anim`；liquid 控件族（glass panel/icon/button/bar）几乎纯函数化，只依赖 fonts/anim/theme。

### D5 ClickGUI 构建（GPU builders + legacy CPU GUI）（~2600 行）
- 打开/关闭：`set_clickgui_visible` (3929)、`open_legacy_clickgui` (3484)、`return_to_jello_clickgui` (3500)、`active_clickgui_mode`/`gui_mode_label` (16686–16701)
- GPU 构建：`build_gpu_clickgui` (12678)、`build_gpu_glass_rect/build_gpu_startup_button/build_gpu_startup_session/build_gpu_startup_bottom_bar/build_gpu_startup_hover_layer` (12908–13119)、颜色工具 `gpu_alpha/gui_primary_text/gui_secondary_text/gui_disabled_text` (13120)、`build_gpu_panel_gui/build_gpu_old_gui/build_gpu_new_gui/build_gpu_dropdown_gui` (13135–13316)、`register_gui_scroll_viewport` (13317)、`polar_view_modules` (13327)、PolarUnified/Multi 族 `build_gpu_polar_glass/build_gpu_polar_unified/build_gpu_scroll_island/build_gpu_polar_multi/build_gpu_polar_module_row/build_gpu_module_row` (13333–13581)、设置行族 `build_gpu_settings/build_gpu_setting_row/build_gpu_inline_settings/build_gpu_toggle` (13582–13726)、`build_gpu_mode_switcher/build_gpu_legacy_return/build_gpu_toasts/build_gpu_tooltip/elide_for_gpu/build_gpu_keybind_overlay` (13727–13805)
- legacy CPU GUI：`draw_panel_gui…draw_tooltip` (13806–14450)：draw_panel_gui/draw_profile_widget/draw_panel_category_bar/draw_panel_module_list/draw_settings_area/draw_bind_row/draw_setting_row/draw_compact_setting_row/draw_search_bar/draw_old_gui/draw_new_gui/draw_new_panel_shell/draw_new_module_block/draw_dropdown_gui/draw_dropdown_panel/draw_inline_settings/module_draw_height/inline_bind_height/inline_setting_height/waterfall_reveal/compact_keybind/draw_mode_switcher/draw_legacy_return/draw_toasts/draw_keybind_overlay/draw_toggle_switch/draw_pill/draw_tooltip
- 耦合：中高。共享 `registry/jello_state/gui_timeline/polar_unified_morph/module_expanded/module_list_rows/settings_scroll/gui_scroll_viewports/selected_category/selected_module/search_query/hotspots`（builder 边画边 add_hotspot）。

### D6 经济工作区（~2100 行）
- 数据/传输：`economy_scale_steps(static)/economy_ui_scale/economy_uses_mock_transport/send_economy_request/economy_offers/economy_categories/economy_selected_offer` (3407–3483)
- 绘制：`draw_economy_overlay_legacy` (3344)、`_finalize_economy_restore` (3895)、`draw_economy_overlay_compat` (4300–4753，454 行)、`build_gpu_economy_workspace` (12088–12677，590 行)、玻璃助手 `_economy_glass_row/_economy_dim_around/_economy_island_well/economy_lerp_rect(static)` (4257–4299)
- 交互/状态机：`open_economy_workspace` (3984)、`close_economy_workspace` (4037)、`select_/submit_/activate_economy_offer` (4178–4231)、`begin_/finish_economy_hold` (4232)、`start_economy_qualification_test` (15908)
- 耦合：域内高、域外中。共享 `EconomyIslandState(economy_island)/economy_phase(EconomyScenePhase)/_economy_generation/_economy_restore_pending_generation/economy_*scroll(InertialScroll×3)/economy_bridge/economy_workspace_layer/overlay_coordinator`。与 D2 有 FBO 清理协议（restore generation），与 D15 有 hotspot action 协议（"economy*" 前缀）。

### D7 视频管线 / 后端接线 / 英雄部署（~1300 行）
- 视频：`ensure_camera_started` (4885)、`draw_video` (4918)、`refresh_vision_runtime` (4950)、`on_captured_camera_frame` (4996)、`consume_capture_frame` (5092)、`consume_backend_video_frame` (5134)、`normal_backend_video_fresh/normal_video_frame_ready/clear_normal_backend_video_frame/backend_video_source_selected/draw_backend_video_lost` (5191–5245)、`draw_synthetic_video(+cached/scene)` (5700–5844)、`update_hud_liquid_source` (5743)、`active_tongji_result` (5246)
- 同济桥：`sync_tongji_vision_state` (5606)、`publish_vision_control_if_armed` (5653)、`tongji_target` (5680)、`alliance_side` (5430)
- 英雄部署：`hero_range_profile_selected/hero_deploy_video_cut_active/hero_deploy_uses_mock_transport/open_/close_hero_deploy_interface/send_hero_deploy_request/update_hero_deploy_state/update_auto_spin_guard` (3589–3781)、`draw_hero_deploy_interface` (3782)、`hero_lob_preview/update_hero_lob_guard` (3842–3877)、`consume_hero_native_video_frame/hero_native_frame_state/_aspect_fit_image_rect(static)/draw_hero_native_background` (5002–5091)
- 耦合：中。共享 `backend/vision/camera_worker/video_pipeline/composite_vision/local_vision/tongji_*/hero_deploy_ui/hero_deploy_renderer/state`。

### D8 目标锁定 / 自瞄 FOV / ESP 线框（~1200 行）
- FOV/锁定判定：`autoaim_logical_size/autoaim_circle_radius/sync_local_autoaim_fov/armor_center_in_autoaim_fov/vision_target_in_autoaim_fov/apply_autoaim_fov_lock/vision_result_for_display/interpolated_vision_result/has_valid_combat_target/vision_result_calibrated` (5283–5429)
- ESP 绘制：`draw_target_overlay` (7244)、荧光白族 `draw_fluorescent_white_segments/_polyline/rasterize_fluorescent_white_circle/_ellipse` (7276–7441)、`draw_armor_fov_circle` (7442)、三种锁框 `draw_white_outline_lock/draw_minimal_bracket_lock/draw_rune_ring_lock` (7459–7545)、`armor_esp_points/armor_esp_back_points/draw_3d_esp_box/constrain_prediction_geometry/draw_clean_3d_esp_box/draw_polar_mechanical_wire` (7551–7728)、GPU 批量线框 `_vision_wire_key/_append_vision_wire_armor/build_vision_wire_batch/paint_gpu_vision_layer` (7729–7962)、`draw_armor_quad/smooth_armor_geometry/draw_armor_3d_esp` (7963–8186)
- 耦合：中。共享 `vision_render_interpolator/target_hud_presence/_armor_geometry_smooth/_fluorescent_circle_cache/vision_wire_gpu/calibration`。`build_vision_wire_batch` 是纯几何批处理，最易先切。

### D9 战斗 HUD 绘制（CPU QPainter）（~1100 行）
- 总 HUD：`draw_rm_hud` (7004)、HUD 风格助手 `hud_density/target_hud_style/hud_visual_tone/hud_clean/hud_accent/hud_surface/hud_panel_outline/hud_warning/hud_danger/hud_success/hud_state_color/liquid_map_enabled/liquid_map_setting/liquid_map_bool` (7076–7160)、`draw_watermark` (7161)
- 准星/云台：`draw_crosshair` (8474)、`draw_chassis_gimbal_indicator/draw_chassis_gimbal_compass_base/draw_chassis_body_direction/draw_gimbal_turret_direction/direction_point/animated_angle/animated_scalar/chassis_follow_mode` (8490–8731)
- 目标 HUD：`combat_target_visual/draw_combat_target_arc/draw_combat_target_hud/draw_combat_target_hud_layer/combat_health_color/combat_heat_color/draw_combat_target_card` (8187–8473)、`paint_combat_target_overlay` (3102)、`paint_gpu_target_hud_layer` (3127)、样式分发族 `draw_target_hud_by_style/draw_target_round_compact/draw_target_bar_only/target_ratio/target_short_name/target_compact_info/draw_target_card` (11906–11993)
- 耦合：中。共享 `combat_hud_animator/telemetry_render_tracks/hud_angle_tracks/state`。HUD 风格助手被 D6/D10/D12 广泛复用（跨域读）→ 应最先抽成独立 helper 模块。

### D10 战术地图 / 官方地图 / 状态坞（~1800 行）
- 入口/交互态：`queue_gpu_module_list/draw_module_list_for_tactical_map/draw_match_header` (9144–9190)、`draw_tactical_map_hud` (9191)、`tactical_map_rect/tactical_map_morph_progress/tactical_map_hold_amount/publish_map_click_from_screen/open_event_command_menu` (9286–9415)、chrome/status 助手 `tactical_map_chrome/tactical_map_status_display/effective_tactical_map_status_display/tactical_map_status_kind/tactical_map_footer_height/liquid_status_footer_height` (9416–9475)
- 液态地图：`draw_liquid_tactical_map_hud` (9476)、`official_map_fit_rect/draw_liquid_map_robots/draw_liquid_mini_status_overlay/draw_liquid_mini_status_chip/liquid_entity_color/map_team_color/map_control_color/draw_liquid_radar_pointer` (9558–9753)
- 状态坞：`draw_liquid_status_dock/draw_liquid_status_row/draw_liquid_status_item/liquid_status_color/draw_liquid_status_bar/draw_liquid_status_card` (9754–10081)
- 官方地图：`draw_official_map` (10082–10179，⚠️ 并行编辑区)、`official_map_image/official_map_display_image/fit_aspect/map_point/draw_map_zones/draw_map_robots/draw_map_markers` (10180–10316)、轨道坞/黑洞盘 `draw_map_status_orbit_dock/draw_blackhole_disc_row/animated_status_ratio/draw_blackhole_status_disc/draw_status_label_capsule` (10317–10572)、状态行数据 `map_status_groups/map_telemetry_status_rows/draw_match_status_lines/_stack/_rings/match_status_ring_rows/short_ring_number/short_outpost_value/match_status_rows` (10573–10779)、遥测条 `draw_telemetry_strip/draw_compact_telemetry_strip/format_time` (10780–10863)、`draw_right_hud_mode` (9104)
- 耦合：中低。大量方法是 `(p, rect, config) → None` 形态，读 `state/official_feed/map_images/map_display_cache/tactical_map_state`。`draw_official_map` 新增的 `_rounded_map_layer` 圆角预裁剪有界缓存是性能纪律范本（见 §7）。

### D11 动态岛（~500 行）
- `dynamic_island_bottom_anchor` (5567)、`draw_dynamic_island/_draw_dynamic_island_legacy/dynamic_smooth/dynamic_island_payload/dynamic_message_kind/dynamic_message_title` (8732–8952)、GPU 图标收集 `begin_gpu_island_icon_collection/begin_gpu_hud_command_collection/flush_gpu_hud_commands/flush_gpu_island_icons` (8953–9003)、`draw_dynamic_island_icon` (9053–9103)
- 耦合：中。共享 `dynamic_island_state(IslandContainerState)/island_icon_gpu/_gpu_island_icon_commands/_collect_gpu_island_icons/dynamic_smooth_values/dynamic_island_last_event`。payload 组装读全窗口状态（消息源多）。

### D12 ModuleList 模块列表（~1500 行）
- 布局/入口：`module_list_layout` (10864)、`draw_minecraft_module_list` (10885)、`draw_module_list_hud` (10915)、`draw_module_list_fast_rows` (10976)、`module_list_preferences/module_list_tag(static)/module_list_surface/module_list_entries` (11003–11116)、`build_gpu_module_list` (11995–12087)
- 字体/阴影工具：`debug_tahoma_font/debug_tahoma16_font/measure_debug_tahoma16/arraylist_shadow_image/draw_string_with_shadow_mc` (11117–11240)
- 十种样式变体：`draw_module_list_debug_white/_liquid_array/_polar_text/_rainbow_right/_glow_rows/_segmented/_dynamic_island/_keybind_rows/_status_bars/_robot_cards` (11241–11778)
- 周边 HUD：`draw_keybinds_strip/draw_keybinds_hud/draw_robot_list_hud/draw_status_cards_hud/draw_rm_indicators_hud` (11779–11905)
- 耦合：中低。共享 `registry/module_list_rows/_module_list_sort_cache_key/_module_list_sort_widths/fonts`。样式变体之间零互相调用，是最典型的可切分域。

### D13 快捷轮盘 + 比赛聊天（~600 行）
- 轮盘：`quick_action_sector_path` (2829)、`draw_quick_action_wheel` (2860–3007)、GPU 收集 `begin_gpu_quick_action_wheel_collection/flush_gpu_quick_action_wheel` (9004–9052)、交互 `begin_/cancel_/finish_quick_action_wheel/execute_quick_action` (4113–4177)、设置同步 `sync_quick_action_wheel_settings/apply_quick_action_wheel_to_settings` (16486–16547)
- 聊天：`open_match_chat/close_match_chat` (4074–4112)、`draw_match_chat/match_chat_reserved_height` (3008–3101)
- 耦合：低。共享 `quick_action_wheel(QuickActionWheelState)/match_chat(MatchChatController)/chat_event_adapter/overlay_coordinator`。

### D14 Minecraft 功能槽（~120 行）
- `append_minecraft_drop_overlay/assign_minecraft_function_slot/activate_minecraft_function_slot` (3508–3588)；配合 `minecraft_hud(MinecraftCombatHudRenderer)/_last_minecraft_hud_layout`
- 耦合：低，边界清晰，可最早切出。

### D15 输入 / hotspot / dispatch（~1150 行）
- `add_hotspot` (14451)、`mousePressEvent/mouseMoveEvent/mouseReleaseEvent/wheelEvent/keyPressEvent/keyReleaseEvent` (14461–14942)、`handle_tactical_map_hold_event/handle_control_key_event/combat_control_input_allowed/toggle_bound_module_for_event/publish_spin_control_state/handle_keybind_event` (14943–15050)、`dispatch` (15051–15310，260 行巨型动作路由)、按键工具 `qt_button/key_name/keybind_matches/is_right_shift_event` (16837–16889)、`_clear_control_inputs_for_lock` (4868)
- 耦合：**极高**。dispatch 按 action 字符串路由到所有域；hotspots 由各绘制域填充。此域必须最后一个动，或只做"action handler 注册表"化改造。

### D16 动作处理 / 配置动作 / 资格赛（~750 行）
- `after_setting_changed` (15311)、`handle_config_action` (15390–15580)、`handle_qualification_action` (15581–15836)、`start_kmc_qualification_test` (15837–15907)、`restore_compact_hud` (15931)、`on_module_toggled` (15952)、`play_gui_transition_sound/preview_elimination_fx/handle_calibration_action` (16019–16079)
- 耦合：高（触达 backend/config_store/calibration/ui_audio/kill_fx/所有 UI 态），与 D15 dispatch 是一对。

### D17 配置 / 档案 / 壁纸持久化（~550 行）
- `apply_match_mode/apply_robot_profile/seed_match_state` (16142–16207)、`current_robot_profile_key/current_robot_performance` (12889)、`refresh_config_profiles/refresh_wallpaper_profiles/refresh_custom_ui_sound_options/custom_ui_sound_selection/import_custom_ui_sound/import_wallpaper_from_dialog/apply_/remove_/reset_wallpaper_profile` (16208–16331)、`current_profile/current_config_data/load_startup_config/apply_config_data/sync_runtime_from_registry/save_current_config/reload_current_config/import_config_from_dialog/auto_save_config/flush_auto_save_if_due/flush_auto_save/sync_mode_setting` (16332–16485)、`panel_modules/get_setting_number/get_auto_ui_scale/get_hud_scale/high_res_optimize/video_sample_size/get_gui_scale` (16548–16611)
- 耦合：中。共享 `config_store/scenario_manager/match_mode_manager/startup_wallpaper/paths/registry`。auto-save 已做合并写（`_auto_save_pending/_auto_save_due_at`），勿破坏。

### D18 官方消息 / 战斗事件 / 击杀特效（~170 行）
- `consume_official_messages/apply_official_state/process_vision_kill_events/accept_combat_event` (5437–5525)、`elimination_element_toggles/update_elimination_hit_info` (5526–5566)、`draw_elimination_fx` (5583–5605)
- 耦合：低。共享 `official_feed/vision_kill_detector/kill_fx/state`。**最低耦合域之一，适合作为 mixin 化试点。**

### D19 绘制 / 文本 / 缩放工具（~400 行）
- 文本：`font/text_advance/font_line_height/draw_text/draw_glass_text/elide/rect_visible/toast/category_icon` (16676–16836)、`_client_asset_path` (11117)、`setting_bool/setting_mode/anim_duration/gui_mode_label` 等
- 耦合：**被全域依赖**（fonts 缓存 `_text_metric_cache/_font_height_cache/_elide_cache`）。应抽成 `UiTextContext`/helper 最先服务化，其余域改为显式依赖注入。

### D20 附注：重复定义（重构时顺带修复）
以下三组方法在同一类中**定义了两次**，后者静默覆盖前者（Python 语义），机械移动时必须去重：
- `startup_scenario_meta`：6912 与 6955
- `startup_match_meta`：6934 与 6977
- `reset_startup_page_animation`：6950 与 6993

另发现死代码：`paint_gpu_frame` (2036) 首行即 `return self._paint_gpu_frame_cached()`，其后 2040–2143 为不可达旧实现。

---

## 3. 外部触点清单（公共 API 冻结面的依据）

全仓 grep `polar_app` 结果（共 7 个文件引用）：

| 引用方 | 导入符号 | 用途 |
|---|---|---|
| `main.py:59` | `from rm_client.ui.polar_app import main` | 入口转发 |
| `rm_client/app.py:655` | `from .ui.polar_app import main as run_gpu_client` | 应用内启动 GPU 客户端 |
| `tools/economy_live_capture.py` | `PolarRMWindow` | 经济工作台桌面截图回归 |
| `tools/overlay_live_capture.py` | `PolarRMWindow` | 轮盘/聊天/ClickGUI 交互链路截图 |
| `tools/modlist_rgb_audit.py` | `PolarRMWindow` | ModuleList 十种样式 RGB 审计（直接调 `draw_module_list_hud`） |
| `tools/visual_audit.py` | `PolarRMWindow` | 多 GUI 模式视觉基线 |
| `tools/render_combat_target_hud_baselines.py` | `PolarRMWindow` | 战斗目标 HUD 基线渲染（直接调 `draw_combat_target_hud`） |
| `tests/smoke_test.py`（13 处 import） | `PolarRMWindow`、`EconomyScenePhase`、`InertialScroll`、`FrameScheduler` | 大规模单元/集成测试，直接驱动窗口方法 |
| `tests/transition_visual_check.py` | `PolarRMWindow` | 启动页转场 2K 截图回归 |

**关键发现**：`tests/smoke_test.py` 对 `window.<member>` 的直接访问覆盖了 **约 190 个不同成员**，其中包括大量下划线私有成员。这意味着冻结面不是"公共方法子集"，而几乎是"整个类表面"。统计明细（出现次数 ≥2 的抽样）：

- 高频属性：`hotspots`(28)、`jello_state`(37)、`registry`(23)、`state`(16)、`overlay_coordinator`(10)、`gui_visible`(8)、`resize`(8)、`economy_phase`(7)、`close`(11)、`backend`(6)、`home_visible`(6)、`clickgui_gpu`(6)、`gui_timeline`(5)、`gui_motion`(7)、`gui_scroll_viewports`(5)
- 私有成员（测试直读/直写）：`_economy_generation`(4)、`_economy_restore_pending_generation`(5)、`_elide_cache`(4)、`_gpu_hud_commands`(5)、`_finalize_economy_restore`(3)、`handle_tactical_map_hold_event`(3)、`_normal_frame_source`(3)、`_watermark_title_cache(_key)`、`_gpu_blur_source_key`、`_gpu_control_backdrop_key`、`_gpu_static_ui_key`、`_gpu_motion_layer_ready`、`_collect_gpu_hud_commands`、`_display_frame_sequence`、`_vision_source`、`_hero_native_video_at`、`_jello_gpu_fonts`、`_jello_module_text_pages`、`_last_minecraft_hud_layout`、`_economy_close_finalized`、`_economy_pending_overlay`、`_last_capture_sequence`、`_last_present_time`、`fps_samples`、`frame_image/frame_pixmap`、`_target_box_regression_failed`（transition 测试**写入**）
- 直调的绘制方法（smoke_test 注入 QPainter 验证像素输出）：`build_gpu_clickgui`(16)、`dispatch`(4)、`draw_video`、`draw_watermark`、`draw_text`、`draw_glass_text`、`draw_elide`、`draw_economy_overlay_compat`、`draw_armor_3d_esp`、`draw_chassis_gimbal_indicator`、`draw_combat_target_hud(_layer)`、`draw_dropdown_gui`、`draw_dynamic_island`、`draw_hero_deploy_interface`、`draw_hero_native_background`、`draw_hud_liquid_glass`、`draw_liquid_status_bar/card`、`draw_match_chat`、`draw_match_header`、`draw_minecraft_module_list`、`draw_module_list_debug_white/_hud`、`draw_new_gui`、`draw_old_gui`、`draw_panel_gui`、`draw_quick_action_wheel`、`draw_tactical_map_hud`、`draw_telemetry_strip`、`draw_elimination_fx`、`paint_clickgui_overlay`、`paint_combat_target_overlay`、`paint_hud_motion_overlay`、`update_hud_liquid_source`、`consume_capture_frame`、`consume_hero_native_video_frame`、`build_gpu_economy_workspace`、`build_gpu_robot_profile_launcher` …等

**结论**：重构必须采用**保持类表面不变**的手法（mixin 继承 / 同名模块级函数包装），而不是改造成组合+委托后删除原入口。详见 §5 冻结面。

---

## 4. 依赖方向分析

```
                    ┌────────────────────────────────────────────┐
                    │        D0 __init__（状态 schema 定义者）      │
                    └──────┬─────────────────────────────────────┘
           ┌───────────────┼─────────────────┐
           ▼               ▼                 ▼
   D1 on_tick 编排 →  D2 GPU 帧编排  →  D3 paint_overlay 分发
   （驱动一切）        （FBO 层管理）      （CPU 绘制总线）
           |               |                 |
     ┌─────┴───────┬───────┴──────┬──────────┴────┬─────────────┐
     ▼             ▼              ▼               ▼             ▼
 D7 视频/后端   D18 官方事件   D4 startup    D5 clickgui   D6 经济
 D8 ESP 锁定   D9 战斗HUD    D11 动态岛     D12 ModuleList D13 轮盘/聊天
              D10 战术地图   D14 MC槽位     D15 输入/dispatch ←── 各域回写 hotspots
                     D16 动作处理  D17 配置持久化
                              ▲
              D19 工具层（font/draw_text/elide/scale）← 被以上所有域调用
```

### 依赖要点

1. **D19（文本/字体/缩放工具）是被所有人依赖的底座**，且带三个每帧查询缓存。它必须第一个抽离为无状态 helper 模块（显式传入 window 或 context），否则后续任何域外迁都拖着它走。
2. **D15（输入/dispatch）与 D16（配置动作）是反向汇聚点**：所有绘制域通过 `add_hotspot(action=...)` 向 D15 投递字符串，D15.dispatch 再 if/elif 路由回来。这是最大的隐性双向耦合。解法：dispatch 改成 action-handler 注册表（各域 mixin 自注册 `self._register_actions({...})`），而不是把 dispatch 本身搬走。
3. **D2 ↔ D6 存在唯一的跨域协议耦合**：经济关闭的 FBO 原子清理（`_economy_restore_pending_generation` + `invalidate_transient_overlay_scene` + `clear_scene_layers`）。迁移 D6 时该协议必须整体搬移并在文档标注。
4. **D9 的 hud_accent/hud_clean 等 20 个风格 getter 被 D6/D10/D12 跨域调用**——它们实际是"主题服务"，不是战斗 HUD 私有物。应随 D19 一起进入 theme/helper 层。
5. **低耦合、可先行切分的域排序**（依据：对外只读 state/registry、不写共享热点结构、不被 dispatch 反向深调）：
   - ① D14 minecraft 槽位（~120 行，几乎孤立）
   - ② D18 官方事件/击杀特效（~170 行）
   - ③ D13 轮盘+聊天（~600 行）
   - ④ D12 ModuleList 样式变体（十变体互不调用）
   - ⑤ D8 ESP 线框批量构建（build_vision_wire_batch 纯几何）
   - ⑥ D4 startup liquid 控件族（近纯函数）
   - 高风险殿后：D15/D16（dispatch 路由）、D2（帧编排）、D0（构造）。

---

## 5. 拆分蓝图（分阶段）

### 阶段划分原则

1. **先纯函数/渲染器类（低风险）→ 再 mixin 化大域 → 最后窗口壳**；
2. 每一步之后 polar_app.py 必须**仍然可直接运行**且外部 import 不变（`polar_app` 作为兼容壳 re-export 一切被引符号）；
3. 手法优先级：**机械移动（模块级函数/独立类）> mixin（方法留在类上，保住 `window.xxx` 表面）> 参数化 self > 重写**。禁止在本轮重构中重命名/删除任何 §5.6 冻结面成员；
4. 每阶段一个 PR/commit，提交前跑该阶段对应的验证矩阵。

目标子包结构：

```
rm_client/ui/polar/
├── __init__.py            # re-export 兼容面
├── primitives.py          # FrameScheduler/InertialScroll/StartupLayerCache/
│                          # Hotspot/ModuleListLayout/EconomyScenePhase
├── text_metrics.py        # D19：字体/测量/draw_text/draw_glass_text/elide + 三缓存
├── hud_theme.py           # D9 的 hud_* 风格 getter（主题服务）
├── renderers/
│   ├── combat_target_hud.py
│   ├── esp_wireframe.py
│   ├── module_list.py
│   ├── tactical_map.py
│   ├── dynamic_island.py
│   └── startup_scene.py
├── mixins/                # 大域 mixin（阶段 3）
│   ├── economy_mixin.py
│   ├── clickgui_builders_mixin.py
│   ├── video_backend_mixin.py
│   ├── input_dispatch_mixin.py
│   ├── config_actions_mixin.py
│   └── persistence_mixin.py
└── app_entry.py           # main()（最后阶段）
```

### 阶段 0：安全网与冻结面固化（半天）

- 内容：
  - 把 §5.6 冻结面写成自动化守卫：新增 `tests/api_freeze_test.py`，用 `dir(PolarRMWindow)` 断言全部冻结成员存在且 callable/attribute 类型正确；
  - 记录当前基线截图：跑 `tools/visual_audit.py`、`tools/render_combat_target_hud_baselines.py`、`tests/transition_visual_check.py`，产物存档；
  - 清理两处已知瑕疵（可选但建议先行，独立 commit）：①三组重复方法定义去重（§2.20）；②`paint_gpu_frame` 死代码块删除（2036 return 之后）。
- 风险：低。验证：`pytest tests/smoke_test.py` 相关段 + 守卫测试绿。

### 阶段 1：叶子外迁 —— primitives + text 工具（1 天）

- 提取目标：`ui/polar/primitives.py`（六个顶层小类，机械移动，polar_app 顶部 `from .polar.primitives import ...` 保持 import 兼容——smoke_test 直接 `from rm_client.ui.polar_app import FrameScheduler` 必须继续成立）；
- `ui/polar/text_metrics.py`：`mix_color`、`economy_lerp_rect`、`fit_aspect`、`_aspect_fit_image_rect`、`format_time`、`short_ring_number`、`short_outpost_value`、`painter_device_scale` 先以**模块级纯函数**迁出；`font/text_advance/font_line_height/draw_text/draw_glass_text/elide` 及 `_text_metric_cache/_font_height_cache/_elide_cache` 以 mixin（`TextMetricsMixin`）迁出——保持 `self.font(...)` 调用面；
- 迁移手法：机械移动 + mixin；风险：低；
- 验证：api_freeze_test + smoke_test 中 font/draw_text/glass_text 段 + `FrameScheduler/InertialScroll` 单测仍过。

### 阶段 2：渲染器提取（2–4 天，按序逐个提交）

每个 renderer 按同一套路：先把方法组剪切成 `renderers/<name>.py` 的 Mixin 类（方法体不动，签名不动）→ `PolarRMWindow(...)` 继承列表追加 → 跑视觉基线。稳定后再（可选、另一 PR）把 Mixin 降级为"接收 window 参数的渲染器函数"。

| 序 | 目标模块 | 包含符号（域编号） | 行数估计 | 风险 | 验证手段 |
|---|---|---|---|---|---|
| 2a | `renderers/combat_target_hud.py` | D9 目标 HUD 族 + `combat_hud_animator` 接线（3102–3206, 8187–8473, 11906–11993） | ~700 | 低 | `render_combat_target_hud_baselines.py` 像素 diff + smoke_test draw_combat_target_hud 段 |
| 2b | `renderers/esp_wireframe.py` | D8 全部（5283–5429, 7244–7545, 7551–8186） | ~1200 | 中低 | transition_visual_check target_hud 段（`_target_box_regression_failed` 回归断言）+ smoke_test draw_armor_3d_esp |
| 2c | `renderers/module_list.py` | D12 全部 + `ModuleListLayout` + 排序缓存 | ~1500 | 中低 | `modlist_rgb_audit.py` 十样式 RGB 审计 |
| 2d | `renderers/tactical_map.py` | D10 全部（含官方地图并行编辑区——等另一代理完成后 rebase） | ~1800 | 中 | smoke_test tactical_map 段 + 截图对比 |
| 2e | `renderers/dynamic_island.py` | D11 全部 | ~500 | 低 | overlay_live_capture 截图 |
| 2f | `renderers/startup_scene.py` | D4 全部（含壁纸选择器） | ~1700 | 中 | `transition_visual_check.py` 四张 2K 转场图 |

注意：2d 之前必须确认 draw_official_map 区域并行修改已合并完毕（git log 该区域），否则会产生冲突。

### 阶段 3：大域 mixin 化（3–5 天）

| 序 | 目标模块 | 包含符号 | 行数 | 风险 | 特别注意 |
|---|---|---|---|---|---|
| 3a | `mixins/persistence_mixin.py` | D17 全部 | ~550 | 中 | auto-save 合并写纪律不能破坏；`load_startup_config` 在 `__init__` 中被调用，mixin 方法在 `__init__` 可用性由 MRO 保证，需加冒烟 |
| 3b | `mixins/video_backend_mixin.py` | D7 + D18 + D14 | ~1600 | 中 | tick stage 列表仍在 D1 引用这些方法名——名字不变即可 |
| 3c | `mixins/clickgui_builders_mixin.py` | D5 全部 | ~2600 | 中高 | builder 边画边 `add_hotspot`；`gui_scroll_viewports` 注册协议保持 |
| 3d | `mixins/economy_mixin.py` | D6 全部 | ~2100 | 高 | D2↔D6 FBO restore 协议整体搬迁；`economy_live_capture.py` 全链路回归（opening/mid_close/closed 三相截图） |
| 3e | `mixins/input_dispatch_mixin.py` | D15 | ~1150 | 高 | 先把 dispatch 的 if/elif 路由表化为 `{action: handler}` 注册表（行为等价重构，单独 commit），再整体搬移 |
| 3f | `mixins/config_actions_mixin.py` | D16 | ~750 | 高 | 与 3e 成对，资格赛流程（KMC 75Hz）需实机验证 |

验证矩阵（3c 起）：`pytest tests/smoke_test.py` 全量 + `tools/visual_audit.py` + `tools/overlay_live_capture.py` + `tools/economy_live_capture.py`。

### 阶段 4：窗口壳收编（2 天）

- 最终形态：`polar_app.py` 只保留
  - `PolarRMWindow(QOpenGLWidget)` 壳：`__init__`（装配，顺序不动）、`on_tick` 编排骨架（stage 列表）、`paintGL`、`resizeEvent/closeEvent/focusOutEvent`、`initializeGL`、`paint_overlay` 分发器、`VisionViewport/PolarHudOverlay`；
  - 底部 `def main()`（或移至 `polar/app_entry.py` 并在 polar_app re-export）。
  - 类声明形如 `class PolarRMWindow(TextMetricsMixin, StartupMixin, ..., QOpenGLWidget):`——**QOpenGLWidget 必须放最后**，自定义 Mixin 在前（Qt 前置 MRO 无冲突，因为 Mixin 不重写 Qt 虚函数除事件处理器所在 mixin——mouse/key 事件在 input mixin 中，MRO 顺序在阶段 3e 时用 `PolarRMWindow.__mro__` 断言固化到 api_freeze_test）。
- 风险：高（初始化顺序敏感：`__init__` 里调用了 mixin 方法 `setting_bool/sync_quick_action_wheel_settings/apply_match_mode/...`，MRO 变化可能暴露属性未初始化）。缓解：阶段 0 的 api_freeze_test 加"构造即冒烟"（`POLAR_AUTOSTART=1` 下实例化并 processEvents 数帧）。
- 验证：全量验证矩阵 + 手工实机跑一轮完整流程（启动页→匹配→经济→ClickGUI→资格赛入口）。

### 5.6 公共 API 冻结面（重构中绝对不变量）

**模块级符号**（import 路径 `rm_client.ui.polar_app` 必须继续可用）：
`PolarRMWindow`、`main`、`EconomyScenePhase`、`InertialScroll`、`FrameScheduler`（Hotspot/ModuleListLayout/StartupLayerCache/VisionViewport/PolarHudOverlay 目前未被外部 import，但建议一并保留导出以防 tools 演进）。

**PolarRMWindow 成员**——以下被 tools/tests 直接触达，重构期间禁止改名/改签名/改可见性（私有成员也冻结）：

- Qt 面：`show/close/resize/update/repaint/grabFramebuffer/winId/devicePixelRatioF/width/height/screen/mapToGlobal/makeCurrent/doneCurrent/keyPressEvent`
- 状态属性：`registry, state, backend, mode_manager, calibration, camera_worker, timer, ui_audio, frame_image, frame_pixmap, _last_capture_sequence, _last_present_time, fps_samples, home_visible, startup_step, gui_visible, gui_timeline, jello_state, jello_clickgui, gui_motion, polar_unified_morph, hotspots, selected_category, selected_module, economy_visible, economy_phase, economy_island, economy_bridge, quick_action_wheel, match_chat, overlay_coordinator, hero_deploy_ui, tactical_map_hold, tactical_map_state, minecraft_hud, liquid_glass, startup_wallpaper, combat_hud_animator, gpu_compositor, clickgui_gpu, target_hud_presence, render_frame_ms_ema, render_fps_target, frame_scheduler, wallpaper_picker_visible, gui_scroll_viewports`
- 私有但被测试读写：`_gpu_background_key, _gpu_static_ui_key, _gpu_blur_source_key, _gpu_control_backdrop_key, _gpu_hud_commands, _collect_gpu_hud_commands, _gpu_motion_layer_ready, _normal_backend_mode, _normal_frame_source, _display_frame_sequence, _vision_source, _watermark_title_cache, _watermark_title_cache_key, _elide_cache, _economy_generation, _economy_pending_overlay, _economy_restore_pending_generation, _economy_close_finalized, _hero_native_video_at, _last_minecraft_hud_layout, _target_box_regression_failed`（最后一项由 transition 测试写入，需保证实例上可赋值）
- 方法（外部直调）：`ensure_camera_started, open_economy_workspace, close_economy_workspace, set_clickgui_visible, open_legacy_clickgui, begin_startup_page_transition, dispatch, consume_capture_frame, consume_hero_native_video_frame, update_hero_deploy_state, close_hero_deploy_interface, execute_quick_action, on_module_toggled, handle_tactical_map_hold_event, active_clickgui_mode, economy_stage_active, effective_tactical_map_status_display, economy_offers, normal_video_frame_ready, current_config_data, auto_save_config, get_hud_scale, module_list_layout, tactical_map_rect, compact_map_status_label, combat_target_visual, update_hud_liquid_source, elide, font, text_advance, draw_text, draw_glass_text, toast, anim_duration, setting_bool, setting_mode, build_gpu_clickgui, build_gpu_economy_workspace, build_gpu_robot_profile_launcher, _finalize_economy_restore, _jello_gpu_fonts, _jello_module_text_pages` 以及 §3 列出的全部 `draw_* / paint_*` 家族。

---

## 6. 性能注意点（热路径与缓存纪律）

### 热路径调用链

```
QTimer(self.timer, interval≈4ms) → on_tick (最高 render_fps_target=240Hz)
 ├─ UI 时间线推进（gui_timeline/jello_state/economy_island/dynamic_island_state/InertialScroll×4…）
 ├─ 75Hz 门控 → control.tick
 ├─ 60Hz 门控 → 12 个逻辑 stage（backend/official/vision/fx/registry.tick）
 └─ FrameScheduler.should_request → self.update() → paintGL
      └─ paint_gpu_frame → _paint_gpu_frame_cached
           ├─ gpu_compositor.begin_frame(rebuild_static_ui=key变化才True)
           ├─ paint_gpu_background（背景层，key 失效制）
           ├─ set_backdrop_treatment / paint_gpu_control_backdrop
           ├─ paint_gpu_vision_layer（视频纹理仅在新源帧上传）
           ├─ 静态 overlay 层：仅 gpu_static_ui_key 变化时整帧重画（paint_overlay split_motion_layer）
           ├─ dynamic 层：每帧（motion HUD + flush_gpu_hud_commands/island icons）
           └─ render_glass + present（唯一一次触碰窗口默认 FBO）
```

### 重构红线

1. **不得在 on_tick 增加 O(域数量) 的新工作**：stage 列表已是显式元组，迁移 stage 回调到 mixin 时保持列表结构与门控（60Hz/75Hz）不动。
2. **静态 key 失效纪律**：`gpu_static_ui_key/_gpu_background_key/_gpu_control_backdrop_key/_gpu_blur_source_key` 是"内容变化才重画"的核心。任何被迁入 renderer 的绘制代码，其失效键计算必须随方法一起迁移且结果 bit 级一致（建议 api_freeze_test 中加 key 函数纯度断言：同参数两次调用返回相同 tuple）。
3. **已有缓存机制一览**（迁移时归属跟域走，key 生成逻辑一字不改）：
   - `gui_cache`（ClickGuiLayerCache，resize 即清）
   - `map_display_cache`（官方地图显示尺寸重采样缓存，resize 即清）
   - `_rounded_map_layer` 圆角地图预合成缓存（含源图 cacheKey()，有界——新代码范本）
   - `_fluorescent_circle_cache`（CPU 荧光圆环位图）
   - `_text_metric_cache/_font_height_cache/_elide_cache`（文本度量/省略，每帧被数十个稳定 label 查询）
   - `synthetic_video_cache`、`_watermark_title_cache`、`_module_list_sort_widths`
   - `StartupLayerCache._vignettes`（容量 4 有界清空策略）
4. **禁止每帧路径引入**：新的 per-frame dict/set 重建、QFontMetricsF 反复构造、不必要的 painter save/restore、per-frame QImage/QPixmap 分配。需要新中间产物时照抄 `_rounded_map_layer` 的"有界 + key 失效 + dpr 对齐"模式。
5. **`tune_render_rate` 已注释"不再自动降档"**（2432–2470）：呈现节奏由 UIScale.HUD Refresh Rate 独立控制，重构不得恢复自动降档逻辑，也不得把媒体帧率（24/30/60）与 HUD 呈现率重新耦合。
6. **`paint_gpu_frame` 死代码块**（2040–2143）删除属于零风险清理，但应在阶段 0 单独 commit，便于后续 diff 定位。
7. **Windows 驱动脉冲坑**：`startup_gpu_enabled=False`（原生视频 shader 路径禁用）与 `_paint_gpu_frame_cached` 中"事件线程不能清 FBO → generation 延迟到下一渲染帧原子执行"的协议，都是踩坑后的修复。迁移相关代码时注释必须随行搬运，禁止"顺手简化"。

---

## 7. 开工检查单（摘要）

1. ☐ 阶段 0：api_freeze_test + 视觉基线存档 + 重复定义/死代码清理
2. ☐ 确认 draw_official_map 区域并行修改已合并（git blame 10082–10179）
3. ☐ 阶段 1：primitives.py + text_metrics.py（mixin 保 `self.font` 面）
4. ☐ 阶段 2a–2f：六个 renderer mixin，每个独立 commit + 基线 diff
5. ☐ 阶段 3a–3f：大域 mixin；3e 先做 dispatch 注册表化行为等价重构
6. ☐ 阶段 4：壳收编 + MRO 断言入 api_freeze_test
7. ☐ 每步之后：`python -c "from rm_client.ui.polar_app import main, PolarRMWindow"` 冒烟 + 对应验证矩阵
