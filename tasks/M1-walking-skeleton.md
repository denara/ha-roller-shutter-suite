# M1 — Walking skeleton: one window, dry-run, schedule only

| | |
|---|---|
| Kind | Integration and acceptance block; milestone and review gate |
| Depends on | T01–T03, D00, C01–C05, C03a (binding: cautious fault values and the arbiter's safety net come before the milestone and before any real installation), H01–H04 |
| Blocks | Installation on the project owner's live system; every block after it |

## Goal and reason

The owner wants to install something on a productive system early, next to the old control that still moves the same window, to see real decisions under real conditions (G3, E11). That is only acceptable if it is proven that this version cannot move anything. M1 assembles the blocks built so far, proves that property end to end, and produces the instructions for the pilot. It adds no features.

## Read first

- `tasks/README.md`
- `docs/architecture.md`
- `docs/configuration.md`, `docs/features/dry-run.md`, `docs/features/status-and-events.md`, `docs/features/daily-routine.md`
- `docs/project-brief.md`: G3, G5, E11, D3; section 6 "Safety and behavior" (one controller per window; order of change on a live system)

## Scope

- **End-to-end tests** under `tests/ha/` that set up the integration through its config flow with one group and one window in dry-run, run a simulated day with frozen time, and check entities, events and the absence of any cover service call.
- **The safety proof for the pilot,** as tests: over a full simulated day, across a restart, a reload, a reconfigure, an unavailable cover that returns, and a stub fire trigger, a window in dry-run causes zero cover service calls. In the same run the cover is moved from outside several times (as the other controller would): the movements are logged, no dam is armed, and the decisions keep showing the hypothetical outcome instead of `manual_override`. A second window that is armed does move, which shows the test would notice a call.
- **Restart behavior without persistence** (H05 comes later): after a restart the schedule decision is the same as before, because it is derived from the situation; document what is not yet persistent.
- **Gap list:** walk through the acceptance criteria of all blocks up to here and list what is missing or weaker than specified; fix small gaps, report the rest.
- **A version number and a tagged pre-release** so it can be installed through HACS as a custom repository.
- **Pilot guide** `docs/pilot.md`, generic for any user: install as a custom repository, add one window in dry-run, which entities to watch, how to compare decisions with what the existing control does, how long to observe, what to check before arming (the window is removed from every other controller first: one controller per window), how to uninstall without traces.

## Added after block H01 was reviewed

- **What no test replaces, done by the project owner at this milestone:** a look at every form in a real browser (placeholders in helper texts and in the error for a refused combination, the read-only stand-in, collapsed sections, menus, emptied fields), and proof-reading of the German texts. The reviews checked keys and placeholders for parity, not the wording.
- **For the release notes:** the house level stores every value its form shows, the built-in defaults included. A later change of a built-in default in the core therefore does not reach an existing installation; that is intended (no silent change of behavior by an update) and has to be said.

## Out of scope

- Any new feature. Arming a window on the owner's system. Anything on the owner's live system: installation there is done by the owner after the review, step by step and with approval for each step.

## Deliverables

End-to-end tests, gap list in the pull request, `docs/pilot.md`, updated `README.md` (status: pilot, dry-run only recommended), pre-release tag.

## Acceptance criteria

- All CI workflows pass, including `hassfest`, HACS validation and the three guards.
- The safety proof tests pass, and the armed control window shows they can fail.
- The time-lapse simulation's year scenario passes with the merged state of all blocks.
- A person who has never seen the project can follow `docs/pilot.md` on a test instance and ends with one window in dry-run whose reason sensor and next planned action are plausible; the reviewer does exactly this and reports it.
- Removing the integration leaves no entities, devices or storage files behind.
- The project owner has reviewed M1 and approved the installation on the live system.

## Open questions that block this block

- Approval by the project owner after the review. This gate is not passed by an agent.
