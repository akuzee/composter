# Building the `Compost` shortcut

Ten minutes on the iPhone. The Mac side is already built and tested.

**Do not repurpose the existing quick-note shortcut** — build a new one, so the
old habit keeps working while this one is unproven.

## What it does

Share anything from any app → it lands in the vault on the next hourly run,
with its date, its source URL, and any attached files.

The shortcut writes **JSON, not markdown**. Every formatting decision stays on
the Mac in `vault.py`. Maintaining a markdown template inside Shortcuts is
miserable and produces two renderers that drift apart.

## Setup

**1. New shortcut, named `Compost`.**

**2. Shortcut Details (the ⓘ tab):**
- *Show in Share Sheet* — ON
- *Accepted types*: Text, URLs, Images, Files, Media
- Add it to the **Action Button** too, if your phone has one

**3. Actions, in order:**

| # | Action | Settings |
|---|---|---|
| 1 | **Receive** input from Share Sheet | If there's no input: **Ask For Text** |
| 2 | **Format Date** | Date: *Current Date*; Custom format: `yyyy-MM-dd'T'HHmmss` |
| 3 | **Set Variable** | Name: `TS`, Value: the formatted date |
| 4 | **Text** | The JSON below |
| 5 | **Save File** | Destination: `iCloud Drive/Composter Inbox/`, filename `TS.json`, **Ask Where To Save: OFF**, **Overwrite: OFF** |

The Text action in step 4:

```json
{"captured_at":"[ISO date]","kind":"note","text":"[Shortcut Input]","source_url":"","files":[]}
```

Insert the bracketed parts as **variables**, not literal text. For `[ISO date]`
add a second *Format Date* action set to ISO 8601.

**4. For images and files**, add before step 4:
- **If** *Shortcut Input* has any value and is an image or file:
  - **Save File** → `Composter Inbox/`, filename `TS-1.<ext>`, *Ask Where To Save OFF*
  - Set the JSON's `"files"` to `["TS-1.<ext>"]` and `"kind"` to `"photo"`

**5. For links**, set `"source_url"` to the shared URL variable and `"kind"` to
`"link"`.

**There is no step 6.** No caption prompt, no folder picker, no confirmation.
If you want captions, make a *second* shortcut — do not tax the common path for
the rare one.

## Turning it on

```yaml
# config/composter.yaml
sources:
  ios:
    enabled: true
```

Share one thing from the phone, wait for the next hourly run, and check
`zCompost/Inbox/`.

## What the Mac does with it

- **Waits `quiet_seconds` (30)** before reading a sidecar, so a file still being
  written or synced is never half-imported.
- **Waits for attachments.** A sidecar naming a file iCloud has not downloaded
  yet is deferred and `brctl download` is requested — importing a capture with a
  hole in it is worse than waiting.
- **Reads a photo's EXIF capture date** and uses it as `created`. Once a photo
  leaves the camera roll EXIF may be stripped, so this happens at import or not
  at all; the share timestamp is only when you *sent* it.
- **Moves consumed sidecars** to `Composter Inbox/_ingested/<YYYY-MM>/`. Never
  deletes them, so a bug cannot destroy a capture — and an inbox that looks
  empty on the phone is its own health signal.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Nothing appears | `ios.enabled` is false, or the folder name does not match exactly |
| Sidecar sits in the inbox | An attachment it names has not downloaded; it retries each run |
| Photo has today's date | The image carried no EXIF (screenshots usually don't) |
| `IosInboxBlocked` | Full Disk Access, or the folder does not exist in iCloud Drive |
