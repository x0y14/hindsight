"""UniDic character-boundary tokens for Japanese temporal extraction.

fugashi's ``node.length`` is a MeCab **byte** length. ``re.Match`` offsets are
**characters**. Mixing them silently accepts or rejects the wrong span.

Bounds are accumulated from ``len(white_space) + len(surface)`` in Python
chars. Surfaces are copied immediately after parse: the next MeCab parse
invalidates node pointers. If ``''.join(white_space + surface)`` does not
equal the query, return None so the caller falls back to the character
whitelist rather than mixing offset systems.

The Tagger is created on first tokenize, not at import or before fork.
MeCab releases the GIL, so parse (and construction) run under a lock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class MorphToken:
    surface: str
    white_space: str
    start: int
    end: int


@dataclass(frozen=True)
class JapaneseMorphTokens:
    tokens: tuple[MorphToken, ...]
    bounds: frozenset[int]

    def token_at(self, start: int) -> MorphToken | None:
        for token in self.tokens:
            if token.start == start:
                return token
        return None


_tagger_lock = threading.Lock()
_tagger: object | None = None
_tagger_unavailable = False


def _load_tagger() -> object:
    """Import and construct Tagger. Must not run at module import."""
    from fugashi import Tagger  # type: ignore[unresolved-import]

    return Tagger()


def tokenize_japanese(query: str) -> JapaneseMorphTokens | None:
    """Tokenize an NFKC query into char-indexed UniDic nodes, or None to fall back."""
    global _tagger, _tagger_unavailable
    if _tagger_unavailable:
        return None

    with _tagger_lock:
        if _tagger_unavailable:
            return None
        if _tagger is None:
            try:
                _tagger = _load_tagger()
            except Exception:
                # Missing extra, missing dictionary, or Tagger() failure.
                # Sticky: retrying every query would pay the same import/dict cost.
                _tagger_unavailable = True
                return None
        try:
            # Copy surface/white_space inside the lock; the next parse invalidates
            # MeCab pointers. Do not use node.length — that is bytes, not chars.
            nodes = _tagger(query)
            tokens_list: list[MorphToken] = []
            pieces: list[str] = []
            pos = 0
            for node in nodes:
                white_space = node.white_space
                surface = node.surface
                pieces.append(white_space)
                pieces.append(surface)
                pos += len(white_space)
                start = pos
                pos += len(surface)
                tokens_list.append(
                    MorphToken(
                        surface=surface,
                        white_space=white_space,
                        start=start,
                        end=pos,
                    )
                )
        except Exception:
            return None

    joined = "".join(pieces)
    if joined != query:
        return None
    bounds = frozenset({0, len(query), *(token.start for token in tokens_list), *(token.end for token in tokens_list)})
    return JapaneseMorphTokens(tokens=tuple(tokens_list), bounds=bounds)
