"""Deterministic text matching primitives. No ML, no surprises."""
import re

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def phrase_in(phrase: str, text_norm: str) -> bool:
    return normalize(phrase) in text_norm


def title_match(title: str, target_titles: list[str]) -> float:
    """1.0 exact phrase, 0.8 all tokens present, else best partial token overlap."""
    tnorm = normalize(title)
    ttok = tokens(title)
    best = 0.0
    for target in target_titles:
        if phrase_in(target, tnorm):
            return 1.0
        target_tok = tokens(target)
        if not target_tok:
            continue
        overlap = len(ttok & target_tok) / len(target_tok)
        if overlap == 1.0:
            best = max(best, 0.8)
        else:
            best = max(best, overlap * 0.6)
    return round(best, 4)


def skill_coverage(text: str, required: list[str], preferred: list[str],
                   excluded: list[str]) -> float:
    """Required hits weigh 2x, preferred 1x, excluded subtract 1.5x. Clamped 0..1."""
    tnorm = normalize(text)
    denom = 2.0 * len(required) + 1.0 * len(preferred)
    if denom == 0:
        return 0.0
    score = 0.0
    for kw in required:
        if phrase_in(kw, tnorm):
            score += 2.0
    for kw in preferred:
        if phrase_in(kw, tnorm):
            score += 1.0
    for kw in excluded:
        if phrase_in(kw, tnorm):
            score -= 1.5
    return round(max(0.0, min(1.0, score / denom)), 4)


def any_phrase(text: str, phrases: list[str]) -> str | None:
    tnorm = normalize(text)
    for p in phrases:
        if phrase_in(p, tnorm):
            return p
    return None
