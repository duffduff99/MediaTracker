"""Text helpers: title normalisation, search matching and barcode handling."""

from __future__ import annotations

import re
import unicodedata

_ARTICLE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Leading "007" (Bond releases are often titled "007: GoldenEye") and trailing edition words
# are ignored when deciding whether two records are the same title.
_LEADING_SERIES = re.compile(r"^007\s+")
_TRAILING_EDITION = re.compile(
    r"(\s+(extended|unrated|uncut|theatrical|remastered|widescreen|fullscreen|steelbook)(\s+(edition|cut|version))?"
    r"|\s+(special|collectors|anniversary|deluxe|limited|ultimate|definitive)\s+edition"
    r"|\s+directors\s+cut)+$"
)


def fold(value: str | None) -> str:
    """Lower-case, strip accents and smart quotes, '&' -> 'and'."""
    if not value:
        return ""
    s = unicodedata.normalize("NFKD", value)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ").replace("’", "").replace("'", "")
    return s


def search_norm(value: str | None) -> str:
    """Normalised text used for 'contains' searching."""
    return _NON_ALNUM.sub(" ", fold(value)).strip()


def match_key(name: str | None) -> str:
    """Key used to decide whether two records are the same title.

    Ignores case, punctuation, bracketed qualifiers like "(Widescreen)"
    and a leading "The"/"A"/"An".
    """
    s = _BRACKETS.sub(" ", fold(name))
    s = _NON_ALNUM.sub(" ", s).strip()
    s = _ARTICLE.sub("", s)
    s = _LEADING_SERIES.sub("", s)
    stripped = _TRAILING_EDITION.sub("", s).strip()
    return stripped or s


def sort_name(name: str | None) -> str:
    """Sort key: case-insensitive, ignoring a leading article."""
    s = fold(name).strip()
    return _ARTICLE.sub("", s)


def tokens(query: str | None) -> list[str]:
    return [t for t in search_norm(query).split(" ") if t]


def matches(haystack_norm: str, query_tokens: list[str]) -> bool:
    return all(t in haystack_norm for t in query_tokens)


# ---------------------------------------------------------------- barcodes

def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def barcode_key(value: str | None) -> str:
    """Comparable form of a barcode: digits only, leading zeros removed.

    This makes a 12-digit UPC-A ("043396269514") and the 13-digit EAN-13
    a phone camera may report ("0043396269514") compare equal.
    """
    return digits_only(value).lstrip("0")


def looks_like_barcode_query(query: str) -> bool:
    q = query.strip()
    return bool(re.fullmatch(r"[\d\s-]{6,}", q))


def upc_a_valid(code: str) -> bool:
    if not re.fullmatch(r"\d{12}", code):
        return False
    d = [int(c) for c in code]
    return (sum(d[0:11:2]) * 3 + sum(d[1:11:2]) + d[11]) % 10 == 0


def ean13_valid(code: str) -> bool:
    if not re.fullmatch(r"\d{13}", code):
        return False
    d = [int(c) for c in code]
    return (sum(d[0:12:2]) + sum(d[1:12:2]) * 3 + d[12]) % 10 == 0


def slugify(label: str) -> str:
    s = _NON_ALNUM.sub("_", fold(label)).strip("_")
    return s or "field"
