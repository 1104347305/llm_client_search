import re
from dataclasses import dataclass
from typing import Optional

from models.field_mapping import get_name_candidate_values


PURE_CHINESE_RE = re.compile(r"^[\u4e00-\u9fa5]+$")


@dataclass(frozen=True)
class NameCandidate:
    text: str
    is_candidate: bool
    confidence: float
    surname: Optional[str] = None
    reason: str = ""
    needs_verification: bool = True


@dataclass(frozen=True)
class NameCandidateConfig:
    common_surnames: frozenset[str]
    compound_surnames: tuple[str, ...]
    business_blacklist: frozenset[str]
    business_suffixes: tuple[str, ...]


def load_name_candidate_config() -> NameCandidateConfig:
    return NameCandidateConfig(
        common_surnames=frozenset(get_name_candidate_values("common_surnames")),
        compound_surnames=tuple(get_name_candidate_values("compound_surnames")),
        business_blacklist=frozenset(get_name_candidate_values("business_blacklist")),
        business_suffixes=tuple(get_name_candidate_values("business_suffixes")),
    )


def looks_like_full_person_name(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 2 or len(text) > 4:
        return False
    if not PURE_CHINESE_RE.fullmatch(text):
        return False

    cfg = load_name_candidate_config()
    for surname in cfg.compound_surnames:
        if text.startswith(surname):
            return len(text) >= len(surname) + 1
    return text[0] in cfg.common_surnames


def detect_name_candidate(text: str) -> NameCandidate:
    text = (text or "").strip()

    if not text:
        return NameCandidate(text, False, 0.0, reason="empty")

    if not PURE_CHINESE_RE.fullmatch(text):
        return NameCandidate(text, False, 0.0, reason="not_pure_chinese")

    cfg = load_name_candidate_config()

    if text in cfg.business_blacklist:
        return NameCandidate(text, False, 0.0, reason="business_blacklist")

    if any(text.endswith(suffix) for suffix in cfg.business_suffixes):
        return NameCandidate(text, False, 0.0, reason="business_suffix")

    for surname in cfg.compound_surnames:
        if text.startswith(surname):
            if len(text) in (3, 4):
                return NameCandidate(
                    text=text,
                    is_candidate=True,
                    confidence=0.82,
                    surname=surname,
                    reason="compound_surname_match",
                )
            return NameCandidate(text, False, 0.0, reason="compound_surname_bad_length")

    if len(text) not in (2, 3):
        return NameCandidate(text, False, 0.0, reason="bad_length")

    if text[0] not in cfg.common_surnames:
        return NameCandidate(text, False, 0.0, reason="surname_not_match")

    return NameCandidate(
        text=text,
        is_candidate=True,
        confidence=0.72 if len(text) == 2 else 0.78,
        surname=text[0],
        reason="single_surname_match",
    )
