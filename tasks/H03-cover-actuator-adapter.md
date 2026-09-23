# H03 — Cover actuator adapter

| | |
|---|---|
| Kind | Implementation, Home Assistant layer |
| Depends on | H01, H02 |
| Blocks | Milestone M1; every wiring block after M1 |
| Parallel with | H04 |

## Goal and reason

This is the only place in the integration that is allowed to move a cover (G1). Keeping it single and small is what makes dry-run trustworthy: if nothing else can send a command, a window in dry-run provably does not move. For the walking skeleton on a live system that is the property that matters most.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: gate, dry-run, fire bypass, staggering, capability profile
- `docs/dev/runtime.md`
- `docs/project-brief.md`: E11, E13, N2, D3; G1; section 6 "Safety and behavior"

## Scope

- Implementation of the core's **actuator port**: translate a "send" outcome into the right cover action for the capability profile — set position where supported; open or close only for covers without set position (N2), with intermediate targets mapped as the architecture document specifies; never an action the cover does not support.
- **Windows with several covers:** if `docs/architecture.md` ("Several covers operated as one window") defines such units, the adapter commands all members, observes each member individually and never the group entity, and follows the document on staggering inside a window and on an unavailable member.
- **Dry-run:** the command is recorded (log, decision record for H04) and **not** sent. This holds for every kind of movement including fire. The check lives in the adapter as well as in the gate: defense in depth, with a test that a "send" outcome reaching the adapter for a dry-run window still sends nothing.
- **Staggering (E13):** collective movements are spread with a configurable gap per motor across windows; fire is never staggered.
- **Configuration step "Movement"** contributed in the modular layout of H01: minimum change and minimum interval of the motor protection (E10), staggering gap (E13), with inheritance; expert values in a collapsed section.
- **Own-command bookkeeping:** remember target, time and an own context per command, exposed to the core through the window state, so that C06 can later build the expectation window. No detection logic here.
- **Observation:** map the cover's state and position to the core's window state (position or none, moving, available), including covers that never report transit states. Identical repeated state writes, attribute-only writes that precede the resting state by milliseconds, and a rewritten unchanged state with a new change time must not reach the core as separate movements or changes; the rules are in `docs/architecture.md` ("Observing a movement").
- Errors of the service call are caught, logged with the window's name, and reported to the core as a failed command (`command_failed`). Nothing in this adapter, its logs or its documentation claims that a curtain has arrived: on many installations the reported position is calculated from run time (architecture document, "Calculated positions and drift"). Retry, backoff and the repair issue are block H15 (command verification, after S1).

## Added after block H01 was reviewed

- **The adapter's dry-run check follows the fire ruling of the arbiter's safety net.** Since block C03a, a failed dry-run rule (an exception inside it) does not hold a pending fire wish back: the decision names the failed rule in `Decision.faults`, and the command is sent, because an escape route that stays closed in a fire is the greater evil (`docs/architecture.md`, section 13a; `docs/dev/arbiter.md`). The adapter's second check must not undo that: for a window in dry-run it sends nothing, except a fire command whose decision names the dry-run rule as failed. For every other class the second check stays as it is. A test for each case; `docs/features/dry-run.md` states this one exception in plain words.
- **Sending and recording, decided by the project owner after H02 and C05.** The core records an own command itself (`Engine.state_after_send`) right after the runtime has sent it to a member; the adapter adds the context ID with the result. A `command_failed` result must mark that record, otherwise gate rule 3 ("no position feedback and the last own command already had this target") keeps a member whose actuator never reacted at "reached". After an exception inside the send the runtime arms no new wake-up until the next trigger or the safety tick (block H02): the backoff of this block owns that gap. A send commands only the members that do not stand at the target within tolerance; a member without position feedback cannot be judged and is commanded. The return of a member that was unavailable during a command completes that command: only this member is commanded, it is no comfort movement for the daily count and no fresh wish for the minimum interval (the reasons stand in the C06 row of `TASKS.md`; counter-arguments are welcome when the block starts). Until C06 makes the core name the commanded members, the runtime filters unavailable members before the send.
- **Forms for the settings this block makes effective.** The settings registry of the core already holds the motor protection settings (`motor_min_change`, `motor_min_interval`) and the re-evaluation time (`reevaluate_after`); block H01 built the form mechanism but offers no form for them. This block adds their form metadata and translations (English and German) as a feature page, without a change to a flow class, as `docs/dev/config-flow.md` describes.

## Out of scope

- Manual operation detection (C06, H10). Command verification and retries (H15). Stop and hold-to-move for buttons (H14). Tilt.

## Deliverables

Adapter module, tests, a section "Moving covers" in `docs/dev/runtime.md`. For users: `docs/features/dry-run.md` — what dry-run is for, that it never moves anything, not even at a fire alarm, how to compare its decisions with reality, how to arm a window.

## Acceptance criteria

- No code path outside this adapter calls a cover action; a test scans the integration's source for cover service calls and fails on any other occurrence.
- In dry-run, across all movement kinds including fire, zero service calls are made; the would-be command is recorded with target and reason.
- A cover without set position receives only open or close; a cover without position feedback yields a window state without position and no exception.
- Ten windows commanded together are sent with the configured gap; the same ten windows at fire are sent without a gap.
- A failing service call does not stop other windows and reaches the core as a failed command.
- Commands carry an own context whose ID is kept in the bookkeeping.

## Required tests

Under `tests/ha/` with fake covers of different capability profiles: each acceptance criterion; the source scan test.

## Open questions that block this block

None beyond D00.
