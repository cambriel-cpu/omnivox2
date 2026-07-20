# Omni Vox v2 — Architecture Specification

Status: Approved for implementation (2026-07-20)
Companion documents: `product-spec.md`, `protocol-v2.md`

## 1. Architectural goal

Build a small, secure, observable voice path between the servo-skull and OpenClaw, with strict ownership boundaries and replaceable speech providers.

## 2. System boundaries

```text
┌──────────────────────── Servo-skull / Pi 5 ────────────────────────┐
│ Wake word │ Mic/VAD │ State cues │ Audio playback │ Device client │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ authenticated, versioned WSS
                               │ Opus audio + typed control messages
┌──────────────────────────────▼─────────────────────────────────────┐
│                         Omni Vox Gateway                           │
│ Session control │ Request state │ Cancellation │ Provider routing  │
└──────────────┬──────────────────┬──────────────────┬───────────────┘
               │                  │                  │
          ┌────▼────┐       ┌─────▼─────┐      ┌─────▼────┐
          │   STT   │       │ OpenClaw  │      │   TTS    │
          │provider │       │  session  │      │ provider │
          └─────────┘       └───────────┘      └──────────┘
```

### Ownership

**Servo-skull owns:**

- Physical audio and indicators.
- Wake-word detection.
- Temporary audio buffers.
- Playback queue.
- Local state presentation.
- Network reconnect behavior.

**Gateway owns:**

- Device authentication and protocol enforcement.
- Live conversation/request coordination.
- STT and TTS provider selection.
- OpenClaw session transport.
- Cancellation propagation.
- Cross-service tracing and metrics.

**OpenClaw owns:**

- Omni's identity and instructions.
- Conversation/session semantics.
- Model selection and reasoning.
- Tool permissions and execution.
- Durable memory.

The gateway must not copy these OpenClaw responsibilities.

## 3. Deployment topology

### Servo-skull

- Raspberry Pi OS on Pi 5.
- One systemd-managed, non-root client service.
- Read-only application installation where practical.
- Writable paths limited to bounded cache, state, and logs.
- Seeed audio configuration managed separately from application code.

### Omnissiah

- One unprivileged Omni Vox gateway container.
- No Docker socket.
- Minimal read-only filesystem and dropped capabilities.
- Only required configuration and credential files mounted.
- Reachable only from trusted LAN/Tailscale routes; no public port forwarding.
- STT/TTS endpoints supplied through configuration, never compiled into code.

### External dependencies

- OpenClaw through its supported authenticated interface.
- One selected STT provider and one optional fallback.
- One selected TTS provider and one optional fallback.

## 4. Components

### 4.1 Skull audio layer

Interfaces:

```python
class AudioCapture(Protocol):
    async def start(self) -> None: ...
    async def frames(self) -> AsyncIterator[AudioFrame]: ...
    async def stop(self) -> None: ...

class AudioPlayback(Protocol):
    async def enqueue(self, chunk: AudioChunk) -> None: ...
    async def cancel(self, request_id: str) -> None: ...
    async def close(self) -> None: ...
```

Responsibilities:

- Normalize capture to a documented PCM format before encoding.
- Bound queues and discard stale/cancelled audio.
- Isolate ALSA/Seeed specifics behind adapters.
- Avoid network downloads or model installation during service startup.

### 4.2 Wake-word service

- Runs entirely on-device.
- Loads a pinned local Porcupine runtime and checked-in model artifact.
- Emits a wake event; it does not control the conversation pipeline directly.
- Tracks detections and failures without recording ambient audio.

### 4.3 Skull state controller

Canonical states:

```text
BOOTING → CONNECTING → IDLE → LISTENING → THINKING → SPEAKING
                         ↑         │          │          │
                         └─────────┴──────────┴──────────┘
                         ERROR / RECONNECTING → CONNECTING
```

All state transitions are explicit and tested. Hardware cues subscribe to state changes instead of being scattered through pipeline code.

### 4.4 Device transport

- One persistent authenticated WebSocket per device.
- JSON control frames and binary Opus audio frames.
- Heartbeat, reconnect, and protocol negotiation are transport concerns.
- Every interaction has a `conversation_id` and every utterance has a `request_id`.
- Sequence numbers allow stale, duplicate, and out-of-order frames to be rejected.
- Client and gateway enforce maximum frame size, utterance duration, and queue depth.

### 4.5 Gateway session coordinator

One coordinator instance exists per connected device session. It implements a bounded request state machine:

```text
CREATED → RECEIVING_AUDIO → TRANSCRIBING → GENERATING → SYNTHESIZING → COMPLETE
   └────────────── any active state → CANCELLING → CANCELLED
   └────────────── any active state → FAILED
```

The coordinator owns task cancellation and cleanup. Provider adapters must not mutate session state directly.

