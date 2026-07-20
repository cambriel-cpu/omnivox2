# Omni Vox 2

Omni Vox 2 is a clean rebuild of Omni's physical voice interface, beginning with the Raspberry Pi 5 servo-skull.

The project began with a documentation-first clean rebuild. The approved product
boundary, architecture, quality targets, implementation plan, and current model
research live in `docs/` and remain the source of truth. No legacy implementation
has been imported.

## Start here

1. Read [`docs/product-spec.md`](docs/product-spec.md).
2. Read [`docs/architecture-spec.md`](docs/architecture-spec.md).
3. Read [`docs/protocol-v2.md`](docs/protocol-v2.md) before transport work.
4. Read [`docs/evaluation-harness.md`](docs/evaluation-harness.md) before provider benchmarks.
5. Read [`docs/research/model-selection.md`](docs/research/model-selection.md).
6. Read [`docs/legacy/salvage-guide.md`](docs/legacy/salvage-guide.md) before consulting the prototype.
7. Create a dedicated Git worktree and branch before any write-heavy task.

## Current status

- Product and architecture specifications approved.
- Voice-model landscape researched.
- Initial Python workspace, shared protocol models, and provider-neutral gateway
  pipeline implemented on a feature branch.
- Content-free latency, accuracy, recovery, and cost reports plus an in-process
  skull/gateway simulator cover handshake, request control, audio ordering,
  cancellation, and reconnect isolation; real-provider benchmarks and physical
  acceptance remain pending.
- Legacy code remains in the original repositories and deployments for selective salvage.

## Product direction

- The servo-skull is the MVP client.
- The edge device owns wake word, audio capture/playback, cues, and reconnect behavior.
- A small authenticated gateway coordinates STT, OpenClaw, and TTS.
- OpenClaw exclusively owns identity, reasoning, tools, sessions, and durable memory.
- Providers remain replaceable and measurable.
- GitHub must be the reproducible source of truth for every deployment.

## Development

The initial implementation uses Python 3.12 and an `uv` workspace. Install `uv`,
then run:

```bash
uv sync --all-packages
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy packages tools tests
uv run pip-audit
```

Tests in this phase are hardware-independent. Passing them does not replace the
physical servo-skull acceptance and recovery gates in the product specification.

## License

MIT. See [`LICENSE`](LICENSE).
