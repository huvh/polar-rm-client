# hjq 验证记录（2026-10-26）

## 已通过

- 客户端全部Python源码可解析，`rm_client.ui.polar_app` 导入成功。合并冲突标记导致的启动失败已修复。
- 资源包及来源参考包完整性通过；474个暂存资源文件与已校验的工作区字节一致。当前原生构建：`build_831506e45160efe8`。
- 静态质量门禁通过：300个模块、4069个函数、0个初始化循环。
- `tests/endfield/` 全部专项检查通过，覆盖设置全部分类、独立键盘、窗口缩放、滚动/输入、公告、Wiki、菜单及资源校验。
- 设置中心13项、宿主关闭9项、嵌套工厂所有权5项，Git可见性1项、工具输出可见性6项通过。
- 合并后的计分板与2027前端规则专项检查通过。
- Windows实窗：普通窗口与150%缩放全屏分别完成设置/键盘 × 返回/关闭/Esc的6条路径；键盘测试包含F11往返及F12急停。
- Windows原生表面：窗口移动、最小化恢复、全屏、真实原生按钮命中、世界背景GPU高斯处理及3次菜单往返通过，无纹理增长，退出回收成功。

原生界面验证只使用客户端自有呈现窗口和惰性设备替身。设置/键盘入口由原生语义动作队列注入，Qt按钮真实点击；原生菜单按钮命中另行验证。GPU验证未启动游戏，不代表硬件、实战或帧率资格。

## 尚未通过的回归

稳定源码上复查110套：70 PASS、35 FAIL、5 INCOMPLETE。这是选中范围的复查；全部离线回归尚未通过。

失败包括旧界面/部署行为快照、缓存与生命周期断言、旧补丁入口、设置文档数目、协议/图传回归和可移植串口测试。各项需继续核对，PR保留为草稿。未覆盖真实裁判系统、机器人、摄像头或固件烧录。

