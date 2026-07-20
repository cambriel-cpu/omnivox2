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

Private suites use a UTF-8 JSON manifest with this versioned shape:

```json
{
  "schema_version": 1,
  "cases": [
    {
      "case_id": "clock-basic",
      "audio_file": "audio/clock-basic.opus",
      "codec": "opus",
      "conversation_id": "00000000-0000-4000-8000-000000000002",
      "request_id": "00000000-0000-4000-8000-000000000003"
    }
  ]
}
```

The initial loader enforces these bounds before evaluation:

- The manifest is at most 262,144 bytes, has no duplicate or unknown fields, and
  contains at most 1,000 cases.
- Case identifiers are unique, 1–64 character lowercase identifiers containing
  only letters, digits, and internal hyphens.
- Conversation and request identifiers are canonical UUIDs; request identifiers
  are unique within the suite.
- Audio paths are relative POSIX paths beneath the manifest directory. Absolute
  paths, parent traversal, and symlinks resolving outside that directory fail
  closed.
- Each audio fixture is a non-empty regular file no larger than 4,194,304 bytes.
  The initial manifest accepts only the `opus` codec.

The manifest and its audio directory are private inputs and must remain ignored by
Git. Loading them into memory does not authorize copying paths or content into
reports, logs, commits, or test artifacts.

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

Transport fault scenarios use an in-process deterministic link. A test configures
the zero-based frame indexes to drop; transmission then returns no frame at those
indexes and forwards every other frame byte-for-byte. Dropped frames are not
renumbered or retried by the link, allowing the real protocol state machines to
detect the resulting sequence gap. The link records only frame indexes and byte
counts, never payload content, and introduces no sleeps or wall-clock dependence.

## 6. Provider and hardware policy

- Fake-provider suites run by default.
- Real-provider tests carry the `real_provider` pytest marker and are skipped by
  default. They run only when `pytest --run-real-provider` is supplied explicitly,
  after credentials and billing controls are approved.
- Provider comparisons use the same fixture manifest and decision rule.
- Physical wake, capture, playback, acoustic barge-in, and reboot evidence remains
  separately recorded and pending while the Pi is inaccessible.
