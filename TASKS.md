# Tasks

Index of the work blocks for the Roller Shutter Suite. The project is described in [docs/project-brief.md](docs/project-brief.md); the rules every block follows are in [tasks/README.md](tasks/README.md).

Each block is handed to exactly one agent as its complete brief. Blocks up to milestone M1 have a file in `tasks/`. Blocks after M1 are listed here with ID, title, features and dependencies only; they get their file once the design specification (D00) and the spike results (S1, S2) have been approved by the project owner, because those may cut the blocks differently.

Status values: `planned` (file exists, dependencies open) · `ready` (can start) · `in progress` · `in review` · `done` · `blocked` (needs a decision). The status column is maintained by the orchestrator only.

**Nothing is implemented before the project owner says "Go".**

## Phase 0 — Foundations and spikes

| ID | Block | Depends on | Status |
|---|---|---|---|
| [D00](tasks/D00-domain-design-spec.md) | Domain design specification (`docs/architecture.md`) | — | done |
| [T01](tasks/T01-repository-scaffolding.md) | Repository scaffolding | — | done |
| [T02](tasks/T02-test-setup.md) | Test setup | T01 | done |
| [T03](tasks/T03-continuous-integration.md) | Continuous integration | T01, T02 | done |
| [S1](tasks/S1-spike-cover-behavior.md) | Spike: cover behavior and movement attribution | history data from the owner | done for the design (findings in `docs/architecture.md`; the public taxonomy document is still to be written) |
| [S2](tasks/S2-spike-subentries-inheritance-ux.md) | Spike: subentries, sections and inheritance in the UI | T02 | done |
| [S3](tasks/S3-spike-button-events.md) | Spike: button event semantics | T02 | planned |

## Phase 1 — Domain core up to M1

Plain Python under `custom_components/roller_shutter_suite/core/`, tested without Home Assistant.

| ID | Block | Features | Depends on | Status |
|---|---|---|---|---|
| [C01](tasks/C01-core-model-and-ports.md) | Core model and ports | E5, N2, N3; doors for C15, A7 | D00, T01, T02 | done |
| [C02](tasks/C02-inheritance-resolver.md) | Inheritance resolver | E12, N4 | C01 | in review (pull request 23) |
| [C03](tasks/C03-arbiter.md) | Arbiter: layers, constraints, gate | E5, E4, E9, E10, E11, A6, A12 | C01 | in progress (merges after C02) |
| [C04](tasks/C04-schedule-and-day-types.md) | Schedule and day types | A1–A6, E13 (offset) | C01 | in progress (merges after C03) |
| [C05](tasks/C05-time-lapse-simulation.md) | Time-lapse simulation harness | N6 | C03, C04 | planned |

## Phase 2 — Home Assistant layer up to M1

| ID | Block | Features | Depends on | Status |
|---|---|---|---|---|
| [H01](tasks/H01-config-entry-and-subentries.md) | Config entry, group and window subentries | E12, F4, F7 (part), N2, N3, N4 (part), N5 (part) | S2, C02, T03 | planned (ready once C02 is merged) |
| [H02](tasks/H02-runtime-and-source-adapters.md) | Runtime and source adapters | guardrails 4 and 8, G3, G5 | C03, C04, H01 | planned |
| [H03](tasks/H03-cover-actuator-adapter.md) | Cover actuator adapter | E11, E13, E10 (settings), N2 | H01, H02 | planned |
| [H04](tasks/H04-status-entities-events-diagnostics.md) | Status entities, reason events, logbook, diagnostics | E7, E8 | H02 | planned |
| [M1](tasks/M1-walking-skeleton.md) | **Milestone: walking skeleton** — one window, dry-run, schedule only, status entities | — | all of the above except S1, S3 | planned |

## Maintenance

Work outside the block plan. Done items are listed so the history of the tooling stays readable.

