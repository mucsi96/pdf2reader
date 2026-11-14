# EPUB formatting review — 2026-11-14

Source: *30 Agents Every AI Engineer Must Build*, 542 physical PDF pages.
Page numbers below are PDF positions, not the printed book page numbers.

## Sample and results

| PDF pages | Features checked | Result |
|---|---|---|
| 32 | Block quotation, italic attribution, bold phrases | Semantic quotation and emphasis retained |
| 35–36 | Diagrams, captions, bullets, bold/italic text | Original raster crops retained, scaled to the reader width; printed captions retained |
| 37–38 | Numbered steps with Python listings; code continuing across a PDF page boundary | Code characters and indentation retained; list starts 1 and 4 preserved; continued listing remains in separate blocks |
| 72 | Inline identifier and Python block | Inline monospace retained; code parses as Python without execution |
| 115 | Full-page Python listing, long strings, comments | Searchable code instead of a duplicated screenshot; code parses without execution |
| 134 | Two-column table, inline library name, Python listing | All table cells retained; code parses without execution |
| 138 | Four-column and three-column tables | All visible table cells retained, including risk levels |

## Fixes made

- Exclude code backgrounds and detected text tables from figure extraction.
- Preserve genuine code fences; unwrap only explicitly labelled Markdown wrappers.
- Preserve a bounded set of code language labels while stripping arbitrary attributes.
- Ask for explicit code, emphasis, quotations, and list numbering in page conversion.
- Use plain semantic EPUB code instead of syntax-highlighter line spans. The latter
  produced clipped lines and large blank gaps in the tested EPUB renderer.
- Add bundled e-reader CSS for code wrapping, table borders, images and lists.
  Use `overflow-wrap: break-word` rather than `anywhere`, which the tested renderer
  did not support for long unbroken code tokens.
- Avoid turning image alt text into an extra displayed caption; keep printed captions.
- Add `--refresh-pages` for selective, atomic replacement of saved page conversions.

## Verification

The nine source pages were rendered and visually compared with reflowed EPUB pages.
The sample was regenerated with fresh AI responses, then rebuilt from those responses
as rendering issues were corrected. Both 320×650 and 450×650 layouts at a 12-point
base font passed word-boundary clipping checks in MuPDF. Source code was compared
with monospace PDF text after whitespace normalization, with indentation also
visually inspected. Table comparisons excluded invisible PDF `idx_*` index markers.

This is a representative sample, not a full-book certification. MuPDF was the
rendering engine; the result has not been tested on a physical KOReader device.
Code split across source pages remains split into code blocks rather than inventing
or inferring missing code. Other saved pages can retain older model responses until
explicitly refreshed; export-time styling improvements apply on every rebuild.

Local artifacts:

- Final sample: `/tmp/opencode/format-review/final-output/book.epub`
- Per-page screenshots and JSON audit: `/tmp/opencode/format-review/final-output/inspection/`
- Before-fix sample: `/tmp/opencode/format-review/before-output/book.epub`

The full-book job was stopped when checked: pages 1–229 were checkpointed, and no
full-book output existed. Its recorded estimate was $2.8402375 before this review.
The review added $0.114027, including sample metadata; the new cumulative estimate is
$2.9542645. These figures use recorded API token usage and the configured prices.

## KOReader spine compatibility follow-up

The first 100-page EPUB failed in KOReader with `Failed handling EPUB spine item
'EPUB/text/title_page.xhtml'`. ElementTree had rewritten XHTML tags with namespace
prefixes (`html:body`, etc.). Although valid XML and accepted by MuPDF, these tags
were not recognized by KOReader's HTML parser.

The exporter now preserves Pandoc's XHTML bytes and namespaces, inserting only the
trusted stylesheet link. OPF serialization uses its standard default namespace.
A regression test checks unprefixed HTML/body tags and preservation of all existing
markup, including MathML.

The failure was reproduced headlessly with the official KOReader v2026.07.1
`libkoreader-cre` engine. The rebuilt 100-page EPUB loaded with zero failed spine
items and 227,109 bytes of accessible book text. This verifies parsing in KOReader's
engine, not visual layout on a physical device. No AI requests were repeated.

Corrected local EPUB: `/home/mucsi/pdf2reader/agents-first-100-koreader-output/book.epub`.

## Native navigation only

The PDF outline identifies pages 8–21 as the printed contents section, ending at
the Preface on page 22. The EPUB now excludes those source pages and builds its
linked navigation from the actual included content. Markdown retains the source
contents pages.

