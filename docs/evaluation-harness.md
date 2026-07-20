# Omni Vox 2 — Evaluation Harness

Status: Initial implementation baseline

## 1. Purpose

The evaluation harness compares provider-neutral voice pipelines using repeatable
inputs and content-free output reports. It runs without physical hardware, but its
results do not replace servo-skull acceptance tests.

## 2. Input boundary

An evaluation case contains:

- A non-sensitive case identifier.
- One request and conversation identifier.
- Encoded input audio supplied in memory or from a private fixture location.
- Expected task or transcription annotations held outside public reports.

Raw personal audio and transcripts remain outside the public repository. Fixture
paths, credentials, provider endpoints, and personal annotations are never copied
into result records.

## 3. Per-interaction record

Each interaction produces only:

- Case and request identifiers.
- Terminal outcome: `completed`, `cancelled`, or `failed`.
- End-of-input to transcript, first text, first audio, and terminal latency in
  milliseconds when available.
- Selected STT, OpenClaw, and TTS adapter names when reached.
- A normalized error code for failed interactions.

Records omit audio bytes, transcript text, response text, provider exception
messages, internal URLs, and credentials.

## 4. Suite report

A suite report contains:

- Total case count.
- Outcome counts.
- Completed percentage.
- p50 and p95 latency for transcript, first text, first audio, and total duration.
- The ordered list of content-free per-interaction records.

Percentiles use the deterministic nearest-rank method:

1. Sort available observations in ascending order.
2. Select rank `ceil(percentile × count)`, with ranks starting at one.
3. Return no value when a metric has no observations.

Cancelled and failed interactions contribute to total-duration percentiles but
only contribute to a stage percentile when that stage was actually reached.

## 5. Timing and determinism

Production benchmarks use a monotonic clock. Tests inject a manual clock and must
not sleep. Reports preserve case input order regardless of future execution
parallelism.

## 6. Provider and hardware policy

- Fake-provider suites run by default.
- Real-provider suites require explicit opt-in, approved credentials, and billing
  controls.
- Provider comparisons use the same fixture manifest and decision rule.
- Physical wake, capture, playback, acoustic barge-in, and reboot evidence remains
  separately recorded and pending while the Pi is inaccessible.