| ID | Item | Status |
|---|---|---|
| X01 | Make the guards fail closed: a guard that cannot check fails, the instance data guard really checks in a WSL worktree, judges symbolic links, entries that cannot be examined and the path text of every entry (pull request 19) | done |
| X02 | Guard refinements, to be started before R01 or as soon as a block trips over a false positive (a plausible own name is never renamed to get around a guard). First item: the fixed names of the high-resolution brand images (the icon and logo files whose name carries the scale factor `@2x` before the extension) are taken for an e-mail address, by the path text check and by the content check alike. Further: other false positives on names, entries of the deprecated-names list that Home Assistant logs anyway are matched narrowly and only silent ones broadly, the Python patch version is pinned, smaller notes from the reviews of T03 and X01 | planned |

Transitional rule in `tasks/README.md` ("run the instance data guard on native Windows before every push"): to be removed once C02, C03 and C04 are merged.

## After M1 — listed only

Files are written after D00, S1 and S2 are approved. IDs and cuts may still change.

| ID | Block | Features | Depends on |
|---|---|---|---|
| C06 | Movement tracking, manual detection, override dam; tolerance by position source, report delay, position reference flag, self-measurement for the diagnostics; records real own commands: the time of the last comfort movement and the daily count of comfort movements with its threshold event (new reason code, added to section 5 of the architecture document together with the enumeration) | E1, E2, E3, E10 (count) | C03 |
| C07 | Protection events, fire, person-at-window dam, watchdog; test cases for the four conditions of the return to the manual position (architecture, decision 14) | D1–D6, D8, D9, guardrail 3; door for C13 | C03 |
| C08 | Window interaction and tamper | B1–B4, B9, F6 | C03 |
| C09 | Sun geometry and glass calibration; one curtain edge per element, mapped per member through its vertical offset (architecture, decision 9) | C1, C2, C7 | C01 |
| C10 | Shading episodes, conditions, solar heating; frost release by sun | C3–C6, C8, C9, C12, C14, A12 (part); doors for C3b, C10, C11 | C03, C09 |
| C11 | Sleep mode and privacy | A9, F2 | C03 |
| C12 | Persistence model and restart reconciliation | E6, D5, N5 | C06, C07, C10 |
| H05 | Storage and restart recovery; a reload during a movement, an armed dam or a deferral causes no false manual detection and no duplicate command (report delay up to 60 s) | E6, N4, N5 | C12, H02 |
| H06 | Control entities (pause, maintenance lock, mode, resume) | E4, E9, E2 (button) | H02 |
| H07 | Actions for automations, including fire acknowledgement and reference run. Note: loading service descriptions with a `supported_features` or attribute filter makes Home Assistant import every base platform, including the voice pipeline, whose native packages are not part of the test environment; the block has to find out whether its tests reach that path. If they do: first try documented stand-in modules for the two native packages in `tests/ha/conftest.py` (no warning filter, nothing weakened); add the real packages as development dependencies only if that does not hold, because they have no wheel for the current Python, would be compiled in every CI run without a cache, and would make a C++ toolchain a build dependency of a pure Python project | F1, A11 | H02 |
| H08 | Wiring: protection events, fire, watchdog and blind-source repairs | D1–D6, D8, D9 | C07, H03, H05 |
| H09 | Wiring: window interaction, tamper, blind-contact repair | B1–B4, B9, F6 | C08, H03 |
| H10 | Wiring: manual detection and override; per-member configuration steps (position source, report delay, travel times); the daily count of comfort movements in the diagnostics, its threshold as a setting, its event | E1–E3, E10 (count) | C06, H03, H05 |
| H11 | Wiring: shading (sun, forecast, radiation, indoor temperature); per-member measurement steps: glass height, glass calibration and the offset of the member's top edge within the element | C1–C9, C12, C14 | C10, H03 |
| H12 | Capability-aware configuration and repairs; explains settings masked by the capability mask of C02 (inherited and own values; an own value stays stored and returns with the capability); mask and repair issue never flap at a restart or while an entity is unavailable, with a test | F7 | H01, H03, C02 |
| H13 | Roof window profile | F3 | C09, C10, H11 |
| H14 | Wall buttons | F5 | S3, C07, H07, H12 |
| H15 | Command verification: detects that an actuator did not react, never that a curtain arrived; deadline from the report delay | N1 | C06, H03 |
| H16 | Wiring: sleep mode, privacy, frost source and frost waiver | A9, F2, A12 | C11, H06 |
| R01 | Release audit (quality scale checklist, translation parity, documentation consistency, HACS) | G7, G8 | all |

