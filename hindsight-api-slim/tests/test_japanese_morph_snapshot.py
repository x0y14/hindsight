"""UniDic-backed Japanese temporal bounds (requires the ja-morph extra).

Always-green contracts live in test_query_analyzer.py. This module skips when
fugashi is absent so a default install stays green.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

import pytest

pytest.importorskip("fugashi")

from hindsight_api.engine.japanese_morph_tokens import tokenize_japanese
from hindsight_api.engine.temporal_periods import extract_period

REFERENCE_DATE = datetime(2025, 1, 15, 12, 0, 0)

# Surfaces measured against unidic-lite 1.0.8 / fugashi 1.5.2 before the
# extractor was written. POS is not pinned — UniDic has no 時相名詞 class.
_SURFACE_SNAPSHOT = {
    "先週何について考えてた？": ["先週", "何", "に", "つい", "て", "考え", "て", "た", "?"],
    "昨日何について": ["昨日", "何", "に", "つい", "て"],
    "きのう何した？": ["きのう", "何", "し", "た", "?"],
    "先週末": ["先週", "末"],
    "きのうえに猫がいる": ["き", "の", "うえ", "に", "猫", "が", "いる"],
    "きょうだいと遊んだ": ["きょうだい", "と", "遊ん", "だ"],
    "きょうのう": ["きょう", "のう"],
    "きょうの": ["きょう", "の"],
    "きのうのミーティング": ["きのう", "の", "ミーティング"],
    "きのうから": ["きのう", "から"],
    "きのうにて": ["きのう", "にて"],
    "来週中村": ["来週", "中村"],
    "来週中に": ["来週", "中", "に"],
    "明日方舟攻略": ["明日", "方舟", "攻略"],
    "今日头条新闻": ["今日", "头条", "新", "闻"],
    "明年今日安排": ["明年", "今日", "安", "排"],
    "今日到明天": ["今日", "到", "明", "天"],
}


@pytest.mark.parametrize(
    ("query", "start", "end"),
    [
        ("先週何について考えてた？", datetime(2025, 1, 6), datetime(2025, 1, 12)),
        ("きのう何した？", datetime(2025, 1, 14), datetime(2025, 1, 14)),
        ("昨日何について", datetime(2025, 1, 14), datetime(2025, 1, 14)),
        ("先週ミーティング", datetime(2025, 1, 6), datetime(2025, 1, 12)),
        ("昨日買った店", datetime(2025, 1, 14), datetime(2025, 1, 14)),
        # Proof that the kana-stem gate accepts particle-at-EOS and katakana
        # (きょうの会議 is already green on the old gate and is not a proof).
        ("きょうの", datetime(2025, 1, 15), datetime(2025, 1, 15)),
        ("きのうの", datetime(2025, 1, 14), datetime(2025, 1, 14)),
        ("あしたの", datetime(2025, 1, 16), datetime(2025, 1, 16)),
        ("おとといの", datetime(2025, 1, 13), datetime(2025, 1, 13)),
        ("あさっての", datetime(2025, 1, 17), datetime(2025, 1, 17)),
        ("きのうミーティング", datetime(2025, 1, 14), datetime(2025, 1, 14)),
        ("きのうのミーティング", datetime(2025, 1, 14), datetime(2025, 1, 14)),
        ("きょうー", datetime(2025, 1, 15), datetime(2025, 1, 15)),
        ("きのうにて会議", datetime(2025, 1, 14), datetime(2025, 1, 14)),
    ],
)
def test_japanese_morph_natural_language_positives(query, start, end):
    result = extract_period(query, REFERENCE_DATE)
    assert isinstance(result, tuple)
    assert result[0].date() == start.date()
    assert result[1].date() == end.date()


def test_kyounou_is_not_today():
    """きょうのう aligns as きょう+のう; the continuation gate must still reject it."""
    assert extract_period("きょうのう", REFERENCE_DATE) is None


@pytest.mark.parametrize("query,surfaces", list(_SURFACE_SNAPSHOT.items()))
def test_unidic_surface_snapshot_joins_to_query(query, surfaces):
    normalized = unicodedata.normalize("NFKC", query)
    tokens = tokenize_japanese(normalized)
    assert tokens is not None
    assert [token.surface for token in tokens.tokens] == surfaces
    joined = "".join(token.white_space + token.surface for token in tokens.tokens)
    assert joined == normalized
