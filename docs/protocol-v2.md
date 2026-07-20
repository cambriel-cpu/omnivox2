# Omni Vox 2 — Device Protocol v2

Status: Approved implementation baseline
Protocol major version: 2

## 1. Scope

Protocol v2 defines the authenticated WebSocket boundary between a servo-skull
client and the Omni Vox gateway. It carries control messages and encoded audio; it
does not define STT, OpenClaw, or TTS provider APIs.

The protocol is hardware-independent and must be exercised by golden fixtures and
the skull simulator before physical-device integration.

## 2. Connection and authentication

- The client connects to `/api/v2/devices/connect` using WSS.
- Authentication completes before WebSocket acceptance or message processing.
- The authenticated credential determines `device_id`; the hello message cannot
  grant or change identity.
- Credentials never appear in control messages, URLs, logs, fixtures, or metrics.
- One authenticated WebSocket represents one device session.
- A reconnect creates a new device session. Protocol v2 has no conversation-resume
  operation, so an interrupted request is not silently continued.

## 3. Control-frame encoding

- Control frames are WebSocket text frames containing one UTF-8 JSON object.
- JSON member names are lowercase `snake_case`.
- Unknown members and unknown message types fail closed with `INVALID_MESSAGE`.
- Integers are JSON integers, not strings or floating-point values.
- UUIDs use canonical lowercase hyphenated text.
- Encoders emit compact JSON with lexicographically sorted keys and capability
  lists. Decoders do not depend on member order or insignificant whitespace.
- A control frame is rejected before JSON parsing if it exceeds the negotiated
  `max_control_frame_bytes` value.

The implementation baseline is 16,384 bytes. The gateway may negotiate a lower
value but never a higher value without a protocol revision.

## 4. Handshake

The first client message is `hello`:

```json
{
  "capabilities": ["barge-in", "opus-input", "opus-output"],
  "client_version": "git-sha-or-release",
  "device_id": "servo-skull-primary",
  "protocol_version": 2,
  "type": "hello"
}
```

Constraints:

- `device_id`: 1–64 characters matching `[a-z0-9][a-z0-9-]*` and equal to the
  authenticated device identity.
- `client_version`: 1–128 printable ASCII characters.
- `capabilities`: at most 32 unique identifiers matching
  `[a-z0-9][a-z0-9-]*`, each at most 64 characters.
- `protocol_version`: exactly `2`.

The gateway replies with `welcome`:

```json
{
  "capabilities": ["barge-in", "opus-input", "opus-output"],
  "heartbeat_interval_ms": 15000,
  "limits": {
    "max_binary_frame_bytes": 65536,
    "max_control_frame_bytes": 16384,
    "max_queue_depth": 32,
    "max_utterance_ms": 30000
  },
  "protocol_version": 2,
  "session_id": "00000000-0000-4000-8000-000000000001",
  "type": "welcome"
}
```

Audio is rejected until `welcome` is sent. A major-version mismatch closes the
connection after a safe `PROTOCOL_UNSUPPORTED` error when possible.

## 5. Interaction control envelope

Every request-scoped control message has this exact envelope:

```json
{
  "conversation_id": "00000000-0000-4000-8000-000000000002",
  "payload": {},
  "protocol_version": 2,
  "request_id": "00000000-0000-4000-8000-000000000003",
  "sequence": 0,
  "type": "wake"
}
```

Constraints:

- `conversation_id` and `request_id` are canonical UUIDs.
- `sequence` is an unsigned 32-bit integer, scoped to one request and one sender.
- The first control sequence is `0`; later frames increment by exactly one.
- `payload` is always an object, including for messages with no fields.

Message payloads:

