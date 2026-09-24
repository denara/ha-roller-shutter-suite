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
| [C02](tasks/C02-inheritance-resolver.md) | Inheritance resolver | E12, N4 | C01 | done |
| [C03](tasks/C03-arbiter.md) | Arbiter: layers, constraints, gate | E5, E4, E9, E10, E11, A6, A12 | C01 | done |
| [C04](tasks/C04-schedule-and-day-types.md) | Schedule and day types | A1–A6, E13 (offset) | C01 | done |
| [C03a](tasks/C03a-cautious-fault-values-and-safety-net.md) | Cautious fault values for functions that fall back; safety net of the arbiter for exceptions. **Binding before M1 and before any real installation** | E12, guardrails on protection | C02, C03, C04 | done |
| [C05](tasks/C05-time-lapse-simulation.md) | Time-lapse simulation harness | N6 | C03, C04 | done (pull requests 48 and 50) |

## Phase 2 — Home Assistant layer up to M1

| ID | Block | Features | Depends on | Status |
|---|---|---|---|---|
| [H01](tasks/H01-config-entry-and-subentries.md) | Config entry, group and window subentries | E12, F4, F7 (part), N2, N3, N4 (part), N5 (part) | S2, C02, T03 | done |
| [H02](tasks/H02-runtime-and-source-adapters.md) | Runtime and source adapters | guardrails 4 and 8, G3, G5 | C03, C04, H01 (carry-over: X07, decimal positions) | done |
| [H03](tasks/H03-cover-actuator-adapter.md) | Cover actuator adapter; brings the forms for the motor protection settings and the re-evaluation time | E11, E13, E10 (settings), N2 | H01, H02 | done |
| [H04](tasks/H04-status-entities-events-diagnostics.md) | Status entities, reason events, logbook, diagnostics | E7, E8 | H02 | done |
| [M1](tasks/M1-walking-skeleton.md) | **Milestone: walking skeleton** — one window, dry-run, schedule only, status entities | — | all of the above except S1, S3 | done (pull request 61) |

## Maintenance

Work outside the block plan. Done items are listed so the history of the tooling stays readable.

