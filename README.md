# Omni Vox 2

Omni Vox 2 is a clean rebuild of Omni's physical voice interface, beginning with the Raspberry Pi 5 servo-skull.

The project is currently documentation-first. No legacy implementation has been imported. The product boundary, architecture, quality targets, and current model research live in `docs/` and should be treated as the source of truth for implementation planning.

## Start here

1. Read [`docs/product-spec.md`](docs/product-spec.md).
2. Read [`docs/architecture-spec.md`](docs/architecture-spec.md).
3. Read [`docs/research/model-selection.md`](docs/research/model-selection.md).
4. Read [`docs/legacy/salvage-guide.md`](docs/legacy/salvage-guide.md) before consulting the prototype.
5. Create a dedicated Git worktree and branch before any write-heavy task.

## Current status

- Product and architecture specifications drafted.
- Voice-model landscape researched.
- Implementation intentionally not started.
- Legacy code remains in the original repositories and deployments for selective salvage.

## Product direction

- The servo-skull is the MVP client.
- The edge device owns wake word, audio capture/playback, cues, and reconnect behavior.
- A small authenticated gateway coordinates STT, OpenClaw, and TTS.
- OpenClaw exclusively owns identity, reasoning, tools, sessions, and durable memory.
- Providers remain replaceable and measurable.
- GitHub must be the reproducible source of truth for every deployment.

## License

MIT. See [`LICENSE`](LICENSE).