### 4.6 Provider adapters

```python
class SpeechToText(Protocol):
    async def transcribe(self, audio: AudioInput, context: RequestContext) -> Transcript: ...

class TextToSpeech(Protocol):
    async def synthesize(
        self, text: AsyncIterator[TextSegment], context: RequestContext
    ) -> AsyncIterator[AudioChunk]: ...

class OmniSession(Protocol):
    async def respond(
        self, transcript: str, context: RequestContext
    ) -> AsyncIterator[TextSegment]: ...
    async def cancel(self, request_id: str) -> None: ...
```

Adapters translate provider-specific errors into the common error model. The coordinator decides whether a fallback is allowed.

## 5. Protocol

### 5.1 Connection handshake

The client connects to `/api/v2/devices/connect` using TLS and a device credential. The first message declares compatibility:

```json
{
  "type": "hello",
  "protocol_version": 2,
  "device_id": "servo-skull-primary",
  "client_version": "git-sha-or-release",
  "capabilities": ["opus-input", "opus-output", "barge-in"]
}
```

The gateway replies with accepted limits and features. Unsupported versions are rejected before audio transfer.

### 5.2 Interaction messages

Control messages include:

- `wake`
- `utterance_start`
- `utterance_end`
- `transcript`
- `response_segment`
- `audio_start`
- `audio_end`
- `cancel`
- `state`
- `error`
- `ping` / `pong`

Every interaction message includes:

```json
{
  "protocol_version": 2,
  "conversation_id": "uuid",
  "request_id": "uuid",
  "sequence": 12,
  "type": "message_type"
}
```

Binary frames use a compact header containing protocol version, request ID mapping, sequence number, codec, and end-of-stream flag. The exact representation will be specified before implementation and covered by golden protocol fixtures.

### 5.3 Compatibility

- Major protocol mismatches fail closed.
- Minor optional capabilities are negotiated.
- Unknown message types return a structured protocol error.
- The gateway supports only an explicitly documented compatibility window.

## 6. Authentication and authorization

- Each physical device receives a distinct, revocable credential.
- Credentials are provisioned outside source control and stored with owner-only permissions.
- Authentication occurs before WebSocket acceptance or audio processing.
- Device identity is bound to the credential; the client cannot assert another identity.
- Gateway-to-OpenClaw credentials are separately scoped and never sent to the skull.
- Logs record credential identifiers, never credential values.
- Failed authentication is rate-limited and observable.
- Tailscale/LAN placement is defense in depth, not a substitute for authentication.

Before any v2 code is pushed, the exposed legacy GitHub PATs must be revoked and remote URLs sanitized.

## 7. Configuration and secrets

Configuration uses validated typed settings with no infrastructure defaults hidden in source code.

Categories:

- Device identity and gateway URL.
- Audio device and codec settings.
- Provider selection and endpoints.
- Timeouts, limits, and fallback policy.
- OpenClaw session target.
- Logging and metrics level.

Secrets are supplied through protected files or the platform secret mechanism. Startup fails with a concise actionable error when required values are absent. Effective configuration output redacts all secret fields.

## 8. Error model

```json
{
  "type": "error",
  "request_id": "uuid",
  "code": "STT_UNAVAILABLE",
  "message": "Speech recognition is temporarily unavailable.",
  "retryable": true,
  "trace_id": "uuid"
}
```

Error categories:

- `AUTHENTICATION_FAILED`
- `PROTOCOL_UNSUPPORTED`
- `INVALID_MESSAGE`
- `PAYLOAD_TOO_LARGE`
- `AUDIO_DEVICE_FAILED`
- `STT_UNAVAILABLE` / `STT_TIMEOUT`
- `OPENCLAW_UNAVAILABLE` / `OPENCLAW_TIMEOUT`
- `TTS_UNAVAILABLE` / `TTS_TIMEOUT`
- `REQUEST_CANCELLED`
- `INTERNAL_ERROR`

User-facing messages never contain stack traces, internal URLs, request bodies, or provider credentials. Detailed exceptions are recorded only in protected structured logs with the trace ID.

## 9. Timeouts, limits, and backpressure

All network calls have explicit connect, read, write, and total deadlines. Initial values are configuration with safe bounds.

Required limits:

- Maximum control-frame size.
- Maximum binary-frame size.
- Maximum utterance duration and encoded bytes.
- Maximum simultaneous requests per device.
- Maximum connected devices.
- Bounded capture, synthesis, and playback queues.
- Maximum response characters and spoken duration.

When consumers fall behind, the system cancels or drops the affected request; it never permits unbounded queue growth.

## 10. Health and observability

### Health

- `/health/live`: process event loop is responsive.
- `/health/ready`: required configuration and the minimum viable provider path are available.
- `/version`: release, Git commit, build timestamp, protocol version, and configuration schema version.

