"""Minimal Composer-style version-constraint interval overlap checker.

Scope: numeric dotted versions and the operators Composer/Packagist
constraints actually use in practice — exact, `>=`/`<=`/`>`/`<`, caret
(`^`), tilde (`~`), wildcard (`.*`/`.x`), comma/whitespace-separated AND,
and `||` OR. Pre-release suffixes (`-beta1`) are stripped and ignored for
ordering purposes, and stability flags (`@dev`) aren't handled — this is
not a full reimplementation of composer/semver's grammar, just enough to
answer "do these two constraints overlap" for the CVE check (see
docs/v1-port-roadmap.md's Phase 10 design note on why this needed a real
implementation rather than a one-line library swap).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

Version = tuple[int, ...]

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?")


def _parse_version(raw: str) -> Version:
    raw = raw.strip().lstrip("vV")
    raw = re.split(r"[-+]", raw, maxsplit=1)[0]
    match = _VERSION_RE.match(raw)
    if not match:
        return (0,)
    parts = tuple(int(g) for g in match.groups() if g is not None)
    return parts or (0,)


def _pad(v: Version, length: int) -> Version:
    return v + (0,) * (length - len(v))


def _cmp(a: Version, b: Version) -> int:
    length = max(len(a), len(b))
    a, b = _pad(a, length), _pad(b, length)
    return (a > b) - (a < b)


def _bump(v: Version, index: int) -> Version:
    """The smallest version greater than every version sharing v's first
    `index + 1` components — the exclusive upper bound for ^/~/wildcard."""
    prefix = list(v[: index + 1])
    prefix[index] += 1
    return tuple(prefix)


@dataclass
class Interval:
    low: Version | None  # None = unbounded below
    low_inclusive: bool
    high: Version | None  # None = unbounded above
    high_inclusive: bool

    def overlaps(self, other: Interval) -> bool:
        if self.low is not None and other.high is not None:
            c = _cmp(self.low, other.high)
            if c > 0 or (c == 0 and not (self.low_inclusive and other.high_inclusive)):
                return False
        if other.low is not None and self.high is not None:
            c = _cmp(other.low, self.high)
            if c > 0 or (c == 0 and not (other.low_inclusive and self.high_inclusive)):
                return False
        return True


_UNBOUNDED = Interval(None, True, None, True)


def _parse_simple(token: str) -> Interval:
    token = token.strip()
    if token in ("", "*"):
        return _UNBOUNDED

    if token.startswith(">="):
        return Interval(_parse_version(token[2:]), True, None, True)
    if token.startswith("<="):
        return Interval(None, True, _parse_version(token[2:]), True)
    if token.startswith(">"):
        return Interval(_parse_version(token[1:]), False, None, True)
    if token.startswith("<"):
        return Interval(None, True, _parse_version(token[1:]), False)
    if token.startswith("!="):
        # Not expressible as a single interval; treat as unbounded (never
        # the reason an overlap check says "no overlap") rather than wrong.
        return _UNBOUNDED
    token = token.removeprefix("=")

    if token.startswith("^"):
        v = _parse_version(token[1:])
        bump_index = next((i for i, part in enumerate(v) if part != 0), len(v) - 1)
        return Interval(v, True, _bump(v, bump_index), False)

    if token.startswith("~"):
        v = _parse_version(token[1:])
        bump_index = max(len(v) - 2, 0)
        return Interval(v, True, _bump(v, bump_index), False)

    if token.endswith((".*", ".x")):
        base = token[:-2]
        v = _parse_version(base)
        return Interval(v, True, _bump(v, len(v) - 1), False)

    v = _parse_version(token)
    return Interval(v, True, v, True)


_HYPHEN_RANGE_RE = re.compile(r"(\S+)\s+-\s+(\S+)")


def _parse_and_group(group: str) -> list[Interval]:
    # Composer's hyphenated range syntax ("1.0.0 - 2.1.0", meaning >=1.0.0 <=2.1.0)
    # has no branch of its own below — without this, the plain whitespace tokenizer
    # splits it into ["1.0.0", "-", "2.1.0"], and the bare "-" token falls through to
    # the exact-version branch, parsing as version (0,) and producing an
    # inverted/empty interval that silently reports "no overlap" even when the
    # ranges genuinely do (a false negative feeding straight into the CVE and
    # upgrade-readiness checks). The embedded dash in a pre-release suffix (e.g.
    # "1.0.0-beta") has no surrounding whitespace, so it's unaffected by this.
    group = _HYPHEN_RANGE_RE.sub(lambda m: f">={m.group(1)} <={m.group(2)}", group)
    tokens = [t for t in re.split(r"[,\s]+", group.strip()) if t]
    return [_parse_simple(t) for t in tokens] or [_UNBOUNDED]


def _intersect_and_group(intervals: list[Interval]) -> Interval:
    low: Version | None = None
    low_inclusive = True
    high: Version | None = None
    high_inclusive = True

    for iv in intervals:
        if iv.low is not None and (
            low is None or _cmp(iv.low, low) > 0 or (_cmp(iv.low, low) == 0 and not iv.low_inclusive)
        ):
            low, low_inclusive = iv.low, iv.low_inclusive
        if iv.high is not None and (
            high is None or _cmp(iv.high, high) < 0 or (_cmp(iv.high, high) == 0 and not iv.high_inclusive)
        ):
            high, high_inclusive = iv.high, iv.high_inclusive

    return Interval(low, low_inclusive, high, high_inclusive)


_OR_RE = re.compile(r"\|\|?")  # composer.json uses "||"; Packagist advisories use a single "|"


def parse_constraint(constraint: str) -> list[Interval]:
    """A Composer version constraint as a list of OR'd intervals."""
    return [_intersect_and_group(_parse_and_group(group)) for group in _OR_RE.split(constraint)]


def constraints_overlap(a: str, b: str) -> bool:
    a_intervals = parse_constraint(a)
    b_intervals = parse_constraint(b)
    return any(ia.overlaps(ib) for ia in a_intervals for ib in b_intervals)
