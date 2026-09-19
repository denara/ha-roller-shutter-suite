# Rules for every work block

Every block file in this folder is the complete brief for exactly one agent. This file holds the rules that are the same for all of them. Read it first, then your block file, then the documents your block file lists under "Read first".

## Sources of truth

1. `docs/project-brief.md` — what is built and why. Feature IDs (A1, C5, N2 …), goals (G1–G8) and guardrails refer to it.
2. `docs/architecture.md` — the domain design specification (written by block D00). It refines the brief where the brief says so. If the two contradict each other, stop and report it; do not pick one.
3. Your block file — scope, deliverables and acceptance criteria of your work.

You have no access to `docs-internal/` and you do not need it. If something seems to be missing from your brief, say so in your report instead of guessing.

## Hard rules

- **No instance data.** No entity IDs, device names, room names, addresses, coordinates or host names of any real installation in code, tests, fixtures, documentation, commit messages or pull requests. Use neutral examples (`cover.example_window`).
- **The repository is public.** Everything written to GitHub is readable by everyone at once and cannot be reliably taken back: commit messages, branch names, pull request titles and descriptions, review comments, issue comments, CI logs and uploaded artifacts. The rule "no instance data" applies to all of them, not only to files. The same goes for local paths, user names, e-mail addresses, tokens and the content of error messages or logs you paste: read them before you post them and replace anything that identifies a person, a machine or an installation.
- **Hardware- and source-neutral (G6).** No assumption about a vendor, a weather service or a specific sensor may end up in code.
- **English** for code, comments, documentation, commit messages and pull requests. User-facing strings exist in English and German (`strings.json`, `translations/en.json`, `translations/de.json`) with identical keys; every user-facing string has a translation key.
- **Current Home Assistant APIs only.** Minimum version is 2026.9. Before you use a Home Assistant API, check it against the current developer documentation (<https://developers.home-assistant.io>), the developer blog and, where the documentation is silent, the Core source at the tested tag. Do not rely on memory. The section "Home Assistant specifics" of the brief lists what is already known, including items marked "(unverified)" that the block relying on them must verify. Schemas are written with `probatio`, not `voluptuous`.
- **Pure domain core (guardrail 4).** Everything under `custom_components/roller_shutter_suite/core/` imports nothing from `homeassistant` and nothing from the rest of the integration. It receives time, sun position and all inputs through its ports. It never reads a clock itself.
- **Missing data is not good news.** `unavailable` and `unknown` never count as "no warning", "no rain" or "window closed".
- **Timestamps are timezone-aware.** Naive datetimes are rejected at every boundary.
- **Repository conventions:** `.editorconfig` and `.gitattributes` are binding: UTF-8 without BOM, LF line endings, final newline, 4 spaces for Python, 2 spaces for JSON, YAML, TOML and Markdown.
- **Scope discipline.** Build what your block says, nothing more. Features with status "Not yet" or "Will not be implemented" are not built; where your block says "keep the door open", that means a place in the model, not an implementation.
- No new runtime dependency without it being named in your block file. Libraries that Home Assistant Core already ships are not listed in `manifest.json`.

## Definition of done

A block is done when all of this holds:

- every acceptance criterion of the block file is met and demonstrated by a test or, where the block says so, by a written result;
- the required tests exist and pass; the whole test suite passes with warnings treated as errors;
- `ruff check`, `ruff format --check` and `mypy` pass (from block T01 on), and the CI workflows pass (from block T03 on);
- the public documentation named in the block is written: plain language, worked examples, no knowledge assumed beyond operating Home Assistant;
- `TASKS.md` is **not** edited by you; the orchestrator keeps the status.

## Git workflow

- One branch per block, named `block/<id>-<slug>` (for example `block/c03-arbiter`), created from the current `main`.
- Commit in small, meaningful steps with imperative English messages. You commit and push your own block branch yourself.
- Stage files by naming their paths. Never use `git add -A`, `git add .` or `git commit -a`: local files that must stay out of a public repository can sit next to your work. Look at `git status` and `git diff --cached` before every commit.
- The commit author is configured in the repository. Never change `user.name` or `user.email`, and never pass them with `-c` or through environment variables. GitHub rejects pushes that contain a private e-mail address.
- When done, open a pull request against `main` with `gh pr create`. The description lists: what was built, how each acceptance criterion is demonstrated, which Home Assistant APIs were verified against which source, deviations from the block file with their reason, and open questions.
- **Only the project owner merges into `main`.** No agent merges, and that includes the reviewer. A reviewer agent with a fresh context checks the pull request against the block file and posts its verdict on the pull request: accept, or return with findings. The project owner merges after an accepting verdict; GitHub deletes the branch after the merge.
- Never push to `main`, never force-push, never skip hooks, never commit secrets.

## Report

End your work with a short report: what is done, what is not, what you verified and how, what surprised you, and which questions the project owner has to answer. If you could not meet an acceptance criterion, say so plainly.
