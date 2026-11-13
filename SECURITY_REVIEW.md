# Security review — 2026-11-13

## Scope and conclusion

Reviewed every tracked file in this small repository, plus the new OpenAI tests:
`pdf2reader.py`, `server.py`, `tex2text.py`, `requirements.txt`,
`pdf2reader.service`, `config.example.json`, `README.md`, `LICENSE`,
`.gitignore`, and `test_openai.py`.

No obvious malware, hidden telemetry, obfuscated payloads, credential harvesting,
or download-and-execute behavior was found in the reviewed source. **This is not
a guarantee of safety:** the upstream implementation has the risks below.
Dependencies were scanned for known advisories, not individually audited from
source; native PDF parsing and Pandoc were not fuzzed. Git history and external
services are outside the review scope.

## Unresolved findings

1. **Untrusted image references can read local files or trigger network fetches.**
   `pdf2reader.py:to_readwise` resolves image targets from model-generated Markdown
   without restricting them to the generated asset directory. Absolute paths and
   `../` paths can therefore be read and embedded in content sent to Readwise.
   EPUB generation also passes model Markdown to Pandoc without sandboxing or
   a resource allowlist. A malicious document could try to induce those references
   through prompt injection. Remove or validate all image targets against the
   generated figures before rendering/exporting; this has not been implemented.

2. **The optional web server lacks upload authentication and can fetch internal URLs.**
   `server.py:H.do_POST` accepts jobs without an authorization check. Both listeners
   bind to loopback, but a reverse proxy can expose them. The webhook secret is
   optional, and `fetch_pdf` allows HTTP(S) destinations and redirects without
   private-network filtering. Accessible callers could enqueue paid conversions
   or make server-side requests to internal services. URL downloads read at most
   200 MB + 1 byte but do not reject that overflow, and the job queue is unbounded.

3. **Existing output assets are recursively deleted.**
   `pdf2reader.py:main` removes the entire `<output-stem>_images` directory on a
   rerun, including unrelated files placed there. Markdown and EPUB outputs are
   also overwritten. Use a dedicated output directory until asset cleanup is
   restricted to files created by the converter.

4. **Readwise integration intentionally deletes remote content.**
   Successful webhook jobs delete the original Reader PDF. `--readwise-api
   --replace` deletes an existing document and its highlights. Email-stub cleanup
   deletes matching short email documents using a heuristic. These are documented
   features, not hidden malware, but they can cause data loss. They do not run in
   local `--epub` mode.

5. **Local data and configuration are trusted and persistent.**
   Rendered pages, text caches, uploaded PDFs and job logs persist locally.
   `gmail_token_command` executes a command from the user's configuration without
   a shell; it must remain trusted. macOS credential access is limited to the
   named `readwise-token` keychain entry. Dependency versions are not locked, so
   future installations may differ from the environment scanned here.

## Expected external communication

- User-supplied HTTP(S) PDF URLs and redirects for downloads.
- `https://api.openai.com/v1/responses`: rendered pages, text layers, and metadata
  prompts, authenticated using `OPENAI_API_KEY`. Model fixed to `gpt-6.1-sol`,
  reasoning effort omitted, `store=False`. No model tools are enabled.
- `readwise.io` and `gmail.googleapis.com` only for requested Reader integration.
- A configured Gmail token command may contact its own authentication service.
- Pandoc may resolve resources referenced by Markdown (see finding 1).

No API keys are embedded in source. Base64 use encodes page images and email
attachments; it is not an executable payload.

## Checks performed

- OpenAI SDK integration tests against a local HTTP stub: **4 passed**, covering
  image transport, fixed model/endpoint, default effort omission, metadata,
  incomplete output rejection, and API error reporting. No paid API calls made;
  actual account access to `gpt-6.1-sol` has not been verified.
- CLI help inspected: no provider/model selection flags remain.
- `git diff --check`: passed.
- Bandit scan of all three production Python files: 24 findings (1 high,
  8 medium, 15 low). The high finding is SHA-1 used for a cache identifier,
  not authentication. Other findings concern subprocesses, URL opening and broad
  exception handling; manually reviewed in context. The scan is not a clean bill
  of health and does not detect all findings above.
- `pip-audit` of the installed virtual environment initially flagged its bundled
  pip 25.1.1. Upgraded that local tool to 26.3 and rescanned:
  **no known vulnerabilities found** in the installed environment.

Local EPUB conversion needs further hardening for hostile input; the optional
server should not be treated as an authenticated public service.
