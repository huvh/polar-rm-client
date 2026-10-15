"""Display-only economy labels; no transport, timer, hardware or GL context."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ast
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage
from rm_client.ui.student_panels import StudentPanelRenderer
from rm_client.model import build_default_registry
from rm_client.ui.jello_locale import toast_text
from rm_client.ui.economy_locale import economy_text, ECONOMY_ZH
from rm_client.ui.polar.mixins.economy_mixin import EconomyMixin

class EconomyDisplayTests(unittest.TestCase):
    def host(self, language):
        host = NS(registry=build_default_registry(), state=NS(remaining_economy=100), economy_selected=0,
                  get_auto_ui_scale=lambda *a, **k: 1, draw_liquid_glass_panel=lambda *a, **k: None,
                  font=lambda *a: None, match_mode_manager=NS(current=NS(title='RMUC', key='RMUC7v7')),
                  current_robot_profile_key=lambda: 'Hero', hover_point=QPointF(-1,-1),
                  anim=NS(value=lambda *a: a[1]), anim_duration=lambda x:x)
        host.registry.get('ClickGui').get_setting('Language').value = language
        host.texts=[];host.hits=[]
        host.draw_glass_text=lambda p,r,t,*a: host.texts.append((r.getRect(), t))
        host.add_hotspot=lambda r,a,p=None,**k:host.hits.append((r.getRect(),a,p))
        return host
    def test_legacy_draw_preserves_actions_and_geometry(self):
        offer=NS(key='ammo',short_title='补弹',title='弹丸兑换',cost=5,unit='17 mm',enabled=True,reason='')
        en=self.host('English');zh=self.host('简体中文')
        with patch('rm_client.ui.polar.mixins.economy_mixin.available_actions',return_value=[offer]), \
             patch('rm_client.ui.polar.mixins.economy_mixin.profile_by_key',return_value=NS(title='Hero')):
            for host in (en,zh):EconomyMixin.draw_economy_overlay_legacy(host,Mock(),1280,720,1)
        self.assertEqual(en.hits,zh.hits)
        self.assertEqual([r for r,_ in en.texts],[r for r,_ in zh.texts])
        self.assertIn('SEND MOCK REQUEST',[t for _,t in en.texts])
        self.assertIn('发送模拟请求',[t for _,t in zh.texts])
        self.assertIn('战斗经济  ·  100 金币',[t for _,t in zh.texts])
        self.assertIn('RMUC · Hero · 默认模拟',[t for _,t in zh.texts])
        self.assertEqual(offer.key,'ammo');self.assertEqual(offer.cost,5)
    def test_currency_status_templates_and_user_values(self):
        self.assertEqual(economy_text('{gold} G',True,gold=123),'123 金币')
        self.assertEqual(economy_text('{gold} G',False,gold=123),'123 G')
        self.assertEqual(economy_text('HP',True),'血量')
        self.assertEqual(economy_text('AMMO',True),'弹量')
        self.assertEqual(economy_text('{cost} GOLD  ·  {unit}',True,cost=7,unit='Custom {x}'),'7 金币  ·  Custom {x}')
    def test_known_labels_in_opaque_toast_suffixes_remain_verbatim(self):
        prefixes=('Wallpaper loaded: ','Wallpaper import failed: ','Sound import failed: ',
                  'Import failed: ','Evidence exported: ','Tongji YAML exported: ',
                  'Invalid configuration value: ')
        for prefix in prefixes:
            for suffix in ('Small','READY','Off','ArmorAutoAim','C:/Custom/{Profile}.json'):
                self.assertTrue(toast_text(prefix+suffix,True).endswith(suffix),(prefix,suffix))
                self.assertEqual(toast_text(prefix+suffix,False),prefix+suffix)
        self.assertEqual(toast_text('Arm blocked: telemetry stale',True),'解锁受阻：遥测已超时')
    def test_blocked_message_does_not_split_opaque_error_details(self):
        self.assertEqual(toast_text('BLOCKED: invalid HeroDeployModeEventCommand: custom READY, OFF',True),
                         '受阻：HeroDeployModeEventCommand 数据无效：custom READY, OFF')
        self.assertEqual(toast_text('BLOCKED: custom error: Off, READY',True),'受阻：custom error: Off, READY')
        self.assertEqual(toast_text('BLOCKED: gimbal offline, telemetry stale',True),'受阻：云台离线、遥测已超时')
    def test_window_title_refreshes_after_language_switch(self):
        from tests.test_startup_display_locale import methods, APP
        window=methods([(APP, {'invalidate_gui_cache'})])()
        window.registry=build_default_registry();window.gui_cache=Mock()
        titles=['old title'];window.windowTitle=lambda: titles[-1]
        window.setWindowTitle=titles.append
        window.invalidate_gui_cache()
        self.assertEqual(titles[-1],'POLAR-RM 自定义客户端')
        count=len(titles);window.invalidate_gui_cache();self.assertEqual(len(titles),count)
        window.registry.get('ClickGui').get_setting('Language').value='English'
        window.invalidate_gui_cache();self.assertEqual(titles[-1],'POLAR-RM Custom Client')
    def test_qualification_messages_keep_ids_and_lock_state(self):
        self.assertEqual(toast_text('hero_deploy_status_test: PASS · LOCKED',True),'hero_deploy_status_test：通过 · 已锁止')
        self.assertEqual(toast_text('KMC FAIL · P95 12.3 ms · LOCKED',True),'KMC 未通过 · P95 12.3 ms · 已锁止')
        self.assertEqual(toast_text('custom_test: PASS · LOCKED',True),'custom_test: PASS · LOCKED')
        self.assertEqual(toast_text('BLOCKED: DeployModeStatusSync timeout',True),'受阻：部署状态同步超时（DeployModeStatusSync）')
    def test_command_toasts_preserve_coordinates_and_unknown_reasons(self):
        self.assertEqual(toast_text('Map click (12.3, 4.5)m sent',True),'地图标记（12.3, 4.5）m：已发送')
        for prefix in ('Rune','Dart','Sentry','Assembly','Performance selection'):
            text=prefix+' customError: ID=0x0310'
            self.assertTrue(toast_text(text,True).endswith('customError: ID=0x0310'))
            self.assertEqual(toast_text(text,False),text)
        self.assertEqual(toast_text('Event command failed: READY',True),'事件指令失败：READY')
    def test_preview_numbers_and_signs_stay_exact(self):
        original='PREVIEW Y-12.3 P+45.0 T1.20'
        self.assertEqual(toast_text(original,False),original)
        self.assertEqual(toast_text(original,True),'预览：偏航 -12.3°，俯仰 +45.0°，飞行时间 1.20 秒')
        self.assertEqual(toast_text('User PREVIEW Y-12.3 P+45.0 T1.20',True),'User PREVIEW Y-12.3 P+45.0 T1.20')
    def test_inventory_tooltips_localize_without_payload_changes(self):
        groups=[]
        for language in ('English','简体中文'):
            host=self.host(language)
            host.student_ui=NS(category='System',page=0,selected_slot=0)
            host.minecraft_hud=NS(assignments=lambda module:['Empty']*9)
            renderer=object.__new__(StudentPanelRenderer)
            renderer.inventory=QImage();renderer.items=NS(image=Mock(return_value=QImage()))
            renderer.text=Mock();renderer.button=Mock()
            hits=[]
            with patch('rm_client.ui.student_panels.presentation_data',return_value={}):
                renderer.inventory_panel(host,Mock(),QRectF(0,0,190,220),1,hits)
            groups.append(hits)
        en,zh=groups
        self.assertEqual([(h.rect,h.action,h.payload) for h in en],[(h.rect,h.action,h.payload) for h in zh])
        self.assertIn('Chassis Points',[h.tooltip for h in en])
        self.assertIn('底盘性能点（草稿）',[h.tooltip for h in zh])
        self.assertTrue(any('1: 空' in h.tooltip for h in zh))
    def test_inventory_templates_have_translations_and_no_raw_legacy_labels(self):
        for template in ECONOMY_ZH:
            self.assertNotEqual(economy_text(template,True),template)
            self.assertEqual(economy_text(template,False),template)
        path=Path(__file__).resolve().parents[1]/'rm_client/ui/polar/mixins/economy_mixin.py'
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('draw_glass_text','text'):
                index=2 if node.func.attr=='draw_glass_text' else 1
                if len(node.args)>index and isinstance(node.args[index],ast.Constant):
                    self.assertNotIn(node.args[index].value,ECONOMY_ZH)

if __name__=='__main__':unittest.main()
