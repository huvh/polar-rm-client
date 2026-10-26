"""Versioned competition rules, independent of referee wire and team firmware.

Rule facts do not register a codec, authorize outputs or certify field readiness.
2026's historical interfaces remain explicit; missing annual facts never fall
back to a previous year's performance table, map, economy or robot identity.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass,field
from functools import lru_cache
import math
from types import MappingProxyType


SEASONS = (2026, 2027)


class UnsupportedRules(ValueError):
    pass


def validate_season(value) -> int:
    if type(value) is str and value in ('2026','2027'):
        return int(value)
    if type(value) is int and value in SEASONS:
        return value
    raise UnsupportedRules(f'Unsupported competition season {value!r}; no annual fallback')


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key:_freeze(item) for key,item in value.items()})
    if isinstance(value,(list,tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value,float) and not math.isfinite(value):
        raise ValueError('Non-finite rule fact')
    return value


@dataclass(frozen=True,slots=True)
class CompetitionRules:
    season: int
    match_mode: str
    version: str
    published: str
    sources: tuple
    facts: Mapping
    citations: Mapping = field(default_factory=lambda:MappingProxyType({}))

    @property
    def duration_sec(self):
        return self.facts.get('duration_sec')

    @property
    def field_size_m(self):
        return self.facts.get('field_size_m')

    @property
    def roles(self):
        return self.facts.get('roles',())

    @property
    def performance(self):
        return self.facts.get('performance',{})

    @property
    def economy(self):
        return self.facts.get('economy',{})

    @property
    def features(self):
        return self.facts.get('features',{})

    @property
    def title(self):
        return f'{self.match_mode[:4]} {self.season} {self.match_mode[4:]}'


@lru_cache(maxsize=1)
def _annual_2027():
    # Explicit imports let frozen builds discover the versioned data modules.
    from .rmul2027 import DATA as rmul
    from .rmuc2027 import DATA as rmuc
    result={}
    for book in (rmuc,rmul):
        if book['season'] != 2027 or not book['rule_version'] or not book['sources']:
            raise ValueError('Incomplete 2027 rule-book identity')
        for source in book['sources']:
            digest=source['sha256']
            if (source['kind']!='official_rules' or len(digest)!=64
                    or any(char not in '0123456789abcdef' for char in digest)):
                raise ValueError('Rule source lacks official-document integrity evidence')
        for key,facts in book['modes'].items():
            if key in result:
                raise ValueError('Duplicate annual match mode')
            duration=facts.get('duration_sec')
            size=facts.get('field_size_m')
            if duration is not None and (type(duration) is not int or duration<=0):
                raise ValueError('Invalid rule duration')
            if size is not None and (len(size)!=2 or any(
                    type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in size)):
                raise ValueError('Invalid rule field dimensions')
            result[key]=CompetitionRules(2027,key,book['rule_version'],book['published'],
                _freeze(book['sources']),_freeze(facts),_freeze(book.get('field_citations',{})))
    return MappingProxyType(result)


def match_modes_for_season(season=2026):
    year=validate_season(season)
    return ('RMUC7v7','RMUL3v3') if year==2026 else tuple(_annual_2027())


def competition_rules(season,match_mode) -> CompetitionRules:
    year=validate_season(season)
    if year==2026:
        # These are compatibility settings from the old client, NOT a claim
        # that every historical rule formula was independently re-certified.
        legacy={'RMUC7v7':(420,(28.0,15.0)), 'RMUL3v3':(300,(12.0,8.0))}
        if match_mode not in legacy:
            raise UnsupportedRules(f'No 2026 rules for {match_mode!r}')
        duration,size=legacy[match_mode]
        return CompetitionRules(year,match_mode,'legacy-client-baseline','',(),
            _freeze({'duration_sec':duration,'field_size_m':size}))
    try:
        return _annual_2027()[match_mode]
    except KeyError as error:
        raise UnsupportedRules(f'No reviewed {year} rules for {match_mode!r}') from error