| 状态 | 测试 | 摘要 |
| --- | --- | --- |
| FAIL | `tests/api_freeze_test.py` | FAIL: 与基线 api_freeze_baseline.json 不一致（exit 2） |
| FAIL | `tests/backend_protocol_test.py` | [FAIL] Uncaught exception reported by verification callback |
| INCOMPLETE | `tests/polar_link_test.py` | [SKIP] 未找到队内 CRC8_CRC16.py 参考实现，跳过三方对拍 |
| FAIL | `tests/settings_doc_consistency_test.py` | [FAIL] 文档「小节标题」等于实测 20  -> 写作 21 / [FAIL] 文档「示例命令」等于实测 20  -> 写作 21 / [FAIL] 文档「结果表」等于实测 20  -> 写作 21 |
| FAIL | `tests/smoke_test.py` | [FAIL] Uncaught exception reported by verification callback |
| FAIL | `tests/test_cached_frame_contract.py` | FAIL: test_escape_intentionally_removes_only_the_two_crisp_foreground_draws (__main__.CachedFrameCharacterizationTests.test_escape_intentionally_removes_only_the_two_crisp_foreground_draws) / FAIL: test_false_results_reject_without_present_or_fabricated_exception (__main__.CachedFrameCharacterizationTests.test_false_results_reject_without_present_o |
| FAIL | `tests/test_cached_window_layers.py` | FAIL: test_real_layouts_commands_interactions_and_raster_layers_match_frozen_entry (__main__.ActualCachedWindowTests.test_real_layouts_commands_interactions_and_raster_layers_match_frozen_entry) (scenario='hud', size=(800, 600), ratio=1.0) / FAIL: test_real_layouts_commands_interactions_and_raster_layers_match_frozen_entry (__main__.ActualCachedWin |
| FAIL | `tests/test_config_json_nesting.py` | ERROR: test_compact_accepted_indented_serializer_failure_precedes_atomic_write (__main__.ConfigurationJsonNestingTests.test_compact_accepted_indented_serializer_failure_precedes_atomic_write) |
| FAIL | `tests/test_cs2_crosshair_import.py` | FAIL: test_small_embedding_stacks_and_scrolls_without_horizontal_overflow (__main__.EditorAndPaintTests.test_small_embedding_stacks_and_scrolls_without_horizontal_overflow) (size=(1140, 830)) / FAIL: test_small_embedding_stacks_and_scrolls_without_horizontal_overflow (__main__.EditorAndPaintTests.test_small_embedding_stacks_and_scrolls_without_hori |
| FAIL | `tests/test_default_catalog_characterization.py` | FAIL: test_all_default_fields_and_order_match_frozen_source (__main__.DefaultCatalogCharacterizationTests.test_all_default_fields_and_order_match_frozen_source) (module='MatchReadiness') / FAIL: test_all_default_fields_and_order_match_frozen_source (__main__.DefaultCatalogCharacterizationTests.test_all_default_fields_and_order_match_frozen_source)  |
| FAIL | `tests/test_enabled_overlay_binding_contract.py` | FAIL: test_five_sites_preserve_getter_short_circuit_and_exception_order (__main__.EnabledOverlayBindingContractTests.test_five_sites_preserve_getter_short_circuit_and_exception_order) (name='MatchChat', phase='press', options={}) / FAIL: test_five_sites_preserve_getter_short_circuit_and_exception_order (__main__.EnabledOverlayBindingContractTests.t |
| FAIL | `tests/test_endfield_clickgui_theme.py` | FAIL: test_preloaded_raster_diagnostic_path_does_not_reload_sprites (__main__.EndfieldClickGuiThemeTests.test_preloaded_raster_diagnostic_path_does_not_reload_sprites) |
| INCOMPLETE | `tests/test_endfield_settings_import.py` | 2 unittest tests skipped |
| FAIL | `tests/test_endfield_settings_theme.py` | ERROR: test_esc_backdrop_is_transferred_before_invalidation_and_consumed_once (__main__.ThemeTests.test_esc_backdrop_is_transferred_before_invalidation_and_consumed_once) / ERROR: test_resize_does_not_restart_entrance_or_resample_text_at_rest (__main__.ThemeTests.test_resize_does_not_restart_entrance_or_resample_text_at_rest) / FAIL: test_resource_ |
| FAIL | `tests/test_framebuffer_generation.py` | FAIL: test_actual_release_false_rejects_frame_without_committing_cache_or_restore (__main__.FramebufferGenerationTests.test_actual_release_false_rejects_frame_without_committing_cache_or_restore) / FAIL: test_changed_dpr_rebuilds_even_when_physical_storage_size_is_equal (__main__.FramebufferGenerationTests.test_changed_dpr_rebuilds_even_when_physic |
| FAIL | `tests/test_gpu_command_frame_rejection.py` | FAIL: test_original_flush_reproducer_is_preserved (__main__.CommandRejectionTests.test_original_flush_reproducer_is_preserved) |
| FAIL | `tests/test_keyboard_routing_characterization.py` | FAIL: test_clickgui_repeat_correction_is_explicit_and_route_scoped (__main__.KeyboardRoutingDifferentialTests.test_clickgui_repeat_correction_is_explicit_and_route_scoped) / FAIL: test_competing_owners_keep_original_priority (__main__.KeyboardRoutingDifferentialTests.test_competing_owners_keep_original_priority) (owners=('home', 'hero'), code=<Key. |
| FAIL | `tests/test_lazy_settings_state.py` | ERROR: test_crosshair_styling_failure_releases_temporary_editor (__main__.LifecycleAudit.test_crosshair_styling_failure_releases_temporary_editor) |
| INCOMPLETE | `tests/test_legacy_intra_refresh.py` | 1 unittest tests skipped |
| INCOMPLETE | `tests/test_legacy_video_bridge.py` | 1 unittest tests skipped |
| FAIL | `tests/test_module_catalog_boundaries.py` | FAIL: test_catalog_can_import_and_build_without_state_qt_or_device_layers (__main__.CatalogBoundaryTests.test_catalog_can_import_and_build_without_state_qt_or_device_layers) / FAIL: test_pure_catalog_matches_all_frozen_defaults_without_discovery (__main__.CatalogBoundaryTests.test_pure_catalog_matches_all_frozen_defaults_without_discovery) |
| FAIL | `tests/test_native_telemetry_epoch.py` | ERROR: test_elapsed_native_timeout_blocks_even_with_retained_ammo (__main__.NativeTelemetryEpochTests.test_elapsed_native_timeout_blocks_even_with_retained_ammo) / ERROR: test_first_new_native_sample_restores_current_epoch_readiness (__main__.NativeTelemetryEpochTests.test_first_new_native_sample_restores_current_epoch_readiness) / ERROR: test_fres |
| FAIL | `tests/test_polar_health_characterization.py` | ERROR: test_both_caller_outputs_and_observation_order (__main__.PolarHealthCharacterizationTests.test_both_caller_outputs_and_observation_order) (caller='stats', estopped=False) / ERROR: test_both_caller_outputs_and_observation_order (__main__.PolarHealthCharacterizationTests.test_both_caller_outputs_and_observation_order) (caller='stats', estopped |
| FAIL | `tests/test_referee_domain_characterization.py` | FAIL: test_moved_types_and_policy_callers_have_identical_ast (__main__.RefereeDomainCharacterizationTests.test_moved_types_and_policy_callers_have_identical_ast) / FAIL: test_public_constructor_shape_and_field_order (__main__.RefereeDomainCharacterizationTests.test_public_constructor_shape_and_field_order) / FAIL: test_scenario_default_and_ordered_ |
| FAIL | `tests/test_referee_v2_air_projection.py` | ERROR: test_actual_match_mode_seed_preserves_existing_aerial_policy (__main__.V2AirProjectionTests.test_actual_match_mode_seed_preserves_existing_aerial_policy) |
| FAIL | `tests/test_referee_v2_runtime_profile.py` | ERROR: test_top_match_bar_actual_gate_and_context_reset (__main__.RuntimeProfileTests.test_top_match_bar_actual_gate_and_context_reset) |
| FAIL | `tests/test_referee_v2_uplink_admission.py` | FAIL: test_all_eight_non_economic_topics_have_real_guarded_routes (__main__.UplinkAdmissionTests.test_all_eight_non_economic_topics_have_real_guarded_routes) (topic='HeroDeployModeEventCommand') |
| FAIL | `tests/test_settings_factory_failure_cleanup.py` | ERROR: test_one_cancel_failure_preserves_primary_and_retires_other_owners (__main__.SettingsFactoryFailureCleanupTests.test_one_cancel_failure_preserves_primary_and_retires_other_owners) / ERROR: test_repeated_late_failure_retires_dialog_and_cancels_builders (__main__.SettingsFactoryFailureCleanupTests.test_repeated_late_failure_retires_dialog_and_ |
| FAIL | `tests/test_startup_confirmation_repeat.py` | ERROR: test_held_confirmation_cannot_advance_to_another_page (__main__.StartupConfirmationRepeatTests.test_held_confirmation_cannot_advance_to_another_page) (key=<Key.Key_Return: 16777220>) / ERROR: test_held_confirmation_cannot_advance_to_another_page (__main__.StartupConfirmationRepeatTests.test_held_confirmation_cannot_advance_to_another_page) ( |
| FAIL | `tests/test_ui_state_regressions.py` | [FAIL] Uncaught exception reported by verification callback |
| FAIL | `tests/test_vision_activation_contract.py` | ERROR: test_auto_reads_and_activates_receiver_before_local_configuration (__main__.VisionActivationContractTests.test_auto_reads_and_activates_receiver_before_local_configuration) / ERROR: test_constructor_and_legacy_aliases_share_one_selection_owner (__main__.VisionActivationContractTests.test_constructor_and_legacy_aliases_share_one_selection_own |
| FAIL | `tests/test_vision_refresh_heartbeat.py` | FAIL: test_held_workers_do_not_block_refresh_or_qt_but_delay_strict_close (__main__.VisionRefreshHeartbeatTests.test_held_workers_do_not_block_refresh_or_qt_but_delay_strict_close) (disabled=True, event_hold_ms=80) / FAIL: test_held_workers_do_not_block_refresh_or_qt_but_delay_strict_close (__main__.VisionRefreshHeartbeatTests.test_held_workers_do_ |
| FAIL | `tests/test_window_async_lifecycle.py` | FAIL: test_scenario_requests_coalesce_and_runtime_stays_stopped_until_poll (__main__.WindowAsyncLifecycleTests.test_scenario_requests_coalesce_and_runtime_stays_stopped_until_poll) |
| FAIL | `tests/test_window_construction.py` | FAIL: test_autostart_does_not_supersede_the_profile_generation (__main__.WindowConstructionTests.test_autostart_does_not_supersede_the_profile_generation) / FAIL: test_autostart_without_profile_captures_the_ordinary_request_projection (__main__.WindowConstructionTests.test_autostart_without_profile_captures_the_ordinary_request_projection) |
| FAIL | `tests/test_window_early_constructor_ownership.py` | FAIL: test_partial_presentation_failure_retires_prior_wallpaper_and_signal_owners (__main__.EarlyWindowConstructorOwnershipTests.test_partial_presentation_failure_retires_prior_wallpaper_and_signal_owners) |
| FAIL | `tests/test_window_presentation_prefix_failure.py` | FAIL: test_gpu_factory_rejection_retires_completed_presentation_owners (__main__.PresentationPrefixFailureTests.test_gpu_factory_rejection_retires_completed_presentation_owners) |
| FAIL | `tests/test_window_vision_runtime.py` | FAIL: test_camera_admission_failure_is_typed_and_does_not_skip_safety_or_repaint (__main__.WindowCameraRuntimeTests.test_camera_admission_failure_is_typed_and_does_not_skip_safety_or_repaint) |
| INCOMPLETE | `tests/video/test_legacy_video_latency.py` | 1 unittest tests skipped |
| FAIL | `tools/firmware/km_link/test_serial_parsers_portable.py` | ERROR: test_sanitized_random_stream (__main__.PortableSerialTests.test_sanitized_random_stream) |
| FAIL | `tools/test_mqtt_link_settings.py` | [FAIL] 旧连接退出后真实重连到最后一次配置 / [FAIL] Uncaught exception reported by verification callback |

逐项状态、执行计数及源码稳定性见 [recheck.json](recheck.json)；资源记录见 [resource-audit.json](resource-audit.json) 和 [staged-resources.json](staged-resources.json)。

本地整合期间首次全量扫描跨越了源码编辑，已由验证器判为不稳定；该次结果未作为本记录的通过证据。
