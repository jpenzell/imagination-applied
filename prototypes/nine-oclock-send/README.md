# The Nine O'Clock Send

A point-and-click learning game in five mornings about working safely with AI at work. Prototype.

## Files

- `index.html` is the source, written for publishing as a Claude artifact (no doctype or head of its own).
- `standalone/index.html` is the same game wrapped as a complete page. Host it on any static web server or open it from disk. Rebuild it after editing `index.html`.

## What works where

| Feature | Claude artifact | Standalone copy |
| --- | --- | --- |
| All five mornings, scripted dialogue | Yes | Yes |
| Typed or spoken lines answered live by Claude | Yes, for people in the owner's organisation, after they allow it | No (scripted lines only) |
| Character voices | Where the browser supports it | No |
| Music and sound | Yes | Yes |
| Progress and run records | Saved in that browser only | Saved in that browser only |

## Running a playtest

1. Give each person the link or the standalone file on their own device.
2. They pick a morning and answer the one-question gut check before it starts.
3. At the end they answer the second gut check, write one sentence about their own work, and press **Copy playtest record**. They paste it wherever you are collecting results.
4. On a shared device, the title screen shows **Facilitator: copy all runs on this device**, which gives a CSV of every run.

Each record holds: morning, cast, ending, score, the state of each practice, hints used, in-game minutes, real seconds, whether the before and after gut checks were the strongest answer, whether live AI was on, and the reflection text. Nothing is sent anywhere; records leave the device only when someone copies them.

## Modes

- **With to-do list and hints** (default on Tuesday to Friday). Hints and teammate advice cost two in-game minutes and are counted in the run record.
- **No to-do list or hints**: a toggle on the team screen for any morning.
- **Monday, "On Your Own"** always runs without help and ends with four questions from the pack's owner. An answer only scores if the player found the evidence for it.
