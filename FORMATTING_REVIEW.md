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
