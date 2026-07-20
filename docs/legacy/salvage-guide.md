# Legacy Salvage Guide

Omni Vox 2 starts with a clean history. The original prototype proved useful hardware and audio concepts, but its repository, deployed gateway, and servo-skull checkout diverged. None is a trustworthy source of truth by itself.

## Where to look

### Original GitHub repository

- Repository: <https://github.com/cambriel-cpu/omni-vox>
- Use it to inspect committed gateway history, especially the later sentence-streaming and TTS-provider experiments.
- Treat every remote URL or historical configuration as potentially containing revoked credentials. Never copy credential material.

### Historical gateway deployment on Omnissiah

- The previously running image was `omni-vox:v2.5.8`.
- During the July 2026 audit, its source matched the legacy OpenClaw workspace copy at `/root/.openclaw/workspace/scripts/voice-gateway`, not GitHub `main`.
- The image was built before the later GitHub streaming changes. Inspect it only when comparing actual deployed behavior with repository history.
- Do not make it a build dependency and do not assume it is still running.

### Servo-skull working tree

- Host: Raspberry Pi 5 known as `servo-skull`, reachable through the private Tailscale mesh when online.
- During the July 2026 audit, its checkout was on an older March feature branch with substantial staged, unstaged, and untracked work.
- The voice service was disabled and inactive; the Seeed audio-driver service was active.
- Before salvage, capture its branch, commit, `git status`, diff, untracked file inventory, service units, package versions, and audio-device configuration without modifying them.

## Likely salvage candidates

- Custom Porcupine wake-word model and pinned runtime details.
- Seeed microphone/audio-device configuration.
- Opus encoding and playback experiments.
- Audio cues and physical playback controls.
- VAD and bounded recording behavior, after removing runtime downloads.
- Recorded audio and evaluation fixtures, after privacy review.
- AEC and barge-in experiments as optional modules.

## What not to carry forward by default

- The monolithic gateway server.
- Parallel memory or personality systems.
- Global conversation state.
- Unauthenticated WebSocket or voice endpoints.
- Permissive CORS settings.
- Hard-coded addresses, model IDs, secrets, or personal behavior.
- Dynamic Torch Hub downloads or `trust_repo=True` startup behavior.
- Retired Qdrant or Mem0 integrations.
- Sonos or PWA features before the servo-skull MVP is reliable.

## Salvage procedure

For each candidate:

1. Record its exact provenance: repository/host, branch or image, commit if known, file path, and audit date.
2. Explain the user or hardware problem it solves.
3. Extract the smallest useful behavior or artifact; do not copy a subsystem wholesale.
4. Remove secrets, machine-specific paths, and obsolete integrations.
5. Define its interface against the v2 architecture.
6. Add a failing hardware-independent test or golden fixture.
7. Reimplement or import the bounded artifact.
8. Verify on a simulator before testing on the physical skull.
9. Record benchmark or hardware evidence and the deployed commit.

If provenance cannot be established or the behavior cannot be tested independently, leave it behind.
