"""Base-out state indexing; runners are bit flags for 1B, 2B, 3B."""
from __future__ import annotations

N_INNING_STATES = 24
LINEUP_SIZE = 9
N_STATES = N_INNING_STATES * LINEUP_SIZE


def index(outs: int, bases: int, next_batter: int) -> int:
    if not (0 <= outs <= 2 and 0 <= bases <= 7 and 0 <= next_batter < 9):
        raise ValueError((outs, bases, next_batter))
    return (next_batter * 3 + outs) * 8 + bases


def unpack(s: int) -> tuple[int, int, int]:
    if not 0 <= s < N_STATES:
        raise ValueError(s)
    batter, remainder = divmod(s, 24)
    outs, bases = divmod(remainder, 8)
    return outs, bases, batter
