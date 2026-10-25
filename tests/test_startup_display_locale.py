"""Exercise actual renderer methods without creating a GL context."""
import ast
from pathlib import Path
import sys
import time
import math
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QFont
from rm_client.ui.quick_action_wheel import ACTION_LABELS, SECTOR_INDEXES, QuickActionWheelState
from rm_client.ui.jello_locale import chinese_enabled, ui_text, toast_text, description_label
from rm_client.model import build_default_registry, PRIMARY_GUI_MODE, LEGACY_GUI_MODES
from rm_client.scenarios import SCENARIOS
from rm_client.match_modes import MATCH_MODES, MATCH_MODE_KEYS
from rm_client.robot_profiles import profiles_for_match, profile_by_key, robot_id_for_alliance

APP = ROOT / 'rm_client/ui/polar_app.py'
BUILDERS = ROOT / 'rm_client/ui/polar/mixins/clickgui_builders_mixin.py'
STARTUP = ROOT / 'rm_client/ui/polar/renderers/startup_scene.py'

class Commands:
    def __init__(self): self.texts = []; self.rects = []
    def text(self, rect, text, *args, **kwargs): self.texts.append((rect.getRect(), text))
    def rect(self, rect, *args, **kwargs): self.rects.append(rect.getRect())


def methods(selections):
    selected = []
    for path, names in selections:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and (path != APP or n.name == 'PolarRMWindow'))
        selected += [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    cls = ast.ClassDef(name='Window', bases=[], keywords=[], body=selected, decorator_list=[])
    mod = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
    scope = dict(QRectF=QRectF, QPointF=QPointF, Qt=Qt, QFont=QFont, ClickGuiDrawList=Commands,
                 ACTION_LABELS=ACTION_LABELS, SECTOR_INDEXES=SECTOR_INDEXES, QuickActionWheelCommand=lambda *args: args,
                 PRIMARY_GUI_MODE=PRIMARY_GUI_MODE, LEGACY_GUI_MODES=LEGACY_GUI_MODES,
                 chinese_enabled=chinese_enabled, ui_text=ui_text, toast_text=toast_text, description_label=description_label,
                 SCENARIOS=SCENARIOS, MATCH_MODES=MATCH_MODES, MATCH_MODE_KEYS=MATCH_MODE_KEYS,
                 time=time, math=math, profiles_for_match=profiles_for_match, profile_by_key=profile_by_key, robot_id_for_alliance=robot_id_for_alliance, color=lambda *args: args,
                 THEME=NS(cyan='cyan', text='text', muted='muted', pink='pink'),
                 Easings=NS(ease_out_pow4=None, ease_out_expo=lambda value: value, ease_out_cubic=None, ease_out_quad=None),
                 LensMaterial=NS(STRONG=None, REGULAR=None), accent_color=lambda *args: 'accent',
                 with_alpha=lambda *args: args, glow_text=lambda *args: None, rounded_rect=lambda *args: None)
    exec(compile(ast.fix_missing_locations(mod), 'display_methods', 'exec'), scope)
    return scope['Window']


class DisplayLocaleTests(unittest.TestCase):
    def window(self, language):
        w = methods([(APP, {'build_gpu_startup_launcher', 'build_gpu_robot_profile_launcher', 'draw_quick_action_wheel', 'toast'}),
                     (BUILDERS, {'build_gpu_startup_button', 'build_gpu_startup_session', 'build_gpu_startup_bottom_bar', 'build_gpu_toasts', 'build_gpu_setting_row', 'draw_setting_row', 'build_gpu_module_row', 'draw_search_bar', 'build_gpu_clickgui'}),
                     (STARTUP, {'startup_scenario_meta', 'startup_match_meta', 'draw_liquid_menu_header'})])()
        w.registry = build_default_registry()
        w.registry.get('ClickGui').get_setting('Language').value = language
        w.startup_step = 'scenario'
        w.scenario_manager = NS(current=SCENARIOS['OfficialEvent'])
        from rm_client.match_modes import MatchModeManager
        w.match_mode_manager = MatchModeManager(MATCH_MODE_KEYS[0])
        w.get_auto_ui_scale = lambda *args, **kwargs: 1
        w.liquid_menu_layout = lambda *args: (50, 130, 600, 130, 12)
        w.font = lambda *args: None
        w.gpu_alpha = lambda *args: None
        w.build_gpu_glass_rect = lambda *args, **kwargs: None
        w.current_profile = lambda: 'Back'  # user-defined name must never be translated
        w.startup_menu_accent = lambda *args: None
        w.hover_point = QPointF(-1, -1)
        w.mix_color = lambda *args: None
        w.width = lambda: 1280
        w.mqtt = NS(connected=False); w.serial = NS(connected=True)
        w.hotspots = []
        w.add_hotspot = lambda rect, action, payload=None, **kwargs: w.hotspots.append((rect.getRect(), action, payload))
        w.current_robot_profile_key = lambda: profiles_for_match(w.match_mode_manager.current.key)[0].key
        w.current_robot_performance = lambda key: NS(max_health=100, power_limit_w=80, heat_limit=200, cooling_rate=20, projectile='17mm')
        w.alliance_side = lambda: 'Red'
        w.anim = NS(value=lambda *args, **kwargs: args[1])
        w.gui_motion = w.anim
        w.gui_primary_text = w.gui_secondary_text = lambda *args: None
        w.anim_duration = lambda value: value
        w.startup_stagger_value = lambda *args: 1
        w.toasts = []; w.events = []
        w.state = NS(push_event=w.events.append)
        return w

    def test_gpu_scene_and_match_preserve_actions_and_geometry(self):
        for page in ('scenario', 'match'):
            en = self.window('English'); zh = self.window('简体中文')
            english = en.build_gpu_startup_launcher(1280, 720, page=page, settled=True)
            chinese = zh.build_gpu_startup_launcher(1280, 720, page=page, settled=True)
            self.assertEqual(en.hotspots, zh.hotspots)
            self.assertEqual(english.rects, chinese.rects)
            self.assertEqual([r for r, _ in english.texts], [r for r, _ in chinese.texts])
            en_labels = [s for _, s in english.texts]; zh_labels = [s for _, s in chinese.texts]
            self.assertIn('CUSTOM CLIENT', en_labels)
            self.assertIn(ui_text('CUSTOM CLIENT', True), zh_labels)
            self.assertNotIn('CUSTOM CLIENT', zh_labels)
            self.assertIn('Back', zh_labels)  # CONFIG row is opaque user data
            self.assertIn(ui_text('PROFILE  {profile}', True, profile='Back'), zh_labels)
            self.assertEqual(en.registry.get('ClickGui').get_setting('Language').value, 'English')

    def test_robot_labels_localize_without_changing_selection_payloads(self):
        en = self.window('English'); zh = self.window('简体中文')
        english = en.build_gpu_robot_profile_launcher(1280, 720)
        chinese = zh.build_gpu_robot_profile_launcher(1280, 720)
        self.assertEqual(en.hotspots, zh.hotspots)
        self.assertEqual(english.rects, chinese.rects)
        self.assertEqual([r for r, _ in english.texts], [r for r, _ in chinese.texts])
        for key in ('ROBOT PROFILE', 'MAX HP', 'POWER', 'HEAT', 'COOLING', 'PROJECTILE', '<  BACK'):
            self.assertIn(key, [s for _, s in english.texts])
            self.assertIn(ui_text(key, True), [s for _, s in chinese.texts])
            self.assertNotEqual(ui_text(key, True), key)
        self.assertIn(ui_text('17mm', True), [s for _, s in chinese.texts])
        self.assertEqual(zh.current_robot_performance('').projectile, '17mm')

    def test_legacy_setting_backends_preserve_raw_mode_and_action(self):
        for language in ('English', '简体中文'):
            w = self.window(language)
            setting = NS(name='Language', kind='mode', value='English')
            gpu = Commands(); w.build_gpu_setting_row(gpu, setting, QRectF(0, 0, 400, 31), 1, 1, None)
            painter = NS()
            cpu = Commands(); w.draw_text = lambda p, rect, text, *args: cpu.text(rect, text)
            w.draw_setting_row(painter, setting, QRectF(0, 0, 400, 31), 1)
            expected = [ui_text('Language', language == '简体中文'), ui_text('English', language == '简体中文')]
            self.assertEqual([text for _, text in gpu.texts], expected)
            self.assertEqual([text for _, text in cpu.texts], expected)
            self.assertEqual(setting.value, 'English')
            self.assertTrue(all(action == 'setting_mode_next' and payload is setting for _, action, payload in w.hotspots))

    def test_legacy_module_translation_precedes_elision(self):
        w = self.window('简体中文')
        module = w.registry.get('ArmorAutoAim')
        seen = []
        w.elide_for_gpu = lambda font, text, width: seen.append(text) or text
        commands = Commands()
        w.build_gpu_module_row(commands, QRectF(0, 0, 300, 30), module, 1, 1, None)
        self.assertEqual(seen, [ui_text('ArmorAutoAim', True)])
        self.assertEqual(module.name, 'ArmorAutoAim')
        self.assertTrue(all(payload == 'ArmorAutoAim' for _, _, payload in w.hotspots))

    def test_legacy_search_does_not_translate_user_input(self):
        w = self.window('简体中文'); w.search_focus = False
        labels = []
        w.draw_text = lambda p, rect, text, *args: labels.append(text)
        for query in ('Back', 'ArmorAutoAim', ''):
            w.search_query = query
            w.draw_search_bar(NS(), QRectF(0, 0, 208, 23), 1)
            self.assertEqual(labels[-1], query or ui_text('Search modules...', True))

    def test_quick_wheel_localizes_stock_but_preserves_custom_labels(self):
        for count in (4, 6, 8):
            w = self.window('简体中文')
            state = QuickActionWheelState(active=True, progress=1, icon_style='Off', label_style='Compact', sector_count=count)
            state.custom_labels[0] = 'Economy'
            w.quick_action_wheel = state
            w._collect_gpu_quick_action_wheel = True
            w.quick_action_wheel_gpu = NS(available=True)
            w.draw_quick_action_wheel(None, 1280, 720)
            texts = [text for _, text in w._gpu_quick_action_wheel_labels.texts]
            self.assertEqual(texts[0], 'Economy')
            for sector in state.sectors()[1:]:
                self.assertIn(ui_text(ACTION_LABELS[sector.action], True), texts)
            self.assertIn(ui_text('CANCEL', True), texts)
            self.assertEqual(state.custom_labels[0], 'Economy')
            self.assertEqual(state.actions[0], 'economy')

    def test_closed_legacy_fade_does_not_publish_new_hotspots(self):
        w = self.window('简体中文')
        original = ('existing', 'map', None)
        w.hotspots = [original]
        w.gui_visible = False
        w.active_clickgui_mode = lambda: 'PolarPanel'
        def draw(*args):
            w.hotspots.append(('new', 'module_toggle', 'ArmorAutoAim'))
            w.gui_scroll_viewports.append('new')
        w.build_gpu_panel_gui = draw
        w.build_gpu_legacy_return = lambda *args: None
        w.build_gpu_toasts = lambda *args: None
        w.hover_tooltip = ''
        w.binding_module = None
        w.build_gpu_clickgui(1280, 720, .5)
        self.assertEqual(w.hotspots, [original])
        self.assertEqual(w.gui_scroll_viewports, [])

    def test_compatibility_header_shows_same_localized_labels(self):
        output = {}
        for language in ('English', '简体中文'):
            w = self.window(language)
            w.startup_stagger_value = lambda *args: 1
            w.draw_liquid_glass_panel = lambda *args, **kwargs: None
            labels = []
            w.draw_text = w.draw_glass_text = lambda p, rect, text, *args: labels.append((rect.getRect(), text))
            painter = NS(save=lambda: None, restore=lambda: None, setOpacity=lambda *args: None)
            w.draw_liquid_menu_header(painter, 1280, 720, 1, 'SCENE SELECT', 'Choose runtime environment', 1)
            output[language] = labels
        self.assertEqual([r for r, _ in output['English']], [r for r, _ in output['简体中文']])
        self.assertEqual([s for _, s in output['简体中文']],
                         [ui_text('CUSTOM CLIENT', True), ui_text('SCENE SELECT', True),
                          ui_text('Choose runtime environment', True), ui_text('PROFILE  {profile}', True, profile='Back')])
        self.assertIn('CUSTOM CLIENT', [s for _, s in output['English']])

    def test_toast_is_localized_only_at_display_and_switches_live(self):
        w = self.window('简体中文')
        w.toast('ClickGUI opened', kind='success')
        raw = w.toasts[0].copy()
        commands = Commands(); w.build_gpu_toasts(commands, 1280, 720)
        self.assertEqual(commands.texts[0][1], toast_text('ClickGUI opened', True))
        self.assertNotEqual(commands.texts[0][1], 'ClickGUI opened')
        self.assertEqual(w.toasts[0], raw)
        self.assertEqual(w.events, ['ClickGUI opened'])
        w.registry.get('ClickGui').get_setting('Language').value = 'English'
        commands = Commands(); w.build_gpu_toasts(commands, 1280, 720)
        self.assertEqual(commands.texts[0][1], 'ClickGUI opened')
        self.assertEqual(w.toasts[0]['kind'], 'success')

    def test_both_toast_backends_translate_after_classification(self):
        tree = ast.parse(BUILDERS.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        for name in ('draw_toasts', 'build_gpu_toasts'):
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'toast_text' for n in ast.walk(method)))
        cpu = ast.get_source_segment(BUILDERS.read_text(encoding='utf-8-sig'), next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'draw_toasts'))
        self.assertLess(cpu.index('dynamic_message_kind(msg)'), cpu.index('toast_text(str(msg)'))

if __name__ == '__main__': unittest.main()
