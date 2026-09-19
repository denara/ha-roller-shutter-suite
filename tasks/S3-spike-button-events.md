# S3 — Spike: button event semantics

| | |
|---|---|
| Kind | Spike (written result, small test code) |
| Depends on | T02 |
| Blocks | H14 (wall buttons). Not needed before milestone M1; may run whenever an agent is free. |

## Goal and reason

F5 builds up, down, hold-to-move and optional multi-press functions on button event entities, and F7 has to tell the user which of these a given button can do. Two things are unclear: how event entities behave in detail, and how the standard event types that Home Assistant introduced in 2026-07 coexist with vendor-specific types that many integrations still deliver. Hold-to-move is safety relevant (a missed release event means a shutter that keeps moving), so the semantics have to be known before the design.

## Read first

- `tasks/README.md`
- `docs/project-brief.md`: features F5, F7; guardrails 3, 7, 10; section 6, the item on button hardware and standard event types

## Questions to answer

1. How does an integration consume event entities correctly: which state and attributes change, does pressing the same button twice with the same event type always produce a state change, what arrives after a restart or when the entity becomes unavailable and returns (a restored state must never be read as a press)?
2. The standard `ButtonEventType` values and the `multi_press_count` attribute: exact names and semantics from the primary source. How can configuration detect whether an entity delivers standard types, vendor types, or both?
3. A mapping table from common vendor event types (short press, long press start, long press repeat, long press release, double press) to the functions of F5, and the rule for unknown types.
4. Own multi-press detection by timing for buttons without native multi press: the latency it adds to a single press, and a recommendation for the configurable trade-off.
5. Hold-to-move safety: what happens if the release event never arrives (lost radio telegram, restart)? Propose a dead-man rule (maximum run time, stop on the next event of any type) and say which cover capabilities it needs.
6. Which combinations of cover and button capabilities allow which functions of F5; this becomes the decision table of F7.

## Out of scope

- The implementation of F5. Any specific vendor integration as a dependency; examples stay generic.

## Deliverables

- `docs/dev/button-events.md` with the answers, the mapping table, the capability decision table and the dead-man rule.
- Tests under `tests/ha/` that pin the event entity behavior of question 1 with a fake event entity, so a change in Home Assistant is noticed.

## Acceptance criteria

- Every statement about Home Assistant behavior is backed by a test or a quoted primary source.
- The decision table covers covers without stop and covers without position.
- The dead-man rule guarantees that a hold-to-move movement ends without a release event.

## Open questions that block this block

None.
