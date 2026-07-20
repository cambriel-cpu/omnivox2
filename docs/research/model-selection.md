# Omni Vox v2 — Voice Model Selection Research

Status: Initial recommendation; benchmark required
Research date: 2026-07-20

## 1. Executive recommendation

Use a **hybrid cascaded pipeline** as the production foundation:

1. Local wake word, capture, cues, encoding, and playback on the servo-skull.
2. Streaming STT with explicit turn detection.
3. OpenClaw as the sole reasoning, identity, tool, session, and memory authority.
4. Streaming TTS through a replaceable provider.
5. Local STT/TTS as privacy and outage fallbacks after the primary path is stable.

Run a **native speech-to-speech challenger** in parallel, led by OpenAI GPT-Realtime-2.1 Mini and GPT-Realtime-2.1. Promote it only if an integration spike proves that it can preserve OpenClaw ownership without duplicating agent state or adding an awkward tool round trip.

Do not make a self-hosted native speech model the v2 foundation on current hardware. Omnissiah has an RTX 4070 Ti Super with 16 GB VRAM. Current open native-dialogue options either exceed that supported envelope or require experimental quantization and operational compromises.

## 2. What changed since the original project

The old architecture assumed separate STT, text reasoning, and TTS services. That remains viable, but it is no longer the only serious option.

Current native realtime models can:

- Consume and generate audio directly.
- Preserve prosody, emotion, hesitation, and some acoustic context that transcription discards.
- Detect speech turns and interruption as part of the model interaction.
- Begin speaking before a complete textual response exists.
- Use tools during a live speech session.

The tradeoff is architectural: a native voice model wants to own the conversation loop. Omni already has a mature owner for that loop—OpenClaw. Using both without a clear boundary risks duplicated prompts, memory, tool policy, context, and billing.

## 3. Architecture options

### Option A: Cascaded cloud pipeline

```text
Wake/VAD → streaming cloud STT → OpenClaw → streaming cloud TTS
```

Strengths:

- Clean OpenClaw integration.
- Best provider interchangeability.
- Transcripts make debugging, evaluation, safety, and memory behavior inspectable.
- Each stage can be benchmarked and replaced independently.
- Lowest local operational burden.

Weaknesses:

- Network and queue latency accumulate across three services.
- Text transcription loses some prosody and emotion.
- Turn-taking and barge-in require explicit coordination.
- Multiple provider accounts may be needed.

Verdict: **Best production starting point.**

### Option B: Cascaded self-hosted pipeline

```text
Wake/VAD → local STT → OpenClaw → local TTS
```

Strengths:

- Audio remains inside the trusted network except for the OpenClaw reasoning request.
- Predictable marginal cost.
- Works during speech-provider outages.
- Current GPU can comfortably host practical STT and lightweight TTS models.

Weaknesses:

- GPU scheduling, model loading, containers, updates, and monitoring become our responsibility.
- Voice quality and turn detection may trail leading hosted services.
- Simultaneously resident STT, TTS, and other GPU workloads compete for 16 GB VRAM.
- The previous local stack already demonstrated operational drift.

Verdict: **Valuable fallback and privacy mode, not the first production milestone.**

### Option C: Cloud-native speech-to-speech

```text
Wake/audio → realtime multimodal model → spoken response
```

Strengths:

- Most natural turn-taking, emotion, cadence, and interruption potential.
- Fewer application-level pipeline stages.
- Modern models support tools and live session control.
- Lowest likely time-to-first-audio.

Weaknesses:

- The realtime model becomes an agent runtime, competing with OpenClaw.
- Harder to preserve one canonical personality, memory, and tool-policy path.
- Debugging is less transparent than a textual boundary.
- Audio token costs and long-session context can be less predictable.
- Provider lock-in is much stronger.

Verdict: **Must benchmark; do not adopt until the OpenClaw boundary is proven.**

### Option D: Self-hosted native speech-to-speech

Strengths:

- Maximum privacy and local control.
- No per-interaction API cost.
- Interesting full-duplex research path.

Weaknesses:

- Current production-grade open models exceed or strain 16 GB VRAM.
- Model quality, voice choice, tool integration, and instruction following may lag hosted systems.
- Quantization and custom serving would dominate the project.
- It would turn a product effort back into infrastructure research.

Verdict: **Research only on current hardware.**

## 4. Candidate models and services

### 4.1 Native cloud speech

#### OpenAI GPT-Realtime-2.1 Mini

Best initial native challenger.

- Distilled reasoning voice model with audio/text input and output.
- 128k context and function calling.
- Officially positioned for faster, lower-cost realtime voice.
- Improved alphanumeric recognition compared with Realtime 2.
- Audio pricing: $10/M input audio tokens and $20/M output audio tokens.

