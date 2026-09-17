"""Original, functional Minecraft-style mod items (not reskinned vanilla loot).

16-grid silhouettes rendered at 32px: hard pixels, dark outlines, three-tone
materials, playful crafted objects. No text initials, generic coloured cubes,
random slot/category colours, or per-frame sprite generation.
"""
from functools import lru_cache

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF


MODULE_RECIPES = {
    "ArmorAutoAim":"aim_turret", "EnergyAutoAim":"rune_turret", "ArmorLock":"armor_lock",
    "HeroLob":"lob_cannon", "FireControlStub":"fire_lever", "FrictionWheel":"friction_wheel",
    "LockState":"padlock", "SpinMode":"spin_chassis", "AutoSpinOnHit":"hit_spin",
    "ChassisAssist":"wing_boots", "PowerGuard":"power_shield", "CameraFeed":"camera",
    "CameraCalibration":"calibration", "TongjiVisionBridge":"vision_bridge",
    "Armor3DESP":"esp_armor", "RobotOverlay":"robot_visor", "RadarOverlay":"radar",
    "MapMarker":"map_flag", "TacticalMap":"tactical_map", "LiquidTacticalMap":"tactical_map",
    "EconomyPanel":"coin_pouch", "ProjectileShop":"ammo_crate", "MatchChat":"chat_sign",
    "ClickGui":"control_book", "MinecraftInventory":"mod_chest", "DartPanel":"dart_launcher",
    "SkillConfiguration":"skill_wand", "InjuryStatistics":"broken_heart",
    "MatchSettlement":"trophy", "RuneRingStatus":"rune_star", "ResourceIsland":"ore_island",
    "GainZone":"buff_beacon", "UWBStatus":"uwb_antenna", "ArmorStatus":"sensor_armor",
    "WirelessCharging":"wireless_cell", "ReloadingPanel":"reload_crate", "MinecraftBuffs":"buff_bottle",
    "HUD":"hud_monitor", "UIScale":"scale_ruler", "MatchTimer":"match_clock", "ConfigManager":"config_scroll",
    "SentinelCommand":"robot_visor", "AirSupport":"wing_boots", "BaseOutpostStatus":"base_castle",
    "VictoryPointStatus":"trophy", "EliminationFX":"kill_spark", "CombatTargetHUD":"target_card",
    "ThermalPowerPanel":"power_shield", "BuffTimeline":"buff_bottle",
    "AllianceProfile":"team_banner", "RobotProfile":"robot_visor", "MatchMode":"team_banner",
    "AudioFeedback":"audio_note", "EmergencyStop":"stop_button", "JumpPTEWheelLES":"wing_boots",
    "MatchReadiness":"readiness", "MQTTLink":"uwb_antenna", "RobotLink":"cable_link",
    "SerialBridge":"cable_link", "QuickActionWheel":"quick_wheel", "UDPVideo":"video_packet",
    "Scenario":"tactical_map", "StartupVisual":"buff_beacon", "MinecraftCombatHUD":"minecraft_hud",
    "Crosshair":"crosshair", "Capacitor":"capacitor", "PowerLimit":"power_limit",
    "SpeedLimit":"speed_limit", "GimbalPower":"gimbal_power", "ChassisGimbalIndicator":"gimbal",
}
CATEGORY_RECIPES = {"Combat":"aim_turret", "Movement":"wing_boots", "Vision":"camera",
                    "Strategy":"tactical_map", "System":"config_scroll", "Render":"hud_monitor"}


def recipe_for(name, category="System"):
    if name in MODULE_RECIPES:return MODULE_RECIPES[name]
    for token,recipe in (("Ammo","ammo_crate"),("Projectile","ammo_crate"),("Respawn","broken_heart"),
                         ("Rune","rune_star"),("Buff","buff_bottle"),("Timer","match_clock"),
                         ("Map","tactical_map"),("Profile","robot_visor"),("Chat","chat_sign"),
                         ("Audio","chat_sign"),("Link","uwb_antenna"),("Readiness","power_shield")):
        if token in name:return recipe
    return CATEGORY_RECIPES.get(category,"config_scroll")


