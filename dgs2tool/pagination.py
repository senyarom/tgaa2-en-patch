"""Paginate translated 3DS dialogue without changing its visible wording.

TGAA's normal top-screen dialogue box only has room for two lines with the
Latin font used by the English patch.  The official PC scripts can contain
three-line pages.  A translated page can safely be split by closing it with
E023/PAGE and reopening the same speaker with E041; Scarlet Study uses the
same no-E800 continuation form in its hand-authored 3DS scripts.
"""

from __future__ import annotations

import re


TAG_RE = re.compile(r"<[^>]*>")
PAGE_RE = re.compile(r"<PAGE>")
NEWLINE_RE = re.compile(r"\r\n|\n|\r")
SPEAKER_RE = re.compile(r"<E041(?:\s[^>]*)?>")
TRACKING_RE = re.compile(r"<E025(?:\s[^>]*)?>")
SENTENCE_END_RE = re.compile(r"(?:[.!?]|\.{3})[\"')\]]*$")


def _segments(text: str) -> list[str]:
    result: list[str] = []
    start = 0
    for match in PAGE_RE.finditer(text):
        result.append(text[start : match.end()])
        start = match.end()
    result.append(text[start:])
    return result


def visible_text(text: str) -> str:
    return TAG_RE.sub("", text)


def _first_visible_offset(text: str) -> int | None:
    in_tag = False
    for index, character in enumerate(text):
        if character == "<":
            in_tag = True
        elif character == ">":
            in_tag = False
        elif not in_tag and not character.isspace():
            return index
    return None


def is_standard_dialogue_segment(segment: str) -> bool:
    """Return whether visible text is introduced by the normal E041 box."""
    first_visible = _first_visible_offset(segment)
    return first_visible is not None and bool(
        SPEAKER_RE.search(segment, 0, first_visible)
    )


def _visible_lines(segment: str) -> list[dict]:
    """Return non-empty visible lines and their following raw newline."""
    lines: list[dict] = []
    cursor = 0
    for newline in list(NEWLINE_RE.finditer(segment)) + [None]:
        end = newline.start() if newline is not None else len(segment)
        raw = segment[cursor:end]
        visible = visible_text(raw).strip()
        if visible:
            lines.append(
                {
                    "visible": visible,
                    "raw_start": cursor,
                    "raw_end": end,
                    "newline_start": newline.start() if newline is not None else None,
                    "newline_end": newline.end() if newline is not None else None,
                    "newline": newline.group() if newline is not None else None,
                }
            )
        cursor = newline.end() if newline is not None else len(segment)
    return lines


def dialogue_page_line_counts(text: str) -> list[int]:
    return [len(_visible_lines(segment)) for segment in _segments(text) if visible_text(segment).strip()]


def _active_emphasis(text: str) -> bool:
    active = False
    for tag in TAG_RE.findall(text):
        if tag == "<E006>":
            active = True
        elif tag == "<E005>":
            active = False
    return active


def _sentence_ends(line: str) -> bool:
    return bool(SENTENCE_END_RE.search(line.rstrip()))


def _split_boundary(segment: str, lines: list[dict], maximum_lines: int) -> tuple[int, dict]:
    candidates: list[tuple[tuple[int, int, int], int, dict]] = []
    upper = min(maximum_lines, len(lines) - 1)
    for line_count in range(1, upper + 1):
        line = lines[line_count - 1]
        if line["newline_start"] is None:
            continue
        boundary = int(line["newline_start"])
        emphasis_split = _active_emphasis(segment[:boundary])
        score = (
            int(emphasis_split),
            int(not _sentence_ends(str(line["visible"]))),
            maximum_lines - line_count,
        )
        candidates.append((score, line_count, line))
    if not candidates:
        raise ValueError("overfull dialogue page has no safe line boundary")
    _score, line_count, line = min(candidates, key=lambda candidate: candidate[0])
    return line_count, line