Why test it: it is the most plausible cost/latency production native path.

Source: <https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini>

#### OpenAI GPT-Realtime-2.1

Native quality ceiling challenger.

- Adds configurable reasoning, stronger tool use, and improved silence, noise, and interruption behavior.
- 128k context.
- Audio pricing: $32/M input audio tokens and $64/M output audio tokens.
- Higher reasoning effort may add latency and output usage.

Why test it: establishes how much conversational quality Mini leaves on the table.

Source: <https://developers.openai.com/api/docs/models/gpt-realtime-2.1>

#### Gemini Live

Secondary native challenger.

- Continuous native audio, text, and vision interaction.
- Suitable for robotics and next-generation interfaces.
- The Live API remains Preview as of this research date.
- Google documents cumulative context reprocessing and audio-token billing across turns; context compression is important for cost control.

Why not lead with it: Preview maturity and compounding session economics add risk, while OpenClaw integration remains unresolved.

Sources:

- <https://ai.google.dev/gemini-api/docs/live-api>
- <https://ai.google.dev/gemini-api/docs/live-api/best-practices>
- <https://ai.google.dev/gemini-api/docs/pricing>

### 4.2 Streaming STT

#### Deepgram Flux

Leading cascaded STT candidate for conversational behavior.

- Purpose-built streaming STT for voice agents.
- Integrates end-of-turn and eager-end-of-turn signals.
- Exposes tunable thresholds and hard turn timeouts.
- Designed to support interruption and sub-second agent pipelines.

Why test it: turn detection is likely more important to perceived naturalness than small WER differences.

Sources:

- <https://developers.deepgram.com/docs/flux/agent>
- <https://developers.deepgram.com/docs/configure-voice-agent>

#### OpenAI GPT-Realtime-Whisper

Leading simple streaming STT candidate.

- Live transcript deltas through realtime transcription sessions.
- Explicit duration pricing of $0.017 per audio minute.
- Very fast according to the official model card.

Why test it: simple economics, strong integration ecosystem, and a clean textual handoff to OpenClaw.

Source: <https://developers.openai.com/api/docs/models/gpt-realtime-whisper>

#### ElevenLabs Scribe v2 Realtime

Strong accuracy/latency challenger.

- Approximately 150 ms reported latency.
- Keyterm prompting for names and domain vocabulary.
- Advertised from $0.28/hour.

Why test it: proper nouns such as Omnissiah, Servo-skull, family names, and project names are historically important failure cases.

Sources:

- <https://elevenlabs.io/docs/overview/capabilities/speech-to-text/>
- <https://elevenlabs.io/realtime-speech-to-text>

#### Local faster-whisper

Local baseline and fallback.

- Already familiar and compatible with the 16 GB GPU.
- No audio leaves the trusted network.
- Existing historical evaluation data can seed regression tests.

Why not assume it wins: the old deployment is stale, and conversational endpointing—not just batch transcription accuracy—must be re-evaluated.

### 4.3 Text reasoning through OpenClaw

The production cascaded path should benchmark the currently available OpenClaw voice route rather than hard-code a remembered model ID.

Current OAuth-visible candidates include GPT-5.6 Sol, Luna, and Terra. The benchmark should compare:

- Time to first text token.
- Time to first speakable segment.
- Tool-selection reliability.
- Concision when spoken.
- Correct use of Omni identity and memory.
- Subscription usage impact.

The voice route should use the lowest reasoning effort that passes the task suite. Long or tool-heavy work can acknowledge quickly, then continue through OpenClaw with a short spoken preamble.

### 4.4 Streaming TTS

#### ElevenLabs Flash v2.5

Leading low-latency cascaded TTS candidate.

- Approximately 75 ms model inference claim for short inputs.
- WebSocket support for incremental LLM text.
- Opus output is available.
- Broad voice selection and cloning options.

Official documentation cautions that end-to-end first audio also includes network, queueing, and playback buffering; we must measure on Omnissiah.

Sources:

- <https://elevenlabs.io/docs/overview/capabilities/text-to-speech>
- <https://elevenlabs.io/docs/api-reference/reducing-latency>

#### Eleven v3 Conversational

Expressiveness challenger.

- Context-aware delivery and richer emotional control.
- Optimized for live conversation.
- Does not necessarily preserve professional voice-clone characteristics.

Why test it: establishes whether a more expressive Omni voice is worth added provider coupling or latency.

Source: <https://elevenlabs.io/docs/eleven-agents/customization/voice/expressive-mode>

