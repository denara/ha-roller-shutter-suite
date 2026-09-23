# W01 — User manual in the wiki of the repository

| | |
|---|---|
| Kind | Documentation for users; a data set for a throw-away instance; a publishing path |
| Depends on | M1 and a stable state: installation through HACS and set-up through the user interface work. Before the first public release |
| Blocks | The first public release |
| Parallel with | Blocks after M1 that do not change the forms of the features the manual describes |

## Goal and reason

A manual for people who use the integration, in the GitHub wiki of the repository. It is written for two readers on the same page: somebody who can operate Home Assistant and wants a first window to work, and somebody who wants to use every option. Every page starts with the simple case and moves to the special one. The manual exists in English and German, matching the languages of the user interface; French and Spanish are planned as a later extension of the wiki and the interface alike, so nothing here may assume two languages.

The manual says what the integration does, how it is set up, which option brings which advantage, and when an option is offered. It contains no implementation detail: no code, no module, class or reason-code names, and no architecture terms such as layer, constraint, gate or arbiter. Its sources are `docs/concepts.md`, `docs/configuration.md`, the feature pages under `docs/features/`, the texts of the user interface (`translations_src/`) and the behavior of the real forms — never the source code. Where a behavior could be found only in the code, the user documentation under `docs/` has a gap; that gap is closed there first, in its own pull request, and the manual is written from the closed gap.

## Read first

- `tasks/README.md`
- `docs/concepts.md`, `docs/configuration.md`, every page under `docs/features/`, `docs/pilot.md` (block M1), `README.md`
- `translations_src/` (the texts of the forms, the explanations of options and their preconditions, the repair issues)
- `docs/dev/config-flow.md` only for the part "Translations are generated", to know where the texts come from; nothing else under `docs/dev/` is a source for this block
- `docs-internal/s2-browser-test.md` is not available to the agent; the orchestrator states the procedure for the throw-away instance in the prompt (a test instance with demo entities, the integration installed as a custom repository, neutral names)

## The example house

The manual follows one made-up house from the first page to the last, like a training course: each chapter adds something to the house, and a reader can do the chapters as an exercise. Nothing in it matches a real installation: no real place, person, address or serial number; coordinates are round example values like those of the sun-port tests. Names are the names a user would really give (rooms, façades, sensors), never placeholders like house "H", group "A", window "B".

The house exists once per language, with names that fit the language (a German house in the German edition, an English one in the English edition; French and Spanish later). Screenshots are taken per language with the interface in that language; no picture mixes languages. The orchestrator's recommendation, to be confirmed by the project owner: one house, translated names, identical structure, so that the data set is one file per language and the chapters stay the same in every edition.

### First draft of the house (for the owner's approval before the start)

A detached house with two floors and a converted loft, one adult bedroom, one child's room, a living room with a terrace door, a kitchen, a study in the loft under a four-part roof window element, and a small weather station on the roof. German names first, English names in brackets.

