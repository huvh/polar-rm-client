"""Bounded, read-only RM observations for the CS competitive timeline silhouette.

An HP alive->dead edge is a loss observation, NOT a kill attribution or a CS
round win. Unknown->dead is never an observed edge. No clock extrapolation.
"""
from collections import deque
from dataclasses import dataclass

from ..top_match_bar import LifeState


@dataclass(frozen=True)
class LossObservation:
    robot_id: int
    alliance: str
    remaining: int


class ScoreboardHistory:
    def __init__(self):
        self.context = None
        self.losses = deque(maxlen=64)
        self._lives = {}
        self.revision = 0

    def reset(self):
        self.context = None
        self.losses.clear()
        self._lives.clear()
        self.revision += 1

    def observe(self, frame, context):
        if context != self.context:
            self.reset()
            self.context = context
        lives = {}
        for team in (frame.left, frame.right):
            for card in team.cards:
                if not card.health_applicable:
                    continue
                lives[card.robot_id] = card.life
                if (frame.phase == 'MATCH' and frame.countdown is not None
                        and self._lives.get(card.robot_id) == LifeState.ALIVE
                        and card.life == LifeState.DEAD):
                    self.losses.append(LossObservation(card.robot_id, team.alliance, frame.countdown))
                    self.revision += 1
        self._lives = lives  # Unknown/stale samples interrupt the edge chain.

    def snapshot(self):
        return tuple(self.losses)
