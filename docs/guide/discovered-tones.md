# Discovered tones

ToneWatch can collect unmatched tonal sequences so you can decide whether a
new tone set is needed. Discovery is enabled by default. A source can opt out,
and the global discovery settings control the minimum and maximum segment
length, the allowed gap, and the clustering tolerance.

The **Discovered tones** page shows each candidate's frequencies, durations,
number of observations, last-seen time, and source. If an evidence clip was
recorded, it provides an audio player.

For a new candidate, choose **Create tone set** to open a prefilled form and
review the values before saving. Choose **Dismiss** to hide a candidate from
the new-candidate workflow. The candidate's status can be filtered as `new`,
`dismissed`, or `promoted`.

The command-line equivalent is:

```sh
tonewatch analyze file.wav --config config.yaml --discover
```

Discovery reports sequences that did not match an existing tone set. Review
the recording and local radio procedures before promoting one into an alerting
configuration.