@lru_cache(maxsize=64)
def crafted_item(recipe):
    image=QImage(32,32,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent)
    p=QPainter(image);p.scale(2,2);p.setRenderHint(QPainter.Antialiasing,False)
    dark="#25232c";steel="#c6d8df";shade="#647785";shine="#f3ffff";cyan="#5ddcec"
    gold="#edb841";wood="#9c6135";green="#69d75f";red="#f16758"
    def rect(x,y,w,h,c):p.fillRect(x,y,w,h,QColor(c))
    def poly(points,c,edge=True):
        p.setPen(QPen(QColor(dark),1) if edge else Qt.NoPen);p.setBrush(QColor(c))
        p.drawPolygon(QPolygonF([QPointF(x,y) for x,y in points]))
    def line(points,c,width=1):
        p.setPen(QPen(QColor(c),width,Qt.SolidLine,Qt.SquareCap,Qt.MiterJoin))
        p.drawPolyline(QPolygonF([QPointF(x,y) for x,y in points]))
    def star(x,y,c=gold):
        rect(x,y-2,1,5,c);rect(x-2,y,5,1,c);rect(x,y,1,1,shine)
    def plate():
        poly([(3,4),(6,3),(7,5),(9,5),(10,3),(13,4),(12,7),(11,7),(11,13),(5,13),(5,7),(4,7)],steel)
        rect(6,7,2,5,shine);rect(9,7,2,5,shade);rect(5,12,6,1,shade)
    def chassis():
        for x in (2,11):
            for y in (9,12):rect(x,y,3,3,dark);rect(x,y,1,2,shade)
        poly([(3,8),(9,6),(13,9),(7,12),(3,11)],shade)
        poly([(3,8),(9,6),(13,9),(7,10)],steel);rect(7,8,3,2,green)
    def spin():
        chassis();line([(2,7),(2,4),(5,2),(11,2),(14,5)],cyan)
        poly([(12,4),(14,7),(15,3)],cyan);rect(5,2,3,1,shine)
    def chest(reload=False):
        poly([(2,6),(9,4),(14,7),(14,13),(7,15),(2,12)],wood)
        poly([(2,6),(9,4),(14,7),(7,9)],"#c99152")
        line([(7,9),(7,14)],"#603f2e");rect(9,10,3,2,gold)
        for x in (4,7,10):rect(x,3,2,4,dark);rect(x,3,1,4,gold);rect(x,2,1,2,"#fff1a1")
        if reload:line([(3,12),(3,9),(5,8)],green);poly([(4,7),(6,8),(4,10)],green)
    def turret(rune=False):
        poly([(3,10),(8,8),(12,10),(12,13),(6,15),(3,13)],shade)
        poly([(3,10),(8,8),(12,10),(6,12)],steel)
        poly([(5,8),(5,6),(10,4),(12,6),(8,8)],cyan)
        poly([(9,5),(13,3),(14,4),(11,7)],steel);rect(13,3,2,2,dark);rect(13,3,1,1,shine)
        if rune:star(3,3)
        else:
            line([(2,2),(4,2),(4,3)],red);line([(2,2),(2,4)],red)
            rect(3,3,1,1,shine);line([(5,5),(5,4)],red)
    if recipe in {"aim_turret","rune_turret"}:turret(recipe=="rune_turret")
    elif recipe in {"spin_chassis","hit_spin"}:
        spin()
        if recipe=="hit_spin":star(3,8,red);line([(0,8),(2,8)],gold)
    elif recipe=="lob_cannon":
        poly([(2,12),(4,8),(7,7),(9,9),(7,12)],shade)
        poly([(3,8),(7,3),(10,5),(7,10)],steel);rect(6,4,3,2,dark)
        rect(1,12,8,2,wood);line([(9,2),(11,2),(13,4)],shine);poly([(12,5),(14,4),(15,6),(13,7)],gold)
    elif recipe in {"armor_lock","sensor_armor","esp_armor"}:
        plate()
        if recipe=="armor_lock":
            line([(7,9),(7,7),(9,7),(9,9)],gold);rect(6,9,5,4,dark);rect(7,9,3,3,gold);rect(8,10,1,1,shade)
        elif recipe=="sensor_armor":rect(7,7,3,4,dark);rect(8,8,1,2,green);star(13,2,cyan)
        else:
            for points in ([(1,6),(1,2),(5,2)],[(11,2),(14,2),(14,6)],[(1,10),(1,14),(5,14)],[(11,14),(14,14),(14,10)]):line(points,cyan)
    elif recipe in {"camera","calibration","vision_bridge","video_packet"}:
        poly([(2,5),(5,4),(5,2),(9,2),(10,4),(14,5),(14,12),(2,12)],shade)
        rect(3,5,10,2,steel);rect(5,6,7,6,dark);rect(6,7,5,4,cyan);rect(7,7,2,2,shine);rect(3,8,1,1,red)
        if recipe=="calibration":line([(2,14),(13,14)],gold);rect(3,13,1,2,shine);rect(7,13,1,2,shine)
        elif recipe=="vision_bridge":line([(1,14),(5,14),(6,13),(10,13),(11,14),(14,14)],green)
        elif recipe=="video_packet":
            for x in (3,7,11):rect(x,14,2,1,cyan)
    elif recipe=="friction_wheel":
        poly([(5,2),(10,2),(10,4),(13,4),(13,10),(11,10),(11,13),(4,13),(4,11),(2,11),(2,5),(5,5)],shade)
        poly([(5,4),(9,4),(11,6),(11,10),(9,12),(5,12),(3,10),(3,6)],gold)
        rect(6,6,3,4,dark);rect(7,7,1,2,shine);star(13,2,red)
    elif recipe in {"power_shield","wireless_cell","power_limit"}:
        poly([(3,4),(8,2),(13,4),(12,10),(8,14),(4,10)],shade if recipe=="power_shield" else cyan)
        line([(4,5),(8,3),(11,5)],shine)
        poly([(9,4),(6,8),(8,8),(7,12),(11,7),(8,7)],gold,False)
        if recipe=="wireless_cell":line([(2,2),(2,1),(13,1),(13,2)],green)
        elif recipe=="power_limit":line([(3,12),(12,3)],red,2)
    elif recipe in {"wing_boots","speed_limit"}:
        poly([(6,3),(11,3),(10,9),(13,10),(13,13),(5,13),(5,10)],"#ad8c67")
        rect(7,4,3,5,steel);rect(6,11,6,1,gold)
        poly([(6,8),(2,5),(1,5),(2,9),(5,11)],shine);line([(2,7),(5,9)],cyan)
        if recipe=="speed_limit":rect(10,1,5,5,dark);rect(11,2,3,3,shine);line([(12,2),(12,3),(13,3)],red)
    elif recipe in {"ammo_crate","reload_crate","mod_chest"}:
        chest(recipe=="reload_crate")
        if recipe=="mod_chest":rect(8,4,3,3,cyan);rect(9,4,1,1,shine)
    elif recipe=="coin_pouch":
        poly([(6,3),(10,3),(9,5),(12,8),(13,12),(10,14),(4,14),(2,11),(3,7),(7,5)],"#bc8554")
        rect(6,4,4,1,shade);poly([(7,8),(10,8),(12,10),(10,12),(7,12),(5,10)],gold);rect(7,9,1,2,"#fff1a1")
    elif recipe in {"tactical_map","map_flag","config_scroll"}:
        poly([(2,3),(6,4),(10,2),(14,3),(13,13),(9,12),(5,14),(1,12)],"#ead4a2")
        line([(6,4),(5,13)],"#b39469");line([(10,3),(9,12)],"#b39469")
        line([(3,9),(6,7),(10,8),(12,5)],cyan)
        if recipe=="config_scroll":line([(9,11),(13,6)],gold,2);rect(12,5,2,2,shade)
        else:line([(10,11),(10,5)],wood);poly([(10,4),(14,5),(10,7)],red)
    elif recipe=="chat_sign":
        poly([(2,3),(13,3),(14,5),(14,10),(8,10),(5,13),(5,10),(2,10)],wood)
        rect(3,4,10,5,"#e5bc80")
        for x in (4,7,10):rect(x,6,1,1,dark)
    elif recipe=="control_book":
        poly([(1,4),(7,3),(8,4),(14,3),(14,12),(8,13),(7,12),(1,13)],wood)
        poly([(2,4),(6,4),(7,5),(7,11),(2,12)],"#fff1c9")
        poly([(8,5),(13,4),(13,11),(8,12)],"#dfd8b7")
        for y in (6,8,10):rect(3,y,3,1,shade);rect(9,y,3,1,cyan)
        rect(7,5,1,7,"#ac8b66")
    elif recipe in {"dart_launcher","skill_wand","kill_spark"}:
        line([(3,13),(11,4)],wood,3);line([(3,12),(11,3)],gold,1)
        if recipe=="dart_launcher":
            poly([(10,2),(14,1),(13,5),(11,7)],steel);poly([(5,9),(2,9),(3,13),(7,12)],red)
            rect(10,3,2,2,shine)
        else:star(11,3,cyan if recipe=="skill_wand" else red);star(3,4,gold)
    elif recipe in {"broken_heart","target_card"}:
        poly([(2,4),(5,2),(8,4),(11,2),(14,4),(14,7),(8,14),(2,7)],red)
        rect(3,4,3,1,"#ffa595");line([(8,4),(6,7),(9,9),(7,12)],dark)
        if recipe=="target_card":line([(1,2),(1,1),(5,1)],cyan);line([(10,14),(14,14),(14,10)],cyan)
    elif recipe=="trophy":
        poly([(4,2),(12,2),(11,8),(8,10),(5,8)],gold);rect(5,3,2,4,"#fff1a1")
        line([(4,3),(2,3),(2,6),(5,8)],wood);line([(12,3),(14,3),(14,6),(11,8)],wood)
        rect(7,9,2,3,gold);rect(4,12,8,2,wood);rect(5,12,6,1,gold)
    elif recipe in {"rune_star","buff_beacon","ore_island"}:
        poly([(2,10),(8,8),(14,10),(9,15),(5,14)],wood)
        poly([(2,10),(8,8),(14,10),(9,12),(5,12)],green)
        if recipe=="ore_island":poly([(5,8),(6,3),(9,1),(11,5),(10,9)],cyan);line([(7,3),(7,8)],shine)
        elif recipe=="buff_beacon":rect(6,5,4,5,cyan);rect(7,3,2,6,shine);star(8,2,gold)
        else:
            for points in ([(8,7),(8,2)],[(8,7),(13,5)],[(8,7),(11,11)],[(8,7),(4,11)],[(8,7),(3,5)]):line(points,gold,2)
            rect(7,6,3,3,cyan);rect(8,6,1,1,shine)
    elif recipe in {"radar","uwb_antenna"}:
        if recipe=="radar":
            poly([(4,3),(11,3),(14,6),(14,11),(10,14),(4,13),(2,10),(2,6)],shade)
            poly([(5,5),(11,5),(12,7),(12,11),(9,12),(5,11),(4,9),(4,7)],"#293f3d")
            line([(8,9),(11,6)],green);rect(5,7,1,1,green);rect(10,10,1,1,red);rect(8,9,1,1,shine)
        else:
            rect(7,6,2,7,steel);rect(4,13,8,2,shade);rect(7,4,2,2,cyan)
            line([(4,7),(3,5),(4,3)],green);line([(11,3),(12,5),(11,7)],green)
            line([(1,2),(0,5),(1,9)],cyan);line([(14,2),(15,5),(14,9)],cyan)
    elif recipe=="robot_visor":
        poly([(4,3),(11,3),(14,6),(13,12),(3,12),(2,6)],steel)
        rect(4,6,8,4,dark);rect(5,7,2,2,green);rect(9,7,2,2,green);rect(7,2,2,2,gold)
    elif recipe=="buff_bottle":
        rect(6,1,4,2,wood);poly([(6,3),(10,3),(10,6),(13,9),(12,13),(4,13),(3,9),(6,6)],cyan)
        rect(5,9,6,3,"#a685de");rect(4,8,1,3,shine);star(12,4,gold)
    elif recipe=="match_clock":
        poly([(5,2),(11,2),(14,5),(14,11),(11,14),(5,14),(2,11),(2,5)],gold)
        poly([(5,4),(11,4),(12,6),(12,10),(10,12),(6,12),(4,10),(4,6)],"#fff1cf")
        line([(8,5),(8,8),(11,9)],shade);rect(7,7,2,2,red)
    elif recipe=="hud_monitor":
        poly([(1,3),(14,3),(14,12),(1,12)],shade);rect(2,4,11,7,"#243b43")
        rect(3,5,4,3,cyan);rect(9,5,3,1,green);rect(9,7,3,1,gold);rect(6,12,3,2,steel)
    elif recipe=="scale_ruler":
        poly([(2,11),(11,2),(14,5),(5,14)],gold)
        for x,y in ((4,10),(6,8),(8,6),(10,4)):line([(x,y),(x+1,y+1)],wood)
        line([(2,2),(2,6)],cyan);line([(2,2),(6,2)],cyan)
    elif recipe=="padlock":
        line([(5,7),(5,3),(10,3),(11,4),(11,7)],steel,2)
        poly([(3,7),(12,7),(12,13),(3,13)],gold);rect(7,9,2,3,dark);rect(4,8,2,1,"#fff1a1")
    elif recipe=="fire_lever":
        poly([(3,12),(8,10),(12,12),(8,14)],shade);line([(7,12),(10,5)],wood,2)
        rect(9,4,3,2,red);star(3,4,gold)
    elif recipe=="stop_button":
        poly([(2,10),(10,8),(14,10),(14,13),(6,15),(2,13)],shade)
        poly([(4,3),(10,2),(13,4),(13,8),(7,10),(3,7)],red)
        rect(5,3,4,1,"#ffa595");rect(6,9,3,3,steel)
    elif recipe=="crosshair":
        poly([(5,4),(10,4),(12,6),(12,10),(10,12),(5,12),(3,10),(3,6)],cyan)
        poly([(6,5),(9,5),(11,7),(11,9),(9,11),(6,11),(4,9),(4,7)],"#2d515b")
        for points in ([(8,1),(8,5)],[(1,8),(5,8)],[(11,8),(14,8)],[(8,11),(8,14)]):line(points,shine)
        rect(7,7,2,2,red)
    elif recipe=="audio_note":
        poly([(1,5),(4,5),(7,2),(7,13),(4,10),(1,10)],wood);rect(2,6,2,3,gold)
        line([(10,5),(10,11),(13,10),(13,3),(10,4)],cyan,2);rect(8,11,3,2,cyan)
    elif recipe=="quick_wheel":
        poly([(5,2),(10,2),(14,6),(14,10),(10,14),(5,14),(1,10),(1,6)],shade)
        line([(8,3),(8,13)],steel);line([(2,8),(13,8)],steel)
        poly([(9,3),(11,4),(13,6),(13,7),(9,7)],gold,False);rect(6,6,4,4,cyan)
    elif recipe=="team_banner":
        line([(3,2),(3,14)],wood,2);poly([(4,2),(8,3),(8,8),(4,7)],red)
        line([(10,4),(10,14)],shade,2);poly([(11,4),(14,3),(14,9),(11,10)],cyan)
        rect(2,14,11,1,steel)
    elif recipe=="cable_link":
        line([(4,6),(4,12),(11,12),(11,8)],wood,2);line([(4,6),(4,11),(11,11),(11,8)],cyan)
        poly([(2,2),(6,2),(7,5),(6,7),(2,7),(1,5)],steel);rect(2,3,4,2,dark)
        poly([(9,3),(13,3),(14,6),(13,8),(9,8),(8,6)],shade);rect(9,4,4,2,gold)
    elif recipe=="capacitor":
        rect(5,2,7,2,steel);poly([(4,4),(12,4),(12,12),(10,14),(6,14),(4,12)],cyan)
        rect(5,8,6,4,green);rect(5,5,1,6,shine);poly([(9,5),(7,9),(9,9),(8,12),(11,8),(9,8)],gold,False)
    elif recipe in {"gimbal","gimbal_power"}:
        chassis();line([(5,9),(5,4),(11,4),(11,9)],steel,2)
        rect(6,3,4,5,dark);rect(7,4,2,2,cyan);line([(2,6),(2,3),(4,2)],gold)
        if recipe=="gimbal_power":star(13,2,gold)
    elif recipe=="minecraft_hud":
        poly([(2,6),(9,4),(14,7),(14,13),(7,15),(2,12)],wood)
        poly([(2,6),(9,4),(14,7),(7,9)],green);rect(8,10,5,2,red);rect(8,13,5,1,cyan)
        rect(4,8,2,2,"#a67d50")
    elif recipe=="readiness":
        poly([(3,3),(12,3),(12,14),(3,14)],wood);rect(4,4,7,9,"#efddbb");rect(6,2,4,2,steel)
        line([(5,8),(7,10),(10,6)],green,2)
    else: # Base/outpost: tiny voxel castle, not an arbitrary category cube.
        rect(3,6,10,8,shade)
        for x in (3,7,11):rect(x,3,2,4,steel)
        rect(4,7,2,5,shine);rect(7,10,3,4,dark);rect(8,2,1,2,red)
    p.end();return image