| Part of the house | What it has | Which chapter adds it | What it demonstrates |
|---|---|---|---|
| The house itself, "Haus Lindenweg" ("Maple House") | location as round example coordinates, the house-level defaults: morning and evening times, workday and holiday sources | Installation, first steps | the house entry, defaults, inheritance |
| Kitchen ("Küche" / "Kitchen"), one roller shutter with position feedback | one cover entity | First window | the minimal configuration; dry-run; the status entities |
| Kitchen again | the same window with its options: morning and evening positions, seasonal evening position, an offset from sunrise | Options of a window | how one window overrides the house; how an inherited value looks in the form |
| Bedroom ("Schlafzimmer" / "Bedroom") and child's room ("Kinderzimmer" / "Child's room"), group "Schlafräume" ("Bedrooms") | two shutters, a group with later mornings on weekends and a sleep switch | Groups; day types and sleep mode | group values, weekend and holiday day types, the sleep-room behavior |
| Living room ("Wohnzimmer" / "Living room"), group "Südfassade" ("South façade") with the kitchen | a wide shutter, the façade group with orientation and glass measurements | Shading | orientation, permitted depth, the difference between a fixed shading position and a computed one |
| Terrace door ("Terrassentür" / "Terrace door") in the living room | a shutter and a door contact | Open window and lockout protection | the ventilation position; why a shutter never closes in front of an open door |
| Study in the loft ("Arbeitszimmer" / "Study"), a four-part roof window element | four roof windows with one shutter each, two larger ones above two smaller ones, operated as one window; measurements per part | Several covers as one window | the element as one window, per-part measurements, shading of the whole element, operation by hand of one part |
| Weather station on the roof ("Wetterstation" / "Weather station") | wind speed, outdoor temperature, rain, brightness | Protection functions; shading; daily routine | storm, frost with the test movement and the waiver, rain, evening by brightness |
| Smoke detectors in the hall | a fire alarm source | Protection functions | fire: everything opens, nothing returns by itself |
| Kitchen wall button ("Taster Küche" / "Kitchen button") | a wall button | Buttons | a button press and the override |
| Living room display ("Display Wohnzimmer" / "Living-room display") | a dashboard with the status entities | Status and diagnostics; notifications | reading the status, an example automation |
| The old automations of the house | two existing automations that move the kitchen and the bedroom shutters | Migration with dry-run | running the integration next to the old control, comparing, arming one window at a time |

The four-part roof window element is described as a common product of that kind, with the Velux "Lichtlösung QUARTETT" named as an example of the product family and clearly marked as a product name of Velux with no connection to this project.

The house is a data set in the repository, not only prose: a description per language and a template that fills a throw-away Home Assistant instance reproducibly with demo covers, sensors and contacts under these names, so that every screenshot can be taken again for every version. The data set takes the normal pull-request path; if a made-up name trips the instance data guard, the name changes, never the guard.

## Page structure (proposal; the block confirms it against what integrations of this kind usually offer)

Every page exists per language, with a fixed naming convention (a language suffix in the page name), a language-switch line at the top of every page and a sidebar per language. The convention is chosen so that a further language is added by adding pages, without renaming anything.

1. **Home** — what the integration does in three paragraphs, who it is for, the language switch, where to start.
2. **Installation** — requirements (the minimum Home Assistant version, what entities a window needs: a cover; what is optional), installation through HACS as a custom repository, the first restart.
3. **First steps** — creating the house entry; what the house-level values are; the example house is founded here.
4. **Basic ideas for users** — day types; protection before comfort; operation by hand and the override; inheritance house → group → window; dry-run. Written without technical terms.
5. **Your first window** — the kitchen: the minimal configuration, what the status entities show, dry-run, the first evening.
6. **Options of a window** — the kitchen again: every option of the daily routine with its advantage and where it can be set.
7. **Groups** — the bedrooms: what a group is for, what it can set, how a window overrides it.
8. **Day types and sleep mode** — workdays, weekends, holidays, the sources for them; the sleep switch and the sleep-room exception.
9. **Several covers as one window** — the loft element: measurements per part, what is shared, what stays separate, operation by hand of one part; the product family named as an example.
10. **Shading** — the south façade: orientation, permitted depth, fixed and computed positions, temperature and weather conditions, glass calibration with the tape measure, what a roof window needs in addition.
11. **Protection functions** — storm, hail, frost (with the test movement and the waiver), fire, open window and lockout protection, tamper contact; what each does, what it needs, what the user sees.
12. **Daily routine in detail** — fixed times, sun times with offsets, elevation, the evening by brightness, the seasonal evening position, random offsets.
13. **Buttons** — wall buttons and what a press means during automatic operation.
14. **Options reference** — one entry per option: what it does, its advantage, on which level it can be set, under which preconditions it is offered (position feedback, a contact, a known orientation …) and what happens when the precondition goes away later. The texts of the preconditions are the ones the forms show (F7), not new ones.
15. **Status and diagnostics** — the status entities, repair issues, events, the logbook: what the user sees and what to do; how to download diagnostics for a bug report.
16. **Notifications** — an example automation that turns an event into a notification; what is worth notifying.
17. **Migration from existing automations** — running next to the old control in dry-run, comparing decisions, arming one window at a time, removing the old automation; one controller per window.
18. **FAQ and troubleshooting** — the questions the pilot and the repair issues raise, each with what to check.
19. **Glossary** — the user-facing terms of the manual, one sentence each.
20. **Release notes and getting help** — what changes between versions in user terms (including the note that the house stores its values, so a later change of a built-in default does not reach an existing installation), where to ask, what to include in a report.

