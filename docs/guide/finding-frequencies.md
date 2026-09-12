# Find tone frequencies

Use the live spectrum to measure a tone from a connected source, then save the
captured value in a tone set.

## Live spectrum and capture

1. Add and enable a source in **Sources**.
2. Open **Spectrum** and choose that source.
3. Wait for the dominant frequency, purity, and level to settle while the tone
   is present. The spectrum covers 250 to 3000 Hz.
4. Select **Capture tone**. ToneWatch opens a new tone-set form with the
   current dominant frequency prefilled.
5. Set the duration and tolerance, add the next tone if the page uses a
   sequence, and save the tone set.

The spectrum can be paused while you read a value. A captured value is a
starting point: measure several examples and choose a tolerance that covers
normal frequency drift without covering nearby tones.

## Offline discovery

For a WAV file, run the analyzer with the discovery flag:

```sh
tonewatch analyze file.wav --config config.yaml --discover
```

The output includes a `Discovered tones` section after detections. It lists the
frequencies, durations, and time range of unmatched tone sequences. The same
unmatched candidates appear in the [Discovered tones page](discovered-tones.md)
when discovery is enabled for a live source.
