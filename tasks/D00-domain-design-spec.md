# D00 — Domain design specification

| | |
|---|---|
| Kind | Design document, no code |
| Executed by | Orchestrator, reviewed and approved by the project owner |
| Depends on | — |
| Blocks | C01 and everything after it |

## Goal and reason

The brief fixes decisions and constraints but deliberately contains no design. Every later block is handed to an agent that knows only its block file and the documents it points to. Without one shared vocabulary and one shared model, fifteen agents will invent fifteen. D00 writes that model down once, as `docs/architecture.md`, and settles the open points the brief refers to it. It is the most important review gate of the project: everything after it builds on it.

## Read first

- `tasks/README.md`
- `docs/project-brief.md` completely; in particular section 5 (guardrails 1–3, 6, 8), section 6 and section 9 (open points 1–9)

## Scope

`docs/architecture.md`, written for implementing agents and maintainers, containing:

1. **Vocabulary.** Window, group, cover, covering type, position (100 = open), wish, "leave alone", constraint, gate decision (send / defer until / suppress), reason code, layer, episode, part of the day, day type, dam, owner of a position, expectation window, capability profile, source (entity or attribute) with its three states (value / unknown / unavailable).
2. **The arbiter** (guardrails 1 and 2): final layer order; complete list of constraints with what each may limit; complete list of gate rules in evaluation order; the explicit, named **fire bypass** with its two exceptions, maintenance lock and dry-run; how the sleep-room exception (D4) is expressed; how operating modes (E9) and pause (E4) act; tie-breaking between global, group and window level.
3. **The two dams** (guardrails 2 and 3, open point 2): the manual override dam and the time-limited "person at the window" dam. What arms each, what each holds back, how each ends, how they interact, and whether a wall button on the full Home Assistant path is refused during a maintenance lock.
4. **Reason codes.** A closed, stable list of machine-readable codes for every outcome, wins and skips alike, with the rule that a new code needs a translation in English and German.
5. **Episodes and parts of the day** (open point 4): definition, start, end, what is persisted; source of the season for A5.
6. **Schedule and catch-up** (open point 3): the state-based model (the schedule defines a target state per part of the day, nothing is replayed), the expiry of one-time actions such as C8, random offsets (E13) without breaking determinism in tests.
7. **Day types** (open point 9): how user-chosen entities map to workday, weekend and public holiday, including their behavior when unavailable.
8. **Protection details:** watchdog semantics of "released" while the trigger is still active, without contradicting D6 (open point 5); interaction of D5 and E2 (open point 6); frost against protection movements (A12, configurable, default comfort only).
9. **Inputs of F2** (open point 7) and the remaining vague wording (open point 8: C4, F3, E13, D9 defaults), each as a concrete proposal.
10. **Persistence model:** what is persisted per window (few scalars, versioned), and restart reconciliation as a pure function of persisted data and live state.
11. **Module map of the core** and its ports (clock, sun position, sources, actuator, storage), so that blocks C01–C12 have fixed seams. Doors kept open: covering type (C15), condition input for the morning opening (A7), further protection events (C13), multi-stage thresholds (C3b, C11), absence profile (D7), named profiles (E9b).
12. **Default for new windows:** proposal whether a newly added window starts in dry-run.
13. **Several covers operated as one window (N3).** This is a requirement, not an edge case: covers that sit side by side, are always operated together and are never addressed individually by any automation, only by hand at a vendor's remote control. The members may differ in size and therefore in travel time and in glass measurements. For the user the unit stays **one** window with **one** device and **one** status; members appear only where they differ: measurements, travel time, capabilities. The shading positions of the roof window profile (F3) must work for such a unit, so a solution without position logic does not meet the requirement.

    A first measurement, taken while a single member moved (the untypical case), showed that a Home Assistant cover group entity reports a transit state as soon as one member moves and the mean of its members as position. With unequal travel times that mean passes through values no member has, which speaks against the group entity as the source of observation. A measurement with all members moving together is still to be delivered by the owner.

    Evaluate these options against each other and recommend one, with the rejected alternatives and their reasons:

    - (a) Reject cover groups.
    - (b) Accept a group entity only in the degraded mode of N2 (open and close, no position logic). Does not meet the requirement above; say so.
    - (c) Accept the Home Assistant group entity as the unit: command it and observe it as one cover.
    - (d) **A window has one or more covers that are always moved together.** Commands go to all members; every member is observed individually. The window is "moving" until the last member has come to rest. A member that deviates counts as manual operation of the window. Capability profile and command verification (N1) are kept per member; for the window the lowest common denominator applies and F7 explains it. If the user selects a Home Assistant cover group, configuration resolves it into its members visibly, not behind the user's back.

    For option (d), settle:

    - **Travel times:** expectation window and command verification per member; the unit is moving until the slowest member rests.
    - **Staggering inside a window** (E13): yes or no, and how fire behaves.
    - **A member that is unavailable:** what the window does, what is commanded, what the status shows.
    - **Validation:** whether "a cover belongs to at most one window" then applies per member, and how a group entity whose members are partly used elsewhere is handled.
    - **Geometry with unequal glass measurements:** the same percentage lets different amounts of sun into the room. Evaluate both ways: one geometry for the unit and the same percentage for all members; or measurements per member and an own target position per member derived from the same decision. Name the consequences of each for C1, C2, F3 and for the status entities (one target position or several) and for the decision record.
    - **Manual operation of a single member:** override for the whole unit or only for that member. The owner leans towards the whole unit. Give a reasoned proposal and the rejected alternative, including what happens to the other members while the override lasts and how the unit returns to a common state afterwards.
    - **How a group is recognized** at configuration time, and what is stored (the members, not the group).

    N3 in the brief currently says "exactly one cover, which may be a cover group". If the decision is (d), its wording changes to "one or more covers operated as a unit"; report this to the owner as a change to the brief, do not make it yourself.