Milestones after M1: **M2** protection and manual override armed on the pilot window (C06, C07, C12, H05–H08, H10, H15) · **M3** window interaction and shading (C08–C11, H09, H11, H16) · **M4** capabilities, roof windows, buttons, release (H12–H14, R01).

## What can run in parallel

- From the start: **D00**, **T01 → T02 → T03**, and **S1** (needs only the owner's data) run side by side. **T01 is the first block after "Go"**: the public repository has no `LICENSE` file until T01 adds it, and until then "all rights reserved" applies although the brief names MIT.
- After T02: **S2** and **S3**. S3 is not needed before H14 and fills gaps in capacity.
- After D00 is approved and C01 is merged: **C02**, **C03**, **C04** in parallel (and C09 from the later list). C05 follows C03 and C04.
- Home Assistant layer: **H01** needs S2 and C02; **H02** follows; then **H03** and **H04** in parallel; then M1.
- After M1: H05, H06, H07 in parallel; the core blocks C06–C11 in parallel once C03 is merged (C06 waits for S1); the wiring blocks H08–H11 and H16 in parallel, which works because each feature contributes its own configuration module (layout from S2 and H01).
- At most three implementing agents at the same time, so that reviews keep up.

## Review gates for the project owner

1. **D00** — the design specification. Nothing in the core starts before it is approved.
2. **S1 and S2** — spike results; they can change the cut of later blocks.
3. **M1** — before anything is installed on the live system. Every step on the live system is approved individually.
4. **M2, M3, M4.**

Between the gates, every block passes CI, an independent reviewer agent and, for Home Assistant blocks, a check of the APIs used against the current developer documentation. The reviewer agent posts a verdict on the pull request; it does not merge. **Every merge into `main` is done by the project owner**, after an accepting verdict. The orchestrator presents the verdicts in batches, not one by one, so that the owner can merge several pull requests in one sitting. A block counts as `done` only when its pull request is merged, and a block that depends on it starts from the `main` that contains it.

The repository is public. What agents write on GitHub (commit messages, branch names, pull requests, comments, CI logs) is subject to the same "no instance data" rule as the files; see [tasks/README.md](tasks/README.md).

## Feature coverage

Every feature with status "Will be implemented" and the blocks that build it. Core block first, Home Assistant block second.

| Features | Blocks |
|---|---|
| A1–A6 | C04, H01, H02 |
| A9 | C11, H16 |
| A11 | H07 |
| A12 | C03, H16 |
| B1–B4, B9 | C08, H09 |
| C1, C2, C7 | C09, H11 |
| C3–C6, C8, C9, C12, C14 | C10, H11 |
| D1–D6, D8, D9 | C07, H08 |
| E1–E3 | C06, H10 |
| E4, E9 | C03, H06 |
| E5 | C01, C03 |
| E6 | C12, H05 |
| E7, E8 | H04 |
| E10 | C03, H03 |
| E11 | C03, H03 |
| E12 | C02, H01 |
| E13 | C04 (offset), H03 (staggering) |
| F1 | H07 |
| F2 | C11, H16 |
| F3 | C09, C10, H13 |
| F4 | H01, then every wiring block for its own steps |
| F5 | S3, H14 |
| F6 | C08, H09 |
| F7 | H01 (covers), H12 |
| N1 | H15 |
| N2 | C01, H01, H03 |
| N3 | C01, H01 |
| N4 | C02, H01, H05 |
| N5 | H01, C12, H05 |
| N6 | C05 |

Deferred features appear only as doors kept open: A7 and C15 in C01 and C04, C13 in C07, C3b, C10 and C11 in C10, D7 in C04, E9b in C03.
