# Import a `tones.cfg` file

ToneWatch can preview and apply a legacy `tones.cfg` file. The importer only
changes tone sets; it does not create sources or alert targets.

## Command line

Preview the proposed tone sets without changing the saved configuration:

```sh
tonewatch import tones-cfg tones.cfg
```

Use JSON output for automation:

```sh
tonewatch import tones-cfg tones.cfg --json
```

Apply valid sections and keep existing tone sets with merge mode:

```sh
tonewatch import tones-cfg tones.cfg --apply --mode merge
```

Use `--mode replace` to replace all current tone sets with the valid imported
sections. The importer accepts files up to 256 KiB and 500 sections. Invalid
sections are shown as skipped in the preview; no commands from the file are
executed.

## Web preview and apply

Open **Tone sets**, choose **Import legacy tones.cfg**, and select the file.
The preview lists imported and skipped sections, proposed frequencies,
durations, tolerances, and notes. Choose **Merge** or **Replace** after
reviewing the preview. Replace asks for confirmation because it removes the
current tone sets from the saved configuration.

## What is imported

The importer maps two-tone definitions (`atone`, `atonelength`, `btone`, and
`btonelength`) or a long tone (`longtone` and `longtonelength`) into ToneWatch
tone sequences. It also maps `tone_tolerance`, `record_seconds`,
`ignore_after`, and `gaplength`. Descriptions become tone-set names; missing
values use the ToneWatch model defaults where the preview says so.

Email recipient keys and email delivery settings are dropped. Command keys are
also dropped and are never run. Configure a webhook, MQTT target, or the
optional script target separately in ToneWatch's Alerts page.