def _continuation_styles(segment: str, speaker_end: int, boundary: int, continuation: str) -> list[str]:
    """Repeat renderer state that E041 resets at the start of a new page."""
    source = segment[speaker_end:boundary]
    visible_offset = _first_visible_offset(continuation)
    continuation_prefix = continuation[:visible_offset] if visible_offset is not None else continuation
    continuation_tags = TAG_RE.findall(continuation_prefix)
    source_tags = TAG_RE.findall(source)
    styles: list[str] = []

    tracking = next((tag for tag in reversed(source_tags) if TRACKING_RE.fullmatch(tag)), None)
    if tracking is not None and not any(TRACKING_RE.fullmatch(tag) for tag in continuation_tags):
        styles.append(tracking)

    mode = next((tag for tag in reversed(source_tags) if tag in {"<E007>", "<E008>"}), None)
    if mode is not None and not any(tag in {"<E007>", "<E008>"} for tag in continuation_tags):
        styles.append(mode)

    if _active_emphasis(source) and "<E006>" not in continuation_tags:
        styles.append("<E006>")
    return styles


def _is_subsequence(original: list[str], candidate: list[str]) -> bool:
    cursor = 0
    for tag in candidate:
        if cursor < len(original) and tag == original[cursor]:
            cursor += 1
    return cursor == len(original)


def _split_page(segment: str, maximum_lines: int) -> tuple[str, str, dict]:
    lines = _visible_lines(segment)
    if len(lines) <= maximum_lines:
        raise ValueError("dialogue page does not need pagination")

    first_visible = _first_visible_offset(segment)
    if first_visible is None:
        raise ValueError("overfull dialogue page has no visible text")
    speakers = list(SPEAKER_RE.finditer(segment, 0, first_visible))
    if not speakers:
        raise ValueError("overfull dialogue page has no E041 speaker command")
    speaker = speakers[-1]

    line_count, boundary_line = _split_boundary(segment, lines, maximum_lines)
    newline_start = int(boundary_line["newline_start"])
    newline_end = int(boundary_line["newline_end"])
    newline = str(boundary_line["newline"])
    continuation = segment[newline_end:]
    styles = _continuation_styles(segment, speaker.end(), newline_start, continuation)

    first = segment[:newline_start].rstrip(" \t") + "<E023><PAGE>"
    second = newline + speaker.group() + "".join(styles) + continuation
    replacement = first + second
    if visible_text(replacement) != visible_text(segment):
        raise ValueError("pagination changed visible dialogue text")
    if not _is_subsequence(TAG_RE.findall(segment), TAG_RE.findall(replacement)):
        raise ValueError("pagination dropped or reordered an original control tag")
    return first, second, {
        "original_lines": [line["visible"] for line in lines],
        "split_after_line": line_count,
        "continued_with": [speaker.group(), *styles],
    }


def paginate_dialogue_text(
    text: str,
    maximum_lines: int = 2,
    *,
    skip_without_speaker: bool = False,
    skip_tags: tuple[str, ...] = (),
) -> tuple[str, list[dict]]:
    """Split every dialogue page that exceeds ``maximum_lines``.

    The operation is idempotent: a second pass sees only pages at or below the
    limit and therefore makes no changes.  ``skip_without_speaker`` is useful
    for a mixed main-game script tree: E260/E521 text belongs to specialised
    court and deduction widgets, not the normal E041 dialogue box.
    """
    if maximum_lines < 1:
        raise ValueError("maximum_lines must be positive")

    output: list[str] = []
    reports: list[dict] = []
    for original_segment in _segments(text):
        pending = [original_segment]
        while pending:
            segment = pending.pop(0)
            line_count = len(_visible_lines(segment))
            if not visible_text(segment).strip() or line_count <= maximum_lines:
                output.append(segment)
                continue
            has_speaker = is_standard_dialogue_segment(segment)
            if (skip_without_speaker and not has_speaker) or any(
                tag in segment for tag in skip_tags
            ):
                output.append(segment)
                continue
            first, second, report = _split_page(segment, maximum_lines)
            reports.append(report)
            output.append(first)
            pending.insert(0, second)

    replacement = "".join(output)
    if visible_text(replacement) != visible_text(text):
        raise ValueError("pagination changed visible GMD text")
    return replacement, reports
