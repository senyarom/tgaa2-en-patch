"""Keep TGAA1's centred 3DS location captions inside the top screen.

The captions are a special two-line layout (date plus location), so ordinary
dialogue reflow must not add another line.  The official English names that do
not fit are instead replaced with concise equivalents.
"""

from __future__ import annotations

import re


CONCISE_LOCATION_NAMES = {
    "Supreme Court of Judicature, Courtroom No. 2":
        "Supreme Court, Courtroom No. 2",
    "Supreme Court of Judicature, Defendants' Antechamber 5":
        "Supreme Court, Defendants' Antechamber 5",
    "British Supreme Court, Lord Chief Justice's Office":
        "Supreme Court, Lord Chief Justice's Office",
}

# Issues 1-8 use this layout.
STANDARD_CAPTION_RE = re.compile(
    r"(?P<prefix><CNTR><E008><E025 7\.5><E003 10>)"
    r"(?P<date>[^<>\r\n]+)\r\n"
    r"(?P<location_prefix><CNTR><E003 5>)"
    r"(?P<location>[^<>\r\n]+)"
    r"(?P<suffix><E023>)"
)

# The special issue (issue 0) uses a different sequence around the same text.
SPECIAL_CAPTION_RE = re.compile(
    r"(?P<prefix><CNTR><E008><E025 8><E003 10><E042><CNTR><E008>)"
    r"(?P<date>[^<>\r\n]+)\r\n"
    r"(?P<location>[^<>\r\n]+)"
    r"(?P<suffix><CNTR><E003 5><E042><CNTR><E023>)"
)


def caption_width(text: str, widths: dict[int, int], fallback: int = 18) -> int:
    return sum(widths.get(ord(character), fallback) for character in text)


def compact_location_captions(
    text: str,
    widths: dict[int, int],
    maximum: int,
) -> tuple[str, list[dict]]:
    """Shorten detected location captions that exceed ``maximum`` pixels."""
    reports: list[dict] = []

    def replace(match: re.Match[str]) -> str:
        location = match.group("location")
        original_width = caption_width(location, widths)
        replacement = location
        method = "unchanged"
        if original_width > maximum:
            replacement = CONCISE_LOCATION_NAMES.get(location, location)
            method = "concise_location_name" if replacement != location else "unresolved"
        replacement_width = caption_width(replacement, widths)
        status = "reflowed" if replacement != location else "ok"
        if replacement_width > maximum:
            status = "overflow"
        reports.append(
            {
                "status": status,
                "original_widths": [original_width],
                "new_widths": [replacement_width],
                "text": replacement,
                "original_text": location,
                "layout": "location_caption",
                "method": method,
            }
        )
        if replacement == location:
            return match.group(0)
        start, end = match.span("location")
        relative_start = start - match.start()
        relative_end = end - match.start()
        raw = match.group(0)
        return raw[:relative_start] + replacement + raw[relative_end:]

    result = text
    for pattern in (STANDARD_CAPTION_RE, SPECIAL_CAPTION_RE):
        result = pattern.sub(replace, result)
    return result, reports
