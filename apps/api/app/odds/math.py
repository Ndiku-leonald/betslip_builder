from __future__ import annotations

import math


def implied_probability(decimal: float) -> float:
    if decimal <= 1: raise ValueError("decimal odds must be greater than 1")
    return 1.0 / float(decimal)


def overround(decimals) -> float:
    return sum(implied_probability(float(value)) for value in decimals) - 1.0


def no_vig(decimals) -> list[float]:
    raw = [implied_probability(float(value)) for value in decimals]
    total = sum(raw)
    if total <= 0: raise ValueError("market has no valid implied probability")
    return [value / total for value in raw]


def fair_decimal_odds(probability: float) -> float:
    if not 0 < float(probability) <= 1: raise ValueError("probability must be in (0, 1]")
    return 1.0 / max(1e-12, min(1.0, float(probability)))


def expected_value(probability: float, odds: float, *, push_probability: float = 0.0, loss_probability: float | None = None) -> float:
    if odds <= 1: raise ValueError("decimal odds must be greater than 1")
    p = float(probability); push = float(push_probability); loss = (1 - p - push) if loss_probability is None else float(loss_probability)
    if min(p, push, loss) < 0: raise ValueError("win, push and loss probabilities must be non-negative")
    return p * (odds - 1) - loss
