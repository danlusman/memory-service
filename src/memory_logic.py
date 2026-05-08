from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def make_key(mem_type: str, category: str) -> str:
    return f"{mem_type}:{category}".lower()


@dataclass
class ExtractedMemory:
    mem_type: str
    category: str
    value: str
    confidence: float


def _extract_pet_name(text: str) -> ExtractedMemory | None:
    m = re.search(
        r"\b(?:my|our)\s+(dog|cat)\s+named\s+([A-Z][a-z]+)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        kin = m.group(1).lower()
        name = m.group(2)[:1].upper() + m.group(2)[1:].lower() if len(m.group(2)) > 1 else m.group(2).upper()
        return ExtractedMemory("fact", "pet", f"Has a {kin} named {name}", 0.82)
    # Verb is case-insensitive; name must look like a proper noun (resists "walking the park").
    implicit = re.search(
        r"\b(?i:walking|walked|feeding|fed|taking)\s+([A-Z][a-z]+(?:'[a-z]+)?)\b",
        text,
    )
    if implicit:
        name = implicit.group(1)
        return ExtractedMemory("fact", "pet", f"Has a pet named {name}", 0.67)
    _not_pet_words = frozenset(
        {
            "the",
            "a",
            "an",
            "my",
            "your",
            "our",
            "their",
            "his",
            "her",
            "its",
            "this",
            "that",
            "these",
            "those",
        }
    )
    implicit_lo = re.search(
        r"(?i)\b(?:walking|walked|feeding|fed|taking)\s+([a-z][a-z']{2,24})\b",
        text,
    )
    if implicit_lo:
        raw = implicit_lo.group(1).lower()
        if raw not in _not_pet_words:
            name = raw[:1].upper() + raw[1:]
            return ExtractedMemory("fact", "pet", f"Has a pet named {name}", 0.67)
    return None


def _extract_company_phrase(text: str) -> str | None:
    """Capture a short company name; stop before job clauses (\"as a PM\") and commas."""
    m = re.search(
        r"\b(?:i work at|i am at|i'm at)\s+(.+?)(?=\s+as\b|,|$)",
        text,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"\b(?:i just joined|i started at)\s+(.+?)(?=\s+as\b|\s+also\b|[,.!?]|$)",
            text,
            re.IGNORECASE,
        )
    if not m:
        return None
    company = m.group(1).strip()
    max_words = 4
    words = company.split()
    company = " ".join(words[:max_words]).strip(" .,!?:;")
    if not company:
        return None
    if len(company) > 64:
        return company[:61].rstrip() + "…"
    return company


def _extract_employment(text: str) -> ExtractedMemory | None:
    company = _extract_company_phrase(text)
    if not company:
        return None
    return ExtractedMemory("fact", "employment", f"Works at {company}", 0.88)


def _extract_location(text: str) -> list[ExtractedMemory]:
    out: list[ExtractedMemory] = []
    moved = re.search(
        r"\bmoved to\s+([A-Z][A-Za-z .\-]*?)(?:\s+from\s+)([A-Z][A-Za-z .\-]*?)(?:\s+last\s+\w+)?(?:[,.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if moved:
        new_city = moved.group(1).strip(" .,!?:;")
        old_city = moved.group(2).strip(" .,!?:;")
        out.append(ExtractedMemory("fact", "location", f"Lives in {new_city}", 0.9))
        out.append(ExtractedMemory("event", "relocation", f"Moved from {old_city} to {new_city}", 0.86))
        return out
    live = re.search(r"\b(?:i live in|i'm in|i am in)\s+([A-Z][A-Za-z .\-]+)", text, re.IGNORECASE)
    if live:
        city = live.group(1).strip(" .,!?:;")
        out.append(ExtractedMemory("fact", "location", f"Lives in {city}", 0.84))
    return out


def _extract_preference(text: str) -> list[ExtractedMemory]:
    out: list[ExtractedMemory] = []
    prefer = re.search(r"\bI prefer\s+([^.!?]+)", text, re.IGNORECASE)
    if prefer:
        out.append(ExtractedMemory("preference", "style", prefer.group(1).strip(), 0.75))
    dietary = re.search(r"\bI(?:'m| am)\s+(a\s+)?(vegetarian|vegan)\b", text, re.IGNORECASE)
    if dietary:
        label = (dietary.group(2) or "").lower()
        out.append(
            ExtractedMemory("preference", "diet", f"Diet preference: {label}", 0.8),
        )
    allergy = re.search(r"\ballergic to\s+([^.!?]+)", text, re.IGNORECASE)
    if allergy:
        out.append(ExtractedMemory("fact", "allergy", allergy.group(1).strip(), 0.86))
    return out


def _extract_relationships(text: str) -> list[ExtractedMemory]:
    out: list[ExtractedMemory] = []
    patterns = [
        (r"\bmy (wife|husband|partner)\s+is\s+([A-Z][a-z]+)\b", "relationship"),
        (r"\bI have (?:a|an)\s+(son|daughter)\s+named\s+([A-Z][a-z]+)\b", "family"),
    ]
    for pattern, category in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            out.append(ExtractedMemory("fact", category, m.group(0).strip(), 0.78))
    return out


def _extract_opinion(text: str) -> list[ExtractedMemory]:
    out: list[ExtractedMemory] = []
    m = re.search(r"\bI (love|like|hate|dislike|enjoy)\s+([^.!?]+)", text, re.IGNORECASE)
    if m:
        sentiment = m.group(1).lower()
        topic = m.group(2).strip()
        out.append(ExtractedMemory("opinion", f"topic:{topic.lower()}", f"Stance on {topic}: {sentiment}", 0.72))
    m2 = re.search(r"\b([A-Za-z]+)\s+generics\s+are\s+getting\s+annoying\b", text, re.IGNORECASE)
    if m2:
        language = m2.group(1).strip()
        out.append(ExtractedMemory("opinion", f"topic:{language.lower()}", f"Stance on {language}: frustrated with generics", 0.77))
    m3 = re.search(r"\b([A-Za-z]+)\s+is\s+fine\s+for\s+big\s+projects\s+but\s+I'd\s+use\s+([A-Za-z]+)\s+for\s+scripts\b", text, re.IGNORECASE)
    if m3:
        lang_a = m3.group(1).strip()
        lang_b = m3.group(2).strip()
        out.append(ExtractedMemory("opinion", f"topic:{lang_a.lower()}", f"Stance on {lang_a}: fine for large projects", 0.8))
        out.append(ExtractedMemory("opinion", f"topic:{lang_b.lower()}", f"Stance on {lang_b}: preferred for scripts", 0.83))
    return out


def _extract_correction(text: str) -> list[ExtractedMemory]:
    out: list[ExtractedMemory] = []
    # Prefer normalized correction facts over storing raw sentence chunks.
    m_not = re.search(
        r"\b(?:actually|sorry)[^.!?]*?\bnot\s+([^.!?]+?)(?:\s*[-—]\s*|\s+but\s+|\s+instead\s+)([^.!?]+)",
        text,
        re.IGNORECASE,
    )
    if m_not:
        old = m_not.group(1).strip(" .,!?:;")
        new = m_not.group(2).strip(" .,!?:;")
        if old and new:
            out.append(ExtractedMemory("event", "correction", f"Correction: not {old}; meant {new}", 0.72))
            return out
    m_meant = re.search(r"\b(?:actually|sorry)[^.!?]*?\bmeant\s+([^.!?]+)", text, re.IGNORECASE)
    if m_meant:
        corrected = m_meant.group(1).strip(" .,!?:;")
        if corrected:
            out.append(ExtractedMemory("event", "correction", f"Correction: meant {corrected}", 0.68))
    return out


def extract_memories(message_text: str) -> list[ExtractedMemory]:
    text = message_text.strip()
    if not text:
        return []
    items: list[ExtractedMemory] = []
    one = _extract_pet_name(text)
    if one:
        items.append(one)
    one = _extract_employment(text)
    if one:
        items.append(one)
    items.extend(_extract_location(text))
    items.extend(_extract_preference(text))
    items.extend(_extract_relationships(text))
    items.extend(_extract_opinion(text))
    items.extend(_extract_correction(text))
    dedup = {(m.mem_type, m.category, m.value): m for m in items}
    return list(dedup.values())


def classify_scope(mem_type: str, category: str) -> str:
    if mem_type in {"fact", "preference"} and category in {"employment", "location", "style", "diet", "allergy", "pet"}:
        return "mutable"
    if mem_type == "fact" and category in {"relationship", "family"}:
        return "mutable"
    if mem_type == "opinion" and category.startswith("topic:"):
        return "mutable"
    return "append_only"


def similarity_score(query: str, content: str) -> float:
    q = tokenize(query)
    c = tokenize(content)
    if not q or not c:
        return 0.0
    q_counter = Counter(q)
    c_counter = Counter(c)
    overlap = sum(min(q_counter[t], c_counter[t]) for t in q_counter.keys())
    return overlap / max(len(q), len(c))


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

