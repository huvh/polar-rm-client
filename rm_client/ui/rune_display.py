"""Keep official mean ring score separate from private mock progress."""
from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class RuneDisplay:
    value: str
    phase: str
    progress: float | None


def rune_display(state: Any) -> RuneDisplay:
    if getattr(state, 'official_state_active', None) is True:
        status = getattr(state, 'rune_status', {})
        status = status if isinstance(status, dict) else {}
        stage = status.get('rune_status')
        phase = {1: 'INACTIVE', 2: 'ACTIVATING', 3: 'ACTIVE'}.get(stage, 'UNKNOWN') if type(stage) is int else 'UNKNOWN'
        score = status.get('average_rings')
        if stage == 2 and type(stage) is int and type(score) in (int, float) and math.isfinite(score) and score >= 0:
            return RuneDisplay(f'{score:g} rings', phase, None)
        return RuneDisplay(phase, phase, None)
    if (getattr(state, 'official_state_active', None) is False
            and getattr(state, 'mock_simulation_enabled', None) is True):
        progress = getattr(state, 'energy_rune_progress', None)
        if type(progress) in (int, float) and math.isfinite(progress):
            return RuneDisplay(f'{progress:g}%', str(getattr(state, 'energy_rune_phase', 'UNKNOWN')),
                max(0., min(1., progress / 100.)))
    return RuneDisplay('UNKNOWN', 'UNKNOWN', None)
