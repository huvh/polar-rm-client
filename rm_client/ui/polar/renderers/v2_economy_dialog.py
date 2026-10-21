"""Explicit V2 economic requests, separate from legacy fixed-price offers.

No telemetry delta is called an ACK; the immutable quote is bound by the final
MQTT guard. This module has no dependency back to tactical_map.
"""
import math
import time
from typing import Any
from PySide6.QtWidgets import QInputDialog, QMessageBox
from ....backend.referee.rm2026_v2.economy_rules import request_decision
from .v2_request_context import _v2_air_context, _same_v2_air_context, _v2_air_snapshot_current

_COMMON = (
    (1, '1 · Local 17mm / 本地17毫米补弹'),
    (2, '2 · Local 42mm / 本地42毫米补弹'),
    (3, '3 · Free respawn / 免费复活'),
    (4, '4 · Paid respawn, current quote / 金币复活，当前报价'),
    (5, '5 · Remote ammunition, one 150-coin pack / 远程补弹，一包150金币'),
    (6, '6 · Remote heal, current estimate / 远程回血，当前估价'),
)
_SENTRY = (
    (1, '1 · Local 50 rounds / 本地50发补弹'),
    (3, '3 · Remote 100 rounds / 远程100发补弹'),
    (4, '4 · Remote healing / 远程回血'),
    (5, '5 · Free respawn request / 免费复活请求'),
    (6, '6 · Paid respawn unavailable: target quote missing / 金币复活不可用：缺目标报价'),
    (7, '7 · Attack stance / 进攻姿态'), (8, '8 · Defense stance / 防御姿态'),
    (9, '9 · Movement stance / 移动姿态'),
    (10, '10 · Enhanced attack / 强化进攻'), (11, '11 · Enhanced defense / 强化防御'),
    (12, '12 · Enhanced movement / 强化移动'),
)


def _economic_premise(topic, command_id, param, snapshot, cost, payload):
    keys = [('GameStatus','current_round'), ('GameStatus','current_stage'),
        ('RobotStaticStatus','robot_id'), ('RobotStaticStatus','robot_type'),
        ('RobotStaticStatus','connection_state'), ('RobotStaticStatus','field_state'),
        ('PenaltyInfo','penalty_type'), ('GlobalLogisticsStatus','remaining_economy')]
    if topic == 'CommonCommand':
        keys += [('RobotStaticStatus','alive_state')]
        if command_id in {3,4}:
            keys += [('RobotRespawnStatus','is_pending_respawn'),
                     ('RobotRespawnStatus','can_free_respawn' if command_id == 3 else 'can_pay_for_respawn')]
            if command_id == 4:
                keys.append(('RobotRespawnStatus','gold_cost_for_respawn'))
        elif command_id in {5,6}:
            keys += [('RobotDynamicStatus','is_out_of_combat'),
                     ('RobotDynamicStatus','can_remote_ammo' if command_id == 5 else 'can_remote_heal')]
            if command_id == 6:
                keys += [('RobotDynamicStatus','current_health'),('RobotStaticStatus','max_health')]
    else:
        keys += [('RobotPerformanceSelectionSync','sentry_control')]
        if topic == 'SentryCtrlCommand' and command_id in range(7,13):
            keys += [('SentryStatusSync','posture_id'), ('SentryStatusSync','is_weakened'),('SentryStatusSync','is_powered')]
    # Countdown receipt changes alone need no extra confirmation. The derived
    # price above does: heal formula changes are captured by the cost value.
    return (topic, command_id, param, bytes(payload), cost, tuple((m,f,
        snapshot.get(m,f).value if snapshot.get(m,f) is not None else None) for m,f in keys))


def _pick(host, title, prompt, choices):
    labels = tuple(label for _,label in choices)
    selected, accepted = QInputDialog.getItem(host, title, prompt, labels, 0, False)
    return choices[labels.index(selected)][0] if accepted and selected in labels else None


