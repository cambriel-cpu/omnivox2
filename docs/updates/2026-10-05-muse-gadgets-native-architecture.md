# Update 2026-10-05 — Native-Muse architecture via Muse Gadgets SDK

**Status:** This document supersedes key parts of the July 2026 specs. It is the current
architectural direction. The docs it revises (`architecture-spec.md`, `product-spec.md`,
`research/model-selection.md`) remain in the repo as historical record — do not delete them.

## What changed

On 2026-10-02 Meta launched **Muse Gadgets**: open-source ESP32 firmware + a Linux SDK
(Apache 2.0, `facebookincubator/muse-gadget-sdk`) for DIY hardware that connects to the
Muse AI assistant. Verified in code (not assumed) on 2026-10-05:

- **ESP32 firmware — voice is native, with two gaps.**
  Push-to-talk voice chat is built in (`esp32/main/voice.h`, Kconfig `HOMEHUB_VOICE`):
  hold button → speak → release → audio goes to the agent's chat **as a voice note,
  which Muse transcribes natively**. No self-hosted STT needed. Spoken replies are
  **not** native — *"To speak it, plug a TTS API of your own into `start_tts`."*
  Playback plumbing ships (`voice_player.h`: 16 kHz mono PCM16 → I2S speaker); the TTS
  engine is bring-your-own. **No wake word** — `noise_control.cpp` hard-codes
  `is_wakeup_supported: false`. Button only.
- **Linux SDK — no audio at all.** Verified zero voice/audio mentions across
  `linux/README.md`, `AGENTS.md`, `executor.py` (exactly four commands: `system.run`,
  `file.read`, `file.write`, `device.health`). It is a text/command/file bridge — but
  `system.run` gives Muse a shell on the Pi and `send-user-msg` lets Pi programs push
  text into chats.
- **Camera:** the SenseCAP Watcher profile has `camera.capture` → JPEG (needs PSRAM).
  The Pi camera is better served via the Linux gadget (rpicam stills → `file.read`).

## Decisions

1. **Lean on natively-supported Muse capabilities wherever possible.** The v1
   self-hosted pipeline (Whisper STT, FastAPI gateway, WebSocket/PWA client, Sonos
   path, OpenClaw voice-session transport) is **retired**. Roughly 70% of the old
   stack goes away.
2. **Kokoro TTS survives** as the single plug-in point: it becomes the `start_tts`
   client (OpenAI-compatible endpoint → 16 kHz PCM16 → `voice_player_write`).
   ElevenLabs stays as cloud fallback. Verify Kokoro's output sample rates; resample
   if needed.
3. **No custom wake-word engineering.** No openWakeWord training; the v1 Porcupine
   model is shelved as fallback only. A native "hey Omni" wake word is on Meta's
   near-term roadmap (Ray-Ban Meta glasses work) and should arrive as a firmware/SDK
   update — any custom wake-word work would be throwaway.
4. **Interim trigger: a physical button** (capacitive touch pad or discrete button in
   the skull base). Thematically fine, zero engineering.
5. **Do not bet on native speech-to-speech** in the SDK. The architecture is
   voice-note → text → BYO TTS; nothing in the code suggests a realtime voice model
   is coming to gadgets.

## Target architecture

```
┌─ Servo skull ─────────────────────────────┐
│ ESP32-S3 (reSpeaker Lite + XIAO ESP32-S3) │  ← mic/speaker, native PTT
│  voice notes → Muse (native STT)          │
│  spoken replies ← Kokoro via start_tts    │
│ Pi 5 (Linux gadget, same token/account)   │  ← camera, home commands
└───────────────┬───────────────────────────┘
                │ Tailscale
┌───────────────▼───────────────────────────┐
│ Omnissiah: Kokoro TTS, Home Assistant,   │
│ OpenClaw, heavy lifting                   │
└───────────────────────────────────────────┘
```

- The skull talks in the existing Muse chat — the v2 spec's "one identity, one
  memory authority" principle is satisfied for free.
- Skull board pick: **reSpeaker Lite + XIAO ESP32-S3** (~$25–40), the cheapest
  documented voice path. The ESP32-S3-BOX-3 is overkill (screen the skull doesn't
  need). The reSpeaker Lite needs XMOS 16 kHz I2S firmware v1.0.9 per Seeed's wiki
  (USB-audio/48 kHz images don't match the profile).
- Build requires ESP-IDF v6.0.1 (v5.5 explicitly unsupported).
- One SDK token covers 50 devices; the skull ESP32 and the Pi 5 pair to the same
  account. Pairing: Muse app → Settings → Devices → Developer mode →
  `MuseGadgetXXXXXX`.
- Pi 5: flash Pi OS, run `linux/install.sh` with the SDK token, pair. Wire rpicam
  stills into something Muse can read (board-state questions mid-game).
- **Caveat (SDK terms):** not a supported product — Meta may change, break, or
  withdraw access at any time. Nothing load-bearing goes through this path.

## Build list

1. Order skull board: reSpeaker Lite + XIAO ESP32-S3.
2. Flash XMOS 16 kHz I2S firmware v1.0.9 on the reSpeaker Lite.
3. Set up ESP-IDF v6.0.1; build the `muse` profile with the SDK token; pair.
4. Write the `start_tts` client (Kokoro `:8880` → 16 kHz PCM16 → `voice_player_write`).
5. Pi 5: Pi OS + `linux/install.sh` + pair; rpicam stills wiring.
6. Retire: Whisper service, FastAPI gateway, WebSocket/PWA client, Sonos path.
7. Security: treat all historical credential material in v1 repos as revoked; nothing
   gets copied.

## Unverified (check at build time)

- Whether the SDK token requires a paid Muse plan.
- Exact `start_tts` signature (hook confirmed via `voice.h` + Kconfig; implementation
  file not pulled during research).
- Whether voice notes land in the main chat or a separate device chat.
- End-to-end PTT → transcription → reply latency (untestable without hardware).
