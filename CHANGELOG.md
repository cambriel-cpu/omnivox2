# Changelog

All notable changes to Omni Vox 2 will be documented here.

## Unreleased

### Added

- Product specification for the servo-skull MVP.
- Secure, provider-neutral architecture specification.
- Initial voice model and deployment strategy research.
- Legacy archaeology and selective salvage guide.
- Repository-wide agent workflow and quality gates.

## [2026-10-05] — Native-Muse architecture update

### Changed

- New architectural direction in `docs/updates/2026-10-05-muse-gadgets-native-architecture.md`:
  Meta's Muse Gadgets SDK (launched 2026-10-02) makes ~70% of the planned v2 stack
  unnecessary. ESP32 firmware provides native push-to-talk voice (voice note → Muse
  transcribes); spoken replies are bring-your-own-TTS via a `start_tts` hook, which
  the self-hosted Kokoro fills. Linux SDK has no audio — Pi 5 becomes the camera +
  home-commands gadget. Self-hosted Whisper, the gateway, WebSocket/PWA client, and
  Sonos path are retired. No custom wake-word engineering: a native "hey Omni" wake
  word is on Meta's roadmap, so the interim trigger is a physical button. The July
  2026 specs remain as historical record.