#### Local Kokoro and Chatterbox

Local fallback candidates.

- Kokoro is lightweight and previously fast enough for interactive use.
- Chatterbox may better preserve the custom Drogan-style voice.

Neither old container should be accepted as the v2 implementation. Models, serving projects, licenses, GPU use, streaming behavior, and current maintenance status must be re-evaluated from clean deployments.

### 4.5 Self-hosted native models

#### Moshi

- Open full-duplex spoken-dialogue system with a practical latency reported around 200 ms on an L4 GPU.
- Official repository says the PyTorch path needs significant GPU memory and cites 24 GB; quantized paths are experimental or backend-specific.

Verdict: valuable research reference, not a 16 GB production baseline.

Source: <https://github.com/kyutai-labs/moshi>

#### Qwen3-Omni

- Open, natively multimodal model with real-time speech generation.
- Official repository lists roughly 79 GB minimum BF16 memory for the full 30B-A3B Instruct model in a representative case.

Verdict: not appropriate for Omnissiah's current GPU as the production model.

Source: <https://github.com/QwenLM/Qwen3-Omni>

## 5. Recommended v2 provider policy

### Initial production candidate

- Wake: local Porcupine.
- Capture/encoding: local VAD plus Opus on the skull.
- STT: benchmark winner between Deepgram Flux and GPT-Realtime-Whisper.
- Reasoning: dedicated OpenClaw voice session using the fastest model that passes the behavior suite.
- TTS: ElevenLabs Flash v2.5 as latency candidate, with voice-quality comparison against v3 Conversational.
- Local fallback: clean faster-whisper plus clean Kokoro deployment after the cloud baseline works.

### Native challenger

- GPT-Realtime-2.1 Mini first.
- GPT-Realtime-2.1 as quality ceiling.
- Reasoning effort starts at low.
- Test two integration boundaries:
  1. Realtime model owns the live agent and receives narrowly scoped OpenClaw-backed tools/context.
  2. Realtime model acts only as a speech shell around an OpenClaw response.

The second boundary may erase native latency and prosody benefits; it must not be assumed viable.

## 6. Evaluation design

Build the evaluation harness before choosing providers.

### Dataset

Use 40–60 recorded utterances from the actual skull microphone:

- Quiet room, HVAC noise, television, music, and speaker echo.
- Short commands, natural questions, pauses, corrections, and interruptions.
- Names and vocabulary: Omni, Omnissiah, Ashley, Isabel, Maggie, Servo-skull, Tailscale, Obsidian, Chatterbox, Kokoro.
- Questions requiring memory, tools, clarification, and refusal.
- Negative samples and accidental wake-word-like speech.

Raw personal audio remains private and outside the public repository. Derived non-sensitive metrics may be committed.

### Measurements

- Wake false accept/reject rates.
- STT WER plus proper-noun accuracy.
- End-of-turn false cutoff and hesitation rate.
- End of speech to transcript finalization.
- End of speech to first model text.
- End of speech to first audible sample.
- Barge-in to playback stop.
- Task correctness and OpenClaw tool behavior.
- Voice naturalness, identity fit, consistency, and listening fatigue.
- Recovery after packet loss, provider timeout, and gateway restart.
- Cost per 100 representative interactions.

### Decision rule

The production choice must:

1. Pass security and OpenClaw ownership constraints.
2. Meet p95 latency and reliability targets from the product spec.
3. Complete the task suite without material identity or memory regression.
4. Beat the local baseline enough to justify recurring cloud cost.
5. Keep a documented fallback and provider exit path.

## 7. Billing implication

OpenAI API usage is billed separately from a ChatGPT subscription. The existing ChatGPT/Codex OAuth login does not by itself fund Realtime, transcription, or speech API calls.

Sources:

- <https://help.openai.com/en/articles/8156019-is-api-usage-included-in-chatgpt-subscriptions-even-if-i-have-a-paid-chatgpt-account>
- <https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform>

No paid provider should be enabled without:

- A user-approved account and credential path.
- Prepaid or capped billing where available.
- Usage metrics and a monthly alert threshold.
- A kill switch that does not disable the local device health path.

## 8. Immediate next step

After credential rotation and legacy preservation, implement only the provider-neutral evaluation harness and skull simulator. Use it to run four focused spikes:

1. Local faster-whisper + OpenClaw + local Kokoro baseline.
2. Streaming cloud STT + OpenClaw + ElevenLabs streaming TTS.
3. GPT-Realtime-2.1 Mini native speech.
4. GPT-Realtime-2.1 native quality ceiling.

Choose the production architecture from measured results before implementing the full device client.
