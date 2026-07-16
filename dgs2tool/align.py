"""Create and apply an initial GMD label/index alignment."""

from __future__ import annotations

import copy


def _replace_terms(text: str | None, glossary: dict[str, str]) -> str | None:
    if text is None:
        return None
    for source, target in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, target)
    return text


def make_alignment(japanese: dict, english: dict, glossary: dict[str, str] | None = None) -> dict:
    glossary = glossary or {}
    english_by_label = {
        entry["label"]: entry for entry in english["entries"] if entry.get("label") is not None
    }
    aligned: list[dict] = []

    for index, source in enumerate(japanese["entries"]):
        label = source.get("label")
        match = None
        method = "unmatched"
        if label is not None and label in english_by_label:
            match = english_by_label[label]
            method = "label"
        elif index < len(english["entries"]):
            match = english["entries"][index]
            method = "index"

        candidate = _replace_terms(match.get("text") if match else None, glossary)
        aligned.append(
            {
                "index": index,
                "label": label,
                "match": method,
                "english_label": match.get("label") if match else None,
                "source_text": source.get("text"),
                "candidate_text": candidate,
                "reviewed": False,
            }
        )

    counts: dict[str, int] = {}
    for entry in aligned:
        counts[entry["match"]] = counts.get(entry["match"], 0) + 1
    return {"schema": 1, "format": "gmd-alignment", "summary": counts, "entries": aligned}


def apply_alignment(source: dict, alignment: dict, reviewed_only: bool = False) -> dict:
    result = copy.deepcopy(source)
    by_index = {int(entry["index"]): entry for entry in alignment["entries"]}
    for index, entry in enumerate(result["entries"]):
        aligned = by_index.get(index)
        if not aligned or aligned.get("candidate_text") is None:
            continue
        if reviewed_only and not aligned.get("reviewed"):
            continue
        entry["text"] = aligned["candidate_text"]
        entry["text_hex"] = entry["text"].encode("utf-8").hex()
    return result
