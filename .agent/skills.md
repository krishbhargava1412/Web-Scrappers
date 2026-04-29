# Web Scrapper Development Skill

Use this guidance when adding, changing, or reviewing code in this repository. The project is a collection of Python scraper/downloader tools with a shared desktop launcher in `scraper_hub.py`.

## Project Shape

- Keep each scraper usable as a direct CLI script from its own folder.
- Keep `scraper_hub.py` as an orchestration layer only: it should collect UI inputs, build command arguments, set the working directory, launch subprocesses, stream logs, and stop/open outputs.
- Do not move site-specific scraping logic into the hub.
- Prefer the more modular `Influencer_Marketing_Scrapper/influencer_marketing_scrapper/` style for new larger features: `cli.py`, config loading, HTTP/client helpers, extraction logic, pipeline orchestration, and data models.
- For smaller existing scripts, improve them incrementally without forcing a full rewrite.
- Preserve existing folder names, including the current `Scrapper` spelling, unless the user explicitly asks for a rename.

## Test-Driven Workflow

Follow TDD for new behavior and bug fixes:

1. Write or update a failing test that describes the desired behavior.
2. Run the smallest relevant test command and confirm the failure is about the intended behavior.
3. Implement the minimal production change needed to pass.
4. Run the relevant tests again.
5. Refactor only after tests pass, keeping behavior covered.

If a test framework is not yet present for the touched area, add focused `pytest` tests under a local `tests/` folder or a nearby test module. Prefer introducing `pytest` over ad hoc executable test scripts for new coverage.

Good first test targets:

- CLI argument parsing and validation.
- Command construction in `scraper_hub.py`.
- URL/query construction.
- HTML parsing from saved fixtures.
- CSV/JSON output formatting.
- Deduplication, normalization, filtering, and retry decision logic.

Avoid live network, real browser, login, CAPTCHA, and rate-limit dependencies in unit tests. Use fixtures, fakes, monkeypatching, or small local HTML samples instead.

## Architecture Rules

- Keep boundaries clear:
  - `cli` parses arguments and converts them into typed settings.
  - `http` or browser helpers fetch pages/data and own retry, timeout, proxy, delay, and user-agent behavior.
  - `extractors` parse HTML/JSON into structured records.
  - `pipeline` coordinates fetch, parse, dedupe, and output.
  - `models` define dataclasses or typed records.
  - `scraper_hub.py` builds commands and displays process output.
- New scraper modules should expose a `main() -> int` or equivalent command entrypoint and guard execution with `if __name__ == "__main__":`.
- Prefer dataclasses for scraper records so CSV/JSON writers have explicit fields.
- Keep output paths configurable through CLI flags and default them to the current project conventions.
- Use `pathlib.Path` for filesystem paths.
- Use `logging` for scraper progress and warnings. Reserve `print` for final CLI summaries or user-facing command output.
- Keep generated CSVs, JSONL files, logs, downloads, browser profiles, and result folders out of Git.

## Hub Integration

When adding or changing a tool in `scraper_hub.py`:

- Add or update a tab builder only for UI state and layout.
- Add or update a command builder that returns `(command: list[str], cwd: Path)`.
- Validate required fields before launching a subprocess and raise `ValueError` with a clear message.
- Use `sys.executable` as the Python executable.
- Pass repeated user entries as repeated CLI flags, matching the existing `--query value --query value` pattern.
- Keep command lists structured; do not build shell strings for execution.
- Update README examples when hub behavior or CLI flags change.
- Add tests for command construction where practical by instantiating the hub without launching subprocesses or by extracting pure command-building helpers.

## Scraper Implementation

- Prefer `requests.Session` for static pages and Playwright only when JavaScript rendering or browser-level interception is required.
- Keep request delays, retries, timeouts, proxy use, and headed/headless mode configurable.
- Detect blocking/CAPTCHA cases and fail gracefully with a warning instead of crashing.
- Keep parsing functions pure where possible: input HTML/JSON, output dataclasses/lists.
- Normalize text, URLs, currencies, dates, and IDs close to the extractor layer.
- Include enough source metadata in output rows to debug results later, such as query, region, platform, source URL, timestamp, or page title.
- Do not hard-code secrets, cookies, proxy credentials, or account-specific data. Use `.env`, CLI flags, or ignored local files.

## Testing Patterns

- Put small HTML fixtures near tests, for example `tests/fixtures/amazon_search.html`.
- Monkeypatch network methods such as `session.get`, Playwright page calls, or project HTTP clients.
- Use `tmp_path` for output files and assert generated CSV/JSON contents.
- For retry and delay logic, monkeypatch sleep/random functions so tests stay fast.
- For hub tests, assert command lists and working directories, not actual subprocess execution.
- Keep one live/manual smoke script only when a site requires real browser validation, and label it clearly as manual. Do not treat it as the main test strategy.

## README And Docs

- Update `README.md` whenever commands, flags, setup steps, outputs, or supported sites change.
- Keep examples copy-pasteable from the project root or clearly show the required `cd`.
- Document generated output names and any known site limitations.
- Mention headed mode requirements for sites that are likely to block headless browsers.

## Definition Of Done

Before finishing a code change:

- The relevant failing test has been added or updated first.
- The relevant tests pass.
- CLI usage still works directly for the changed scraper.
- Hub command wiring is updated if the user-facing workflow changed.
- README/docs are updated if behavior, setup, or outputs changed.
- Generated outputs and local browser/session artifacts are not added to Git.
