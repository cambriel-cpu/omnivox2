# Omni Vox 2 — Initial Implementation Plan

Status: Active
Approved product and architecture baseline: 2026-07-20

## 1. Objective

Build the provider-neutral evaluation harness and skull simulator before selecting
production speech providers or implementing the physical device service.

The first implementation must prove protocol behavior, request lifecycle,
cancellation, bounded resource handling, deterministic metrics, and provider
substitutability without requiring access to the servo-skull.

## 2. Session constraint

The physical Raspberry Pi servo-skull is not locally accessible during this work.
This session must not depend on:

- Hardware reboot or power-cycle testing.
- Manual microphone, speaker, cue, or wake-word checks.
- Changing or replacing software on the Pi.
- Claims that simulator results establish physical-device acceptance.

All work in this session is hardware-independent. Physical wake-word, Seeed audio,
playback, boot recovery, and acoustic barge-in acceptance remain pending until Chris
has local access to the device.

## 3. Delivery sequence

### Increment 1: Deterministic pipeline foundation

- Establish the Python project, test, type-check, lint, dependency-audit, and
  secret-scan commands.
- Define provider-neutral request context, transcript, text segment, audio chunk,
  provider interfaces, and normalized errors.
- Implement a deterministic in-process pipeline driven by fake providers.
- Record stage timing and correlated outcomes without transcript or audio logging.
- Cover success, provider failure, fallback limits, cancellation, and stale output
  with tests written before implementation.

### Increment 2: Versioned protocol and skull simulator

- Specify control-message schemas and negotiated limits before runtime code.
- Add golden fixtures for handshake, utterance, cancellation, error, and heartbeat
  messages.
- Implement an in-process skull simulator and gateway transport adapter.
- Test malformed, oversized, duplicate, stale, and out-of-order messages.

### Increment 3: Evaluation runner

- Define a private-fixture manifest that never commits personal audio.
- Produce machine-readable latency, accuracy, recovery, and cost reports.
- Add deterministic packet-loss, timeout, reconnect, and interruption scenarios.
- Provide explicit opt-in markers for real-provider tests.

### Increment 4: Provider spikes

- Benchmark the local cascaded baseline.
- Benchmark streaming cloud STT, OpenClaw, and streaming TTS.
- Benchmark the approved native realtime challengers.
- Select production providers using the documented decision rule.

## 4. Verification policy

Every behavior change begins with an observed failing test. Work is complete only
when applicable tests, linting, type checking, dependency scanning, and secret
scanning pass. Hardware-independent evidence is reported separately from deferred
physical-device gates.

No paid provider, external deployment, Pi mutation, push, or pull request is part of
this plan without separate authorization.
