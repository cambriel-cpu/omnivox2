# Omni Vox v2 — Product Specification

Status: Draft for decision
Owner: Chris Langston
Primary device: Servo-skull (Raspberry Pi 5)

## 1. Product definition

Omni Vox v2 is the reliable voice interface that gives Omni a physical presence through the servo-skull.

The servo-skull is the product. Omni Vox is the small, headless gateway that connects the skull's audio hardware to speech recognition, OpenClaw, and speech synthesis. OpenClaw remains the authority for Omni's identity, reasoning, tools, sessions, and durable memory.

## 2. Why rebuild

The existing system proved the concept but has no trustworthy source of truth:

- GitHub, the deployed container, the workspace copy, and the Pi contain different code.
- The Pi has substantial uncommitted changes and no running voice service.
- The gateway mixes transport, UI, providers, memory, Sonos, and orchestration in one large module.
- Authentication, isolation, tests, deployment provenance, and failure handling are insufficient for an always-on household device.
- Some integrations target retired infrastructure or superseded OpenClaw behavior.

Version 2 will preserve validated audio and wake-word work while rebuilding the product boundary and delivery process.

## 3. Product principles

1. **Voice is an interface to Omni, not a separate Omni.** There is one identity and one memory authority: OpenClaw.
2. **The skull must fail visibly and recover automatically.** Silence is never an acceptable error state.
3. **Local-first and private by default.** Traffic stays on the trusted LAN/Tailscale mesh; no public port is required.
4. **Providers are replaceable.** STT and TTS services may be local or cloud-based without changing the device protocol.
5. **The edge stays thin.** The Pi owns hardware interaction, not business logic or durable conversation state.
6. **Every deployment is reproducible.** A running service must identify its source commit and configuration version.
7. **Measured quality beats feature accumulation.** Latency, transcription accuracy, interruption behavior, and recovery are release criteria.

## 4. Primary user and job

### Primary user

Chris, speaking naturally to Omni through a dedicated physical device in the home.

### Core job

> When my hands or attention are occupied, I want to wake Omni, speak naturally, and hear a useful response without opening another device.

### Secondary users

Household support may be added later, with explicit identity, privacy, and permission rules. It is not part of the first production release.

## 5. Core experience

1. The skull indicates that it is idle and listening only for the local wake word.
2. Chris says “Hey Omni.”
3. The skull immediately acknowledges detection with a short audio/visual cue.
4. The skull captures the utterance and indicates that it is listening.
5. The gateway transcribes the audio and sends the text to a dedicated OpenClaw voice session.
6. Omni's response is synthesized and played as soon as useful audio is available.
7. Chris can interrupt playback and continue the conversation.
8. The skull returns to idle after the conversation times out or Chris ends it.

At every stage, the device communicates one of a small number of understandable states: idle, listening, thinking, speaking, unavailable, or reconnecting.

## 6. Scope

### MVP: in scope

- Raspberry Pi 5 and Seeed voice hardware support.
- Local Porcupine “Hey Omni” wake word.
- Microphone capture with bounded recording duration.
- Voice activity detection and end-of-speech detection.
- Opus transport from skull to gateway.
- Authenticated, versioned device connection over the trusted network.
- Replaceable STT provider interface with one production provider.
- Dedicated OpenClaw voice session with streaming text responses.
- Replaceable TTS provider interface with one production provider and one fallback.
- Incremental response playback.
- Cancellation and barge-in.
- Audible/visual state and error cues.
- Automatic reconnect with bounded backoff.
- Structured logs, health status, latency metrics, and exact build version.
- Hardware-independent protocol and pipeline tests.
- A minimal command-line diagnostic client.

### Later

- Household voice identity and individualized permissions.
- Browser/PWA voice client.
- Sonos playback.
- Multiple skulls or room devices.
- Fully local inference fallback.
- Advanced acoustic echo cancellation.
- Offline command subset.
- Remote fleet administration.

### Explicitly out of scope for MVP

- A second memory database or transcript knowledge store.
- Direct access from the public internet.
- General-purpose home automation implemented inside Omni Vox.
- Model selection controls exposed to the user during conversation.
- Voice cloning work beyond selecting an already approved TTS voice.
- Recreating every feature present in the old prototype.

## 7. Functional requirements

### FR-1: Wake and acknowledge

- Wake-word detection runs locally on the skull.
- Raw idle audio never leaves the device.
- Detection produces acknowledgement feedback within 250 ms.
- False activations can be counted without retaining raw audio.

### FR-2: Capture speech

- Recording starts immediately after acknowledgement.
- Speech capture ends on validated silence, explicit cancellation, or a hard maximum duration.
- Empty/noise-only captures return the device to idle without contacting OpenClaw.
- Audio buffers and message sizes are bounded.

### FR-3: Establish a trusted session

- Each skull has a unique device identity and revocable credential.
- The gateway rejects missing, invalid, expired, or unauthorized credentials.
- Protocol compatibility is negotiated before audio is accepted.
- Reconnection does not silently merge two logical conversations.

