# Omni Vox 2 — Evaluation Harness

Status: Hardware-independent Increment 3 baseline complete

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

Private suites use a UTF-8 JSON manifest. Schema version 1 remains accepted for
latency-only suites. Schema version 2 adds optional private accuracy and recovery
annotations:

```json
{
  "schema_version": 2,
  "cases": [
    {
      "case_id": "clock-basic",
      "audio_file": "audio/clock-basic.opus",
      "codec": "opus",
      "conversation_id": "00000000-0000-4000-8000-000000000002",
      "request_id": "00000000-0000-4000-8000-000000000003",
      "accuracy": {
        "reference_transcript": "private expected speech",
        "proper_nouns": ["Omni"]
      },
      "recovery": {
        "scenario": "packet_loss"
      }
    }
  ]
}
```

The `accuracy` and `recovery` objects are independently optional. Accuracy
references are private inputs, not report fields. A reference contains 1–16,000
Unicode characters and must produce at least one normalized word. It contains at
most 64 unique proper-noun annotations, each 1–128 characters and present in the
normalized reference. Recovery scenario values are `packet_loss`,
`provider_timeout`, `gateway_restart`, and `interruption`. Unknown annotation
members fail closed. Version 1 cases retain their original exact field set;
version 2 permits only the two documented optional objects in addition to it.

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
- Accuracy counts when the private case supplies an accuracy reference.
- The named scenario, recovered result, and recovery latency when the case and its
  scenario driver supply a recovery observation.
- Request-attributable provider cost in integer micro-US-dollars when supplied by
  provider instrumentation. Zero is a measured local/no-charge result; `null`
  means unavailable.

Records omit audio bytes, transcript text, response text, provider exception
messages, internal URLs, and credentials.

The machine-readable per-case fields added by report schema version 1 are:

```json
{
  "accuracy": {
    "word_errors": 1,
    "reference_words": 4,
    "word_error_rate_percent": 25.0,
    "proper_nouns_correct": 1,
    "proper_nouns_total": 1,
    "proper_noun_accuracy_percent": 100.0
  },
  "recovery": {
    "scenario": "packet_loss",
    "recovered": true,
    "recovery_ms": 125.0
  },
  "cost_microusd": 240
}
```

Each optional measurement is `null` when it was not requested or observed. A
declared recovery scenario without a scenario-driver observation is invalid; the
harness does not infer recovery from ordinary pipeline completion.

## 4. Suite report

A suite report contains:

- Total case count.
- Outcome counts.
- Completed percentage.
- p50 and p95 latency for transcript, first text, first audio, and total duration.
- Micro-averaged accuracy totals and rates across annotated cases.
- Recovery success and latency across observed recovery cases.
- Observed cost and a normalized cost per 100 interactions when every case has a
  cost observation.
- The ordered list of content-free per-interaction records.

The top-level report has `schema_version: 1`. Its additional aggregates have this
shape:

```json
{
  "accuracy": {
    "measured_cases": 2,
    "word_errors": 3,
    "reference_words": 20,
    "word_error_rate_percent": 15.0,
    "proper_nouns_correct": 3,
    "proper_nouns_total": 4,
    "proper_noun_accuracy_percent": 75.0
  },
  "recovery": {
    "measured_cases": 2,
    "recovered_cases": 1,
    "recovered_percent": 50.0,
    "recovery_ms": {"p50": 125.0, "p95": 125.0}
  },
  "cost": {
    "measured_cases": 2,
    "observed_microusd": 480,
    "per_100_interactions_microusd": 24000
  }
}
```

An absent accuracy or recovery aggregate is `null`. Cost remains present with its
measured-case count and observed sum when partially measured, but
`per_100_interactions_microusd` is `null` unless the non-empty suite has a cost
observation for every case. Per-100 cost uses the observed suite total multiplied
by 100 and divided by case count, rounded to the nearest integer micro-US-dollar
with halves rounded up.

Accuracy uses the following deterministic rules:

1. Normalize reference and hypothesis with Unicode NFKC and case folding.
2. Tokenize each maximal sequence of Unicode alphanumeric characters as one word.
3. Calculate word errors with unit-cost Levenshtein distance over word tokens.
4. Treat a missing transcript for an annotated case as an empty hypothesis.
5. Count each distinct annotated proper-noun phrase once and mark it correct only
   when its normalized token sequence occurs contiguously in the hypothesis.
6. Aggregate counts before calculating rates. WER may exceed 100 percent because
   insertions count as errors. A proper-noun rate is `null` when no proper nouns
   were annotated.

Recovery observations are emitted by the deterministic fault-scenario driver and
contain only a boolean plus elapsed milliseconds from fault injection until the
documented post-fault ready condition. A successful observation requires a finite,
non-negative duration; an unsuccessful observation has no recovery duration.
Aggregated recovery latency includes successful observations only. Simulator
recovery remains hardware-independent evidence and is never labeled as physical
device recovery.

Request cost is the sum of billable provider usage attributable to the request,
including failed attempts, fallbacks, and cancelled work when providers charge for
them. Provider adapters or benchmark instrumentation perform provider-specific
usage conversion; reports accept only the resulting non-negative integer
micro-US-dollar amount and never include account, credential, endpoint, prompt,
transcript, or pricing-plan identifiers.

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
