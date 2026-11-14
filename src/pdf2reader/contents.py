"""Locate printed contents sections so EPUB navigation does not duplicate them."""

import re

CONTENTS_TITLE = re.compile(r"(?:table\s+of\s+contents|contents)", re.I)


def printed_contents_pages(doc):
    """Use explicit PDF outline boundaries, with a conservative text fallback."""
    result = set()
    outline = doc.get_toc()
    for index, (level, title, start) in enumerate(outline):
        if not CONTENTS_TITLE.fullmatch(title.strip()) or start < 1:
            continue
        end = next((page for depth, _, page in outline[index + 1:]
                    if depth <= level and page >= start), None)
        # Without an explicit end, do not assume the rest of the book is a TOC.
        if end is not None and end > start:
            result.update(range(start, min(end, len(doc) + 1)))
    if result:
        return result

    for number, page in enumerate(doc, 1):
        lines = [line.strip() for line in page.get_text().splitlines() if line.strip()]
        has_title = any(CONTENTS_TITLE.fullmatch(line) for line in lines)
        leaders = sum(bool(re.search(r"\.{4,}", line)) for line in lines)
        numbered_entries = sum(bool(re.search(r"\S.*\s[•–—]\s*\d+\s*$", line)) for line in lines)
        if has_title and (leaders >= 2 or numbered_entries >= 3):
            result.add(number)
    return result