Additions the orchestrator proposes because manuals of comparable integrations have them: **Uninstalling without traces** (as a section of "Installation"); **Privacy: what the integration stores and sends** (nothing leaves the house; a section of "Status and diagnostics"); **Limits: what the integration cannot know** (calculated positions, a curtain stuck in frost; a section of "Basic ideas"); **A quick reference card** (the three switches pause, maintenance lock, operating mode and what each stops; a section of "Basic ideas").

## Pictures and worked examples

Every set-up page has screenshots of its forms and at least one worked example with the numbers of the example house. Screenshots come only from the throw-away instance filled from the data set, never from a real installation, and are taken per language with the interface in that language. The images live in the main repository (a folder under `docs/`) and are referenced from the wiki; file names carry no scale-factor suffix, because the instance data guard takes such names for an e-mail address.

## Process (binding)

The wiki repository of GitHub has no pull requests, no branch protection and no continuous integration: neither the guards nor the pre-push hook run there. Therefore the pages are maintained in the main repository, in a folder under `docs/` (proposal: `docs/wiki/`, with the images under `docs/wiki/images/`), take the normal pull-request path with guards, hook and reviewer, and are published from there to the wiki: by a workflow that synchronizes on a merge into `main`, or by the project owner by hand. No agent writes to the wiki repository. The block proposes the workflow (permissions, what it copies, how it handles a removed page) as part of its pull request and the project owner decides whether it runs.

The German texts are of native-speaker quality and not a translation of the English ones; the project owner proof-reads them. The reviewer checks every page against the real interface (forms, options, preconditions) and reads every page for anything technical that slipped through.

## Preparation carried by the blocks before this one

- **H03, H04, H12 and every block that adds user-facing texts:** the translation structure and the parity check are not pinned to two languages; a third language is added by adding fragments only.
- **H12 (and every block that masks an option):** an option that needs a capability names its precondition in the explanation the form shows (F7). The manual reuses those texts instead of inventing its own.
- **M1:** `docs/pilot.md` is the seed of the pages "Installation", "First steps" and "Migration".

## Out of scope

- Developer documentation (it stays under `docs/dev/`). Translating the interface into further languages (its own block). A dashboard card. Video.

## Deliverables

The pages under `docs/wiki/` in both languages with the sidebar files, the images, the data set of the example house per language with the template for the throw-away instance, the publishing workflow as a proposal, and a short section in `docs/dev/contributing.md` on how a page is changed (through `docs/`, never in the wiki).

## Acceptance criteria

- Every page of the structure exists in English and German, the two editions cover the same content, and every page has the language-switch line and appears in both sidebars.
- No page contains code, a module, class or reason-code name, or an architecture term; a reviewer finds none.
- Every set-up page has its screenshots and a worked example; every screenshot comes from the throw-away instance filled from the data set, in the language of the page, and can be reproduced from the data set.
- The options reference names, for every option that has a precondition, the precondition in the words of the form and what happens when it goes away.
- The example house carries every chapter; a reader can follow it as an exercise from the first window to the migration.
- The guards and the hook pass for every pull request of the block; no made-up name required a change to a guard.
- The project owner has proof-read the German edition and approved the example house.

## Required tests

No tests of the integration. A small check in the repository that every page under `docs/wiki/` exists in every language of the sidebar and carries the language-switch line, so that a forgotten translation fails the build.

## Open questions that block this block

- Approval of the example house (the draft above) by the project owner before the start.
- The wiki of the repository has to be enabled by the project owner, and the publishing path decided: a synchronizing workflow (the block proposes it; the owner approves its permissions) or publishing by hand.
- Confirmation that the house is one house with translated names per language (the orchestrator's recommendation), not a different house per language.