Optional provider failure may produce `degraded` readiness without making liveness fail.

### Metrics

- Interactions by outcome.
- Wake detections and false-activation feedback.
- STT, OpenClaw, TTS, and end-to-first-audio latency histograms.
- Active connections and requests.
- Reconnects, cancellations, timeouts, fallback use, and dropped frames.
- Queue depth and process resource use.

Metrics contain no transcript, raw audio, or credentials.

### Logs

- Structured JSON in production.
- Correlation by device ID, conversation ID, request ID, and trace ID.
- Transcript logging disabled by default.
- Rotation and retention are bounded by deployment configuration.

## 11. Testing strategy

### Unit tests

- State machines and valid/invalid transitions.
- Message validation and protocol compatibility.
- Buffer and size limits.
- Provider error normalization and fallback policy.
- Text segmentation and playback ordering.
- Configuration validation and secret redaction.

### Integration tests

- Skull simulator ↔ gateway protocol.
- Recorded audio fixture → fake STT → fake OpenClaw → fake TTS.
- Real selected providers behind explicit opt-in test markers.
- Cancellation at each pipeline stage.
- Disconnect and reconnect during capture, generation, and playback.

### Hardware tests

- Wake-word detection with positive, negative, and noisy recordings.
- Seeed capture and speaker playback.
- Barge-in under actual speaker bleed.
- Boot, service restart, unplug/replug, and network-loss recovery.

### Security tests

- Unauthenticated and wrongly authenticated connections.
- Oversized and malformed frames.
- Rate limiting and concurrent-request limits.
- Secret scanning, dependency audit, and container configuration checks.

### Soak and performance tests

- 100 scripted interactions with injected provider failures.
- Seven-day idle/periodic-use run.
- Latency regression report generated from fixed audio fixtures.
- Memory, descriptors, threads, and disk usage checked for bounded growth.

## 12. Repository structure

Recommended monorepo for atomic protocol evolution:

```text
omni-vox/
├── docs/
│   ├── product/
│   ├── architecture/
│   └── decisions/
├── packages/
│   ├── protocol/
│   ├── skull-client/
│   └── gateway/
├── tests/
│   ├── fixtures/
│   ├── integration/
│   └── hardware/
├── deploy/
│   ├── skull/
│   └── omnissiah/
└── tools/
    └── skull-simulator/
```

The protocol package owns schemas and golden fixtures. Neither runtime imports code from the other runtime package.

## 13. Delivery and provenance

- Protected `main` branch with reviewed pull requests.
- One worktree/branch per write-heavy task.
- CI creates versioned artifacts from clean commits only.
- Container tags include release and immutable commit SHA.
- Pi packages or release bundles include the same provenance.
- Deployment records the previous version and supports rollback.
- Runtime `/version` output is compared against the intended release after deployment.
- Uncommitted production edits are forbidden.

## 14. Migration and salvage plan

Before implementation:

1. Rotate exposed GitHub credentials.
2. Export and checksum the current GitHub repository state.
3. Export the exact deployed container source and image metadata.
4. Capture the Pi branch, staged changes, unstaged changes, untracked source/artifacts, service unit, package versions, and audio configuration.
5. Create an immutable legacy tag/archive; do not merge the dirty Pi tree wholesale.

Candidate salvage items are evaluated individually with characterization tests:

- Porcupine model and detector behavior.
- ALSA/Seeed audio configuration.
- Opus encoder.
- Audio cue manager.
- Recorder/VAD behavior.
- AEC and barge-in experiments.
- Existing audio and latency fixtures.

Legacy gateway orchestration, custom memory integration, global conversation buffers, direct infrastructure defaults, and unauthenticated API behavior are not migration candidates.

## 15. Quality gates

No production release may proceed unless:

- Product requirements and protocol schemas are current.
- Unit and integration tests pass.
- Type checking and linting pass with no errors.
- Secret scanning finds no credentials.
- Dependency scanning finds no high/critical unresolved vulnerabilities.
- Container and systemd hardening checks pass.
- No production source file exceeds the agreed size threshold without an architectural exception.
- Physical-device acceptance and recovery tests pass.
- The deployed commit and configuration version are verified after installation.

## 16. Approved architectural decisions

Chris approved the following architectural decisions on 2026-07-20:

1. A Python asyncio client and gateway to maximize safe reuse of validated hardware work.
2. A monorepo with a shared versioned protocol package.
3. WebSocket transport with JSON control frames and binary Opus audio.
4. Device-specific authentication in addition to Tailscale/LAN isolation.
5. One dedicated OpenClaw voice session per active conversation.
6. No application-owned durable memory.
7. One primary STT/TTS path plus at most one controlled fallback each.
8. A simulator and recorded fixtures before physical-hardware development.

Changes to these decisions require a documented architecture decision.