| ID | Item | Status |
|---|---|---|
| X01 | Make the guards fail closed: a guard that cannot check fails, the instance data guard really checks in a WSL worktree, judges symbolic links, entries that cannot be examined and the path text of every entry (pull request 19) | done |
| X02 | Guard refinements, to be started before R01 or as soon as a block trips over a false positive (a plausible own name is never renamed to get around a guard). First item: the fixed names of the high-resolution brand images (the icon and logo files whose name carries the scale factor `@2x` before the extension) are taken for an e-mail address, by the path text check and by the content check alike. Further: other false positives on names, entries of the deprecated-names list that Home Assistant logs anyway are matched narrowly and only silent ones broadly, the Python patch version is pinned, smaller notes from the reviews of T03 and X01. From the work on X03 and X04: a Python slice that takes every second element of a sequence (start, empty stop, step two; not spelled out here because the guard flags it) is taken for an IPv6 address, and an attribute named `.local` for a host name; the summary of the pushed-commits check counts compared tag objects as commits; one vague sentence in the hook documentation ("a fresh clone of another kind"); a comment in the guard about a trailing line end that is stricter than what the shell does; the structural test of the hook and the token probe as noted in the reviews. From the review of H01: the coverage guard counts only `config_flow.py` and files whose name ends in `flow.py` as flow modules; the rule of 100 % lines and branches is to cover the whole `flow/` package (pull request 46) | done |
| X06 | Core performance: `WindowConfig.schedule` rebuilds its view of the schedule settings on every call, which costs about half of the simulated year (C05); a cached view in the core, kept correct by the existing round-trip tests. Small core change, with a reviewer | planned |
| X05 | Guard refinements, second round, to be started before R01 or as soon as a block trips over one of them. Left over from the review of X02: a host name with a trailing full stop (the absolute form of a `.local` name) is never matched in any file kind; a `.py` file that is prose but happens to tokenize is judged as code, so hosts outside strings pass (ruff refuses such a file in CI, the hook does not); a private IPv4 address glued directly behind a letter passes since the version-marker rule; the narrow rule for logging deprecated names does not see membership tests such as `x in registry.devices` (the log guard of the tests is the net) | planned |
| X07 | Robustness of the position reading (`members.py`, block H02): a `current_position` that is a decimal number without a fraction (`100.0`, as the template cover and the cover group of Home Assistant write it) is read as "no position" today, so such a window never reaches `target_reached`. Found in the review of M1 (pull request 61). Checked by the project owner on the pilot installation: every live cover reports an integer and the group is averaged by Home Assistant to an integer, so no change before the pilot; the tolerance for integral decimals is a small change against other integrations, with a test each for `100.0` (read as 100) and `99.5` (still no position), and `docs/pilot.md` and `docs/features/status-and-events.md` lose their paragraph about decimal positions | planned |
| X03 | A pre-push hook (`.githooks/pre-push`) that runs the instance data guard and refuses the push when it fails or cannot check; activated once per clone by a human with `core.hooksPath`, never by an agent | done |
| X04 | The pre-push hook also judges what is actually pushed: the added lines and the path texts of every commit in the ranges git hands to the hook, not only the checkout. Reason: a private value that was committed by mistake and corrected in the next commit passes the hook and CI, but leaves with the branch history and stays retrievable through the pull request reference, even after a squash merge and the deletion of the branch. Fails closed like the rest (a range that cannot be read refuses the push). Also: the identity of every pushed commit (author, committer, tagger) must equal the address configured for the clone, links to a session of an assistant tool are flagged, and the hook makes the guard prove that it knows the mode | done |


## Documentation

Blocks that produce documentation for users rather than code. They follow the same rules as every other block (pull requests, guards, hook, reviewer) and take no test slot.

| ID | Block | Depends on | Status |
|---|---|---|---|
| [W01](tasks/W01-user-wiki.md) | User manual in the GitHub wiki of the repository, for users only: no code, no module, class or reason-code names, no architecture terms. English and German first, matching the languages of the user interface; French and Spanish as a later extension of wiki and interface alike. Built along one made-up example house that grows chapter by chapter; screenshots only from a throw-away instance filled from a data set in the repository. The pages are maintained under `docs/` and published to the wiki from there (a workflow on merge, or the owner by hand); no agent writes to the wiki repository. Preparation that the H blocks carry now: the translation structure and the parity check are not pinned to two languages, and options name their preconditions in the user interface (F7) so that the wiki reuses those texts. The block file with the page structure and the example house is written before the start | M1 and a stable state: installation through HACS and set-up through the user interface work; before the first public release | planned |

## After M1 — listed only

Files are written after D00, S1 and S2 are approved. IDs and cuts may still change.

