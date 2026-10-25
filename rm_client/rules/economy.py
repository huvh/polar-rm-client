"""2027 rule-book price cards, deliberately NOT an unreviewed wire encoder."""
from ..economy_values import EconomyOffer
from . import competition_rules


def rule_economy_cards(state):
    rules=competition_rules(state.rules_season,state.match_mode)
    role=getattr(state,'robot_profile','')
    cards=[]
    for row in rules.facts.get('economy_catalogue',()):
        if role not in row.get('roles',(role,)):continue
        cost=row.get('cost')
        cards.append(EconomyOffer(key=f'2027_{row["key"]}',category=row['category'],
            title=row['title'],short_title=row['title'],description=row['description'],unit=row['unit'],
            minimum=row['quantity'],cost=cost or 0,command_type=0,command_param=0,enabled=False,
            reason='2027规则展示；对应裁判协议/命令尚未审定，不能发送',
            estimated=cost is None,status_only=True))
    if not cards:
        cards.append(EconomyOffer('2027_rules','support','2027 规则资料','规则资料',
            f'{rules.title} V{rules.version}；不会使用2026价格或命令',
            '规则展示',0,0,0,0,False,'2027经济协议未审定',status_only=True))
    return cards
