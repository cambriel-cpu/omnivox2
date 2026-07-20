# AGENTS.md

## Project workflow

- Read `README.md` and the relevant files under `docs/` before planning implementation.
- Documentation precedes code. Update requirements and architecture decisions before changing behavior.
- One write-heavy task equals one Git worktree and one feature branch. Never run concurrent editing sessions in the same checkout.
- Create worktrees under `$CODEX_HOME/worktrees` unless the task is read-only or the user explicitly chooses the primary checkout.
- Do not import legacy code wholesale. Consult `docs/legacy/salvage-guide.md`, identify a bounded artifact, document why it is still appropriate, and bring it across with tests.
- Use test-driven development: write and observe a failing test before implementing behavior.
- Preserve provider boundaries. OpenClaw owns personality, reasoning, tools, sessions, and memory.
- Never commit credentials, device secrets, raw household audio, personal transcripts, or environment-specific endpoints.
- No public network exposure. Authentication is required even on trusted LAN or Tailscale routes.
- Do not push, open or merge pull requests, deploy, change DNS, or alter Cloudflare resources unless the current user request authorizes that external action.

## Quality gates

Before declaring implementation complete:

- Tests pass.
- Type checking and linting pass.
- Dependency and secret scans pass.
- Production source files remain focused; document exceptions above 300 lines.
- The running artifact can report its exact Git commit and configuration version.
- Relevant latency, recovery, security, and hardware-independent tests have evidence.

## Legacy boundary

The original `cambriel-cpu/omni-vox` repository, its deployed image, and the servo-skull working tree are reference material, not dependencies. Do not modify or deploy them as part of Omni Vox 2 work unless explicitly requested.