14. **Observing a movement.** First measurements on two cover platforms, to be taken as given: both report `opening`/`closing` but no intermediate positions; one keeps the old position for the whole travel and jumps to the target at the end; at the end of a movement two state writes arrive within 7 to 30 ms (either the same state twice, or the position as an attribute-only write followed by the resting state); a state write with a new change time but identical state and position occurs without any movement; a transit state can follow a transit state directly when a movement is reversed; travel time differs by direction and is not linear in percent (the part that ends in an end stop takes longer per percent); after an unavailable gap a cover returns with the state it had. The specification of the expectation window and of the movement tracker has to hold under all of these: one evaluation per movement, a short settle time after the resting state, decisions based on state and position values and never on the change time alone, a grace period made of a fixed allowance plus a share of the travel time per direction. The capability profile needs fields for "position updates during travel" and for platforms that never report transit states.

Every open point is answered as a **reasoned proposal** with the alternatives considered, so the project owner can decide in the review. Decisions already taken by the owner are recorded as such, not reopened.

## Out of scope

- Code, class names beyond the module map, Home Assistant specifics (config flow, entities).
- Measurements of cover behavior (block S1); the expectation window is specified in terms of parameters that S1 will fill.
- Changing `docs/project-brief.md`. If D00 finds a contradiction in the brief, it is reported to the owner.

## Deliverables

- `docs/architecture.md`
- A list of decisions for the owner, each with a recommendation
- After approval: updates to `TASKS.md` and to the block files that the decisions affect

## Acceptance criteria

- Every open point 1–9 of the brief, and scope items 12 and 13, have a proposal, a reason and at least one rejected alternative.
- The movement tracker's specification names, for each observation of scope item 14, how it is handled.
- For each of these situations the document states the outcome and the reason code without ambiguity: fire during maintenance lock; fire in dry-run; fire in mode "off"; storm with an open terrace door; storm with an open door and active tamper contact; hail event with a sleep-room exception while sleep mode is active; wall button during storm, then 15 minutes pass; manual override active when storm begins and when it ends; evening closing with a tilted window; frost during evening closing; one member of a window with several covers is moved by hand; one member of such a window is unavailable when a protection event starts; restart in the middle of a shading episode; source of a protection event becomes unavailable while the event is active.
- The fire bypass is a named part of the model that lists exactly which gate rules it skips and which it does not.
- No statement requires knowledge of a specific installation.
- The project owner has approved the document.

## Open questions that block this block

None. D00 exists to answer the open ones.
