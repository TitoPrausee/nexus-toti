---
name: tauri-svelte-setup
description: Bootstrap a Tauri 2 + Svelte 5 desktop app project on Linux (ARM64). Covers Rust install, webkit2gtk deps, project scaffold, and verification.
version: 1.0.0
---

# Tauri 2 + Svelte 5 Project Setup (Linux ARM64)

## Prerequisites

```bash
# 1. Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# 2. Install webkit2gtk + deps (REQUIRED on Linux, Tauri will not build without these)
sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev libappindicator3-dev \
  librsvg2-dev patchelf libsoup-3.0-dev libjavascriptcoregtk-4.1-dev

# 3. Node/Bun
# Already available on Hermes VM at /opt/data/home/.bun/bin/bun
```

## Project Creation

```bash
mkdir cd-shelf-player && cd cd-shelf-player
npm create tauri-app@latest . -- --template svelte-ts --manager npm --yes
npm install
```

**Important:** `npm create tauri-app` refuses to run in a non-empty directory. Start with empty dir or `rm -rf` first.

## Verification

```bash
# Type-check Svelte components (fast, no browser needed)
npx svelte-check --tsconfig ./tsconfig.json
# Expect: 0 errors, some a11y warnings are normal

# DO NOT use `npx vite build` — it starts a long-lived process that blocks
# Use svelte-check instead for CI/agent verification
```

## Git Remote (GitLab)

```bash
# SSH often fails (host key). Use HTTPS with PAT:
git remote set-url origin https://TOKEN@gitlab.com/USER/REPO.git

# Push with conflict resolution:
git pull --rebase origin main
# If conflicts on README.md:
git checkout --theirs README.md
git add -A
GIT_EDITOR=true git rebase --continue
git push origin main
```

## Svelte 5 Component Patterns

- `$state()` for reactive state (replaces `let` from Svelte 4)
- `$derived()` for computed values
- `$effect()` for side effects (replaces `$:` reactive declarations)
- `$props()` for component props in Svelte 5 runes mode
- Stores still use `writable/derived` from `svelte/store`

## Tauri Backend Stubs

Rust commands are registered in `src-tauri/src/lib.rs`:
```rust
#[tauri::command]
fn my_command(arg: String) -> Result<String, String> {
    Ok(format!("result: {}", arg))
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![my_command])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

## Pitfalls

1. **webkit2gtk version** — Must be `4.1` (not 4.0). Tauri 2 requires the newer API.
2. **`npm create tauri-app` in non-empty dir** — Fails silently. Ensure dir is empty.
3. **Git push via SSH** — Host key verification often fails on fresh VMs. Use `ssh-keyscan gitlab.com >> ~/.ssh/known_hosts` or HTTPS with PAT.
4. **`vite build` / `vite dev`** — Long-lived process, will block in terminals. Use `svelte-check` for verification, run dev servers with `background=true`.
5. **Rebase conflicts** — Use `git checkout --theirs <file>` + `GIT_EDITOR=true git rebase --continue`.
6. **Bun vs npm** — Tauri scaffold uses npm. If project uses Bun, `bun install` works but Tauri CLI expects npm scripts in package.json.

## Agent Delegation Pattern

For scaffolding projects, write a detailed prompt to `/tmp/agent-prompts/<task>.md` with:
- Project architecture and desired file structure
- Design guidelines (colors, themes, layout)
- Verification steps (svelte-check, bun test)
- Git commit/push instructions

Launch with Claude Code print mode:
```bash
claude -p "$(cat /tmp/agent-prompts/task.md)" --dangerously-skip-permissions --max-turns 30-50 --output-format json
```

**Budget:** ~$4-8 for a full project scaffold (48 files, 3700 lines cost $4.06).
**Limit:** 30-50 turns may not be enough for push + verify. Plan to push manually after agent finishes.

**Post-agent verification always required:**
1. `npx svelte-check --tsconfig ./tsconfig.json` — 0 errors
2. `git diff --stat` — review what changed
3. Manual `git push` (agents often fail on SSH/auth)