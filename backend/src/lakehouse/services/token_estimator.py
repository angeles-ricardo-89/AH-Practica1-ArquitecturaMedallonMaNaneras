def estimate_tokens(text: str) -> int:
    if not text:
        return 1
    return max(1, len(text) // 4)