| ID | Block | Features | Depends on |
|---|---|---|---|
| C06 | Movement tracking, manual detection, override dam; tolerance by position source, report delay, position reference flag, self-measurement for the diagnostics; records real own commands: the time of the last comfort movement and the daily count of comfort movements with its threshold event (new reason code, added to section 5 of the architecture document together with the enumeration). Decided by the project owner after H02 and C05: **first item of the block: the core names the commanded members itself** (a target and an available member; the gate already reasons in these "addressed members" in rules 2 and 3), and the runtime and the simulation runner read that instead of filtering on their own; until then the runtime filters and the runner does not, which is the kind of drift the owner refused for the almanac and the recorder. Rulings for this block and H03, with the reasons in the block file (counter-arguments welcome at the block): the return of a member that was unavailable during a command is **not a fresh wish** but the completion of the existing command: only that member is commanded, no comfort movement for the daily count, no minimum interval; a send **commands only the members that do not stand at the target within tolerance**, and a member without position feedback counts as not judgeable and is commanded. Also from C05: the pin test `test_a_cover_that_settles_beyond_its_tolerance_is_sent_every_interval` in the simulation fails on purpose once verification and backoff exist; protection wishes have no limiter for re-sends today. From the review of H03: once the decision names the commanded members, the interim filter of the runtime controller is deleted; decide whether the staggering gap is reserved before or after a motor (today after, so a window with gap 0 also removes the gap towards the next motor). From M1 (pull request 61, gap list in `docs/pilot.md`): a movement by another controller shows only in the next decision, the status and the cover's own logbook; once the tracker sees such a movement, the window fires an `external_movement_observed` event with a logbook line of its own, and the manual override entity of H04, always off until then, follows the tracker | E1, E2, E3, E10 (count) | C03 |
| C07 | Protection events, fire, person-at-window dam, watchdog; test cases for the four conditions of the return to the manual position (architecture, decision 14) | D1–D6, D8, D9, guardrail 3; door for C13 | C03 |
| C08 | Window interaction and tamper | B1–B4, B9, F6 | C03 |
| [C09](tasks/C09-sun-geometry-and-glass-calibration.md) (file written; started before M1 because it depends on C01 and C02 only; **done**, pull request 43) | Sun geometry and glass calibration; one curtain edge per element, mapped per member through its vertical offset (architecture, decision 9) | C1, C2, C7 | C01 |
| C10 | Shading episodes, conditions, solar heating; frost release by sun. From C09: an own reason code and "no opinion" when the geometry cannot tell whether the sun is on the window (orientation not stated by any level; other exclusions likewise); the measured mode of the geometry only if at least the glass height was stated by a level, otherwise the simple mode with its fixed position and an own reason code (built-in lengths never drive a computed position); if the block touches the orientation, it drops the switch `shading_orientation_known` and lets "no level states an azimuth" be the unknown state; whether a member without position control takes the end position the geometry offers (closed as soon as any glass is to be covered), with hysteresis against flapping at that boundary; a test that shading and solar heating never both have an opinion with a valid configuration | C3–C6, C8, C9, C12, C14, A12 (part); doors for C3b, C10, C11 | C03, C09 |
| C11 | Sleep mode and privacy | A9, F2 | C03 |
| C12 | Persistence model and restart reconciliation | E6, D5, N5 | C06, C07, C10 |
| H05 | Storage and restart recovery; a reload during a movement, an armed dam or a deferral causes no false manual detection and no duplicate command (report delay up to 60 s). From M1 (pull request 61): the storage of the walking skeleton is in memory, so a restart forgets the simulated dry-run commands (the "would have sent" memory), the dams, own commands with their expectation, the motor protection clock, the held inputs, the latched day type, the seed of the random offsets, and the memory of the last reason event and the last ten decisions (`events.history_of`); this block decides which of these are written to disk and how a restart is reconciled. The in-memory state of a removed window stays until the entry is removed or Home Assistant restarts (`docs/dev/runtime.md` defers it, it harms nothing because a new window gets a new subentry ID); ruling of the project owner after M1: it is cleaned up in this block, together with the rule for a window whose covers cannot be read | E6, N4, N5 | C12, H02 |
| H06 | Control entities (pause, maintenance lock, mode, resume). From M1 (pull request 61): no window can be armed in version 0.1.0, only the stored subentry field `dry_run` can be changed by a test; this block brings the deliberate arming step, and the checks a user makes before arming stand in `docs/pilot.md`, section 8 | E4, E9, E2 (button) | H02 |
| H07 | Actions for automations, including fire acknowledgement and reference run. Note: loading service descriptions with a `supported_features` or attribute filter makes Home Assistant import every base platform, including the voice pipeline, whose native packages are not part of the test environment; the block has to find out whether its tests reach that path. If they do: first try documented stand-in modules for the two native packages in `tests/ha/conftest.py` (no warning filter, nothing weakened); add the real packages as development dependencies only if that does not hold, because they have no wheel for the current Python, would be compiled in every CI run without a cache, and would make a C++ toolchain a build dependency of a pure Python project | F1, A11 | H02 |
| H08 | Wiring: protection events, fire, watchdog and blind-source repairs. Also the repair issue of section 10.3 of the specification for a pause or a maintenance lock that lasts longer than seven days (ruling of the project owner, 2026-09-25): the issue is raised when the seven days are exceeded, closes by itself as soon as the pause or the lock ends, and is raised again by the next long pause or lock; the seven days are a constant, not a setting; nothing is released automatically | D1–D6, D8, D9 | C07, H03, H05 |
| H09 | Wiring: window interaction, tamper, blind-contact repair | B1–B4, B9, F6 | C08, H03 |
| H10 | Wiring: manual detection and override; per-member configuration steps (position source, report delay, travel times); the daily count of comfort movements in the diagnostics, its threshold as a setting, its event | E1–E3, E10 (count) | C06, H03, H05 |
| H11 | Wiring: shading (sun, forecast, radiation, indoor temperature); per-member measurement steps: glass height, glass calibration and the offset of the member's top edge within the element. From C09: the form requires the orientation and the lengths (element height, lower edge, permitted depth; one vocabulary with code and documentation); the switch `shading_orientation_known` is dropped at the latest here, if C10 has not done it, so that the only rule is "no level states an azimuth = unknown"; the member forms are built from the member registry of the core and the block decides the stored shape of member values; a problem code `unknown_member` with its translations for settings of a member the window does not have (reported as `unknown_setting` with level `member` until then); the repair explanation of block H01 must name a fault of level `member` as such, not as a house fault. From H02: an attribute reference is stored as `entity_id#attribute`; the forms offer two fields (entity and attribute) and no free-text syntax; a brightness source in lux passes through without a unit check because Home Assistant has no illuminance conversion, so the reader names the expected unit | C1–C9, C12, C14 | C10, H03 |
| H12 | Capability-aware configuration and repairs; explains settings masked by the capability mask of C02 (inherited and own values; an own value stays stored and returns with the capability); mask and repair issue never flap at a restart or while an entity is unavailable, with a test. Note from C09: a resolved value whose `effective` differs from `value` is not always masked by a capability (the orientation switch is one such case); the readers of the mask key on `unavailable`, and the docstring of `ResolvedValue` should say so. From H04 (decided by the project owner on 2026-09-24): before the first release the repair issue of an unreadable level lists the settings that run on cautious values, with their translated names as a placeholder; until then the issue names the level only, and the diagnostics show each setting | F7 | H01, H03, C02 |
| H13 | Roof window profile | F3 | C09, C10, H11 |
| H14 | Wall buttons | F5 | S3, C07, H07, H12 |
| H15 | Command verification: detects that an actuator did not react, never that a curtain arrived; deadline from the report delay. From the review of H03: for a call that was really made and raised, the time of the last attempt moves to the instant of the call as well (today it stays at the hand-over, so a retry computed from it would come up to the staggering wait too early); a fire command whose call failed is retried earlier than the end of its expectation window; a failed comfort command waits for the minimum interval before it is sent again, which the backoff of this block owns | N1 | C06, H03 |
| H16 | Wiring: sleep mode, privacy, frost source and frost waiver; brings the forms for all frost settings | A9, F2, A12 | C11, H06 |
| R01 | Release audit (quality scale checklist, translation parity, documentation consistency, HACS). Publishing the wiki is a step of the release checklist (the state of `main` at the tag goes to the wiki, the version lines of the pages updated). Open question to decide there, not now: whether several versions of the manual must stay visible side by side, which the GitHub wiki cannot do; GitHub Pages with versioned states would be the alternative | G7, G8 | all, W01 |

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
