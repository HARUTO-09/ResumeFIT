"""Remove contact details before text is logged, stored or sent to a model.

These are heuristics, not guarantees: emails, phone numbers and links are
caught by pattern; the name and address are taken from the resume header
(the lines above the first section heading). See the README for limits.
"""

import re
from dataclasses import dataclass, field

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(
    r"(?:https?://|www\.)\S+|\b(?:linkedin\.com|github\.com|gitlab\.com)/\S+", re.IGNORECASE
)
PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
PIN_CODE = re.compile(r"\b\d{3}\s?\d{3}\b")
ADDRESS_WORDS = re.compile(
    r"\b(street|st\.|road|rd\.|nagar|colony|lane|avenue|apartment|apt|flat|floor|"
    r"block|sector|district|village|post|pincode|pin code|house no|h\.no|door no)\b",
    re.IGNORECASE,
)


@dataclass
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def find_name(header: str) -> str | None:
    """The first header line that looks like a person's name (2 to 4 words, letters only)."""
    for line in header.splitlines()[:5]:
        candidate = line.strip()
        words = candidate.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words):
            return candidate
    return None


def _phone_sub(match: re.Match) -> str:
    digits = sum(ch.isdigit() for ch in match.group())
    return "[PHONE]" if 10 <= digits <= 15 else match.group()


def redact(text: str, header: str | None = None) -> Redaction:
    """Return text with email, phone, links, name and address lines replaced."""
    counts: dict[str, int] = {}

    def sub(pattern: re.Pattern, repl, label: str, value: str) -> str:
        out, _ = pattern.subn(repl, value)
        token = f"[{label.upper()}]"
        n = out.count(token) - value.count(token)
        if n:
            counts[label] = counts.get(label, 0) + n
        return out

    name = find_name(header) if header else None
    address_lines = set()
    if header:
        for line in header.splitlines():
            if line.strip() and (ADDRESS_WORDS.search(line) or PIN_CODE.search(line)):
                address_lines.add(line.strip())

    lines = []
    for line in text.splitlines():
        if line.strip() in address_lines:
            counts["address"] = counts.get("address", 0) + 1
            lines.append("[ADDRESS]")
        else:
            lines.append(line)
    out = "\n".join(lines)

    out = sub(EMAIL, "[EMAIL]", "email", out)
    out = sub(URL, "[URL]", "url", out)
    out = sub(PHONE, _phone_sub, "phone", out)
    if name:
        pattern = re.compile(r"\s+".join(re.escape(w) for w in name.split()), re.IGNORECASE)
        out = sub(pattern, "[NAME]", "name", out)
    return Redaction(text=out, counts=counts)