### FR-4: Transcribe

- The gateway sends audio through the selected STT provider interface.
- Empty, low-confidence, timed-out, and unavailable responses have distinct outcomes.
- A confirmed transcript is associated with one conversation and one request ID.

### FR-5: Ask Omni

- The gateway sends the transcript to a dedicated OpenClaw voice session.
- OpenClaw supplies identity, memory, model routing, tool policy, and response behavior.
- Omni Vox does not duplicate or persist its own long-term memory.
- The gateway supports incremental response text and cancellation.

### FR-6: Speak

- The gateway synthesizes useful response units without waiting for the entire answer.
- Audio chunks retain request and sequence identifiers.
- The skull begins playback as soon as a valid initial buffer is available.
- A provider failure may trigger one configured fallback; fallback loops are forbidden.

### FR-7: Interrupt

- Speech detected during playback can stop local playback and cancel upstream generation.
- Cancellation is idempotent.
- Late audio from a cancelled request is discarded.

### FR-8: Recover

- Network and service failures produce a clear unavailable/reconnecting cue.
- The client reconnects using capped exponential backoff with jitter.
- A reboot returns the skull to a known idle state without manual terminal work.
- Dependency failure must not create an infinite crash or restart loop.

### FR-9: Diagnose

- The skull reports device, audio, connection, and current-state health.
- The gateway reports liveness separately from dependency readiness.
- Logs correlate one interaction across skull, gateway, STT, OpenClaw, and TTS using a request ID.
- Health and version output never expose credentials or transcript content.

## 8. Non-functional requirements

### Performance targets

- Wake acknowledgement: less than 250 ms at p95.
- End of speech to confirmed transcript: less than 2.5 seconds at p50 and 5 seconds at p95.
- End of speech to first spoken response audio: less than 4 seconds at p50 and 8 seconds at p95.
- Barge-in to playback stop: less than 300 ms at p95.
- Idle Pi CPU usage: target below 15% averaged over five minutes.

Targets are measured on the actual home network and skull hardware. They may be revised only with recorded benchmark evidence.

### Reliability targets

- Survive 100 consecutive scripted interactions without a process crash or wedged state.
- Recover automatically after gateway restart, network interruption, and individual provider restart.
- Operate for seven days without unbounded memory, file, or log growth.
- No duplicate spoken response after reconnect or retry.

### Security and privacy

- No embedded secrets in code, images, Git remotes, logs, or test fixtures.
- No public network exposure.
- Device authentication is mandatory even on the LAN/Tailscale mesh.
- Credentials are independently revocable and minimally scoped.
- Raw audio is not retained by default.
- Transcript persistence follows OpenClaw's session/memory policy; Omni Vox creates no parallel archive.
- Error responses are safe for users; detailed exceptions stay in protected logs.
- Input size, duration, concurrency, and rate limits are enforced.

### Maintainability

- Provider implementations conform to small tested interfaces.
- Hardware-specific modules can be tested with recorded fixtures and fakes.
- Production files should remain below 300 lines unless an exception is documented.
- CI must run tests, linting, type checks, dependency audit, and secret scanning.

## 9. Success criteria

MVP is complete only when:

- A fresh Pi installation can be provisioned from the repository documentation.
- The installed service starts at boot and reports the exact deployed commit.
- The core wake → listen → transcribe → reason → speak loop passes on the physical skull.
- Cancellation, provider failure, gateway restart, and network loss tests pass.
- The latency and seven-day reliability targets are measured and recorded.
- No high/critical security findings or committed secrets remain.
- GitHub is the verified source of truth for both build artifacts and deployment configuration.
- The old deployment can remain archived without being required at runtime.

## 10. Release stages

### Stage 0: Preserve and secure

- Rotate exposed GitHub credentials.
- Capture immutable archives of GitHub main, the deployed image source, and the Pi working tree.
- Record hardware and audio-device configuration.

### Stage 1: Hardware loop

- Boot service, wake detection, capture, local playback, state cues, and diagnostics.
- No LLM dependency.

### Stage 2: Remote pipeline

- Authenticated protocol, STT, OpenClaw, TTS, cancellation, and reconnect.

### Stage 3: Production hardening

- Fault injection, soak testing, metrics, security gates, reproducible deployment, and rollback.

### Stage 4: Experience improvements

- Barge-in tuning, latency optimization, better acoustic processing, and optional clients.

## 11. Product decisions requested

The draft assumes:

1. The servo-skull is the sole MVP client; the PWA is deferred.
2. OpenClaw is the sole memory and personality authority.
3. The system may use cloud inference when it materially improves quality, while preserving provider portability.
4. Raw audio is not retained by default.
5. The initial product recognizes Chris only; household identity is deferred.
6. Sonos is not part of the core voice loop.

These decisions should be confirmed before implementation planning.
