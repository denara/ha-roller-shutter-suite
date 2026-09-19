# S1 — Spike: cover behavior and movement attribution

| | |
|---|---|
| Kind | Spike (measurement and written result, no product code) |
| Executed by | Orchestrator together with the project owner. Not handed to a coding agent, because the raw data is instance data. |
| Depends on | Data delivered by the project owner |
| Blocks | C06 (manual detection), H15 (command verification), parts of H03 |

## Goal and reason

Guardrail 6 says the expectation window decides whether a movement was the integration's own. That window consists of numbers nobody knows yet: how long a cover takes to react, how long it travels, how far it settles from the commanded position, whether it reports `opening`/`closing`, whether it reports intermediate positions, and how late the last report arrives. Related projects show that every serious bug in manual detection lives in exactly these differences between cover platforms. S1 measures them before anything is built on them.

## Read first

- `tasks/README.md`
- `docs/project-brief.md`: guardrail 6, features E1, E3, N1, N2, section 7 (pitfalls from related work)

## Procedure

**Stage 1 — history data, no change to any live system.** The project owner exports the recorded state history (state, position attribute, timestamps, context IDs where available) for at least two covers of different platforms: one that reports transit states and one that offers no stop. The analysis answers, per platform:

- Does the cover report `opening`/`closing`? Also when moved by a wall button?
- Intermediate positions during travel, or only the end position? How many, at what interval?
- Time from command to first state change; time from command to the last position report; time between the physical stop and the last report, as far as it can be derived.
- Distribution of |commanded − reported| at rest; is it asymmetric by direction or by end stop?
- Behavior around unavailability: does the cover come back in the same state?
- What the context looks like on the first and on the last state change of a movement (confirms or refutes the five-second rule on real data).

**Stage 2 — only if stage 1 demonstrably cannot answer a question.** A passive logging aid that observes and never commands. It needs the owner's explicit approval for that single step, including which questions remained open and why history data cannot answer them. The scenarios are then: own command, dashboard command, automation command, wall button, wall button one, three and six seconds after a command, stop in mid-travel, a second command during travel, a command to the position the cover already has, restart during travel.

## Progress

Stage 1 is done as far as history data allows: two platforms, 98 movements. The findings that the design needs are recorded in D00 (scope items 13 and 14). Not answerable from history data, because it contains no commands and no context: the deviation between commanded and reported position, the real command latency, a second command during travel, and movements from a vendor's own remote control. The cheapest way to close the first and third point is a handful of approved commands with known targets and live polling on one cover, without any logging aid; like every step on the live system it needs the owner's approval for that single step. Also outstanding: one movement of a whole cover group with live polling of the group entity and of every member, to document how they report when all members move together and have different travel times (input for D00 scope item 13). None of the open points blocks D00; the first and third should be closed before C06 and H15 get their block files.

## Out of scope

- Any change to a live system without explicit approval. Any command sent to a real cover in stage 1.
- Product code. Design of the detection algorithm (D00 and C06).

## Deliverables

- Internal: raw analysis with instance data, kept outside the public repository.
- Public, neutral: `docs/dev/cover-behavior.md` — a taxonomy of cover behavior (reports transit states yes/no, position feedback live / end only / none, settles exact / rounded / asymmetric, supports stop yes/no, late final report yes/no) and the parameter ranges found, without entity IDs or device names beyond the generic platform type.
- A proposal for the **capability profile** fields and for the default parameters of the expectation window (tolerance, minimum grace, slack factor on travel time), to be taken over by D00/C06.
- A statement on whether the context is usable as a supporting hint on the measured platforms.

## Acceptance criteria

- Every question of stage 1 is answered per platform, or marked as not answerable from history data with the reason.
- The public document contains no instance data and is understandable without the internal one.
- The proposal for the expectation window holds for all measured movements: no own movement in the data would have been classified as manual, and the document says which manual movements would have been missed and why.
- The owner has accepted the result.

## Open questions that block this block

- Delivery of the history export by the project owner (which covers, which period; at least several days that include own commands, dashboard use and wall button use).
