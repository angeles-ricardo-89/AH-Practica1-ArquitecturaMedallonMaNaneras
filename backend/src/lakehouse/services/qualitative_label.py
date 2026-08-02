from __future__ import annotations


def assign_qualitative_labels(scores: list[float]) -> list[str]:
    if not scores:
        return []
    n = len(scores)
    if n < 4:
        return ["Alta"] * n

    top_count = max(1, n // 4)
    bottom_count = max(1, n // 4)
    mid_count = n - top_count - bottom_count

    return ["Alta"] * top_count + ["Media"] * mid_count + ["Baja"] * bottom_count
