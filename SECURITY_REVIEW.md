# Security review and remediation — 2026-11-13

All source, configuration, documentation, and dependency declarations were reviewed.
No obvious malicious source was found. The risky optional features identified in the
original review have now been removed, and export handling has been hardened.

## Changes

| Original finding | Resolution |
|---|---|
| Local file access/network fetches through model-generated image references | Parse Markdown into a Pandoc AST; accept only exact `FIG_k` IDs from the page's own extracted figures. Embed trusted PNG bytes in EPUB. Never open model-provided paths. |
| Active raw content or arbitrary attributes in document output | Disable raw HTML/TeX parsing, remove residual raw nodes, strip links and document-supplied attributes. LaTeX math remains supported via MathML. |
| Pandoc resolving arbitrary resources | Run every Pandoc invocation with `--sandbox`, pass document data through stdin, and embed allowlisted image bytes before EPUB export. |
| Unauthenticated upload/webhook server and server-side URL fetching | Remove the server, service unit, URL download support and all networking except OpenAI requests. |
| Readwise/Gmail credential use and remote deletion | Remove all Reader/Gmail integration, keychain access and token-command configuration. |
| Recursive output-directory deletion and overwriting | Require a new output directory and write with exclusive file creation. No cleanup or deletion of existing outputs. |
| Uncontrolled persistent PDF/text/image caches | Full-page rasterizations use temporary directories cleaned up on completion or exceptions. At the user's request, completed AI responses and extracted figures persist in private resumable checkpoint directories with atomic writes. No uploaded-job storage. |
| Unpinned dependency resolution | Pin direct and transitive dependencies in `requirements.lock`; remove unused google-auth dependency. |
| Weak cache identifier | Replace SHA-1 with SHA-256 over PDF content and conversion settings for resumable AI checkpoints. |
| Concurrent PyMuPDF access | Render pages in separate worker processes rather than threads, keeping parallel API processing. |

## Expected access

- Read the local PDF selected by the user.
- Read `OPENAI_API_KEY` and the OpenAI SDK's normal environment configuration.
- Send page images/text and a metadata prompt to the official OpenAI Responses API,
  using only `gpt-6.1-sol`, default reasoning effort, and `store=False`.
- Run the installed Pandoc executable with fixed options and sandboxing.
- Write temporary files, private resumable AI checkpoints and a new output directory.

## Verification results

- Seven tests passed, including real SDK requests to a local stub, PDF rasterization,
  malformed resource references, EPUB contents, failed-page resume, and a simulated
  EPUB export failure followed by a rerun with **zero repeated AI calls**.
- `pip-audit -r requirements.lock`: no known vulnerabilities found.
- Bandit: no high/medium findings; two low findings for importing subprocess and
  calling Pandoc. The call uses fixed arguments, sandboxing, and no shell.
- `git diff --check`: passed.

## Remaining limits

This is not a proof that all inputs or dependencies are harmless. Native PDF parsing
and the installed Pandoc binary are trusted dependencies, not individually audited
or fuzzed here. Keep them updated. Very large or malformed PDFs can still consume
substantial memory, CPU, or API budget. A forced process kill or power loss can
prevent temporary-directory cleanup. Final outputs and resumable AI checkpoints
intentionally persist. Checkpoints are trusted local data, not an encrypted store;
they must not be shared with untrusted writers.

The SDK integration and conversion tests use stubbed model responses. No live paid
conversion or account access to `gpt-6.1-sol` has been verified. `store=False` is an
API request setting, not a claim about all server-side retention policies.
