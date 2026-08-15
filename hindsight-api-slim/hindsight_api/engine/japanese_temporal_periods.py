"""Japanese period extraction helpers for DateparserQueryAnalyzer.

Japanese relative periods use a different prefix system from Chinese
(先/来/今 vs 上/下/这|本). Shared CJK ideographs are not enough: closed
Japanese compounds are matched here before falling through to Chinese rules.
Hiragana aliases are also handled here because kana alone does not enter the
CJK ideograph route in extract_period.

Matching contract mirrors Chinese (recurring → open/since → closed longest-first):
1. Recurring 毎… forms return the sentinel so they never invent a single day/week.
2. Open starts (から/以降) over the full compound catalog return the sentinel.
3. Closed ranges match longest compounds first; optional 中/内/以内 is a stem
   suffix, not a generic follower character (来週中村 must not become 来週).

Independence of a catalog match is a UniDic **character** boundary oracle
(match.start()/end() in the token-bound set), not a one-character follower
whitelist. The whitelist remains only when fugashi/unidic-lite is missing.
A one-token match is not required: UniDic splits 先週末 into 先週+末.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import datetime, timedelta

from hindsight_api.engine.japanese_morph_tokens import JapaneseMorphTokens, tokenize_japanese
from hindsight_api.engine.temporal_periods import NO_TEMPORAL_CONSTRAINT, DateRange, NoTemporalConstraintSentinel

_JAPANESE_TEMPORAL_FOLLOWER_CHARS = frozenset(
    " \t\r\n"
    ".,!?;:()[]{}<>\"'"
    "，。！？；：（）【】《》“”‘’、"
    # Japanese particles (omit か so open forms like 昨日から do not look closed).
    "のはがをにでともへ"
    # Chinese particle so JA-owned 来年 still accepts 来年的计划.
    "的"
)

_JAPANESE_NUMERAL_CHARS = "一二三四五六七八九十百千"
_JAPANESE_NUMERAL_PREFIX = f"0-9{_JAPANESE_NUMERAL_CHARS}"
_MONTH_UNIT = r"(?:ヶ月|か月|ヵ月|カ月)"
_OPEN_SUFFIX = r"(?:から先|から|以降)"
# 以内 before 内 so 今月以内 is not truncated to 今月内.
_STEM_DURATION = r"(?:以内|中|内)?"
_WEEKDAY_BASES = ("月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜")
_WEEKDAY_INDEX = {f"{base}日": index for index, base in enumerate(_WEEKDAY_BASES)}
_WEEKDAY_PATTERN = "|".join(f"{base}(?:日)?" for base in _WEEKDAY_BASES)
_RELATIVE_WEEKDAY = rf"(?:(先々|再来|先|今|来)?週の({_WEEKDAY_PATTERN}))"
_WEEK_NOT_COMPOUND = r"(?!末)(?!の(?:曜(?:日)?))"


def _is_kana_character(char: str) -> bool:
    return ("\u3040" <= char <= "\u309f") or ("\u30a0" <= char <= "\u30ff")


def _is_hiragana_character(char: str) -> bool:
    return "\u3040" <= char <= "\u309f"


# Surfaces allowed immediately after a kana day stem. Omit か (open きのうか).
# にて is one UniDic token; without it, きのうにて会議 regresses.
# から is not listed: open/since (から/以降) runs before closed kana stems.
_KANA_STEM_FOLLOWER_SURFACES = frozenset("のはがをにでともへ") | frozenset({"にて"})


def _kana_stem_continuation_ok(query: str, match_end: int, morph: JapaneseMorphTokens) -> bool:
    """Accept a kana stem when the next token is not still the same word.

    UniDic splits きょうのう as きょう+のう. Morph alignment alone would
    accept きょう. Distinguish by surface: の is a case particle (きょうの),
    のう is not. Do not use POS — のう is also 助詞 — and do not require a
    non-kana character after a particle (that rejects きょうの at EOS and
    きのうのミーティング). Katakana, kanji, punctuation, and ー are word
    boundaries (きのうミーティング, きょうー), matching 先週ミーティング / 今日ー.
    """
    if match_end >= len(query):
        return True
    next_char = query[match_end]
    if not _is_hiragana_character(next_char):
        return True
    next_token = morph.token_at(match_end)
    if next_token is None:
        return False
    return next_token.surface in _KANA_STEM_FOLLOWER_SURFACES


def extract_japanese_period(query: str, reference_date: datetime) -> DateRange | NoTemporalConstraintSentinel | None:
    """Extract Japanese period-based temporal expressions as closed date ranges."""
    query = unicodedata.normalize("NFKC", query)
    has_kana = any(_is_kana_character(char) for char in query)
    # Tokenize the same NFKC string the regexes see. None → follower whitelist.
    morph = tokenize_japanese(query)

    def constraint(start: datetime, end: datetime) -> DateRange:
        return (
            start.replace(hour=0, minute=0, second=0, microsecond=0),
            end.replace(hour=23, minute=59, second=59, microsecond=999999),
        )

    def safe_constraint(start: datetime | None, end: datetime | None) -> DateRange | NoTemporalConstraintSentinel:
        if start is None or end is None:
            return NO_TEMPORAL_CONSTRAINT
        return constraint(start, end)

    def add_months(base_date: datetime, months: int) -> datetime | None:
        month_index = base_date.month + months - 1
        year = base_date.year + month_index // 12
        if year < datetime.min.year or year > datetime.max.year:
            return None
        month = month_index % 12 + 1
        day = min(base_date.day, calendar.monthrange(year, month)[1])
        return base_date.replace(year=year, month=month, day=day)

    def month_end(year: int, month: int) -> datetime:
        return datetime(year, month, calendar.monthrange(year, month)[1])

    def add_days(base_date: datetime | None, days: int) -> datetime | None:
        if base_date is None:
            return None
        try:
            return base_date + timedelta(days=days)
        except OverflowError:
            return None

    def has_japanese_temporal_context(match: re.Match[str], *, kana_stem: bool = False) -> bool:
        # Prefer UniDic char bounds over the one-character follower whitelist.
        # 何 and katakana (ミーティング) were never in that set, so 先週何 / 先週ミーティング
        # missed. match.start()/end() must both be token boundaries; a one-token
        # span is not required (先週末 = 先週+末).
        #
        # Greedy _STEM_DURATION plus non-overlapping finditer is what keeps
        # 来週中村 None: UniDic splits 来週|中村, the regex consumes 来週中, end=3
        # is not a bound, and finditer does not retry bare 来週 at 0.
        if morph is not None:
            if match.start() not in morph.bounds or match.end() not in morph.bounds:
                return False
            if kana_stem:
                return _kana_stem_continuation_ok(query, match.end(), morph)
            return True
        if match.end() >= len(query):
            return True
        return query[match.end()] in _JAPANESE_TEMPORAL_FOLLOWER_CHARS

    def japanese_search(pattern: str, *, kana_stem: bool = False) -> re.Match[str] | None:
        for match in re.finditer(pattern, query):
            if has_japanese_temporal_context(match, kana_stem=kana_stem):
                return match
        return None

    def parse_japanese_number(text: str) -> int | None:
        if text.isdigit():
            return int(text)
        if not any(unit in text for unit in "十百千"):
            if len(text) != 1:
                return None
            index = "一二三四五六七八九".find(text)
            return index + 1 if index >= 0 else None

        total = 0
        section = 0
        number = 0
        for char in text:
            digit_index = "一二三四五六七八九".find(char)
            if digit_index >= 0:
                number = digit_index + 1
                continue
            unit = {"十": 10, "百": 100, "千": 1000}.get(char)
            if unit is None:
                return None
            section += (number or 1) * unit
            number = 0
        return total + section + number

    def week_start(week_offset: int) -> datetime:
        monday = reference_date - timedelta(days=reference_date.weekday())
        return monday + timedelta(weeks=week_offset)

    def week_period(week_offset: int) -> DateRange:
        start = week_start(week_offset)
        return constraint(start, start + timedelta(days=6))

    def weekend_period(week_offset: int) -> DateRange:
        # Mirror Chinese prefixed weekends: Saturday–Sunday of the target ISO week.
        # Bare "last weekend" in EN uses a different "most recent Saturday" rule;
        # Japanese 先週末 aligns with Chinese 上周末 for mid-week references.
        if week_offset == -1:
            days_since_sat = (reference_date.weekday() + 2) % 7
            if days_since_sat == 0:
                days_since_sat = 7
            sat = reference_date - timedelta(days=days_since_sat)
            return constraint(sat, sat + timedelta(days=1))
        start = week_start(week_offset)
        sat = start + timedelta(days=5)
        return constraint(sat, sat + timedelta(days=1))

    def month_period(month_offset: int) -> DateRange | NoTemporalConstraintSentinel:
        start = add_months(reference_date.replace(day=1), month_offset)
        if start is None:
            return NO_TEMPORAL_CONSTRAINT
        return constraint(start, month_end(start.year, start.month))

    def year_period(year_offset: int) -> DateRange | NoTemporalConstraintSentinel:
        year = reference_date.year + year_offset
        if year < datetime.min.year or year > datetime.max.year:
            return NO_TEMPORAL_CONSTRAINT
        return constraint(datetime(year, 1, 1), datetime(year, 12, 31))

    def day_period(day_offset: int) -> DateRange | NoTemporalConstraintSentinel:
        d = add_days(reference_date, day_offset)
        return safe_constraint(d, d)

    def weekday_period(week_offset: int, weekday_name: str) -> DateRange | None:
        full_name = weekday_name if weekday_name.endswith("日") else f"{weekday_name}日"
        weekday = _WEEKDAY_INDEX.get(full_name)
        if weekday is None:
            return None
        d = week_start(week_offset) + timedelta(days=weekday)
        return constraint(d, d)

    # 1. Recurring forms — one regex so 毎週月曜日 is not split into 毎週 + bare 月曜日.
    # 週末 before 週 so 毎週末 does not fall through to Chinese 周末.
    if japanese_search(rf"毎(?:週末|週|月|日|年)(?:の)?(?:{_WEEKDAY_PATTERN})?"):
        return NO_TEMPORAL_CONSTRAINT

    # 2. Open/since over the full catalog (including short 曜 and relative weekdays).
    open_period_stems = (
        r"先々週末|先週末|今週末|来週末|"
        rf"{_RELATIVE_WEEKDAY}|"
        r"先々週|再来週|先週|今週|来週|"
        r"先々月|再来月|先月|今月|来月|"
        r"一昨年|再来年|来年|"
        r"一昨日|明後日|昨日|今日|明日|"
        r"きのう|きょう|あした|おととい|あさって|"
        rf"(?:{_WEEKDAY_PATTERN})"
    )
    if japanese_search(rf"(?:{open_period_stems}){_STEM_DURATION}{_OPEN_SUFFIX}"):
        return NO_TEMPORAL_CONSTRAINT

    # 3. Closed ranges, longest-first. Optional 中/内/以内 is a stem suffix.

    # Prefixed weekends before bare week compounds (先週末 must not become 先週).
    if japanese_search(rf"先々週末{_STEM_DURATION}"):
        return weekend_period(-2)
    if japanese_search(rf"先週末{_STEM_DURATION}"):
        return weekend_period(-1)
    if japanese_search(rf"今週末{_STEM_DURATION}"):
        return weekend_period(0)
    if japanese_search(rf"来週末{_STEM_DURATION}"):
        return weekend_period(1)

    # Relative weekday before bare 先週 (先週の月曜日 ≠ 先週; short 曜 included).
    relative_weekday = japanese_search(rf"{_RELATIVE_WEEKDAY}{_STEM_DURATION}")
    if relative_weekday:
        prefix = relative_weekday.group(1)
        week_offset = {
            "先々": -2,
            "再来": 2,
            "先": -1,
            "今": 0,
            "来": 1,
            None: 0,
        }[prefix]
        result = weekday_period(week_offset, relative_weekday.group(2))
        if result is not None:
            return result

    # Relative week / month / year. Reject compound tails and recurring 毎X.
    if japanese_search(rf"(?<!毎)先々週{_WEEK_NOT_COMPOUND}{_STEM_DURATION}"):
        return week_period(-2)
    if japanese_search(rf"(?<!毎)再来週{_WEEK_NOT_COMPOUND}{_STEM_DURATION}"):
        return week_period(2)
    if japanese_search(rf"(?<!毎)先週{_WEEK_NOT_COMPOUND}{_STEM_DURATION}"):
        return week_period(-1)
    if japanese_search(rf"(?<!毎)今週{_WEEK_NOT_COMPOUND}{_STEM_DURATION}"):
        return week_period(0)
    if japanese_search(rf"(?<!毎)来週{_WEEK_NOT_COMPOUND}{_STEM_DURATION}"):
        return week_period(1)

    if japanese_search(rf"(?<!毎)先々月{_STEM_DURATION}"):
        return month_period(-2)
    if japanese_search(rf"(?<!毎)再来月{_STEM_DURATION}"):
        return month_period(2)
    if japanese_search(rf"(?<!毎)先月{_STEM_DURATION}"):
        return month_period(-1)
    if japanese_search(rf"(?<!毎)今月{_STEM_DURATION}"):
        return month_period(0)
    if japanese_search(rf"(?<!毎)来月{_STEM_DURATION}"):
        return month_period(1)

    if japanese_search(rf"(?<!毎)一昨年{_STEM_DURATION}"):
        return year_period(-2)
    if japanese_search(rf"(?<!毎)再来年{_STEM_DURATION}"):
        return year_period(2)
    if japanese_search(rf"(?<!毎)来年{_STEM_DURATION}"):
        return year_period(1)

    # Longer day compounds before short shared forms handled by Chinese.
    if japanese_search(rf"一昨日{_STEM_DURATION}"):
        return day_period(-2)
    if japanese_search(rf"明後日{_STEM_DURATION}"):
        return day_period(2)

    # Shared 昨日/今日/明日 become JA closed ranges only when the query has kana
    # (昨日何について). Bare 今日 and 明日方舟攻略 have no kana and stay on the
    # Chinese path — no CJK follower-class routing.
    if has_kana:
        if japanese_search(rf"昨日{_STEM_DURATION}"):
            return day_period(-1)
        if japanese_search(rf"今日{_STEM_DURATION}"):
            return day_period(0)
        if japanese_search(rf"明日{_STEM_DURATION}"):
            return day_period(1)

    # Exact counters (Arabic or Japanese numerals).
    exact_days_past = japanese_search(rf"(?<![{_JAPANESE_NUMERAL_PREFIX}])([0-9]+|[{_JAPANESE_NUMERAL_CHARS}]+)日[前]")
    if exact_days_past:
        days = parse_japanese_number(exact_days_past.group(1))
        if days is not None:
            return day_period(-days)

    exact_days_future = japanese_search(rf"(?<![{_JAPANESE_NUMERAL_PREFIX}])([0-9]+|[{_JAPANESE_NUMERAL_CHARS}]+)日後")
    if exact_days_future:
        days = parse_japanese_number(exact_days_future.group(1))
        if days is not None:
            return day_period(days)

    exact_weeks_past = japanese_search(rf"(?<![{_JAPANESE_NUMERAL_PREFIX}])([0-9]+|[{_JAPANESE_NUMERAL_CHARS}]+)週間前")
    if exact_weeks_past:
        weeks = parse_japanese_number(exact_weeks_past.group(1))
        if weeks is not None:
            return day_period(-(weeks * 7))

    exact_weeks_future = japanese_search(
        rf"(?<![{_JAPANESE_NUMERAL_PREFIX}])([0-9]+|[{_JAPANESE_NUMERAL_CHARS}]+)週間後"
    )
    if exact_weeks_future:
        weeks = parse_japanese_number(exact_weeks_future.group(1))
        if weeks is not None:
            return day_period(weeks * 7)

    exact_months_past = japanese_search(
        rf"(?<![{_JAPANESE_NUMERAL_PREFIX}])([0-9]+|[{_JAPANESE_NUMERAL_CHARS}]+){_MONTH_UNIT}前"
    )
    if exact_months_past:
        months = parse_japanese_number(exact_months_past.group(1))
        if months is not None:
            d = add_months(reference_date, -months)
            return safe_constraint(d, d)

    exact_months_future = japanese_search(
        rf"(?<![{_JAPANESE_NUMERAL_PREFIX}])([0-9]+|[{_JAPANESE_NUMERAL_CHARS}]+){_MONTH_UNIT}後"
    )
    if exact_months_future:
        months = parse_japanese_number(exact_months_future.group(1))
        if months is not None:
            d = add_months(reference_date, months)
            return safe_constraint(d, d)

    if japanese_search(r"数日前"):
        return constraint(reference_date - timedelta(days=5), reference_date - timedelta(days=2))

    bare_weekday = japanese_search(rf"(?<!毎)({_WEEKDAY_PATTERN}){_STEM_DURATION}")
    if bare_weekday:
        result = weekday_period(0, bare_weekday.group(1))
        if result is not None:
            return result

    # Hiragana aliases (kana-only queries never reach Chinese rules).
    kana_day_offsets = {
        "おととい": -2,
        "きのう": -1,
        "きょう": 0,
        "あした": 1,
        "あさって": 2,
    }
    # Longer forms first so おととい is not partially matched.
    for kana, offset in sorted(kana_day_offsets.items(), key=lambda item: -len(item[0])):
        if japanese_search(rf"{re.escape(kana)}{_STEM_DURATION}", kana_stem=True):
            return day_period(offset)

    return None