Verified with KOReader v2026.07.1's actual engine: zero failed spine items, exactly
one contents heading in the loaded book, and 95 native TOC entries. Every entry's
XPointer resolved to a page and was navigated to with `gotoXPointer`. All 95 EPUB
navigation hrefs were also checked against their XHTML files and fragment IDs.
The rebuild reused checkpoints and incurred no additional model charges.

Latest sample: `/home/mucsi/pdf2reader/agents-first-100-native-toc-output/book.epub`.

## Page 26: GitHub URL typography

Compared the original PDF with screenshots rendered by KOReader's engine at 600×800.
The source uses Consolas at 8 points for the GitHub URLs versus Crimson Pro at 9.5
points for surrounding prose. The earlier conversion lost this distinction and
rendered both URLs in the body serif font.

Clarified the prompt to retain source URL typography using inline code for monospaced
URLs. Refreshed only page 26 and rebuilt the 100-page EPUB. Both exact GitHub URLs
are now `<code>` elements and visibly monospace in the KOReader screenshot. Verified
zero spine errors, one contents heading, and all 95 native TOC destinations again.
The page refresh added approximately $0.013091 in estimated API cost.

Screenshots: `work/page26-review/koreader-before-0.png` and
`work/page26-review/koreader-after-0.png`; original PDF rendering: `work/page26-review/original.png`.

Latest sample: `/home/mucsi/pdf2reader/agents-first-100-url-format-output/book.epub`.

## Random 20-page visual review

Selected 20 unique physical PDF pages using `secrets.SystemRandom().sample` from
all 542 pages. The saved selection is 22, 97, 105, 136, 154, 164, 247, 254, 312,
329, 368, 370, 372, 373, 374, 404, 405, 471, 504, 535.

Compared source PDF renders with actual KOReader v2026.07.1 CRE screenshots at
600×800, Noto Serif 20px. Each source page was exported separately through the
production sanitizer, Pandoc, and EPUB finalizer to make the comparison traceable.
Inspected the reflowed content screens, not just the initial title screen.
These inspection EPUBs have synthetic page-number titles; the combined sample does
not have those per-page inspection titles. This is headless rendering, not a device
or interactive UI test, and not a character-by-character transcription audit.

| PDF pages | Visual result |
| --- | --- |
| 22, 136, 247, 368 | Readable prose, heading hierarchy, emphasis, and lists. |
| 97 | Bullets and JSON readable; source ends partway through the JSON example. |
| 105, 164 | Diagrams retained and scaled; searchable descriptions also present. Small diagram labels remain less comfortable than body text. |
| 154, 254, 372–374, 471 | Monospace code readable without horizontal clipping; long lines wrap. Indented continuation lines are still less easy to follow than in the wide PDF. |
| 312 | Chapter heading, italic quotation, attribution, and bullets preserved. |
| 329, 504 | Diagrams/equations and surrounding text readable with font fallbacks. Page 504's repeated equation is also present in the source PDF. |
| 370 | Four-column table retains cells and borders across screens; readable but cramped, with frequent wrapping. Inline math renders. |
| 404–405 | Monospaced example boxes preserved as high-contrast bordered text, rather than the PDF's dark background. The example continues across the two source pages. |
| 535 | Two-column index becomes a readable single-column nested list. Original printed page references are retained, not converted into EPUB links. |

The review exposed overly aggressive `word-break: break-all` in code. Changed it
to normal word breaking while retaining overflow wrapping, and disabled automatic
hyphenation in code. Rebuilt and visually rechecked the affected code/text boxes;
identifiers now stay together where possible, without invented hyphens.

An initial harness-only problem displayed arrows and math as question marks.
Registering FreeSerif and configuring KOReader's FreeSans/FreeSerif fallback faces
resolved it. This did not require modifying the EPUB's equations.

Verdict: acceptable for general reading at this size, with reservations for dense
code and the four-column table; not a pixel-identical reproduction. No missing
figures or clipped content were observed in the inspected sample. Random selection
means many excerpts begin/end mid-sentence or mid-code, as in their source pages.

Evidence and repeatable local harness: `work/random-review/` (`sample.json`,
`source-N.png`, `koreader-N-S.png`, `review-N.png`, `build.py`, `render.lua`).
The combined EPUB also loaded without failed spine items and rendered all 63
screens to `combined-S.png`. All 27 tests pass. Additional estimated model cost
for this sample: $0.255304; subsequent formatting rebuilds reused checkpoints.

Reviewed sample: `/home/mucsi/pdf2reader/random-20-reviewed-output/book.epub`.