def _open_v2_economy_dialog(host: Any, topic: str = 'CommonCommand') -> None:
    attempted = accepted_enqueue = False
    try:
        admission = _v2_air_context(host)
        if not _v2_air_snapshot_current(admission):
            host.toast('V2 economy requires connected OfficialEvent RMUC7v7 and a matching session')
            return
        title = 'V2 economic confirmation / V2经济确认'
        param = 0
        codec = admission[0][2].codec
        if topic in {'CommonCommand','SentryCtrlCommand'}:
            choices = _COMMON if topic == 'CommonCommand' else _SENTRY
            prompt = ('Own Hero/Infantry supply; Engineer revival only. / 己方英雄步兵补给；工程仅复活。' if topic == 'CommonCommand'
                else 'Aerial operator, same-team Sentry; includes observed intervention fee. / 空中云台手干预己方哨兵，含当前干预费。')
            command = _pick(host, title, prompt, choices)
            if command is None:
                return
            if topic == 'CommonCommand' and command in {1,2}:
                initial, maximum, step = (10,1000,10) if command == 1 else (1,100,1)
                param, accepted = QInputDialog.getInt(host,title,
                    'Round count: 17mm multiples of 10; 42mm single rounds. / 17毫米每10发，42毫米每1发。',initial,initial,maximum,step)
                if not accepted or type(param) is not int or not initial <= param <= maximum or param % step:
                    return
            payload = (codec.encode_common_command(command,param) if topic == 'CommonCommand'
                       else codec.encode_sentry_ctrl_command(command))
            description = next(label for value,label in choices if value == command)
        elif topic == 'MapClickCmd':
            command = 0
            identity = admission[1][-1][1]
            if type(identity) is not int or identity not in {*range(1,10),*range(101,110)}:
                host.toast('Current team identity is required for Sentry map intervention')
                return
            target = 107 if identity > 100 else 7
            field = host.match_mode_manager.current.field
            mark = _pick(host,title,'Same-team Sentry only / 仅己方哨兵',
                ((1,'Attack / 攻击'),(2,'Defense / 防御'),(3,'Warning / 警戒')))
            if mark is None:
                return
            x, accepted = QInputDialog.getDouble(host,title,'X metres / X米',0.,0.,field.width_m,3)
            if not accepted:
                return
            y, accepted = QInputDialog.getDouble(host,title,'Y metres / Y米',0.,0.,field.height_m,3)
            if (not accepted or type(x) not in (int,float) or type(y) not in (int,float)
                    or not math.isfinite(x) or not math.isfinite(y)
                    or not 0 <= x <= field.width_m or not 0 <= y <= field.height_m):
                return
            targets = bytes([target]) + bytes(6)
            payload = codec.encode_map_click_cmd(is_send_all=0,robot_id=targets,
                mode=1,mark_type=mark,map_x=x,map_y=y)
            description = f'Sentry#{target} · mark {mark} · ({x:g}, {y:g})m / 哨兵干预'
        else:
            host.toast('Unsupported V2 economic dialog')
            return
        for confirmation in range(2):
            current = _v2_air_context(host)
            if not _same_v2_air_context(admission,current) or not _v2_air_snapshot_current(current):
                host.toast('Economic dialog context changed; reopen it')
                return
            allowed, reason, cost = request_decision(topic,command,current[2],now=time.perf_counter(),param=param)
            if not allowed:
                host.toast(reason)
                return
            premise = _economic_premise(topic,command,param,current[2],cost,payload)
            message = ('Conditions or price changed; review again. / 条件或报价已变，请重新确认。\n' if confirmation else '')
            message += f'{description}\nEstimated total / 当前估价: {cost} coins / 金币\n{reason}\n'
            message += ('MOCK: no live enqueue / 模拟：不发送正式请求\n' if current[1][4] else 'Live request / 正式请求\n')
            message += ('One request only. Server eligibility is not guaranteed; no unique execution/payment ACK.\n'
                        '只提交一次请求，不保证服务端允许或执行；无唯一执行/支付确认，不自动重发。')
            answer = QMessageBox.question(host,title,message,QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            checked = _v2_air_context(host)
            if not _same_v2_air_context(admission,checked) or not _v2_air_snapshot_current(checked):
                host.toast('Economic dialog context changed; request discarded')
                return
            allowed, reason, cost = request_decision(topic,command,checked[2],now=time.perf_counter(),param=param)
            if not allowed:
                host.toast(reason)
                return
            if premise != _economic_premise(topic,command,param,checked[2],cost,payload):
                if confirmation == 0:
                    continue
                host.toast('Economic conditions changed again; reopen the dialog. No request was sent.')
                return
            break
        token = checked[3]
        session = checked[0][5]
        if token is not None and (session is None or not session.operator.strip()
                or session.robot_id != str(checked[1][-1][1]) or session.referee_profile != checked[1][0]):
            host.toast('Supervised economy requires a matching named V2 session')
            return
        host._economy_qualification_token = None
        host._v2_air_qualification_attempt = None
        attempted = True
        try:
            ok, reason = checked[0][1].publish_topic(topic,bytes(payload),intent='economy',
                qualification_token=token,expected_economy_snapshot=checked[2])
            accepted_enqueue = bool(ok)
        finally:
            if token is not None:
                checked[0][0].lock_control()
        if ok:
            host.toast('MOCK请求已记录，无正式发送或资格证据' if checked[1][4] else '请求已提交，待服务器处理；未取得逐请求确认')
        else:
            host.toast(reason or 'Economic request rejected; state may have updated, please reconfirm')
    except Exception as exc:
        if accepted_enqueue:
            host.toast(f'请求已提交，但后续观察失败：{exc}；不会自动重发')
        elif attempted:
            host.toast(f'经济请求尝试发生错误：{exc}；不会自动重发')
        else:
            host.toast(f'经济确认未完成：{exc}')
