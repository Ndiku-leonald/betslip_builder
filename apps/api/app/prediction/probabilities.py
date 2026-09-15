from __future__ import annotations

import numpy as np


def clip(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def football_markets(matrix: np.ndarray) -> dict[str, float | dict[str, float]]:
    n = matrix.shape[0]
    home = float(np.tril(matrix, -1).sum())
    away = float(np.triu(matrix, 1).sum())
    draw = float(np.trace(matrix))
    markets: dict[str, float | dict[str, float]] = {"home_win": clip(home), "draw": clip(draw), "away_win": clip(away), "home_or_draw": clip(home + draw), "away_or_draw": clip(away + draw), "home_or_away": clip(home + away), "btts_yes": clip(sum(matrix[i, j] for i in range(1, n) for j in range(1, n))), "btts_no": clip(sum(matrix[i, 0] for i in range(n)) + sum(matrix[0, j] for j in range(1, n)))}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        over = sum(matrix[i, j] for i in range(n) for j in range(n) if i + j > line)
        markets[f"over_{str(line).replace('.', '_')}"] = clip(over)
        markets[f"under_{str(line).replace('.', '_')}"] = clip(1 - over)
    for side in ("home", "away"):
        for line in (0.5, 1.5, 2.5, 3.5):
            total = sum(matrix[i, j] for i in range(n) for j in range(n) if (i if side == "home" else j) > line)
            markets[f"{side}_over_{str(line).replace('.', '_')}"] = clip(total)
            markets[f"{side}_under_{str(line).replace('.', '_')}"] = clip(1 - total)
    for line in (-1.5, -0.5, 0.5, 1.5):
        win = sum(matrix[i, j] for i in range(n) for j in range(n) if i + line > j)
        push = sum(matrix[i, j] for i in range(n) for j in range(n) if i + line == j)
        markets[f"home_handicap_{line:+g}"] = {"win": clip(win), "push": clip(push), "lose": clip(1 - win - push)}
    return markets
