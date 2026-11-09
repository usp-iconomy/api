"""Sentiment classification for circulation messages (D6).

Keyword-based for Fase B. The `SentimentClassifier` Protocol is stable so
Fase G can swap this for an ML model (e.g. a PT-BR transformer) without
touching the service.
"""

import re
from typing import Protocol

from iconomy.circulation.models import Sentiment

# Portuguese stems. We check `substring in word` on the normalised message so
# we catch inflections ("obrigada", "obrigado", "obrigadíssima" all share
# "obrigad"). Keep this list conservative — false positives on acknowledgement
# words tilt the whole feed positive and distort RF-15.
POSITIVE_STEMS: frozenset[str] = frozenset(
    {
        "obrigad",
        "paraben",
        "excelent",
        "incriv",
        "maravilh",
        "gratid",
        "gratido",
        "amor",
        "amad",
        "lind",
        "fantastic",
        "sensacional",
        "orgulh",
        "feliz",
        "alegr",
        "melhor",
        "ador",
    }
)
NEGATIVE_STEMS: frozenset[str] = frozenset(
    {
        "triste",
        "decepcion",
        "frustr",
        "raiva",
        "odei",
        "pessim",
        "horrivel",
        "terrivel",
        "chate",
        "ruim",
        "pior",
        "problem",
        "errad",
    }
)

_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def _normalise(text: str) -> list[str]:
    """Lowercase + strip accents (NFKD) + split into word-ish tokens."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _WORD_RE.findall(stripped)


class SentimentClassifier(Protocol):
    async def classify(self, text: str) -> Sentiment: ...


class KeywordSentimentClassifier:
    """Lightweight PT-BR classifier. Ties resolve to NEUTRAL."""

    async def classify(self, text: str) -> Sentiment:
        words = _normalise(text)
        pos = sum(1 for w in words if any(stem in w for stem in POSITIVE_STEMS))
        neg = sum(1 for w in words if any(stem in w for stem in NEGATIVE_STEMS))
        if pos > neg:
            return Sentiment.POSITIVE
        if neg > pos:
            return Sentiment.NEGATIVE
        return Sentiment.NEUTRAL
