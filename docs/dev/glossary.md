# Glossary of user-facing terms

This glossary is the vocabulary of every user-facing text: the forms, the status entities, the reasons, the logbook, the repair issues and the user pages under `docs/`, and later the user manual (block W01). One thing has one word in each language, and the same word everywhere. The texts describe what a setting does for the house, never how the integration does it: words of the design and of the code, such as layer, gate, resolver, level or fault value, do not appear in them. A block that adds a term that users see extends this table in the same pull request.

The German texts address the reader informally, as the German interface of Home Assistant does, and are written in German, not translated from the English. The English texts follow the interface of Home Assistant: short, imperative, sentence case.

"Where" names where a term appears: **forms** (the configuration pages, their helper texts and errors), **status** (the entities of a window, the reasons and the logbook), **issues** (the repair issues) and **pages** (the user documentation).

| English | German | Meaning | Where |
|---|---|---|---|
| house | Haus | The whole installation of Roller Shutter Suite; its settings apply to every group and window that does not override them. | forms, issues, pages |
| group | Gruppe | Several windows that share their settings, such as one side of the house or one floor. Not a cover group of Home Assistant. | forms, issues, pages |
| window | Fenster | One window with its shutter or shutters, which are always moved together: what Roller Shutter Suite takes care of. It has one device and one status. | forms, status, issues, pages |
| roller shutter, shutter | Rollladen (plural Rollläden) | The physical shutter in front of the glass. | forms, status, issues, pages |
| cover | Abdeckung | The Home Assistant entity that controls a roller shutter (`cover.example_window`), as the interface of Home Assistant calls it. Used where the entity is meant: choosing it, its state, what it can do. | forms, status, issues, pages |
| cover group | Abdeckungsgruppe | A group helper of Home Assistant that combines several covers. A window uses its members instead of the group. | forms, pages |
| member | Mitglied | A cover of a cover group of Home Assistant. For a window with several covers the texts say "one cover of the window", not "member". | forms |
| setting | Einstellung | Anything you choose in the forms. "Value" is used only for what is typed into a field. | forms, issues, pages |
| saved setting | gespeicherte Einstellung | A setting as Roller Shutter Suite has stored it; the repair issues speak of it. | issues, pages |
| inherit | übernehmen | A group or window uses the setting of the group or house above it. The list entry for it is called "Inherit". | forms, issues, pages |
| override | überschreiben | A group or window makes a setting of its own instead of inheriting it. | forms, issues, pages |
| none | keine | The choice for an optional entity: no entity, although the group or the house names one. | forms |
| own selection | eigene Auswahl | The choice for an optional entity: the entity chosen in the field below. | forms |
| advanced settings | erweiterte Einstellungen | The section of a page that is folded shut; the defaults suit most homes. | forms, pages |
| feature | Funktion | A part of Roller Shutter Suite that can be turned on or off on the page "Features", such as the daily routine. | forms, pages |
| turn on, turn off | einschalten, ausschalten | Switching a feature or a setting on or off. | forms |
| daily routine | Tagesablauf | Opens the shutters in the morning and closes them in the evening. | forms, status, pages |
| morning, evening | Morgen, Abend | The two moments of the daily routine: the morning raises the shutters, the evening lowers them. | forms, status, pages |
| day, night | Tag, Nacht | The two parts of the day, from the morning to the evening and from the evening to the morning. | status, pages |
| part of the day | Tagesabschnitt | Day or night. | pages |
| kind of day | Art des Tages | Workday, weekend or public holiday; it decides which morning and evening times apply. | forms, status, pages |
| workday, weekend, public holiday | Werktag, Wochenende, Feiertag | The three kinds of day. | forms, pages |
| workday entity, holiday entity | Werktag-Entität, Feiertag-Entität | The entities that tell workdays and public holidays apart. | forms, pages |
| summer, summer entity, summer by date | Sommer, Sommer-Entität, Sommer nach Datum | What decides that the evening position in summer applies. | forms, pages |
| outdoor brightness entity, duration of darkness | Entität für die Außenhelligkeit, Dauer der Dunkelheit | What lets the evening begin early on a dark day. | forms, pages |
| trigger | Auslöser | What starts the morning or the evening: a fixed time, sunrise or sunset, or the elevation of the sun, as for a trigger of an automation. | forms, pages |
| not before, not after | nicht vor, nicht nach | The earliest and the latest time of a trigger that follows the sun. | forms, pages |
| random offset | zufälliger Versatz | Moves each morning and evening by a few minutes, differently for each window and day. | forms, pages |
| position | Position | How far a shutter is open, as Home Assistant counts: 0 % is fully closed, 100 % fully open. A position is sent, never "arrived" or "confirmed". | forms, status, pages |
| morning position, evening position | Morgenposition, Abendposition | How far the shutter opens in the morning and closes in the evening. | forms, pages |
| target position | Zielposition | The position a window should have. The English name of the status entity stays "Computed position", because the entity IDs of new windows are formed from it. | status, pages |
| dry-run | Probelauf | A window decides and records what it would do, and moves nothing. Every new window starts in dry-run. | forms, status, issues, pages |
| arm | scharf schalten | Switching dry-run off for a window, so that it moves its shutters; a later version adds it. | pages |
| comfort movement | Komfortbewegung | A movement for convenience, such as those of the daily routine, as opposed to protection. | forms, issues, pages |
| protection | Schutz | Movements that protect people or the shutters, such as from storm or hail; later versions add them. | status, pages |
| fire alarm, acknowledge | Feueralarm, quittieren | The fire alarm and the confirmation that it is over; later versions add them. | status, pages |
| manual operation | Bedienung von Hand | Moving a shutter by hand: with a wall switch, a remote or an app. Later versions notice it. | status, pages |
| manual override | Handbetrieb | The time after a manual operation during which automatic movements wait. Also the name of a status entity. | status, pages |
| pause | Pause, pausiert | Holds back comfort movements of a window, a group or the house on purpose; a later version adds the switch. | status, pages |
| suspended | ausgesetzt | A comfort feature does not move a window because a saved setting it needs is faulty. Not the same as a pause. | status, issues, pages |
| cautious choice | vorsichtige Vorgabe | What a setting that protects the shutters or limits their movements uses while its saved setting is faulty and no group or house setting stands in. | issues, pages |
| maintenance lock | Wartungssperre | Nothing may move a shutter while somebody works on it; a later version adds the switch. | status, pages |
| operating mode | Betriebsart | Off, protection only, or normal operation; a later version adds it. | status, pages |
| movement (page) | Bewegung | The page with the settings that spare the motors. | forms, pages |
| motor protection | Motorschutz | The minimum change and the minimum interval together: they leave out small comfort movements and space them out. | pages |
| minimum change, minimum interval | Mindeständerung, Mindestabstand | The two settings of motor protection. | forms, status, pages |
| staggering, gap between motors | Staffelung, Abstand zwischen Motoren | When many shutters move together, their motors start one after the other, with this gap. | forms, status, pages |
| repair issue | Reparaturhinweis | A message under Settings > Repairs that names a problem and how to repair it. | pages |
| reason | Grund | Why a window is where it is; the words of a reason code. Also the name of a status entity. | status, pages |
| decision | Entscheidung | What a window worked out at one moment: what it wants, what limits it, and whether it may move. | pages |
| next planned action | nächste geplante Aktion | When the daily routine wants something new next, and which position. Also the name of a status entity. | status, pages |
| command sent, held back | Befehl gesendet, zurückgehalten | Whether a movement was sent to the cover or held back, as the logbook says. | status, pages |
| entity, unavailable, unknown | Entität, nicht verfügbar, unbekannt | As in Home Assistant. An entity that is unavailable or unknown never counts as "off" or "no". | forms, status, issues, pages |
| delete | löschen | Removing a group or a window, as the menu of Home Assistant calls it. | forms, issues, pages |