| Direction | Type | Payload |
| --- | --- | --- |
| Client → gateway | `wake` | Empty object. |
| Client → gateway | `utterance_start` | `codec: "opus"`, `sample_rate_hz: 48000`, `channels: 1`. |
| Client → gateway | `utterance_end` | `final_audio_sequence: uint32`. |
| Either | `cancel` | `reason` set to `barge_in`, `user`, or `system`. |
| Gateway → client | `transcript` | `text: string`, optional `confidence: 0..1`. |
| Gateway → client | `response_segment` | `text: string`, `segment_sequence: uint32`. |
| Gateway → client | `audio_start` | `codec: "opus"`, `sample_rate_hz: 48000`, `channels: 1`. |
| Gateway → client | `audio_end` | `final_audio_sequence: uint32`. |
| Either | `state` | `name` set to a canonical state below. |
| Either | `error` | `code`, safe `message`, `retryable`, and `trace_id`. |

Canonical state names are `booting`, `connecting`, `idle`, `listening`,
`thinking`, `speaking`, `unavailable`, and `reconnecting`.

An `error` payload uses one of the v2 error codes listed in section 9,
requires a strict JSON boolean for `retryable`, and carries a canonical UUID
`trace_id`. Its user-safe `message` is 1–256 printable Unicode characters and
must not contain control characters. The error retains the interaction envelope
so the receiver can enforce request correlation and sender sequence ordering.

Transcript and response text are required on the wire but remain sensitive:
logging and metrics must omit their payloads by default.

## 6. Heartbeats

Heartbeats are connection-scoped and do not use the interaction envelope:

```json
{"nonce":"opaque-bounded-value","protocol_version":2,"type":"ping"}
```

`pong` repeats the exact nonce. A nonce is 1–64 printable ASCII characters.
Heartbeat timeout and reconnect behavior are transport policy, not conversation
state.

## 7. Binary audio frames

Audio uses WebSocket binary frames. Every frame begins with a fixed 28-byte header
in network byte order:

| Offset | Bytes | Field | Definition |
| ---: | ---: | --- | --- |
| 0 | 2 | Magic | ASCII `OV` (`0x4f56`). |
| 2 | 1 | Protocol version | Unsigned integer `2`. |
| 3 | 1 | Flags | Bit 0 is end-of-stream; bits 1–7 must be zero. |
| 4 | 1 | Codec | `1` means Opus. Other values are unsupported in v2. |
| 5 | 3 | Reserved | All zero; nonzero values fail closed. |
| 8 | 16 | Request ID | UUID bytes in RFC 4122/network order. |
| 24 | 4 | Sequence | Unsigned 32-bit audio sequence. |
| 28 | N | Payload | Encoded audio bytes. |

The negotiated `max_binary_frame_bytes` value includes the header. The
implementation baseline is 65,536 bytes. Payloads are non-empty except that a
zero-length payload is allowed when the end-of-stream flag is set.

Audio sequence numbers start at `0` independently in each direction and increment
by exactly one. Duplicate, stale, skipped, unknown-request, oversized, malformed,
or post-cancellation frames are rejected and never played.

## 8. Cancellation and terminal behavior

- `cancel` is idempotent for a request.
- The receiver stops accepting or emitting new request output immediately.
- Upstream generation is cancelled where supported.
- Late text and audio for the cancelled request are discarded.
- A request has exactly one terminal outcome: completed, cancelled, or failed.
- A fallback provider is attempted at most once and cannot restart a cancelled
  request.

## 9. Error handling

The v2 error codes are:

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

User-safe error messages never contain stack traces, internal URLs, raw request
bodies, transcripts, audio, or credentials. Detailed protected logs correlate by
trace ID without copying sensitive payloads.

## 10. Compatibility and fixtures

- Major-version mismatch fails closed.
- Optional features require mutual capability negotiation.
- Unknown message types and nonzero reserved binary fields fail closed.
- The gateway supports only the compatibility window explicitly listed in release
  documentation.

Golden fixtures cover, at minimum:

- Canonical `hello` and `welcome` control frames.
- One request-scoped message of every type.
- Ping and pong.
- Opus audio with and without the end-of-stream flag.
- Unsupported versions, unknown fields, malformed UUIDs, invalid sequences,
  oversized frames, reserved bits, and truncated headers.

The skull simulator must use the same public codec as the real client. Simulator
success is necessary but does not satisfy physical-device acceptance.
