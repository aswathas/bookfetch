"""Candidate scoring: turn a pile of search hits into a pick or an ambiguity."""

from __future__ import annotations

import re

MIN_SCORE = 40  # below this the query and the book are different things
AMBIGUITY_GAP = 5  # top-1 minus top-2 smaller than this -> ambiguous
JUNK_TITLE_WORDS = ("download", "summary")  # scraped download-page titles
JUNK_PENALTY = 30
STARTS_WITH_BONUS = 15


def tokens(s: str) -> list:
    return re.findall(r"[a-z0-9']+", (s or "").lower())


def author_overlap(cand, author: str) -> bool:
    a = " ".join(tok for x in cand.authors for tok in tokens(x))
    at = tokens(author)
    return bool(at) and bool(a) and any(x in a for x in at)


def score(cand, query_text: str, author: str | None = None, year: str | None = None) -> float:
    q = tokens(query_text)
    t = tokens(cand.title)
    if not q or not t:
        return 0.0
    covered = sum(1 for x in q if x in t)
    s = 100.0 * covered / len(q)
    if set(q) <= set(t) and abs(len(t) - len(q)) <= 2:
        s += 40  # title is essentially the query
    elif set(q) == set(t):
        s += 60
    if t and q and t[0] == q[0]:
        s += STARTS_WITH_BONUS
    if any(w in " ".join(t) for w in JUNK_TITLE_WORDS):
        s -= JUNK_PENALTY
    if author:
        a = " ".join(tok for x in cand.authors for tok in tokens(x))
        at = tokens(author)
        if at and a:
            if all(x in a for x in at):
                s += 60
            elif any(x in a for x in at):
                s += 20
    if year:
        y = tokens(str(year))
        if y and y[0].isdigit():
            cy = next((x for x in tokens(cand.year) if x.isdigit()), "")
            if cy:
                try:
                    if abs(int(cy) - int(y[0])) <= 3:
                        s += 20
                except ValueError:
                    pass
    if (cand.language or "").lower() in ("", "english"):
        s += 5
    return s


def pick_best(cands, query_text: str, author: str | None = None, year: str | None = None, min_gap: float = AMBIGUITY_GAP):
    """Return (best, verdict, scored). verdict in {'ok', 'ambiguous', 'none'}.

    An explicit author is a HARD constraint: candidates with no author overlap are
    disqualified (-1), so a wrong book can never win on title similarity alone.
    """
    all_scored = []
    qualified = []
    for c in cands:
        s = -1.0 if (author and not author_overlap(c, author)) else score(c, query_text, author, year)
        all_scored.append((s, c))
        if s >= 0:
            qualified.append((s, c))
    all_scored.sort(key=lambda p: -p[0])
    qualified.sort(key=lambda p: -p[0])
    if not qualified or qualified[0][0] < MIN_SCORE:
        return None, "none", all_scored
    best_score, best = qualified[0]
    second = qualified[1][0] if len(qualified) > 1 else 0.0
    if best_score - second < min_gap:
        return None, "ambiguous", all_scored
    return best, "ok", all_scored
