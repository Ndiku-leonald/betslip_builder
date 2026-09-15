"""Chronological partitions with atomic observation-time groups."""
from __future__ import annotations

from collections import OrderedDict


def timestamp_groups(rows):
    groups = OrderedDict()
    for row in sorted(rows, key=lambda item: (item.data_cutoff_at, str(item.fixture_id))):
        groups.setdefault(row.data_cutoff_at, []).append(row)
    return list(groups.items())


def _boundary(prefix_counts: list[int], target: float) -> int:
    if len(prefix_counts) <= 2:
        return 1 if len(prefix_counts) > 1 else 0
    candidates = range(1, len(prefix_counts) - 1)
    return min(candidates, key=lambda position: (abs(prefix_counts[position] - target), position))


def chronological_split(rows, fractions=(0.6, 0.2, 0.2)):
    """Split rows chronologically, keeping every identical cutoff together."""
    if len(fractions) != 3 or any(value <= 0 for value in fractions):
        raise ValueError("fractions must contain three positive values")
    groups = timestamp_groups(rows)
    if not groups:
        return [], [], [], {"cutoffs": [], "group_counts": [0, 0, 0], "row_counts": [0, 0, 0]}
    counts = [0]
    for _, items in groups:
        counts.append(counts[-1] + len(items))
    total = counts[-1]
    denominator = sum(fractions)
    first = _boundary(counts, total * fractions[0] / denominator)
    second = _boundary(counts, total * (fractions[0] + fractions[1]) / denominator)
    second = max(first + 1, second)
    second = min(second, len(groups) - 1)
    if first >= second:
        first = max(1, second - 1)
    selected = (groups[:first], groups[first:second], groups[second:])
    partitions = [[row for _, items in part for row in items] for part in selected]
    metadata = {
        "cutoffs": [[cutoff for cutoff, _ in part] for part in selected],
        "group_counts": [len(part) for part in selected],
        "row_counts": [len(part) for part in partitions],
        "start_at": [part[0][0] if part else None for part in selected],
        "end_at": [part[-1][0] if part else None for part in selected],
    }
    return partitions[0], partitions[1], partitions[2], metadata


def take_group_boundary(groups, start: int, requested_rows: int) -> int:
    """Return the exclusive end group for an approximate row-sized window."""
    if start >= len(groups) or requested_rows <= 0:
        return start
    total = 0
    end = start
    while end < len(groups) and total < requested_rows:
        total += len(groups[end][1])
        end += 1
    return end
