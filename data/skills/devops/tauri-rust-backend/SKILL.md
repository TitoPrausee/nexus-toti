---
name: tauri-rust-backend
description: >
  Implementing a Rust backend for Tauri 2 apps — audio playback (rodio),
  metadata extraction (lofty), SQLite persistence (rusqlite), and avoiding
  common compilation pitfalls with Tauri's threading model.
version: 1.0.0
prerequisites:
  commands: [cargo, pkg-config]
  knowledge: [tauri-svelte-setup]
---

# Tauri 2 Rust Backend Implementation

## When to Use
- Implementing Tauri commands in `src-tauri/src/lib.rs`
- Adding audio playback, file scanning, or database persistence to a Tauri app
- Fixing `cargo check` compilation errors in Tauri Rust backends

## Critical: rodio::OutputStream is !Send

`rodio::OutputStream` contains `cpal::Stream` which has a `NotSendSyncAcrossAllPlatforms` marker.
You **cannot** store it in a global `Mutex<AudioState>` or `once_cell::Lazy<Mutex<...>>`.

### Wrong (won't compile):
```rust
struct AudioState {
    stream: Option<rodio::OutputStream>,  // !Send
    sink: Option<rodio::Sink>,
}
static AUDIO: once_cell::sync::Lazy<Mutex<AudioState>> = ...;  // E0277
```

### Right: Dedicated audio thread with crossbeam-channel control
The `rodio::Sink` can only be controlled from the thread that owns it. Atomic flags alone are **insufficient** — `sink.pause()`, `sink.play()`, `sink.stop()`, `sink.set_volume()` must be called ON the audio thread, not from Tauri command handlers.

**CRITICAL**: The naive `sink.sleep_until_end()` pattern does NOT allow pause/resume/volume control. Use `crossbeam-channel` to send commands to the audio thread instead.

```toml
# Cargo.toml — add:
crossbeam-channel = "0.5"
```

```rust
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::time::{Duration, Instant};
use tauri::Emitter;

// Command enum for controlling the audio thread
enum AudioCommand {
    Stop,
    Pause,
    Resume,
    SetVolume(f32),
}

static AUDIO_PLAYING: AtomicBool = AtomicBool::new(false);
static AUDIO_PAUSED: AtomicBool = AtomicBool::new(false);
static AUDIO_VOLUME: AtomicU32 = AtomicU32::new(800);
static AUDIO_DURATION_MS: AtomicU64 = AtomicU64::new(0);
static AUDIO_CURRENT_PATH: Mutex<Option<String>> = Mutex::new(None);
static AUDIO_START_INSTANT: Mutex<Option<Instant>> = Mutex::new(None);
static AUDIO_ELAPSED_PAUSED: Mutex<f64> = Mutex::new(0.0); // accumulates paused time
static AUDIO_CMD_TX: Mutex<Option<crossbeam_channel::Sender<AudioCommand>>> = Mutex::new(None);
static AUDIO_THREAD: Mutex<Option<std::thread::JoinHandle<()>>> = Mutex::new(None);

#[tauri::command]
fn play_track(path: String, app_handle: tauri::AppHandle) -> Result<PlaybackStatus, String> {
    stop_playback()?; // Stop any current playback first
    let file_bytes = fs::read(&path)?;
    let vol = AUDIO_VOLUME.load(Ordering::SeqCst) as f32 / 1000.0;
    let duration = lofty::read_from_path(&path)?.properties().duration().as_secs_f64();

    let (cmd_tx, cmd_rx) = crossbeam_channel::bounded::<AudioCommand>(16);
    AUDIO_PLAYING.store(true, Ordering::SeqCst);
    AUDIO_PAUSED.store(false, Ordering::SeqCst);
    *AUDIO_CMD_TX.lock().unwrap() = Some(cmd_tx);

    let handle = std::thread::Builder::new()
        .name("audio-playback".into())
        .spawn(move || {
            let (stream, stream_handle) = rodio::OutputStream::try_default().unwrap();
            let sink = rodio::Sink::try_new(&stream_handle).unwrap();
            let source = rodio::Decoder::new(std::io::BufReader::new(
                std::io::Cursor::new(file_bytes))).unwrap();
            sink.set_volume(vol);
            sink.append(source);

            loop {
                match cmd_rx.try_recv() {
                    Ok(AudioCommand::Stop) => {
                        sink.stop();
                        AUDIO_PLAYING.store(false, Ordering::SeqCst);
                        break;
                    }
                    Ok(AudioCommand::Pause) => {
                        sink.pause();
                        AUDIO_PAUSED.store(true, Ordering::SeqCst);
                        // save elapsed time for accurate position tracking
                        *AUDIO_ELAPSED_PAUSED.lock().unwrap() +=
                            AUDIO_START_INSTANT.lock().unwrap()
                                .as_ref().map(|t| t.elapsed().as_secs_f64())
                                .unwrap_or(0.0);
                    }
                    Ok(AudioCommand::Resume) => {
                        sink.play();
                        AUDIO_PAUSED.store(false, Ordering::SeqCst);
                        *AUDIO_START_INSTANT.lock().unwrap() = Some(Instant::now());
                    }
                    Ok(AudioCommand::SetVolume(v)) => {
                        sink.set_volume(v);
                    }
                    Err(crossbeam_channel::TryRecvError::Empty) => {
                        if sink.empty() { break; } // playback finished
                        // Emit progress event for frontend
                        let _ = app_handle.emit("playback-progress", serde_json::json!({
                            "position_secs": compute_position_secs(),
                            "duration_secs": duration,
                            "is_playing": AUDIO_PLAYING.load(Ordering::SeqCst),
                        }));
                    }
                    Err(crossbeam_channel::TryRecvError::Disconnected) => break,
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            *AUDIO_CMD_TX.lock().unwrap() = None;
            drop(sink); drop(stream);
        })?;
    *AUDIO_THREAD.lock().unwrap() = Some(handle);
    Ok(status)
}

#[tauri::command]
fn stop_playback() -> Result<PlaybackStatus, String> {
    if let Some(ref tx) = *AUDIO_CMD_TX.lock().unwrap() { let _ = tx.send(AudioCommand::Stop); }
    if let Some(handle) = AUDIO_THREAD.lock().unwrap().take() { let _ = handle.join(); }
    // ... reset atomics, return status
}
```

### Pause/Resume Position Tracking
When pausing, accumulate elapsed time in `AUDIO_ELAPSED_PAUSED`. On resume, reset `AUDIO_START_INSTANT`. The `compute_position_secs()` helper returns accurate position across multiple pause/resume cycles:

```rust
fn compute_position_secs() -> f64 {
    let elapsed_paused = *AUDIO_ELAPSED_PAUSED.lock().unwrap();
    if AUDIO_PLAYING.load(Ordering::SeqCst) {
        let current = AUDIO_START_INSTANT.lock().unwrap()
            .as_ref().map(|t| elapsed_paused + t.elapsed().as_secs_f64())
            .unwrap_or(elapsed_paused);
        current.min(AUDIO_DURATION_MS.load(Ordering::SeqCst) as f64 / 1000.0)
    } else if AUDIO_PAUSED.load(Ordering::SeqCst) {
        elapsed_paused
    } else { 0.0 }
}
```

### Critical: is_playing vs is_paused Semantics

**BUG PATTERN**: When pausing, `AUDIO_PLAYING` must remain `true`. If set to `false`, the frontend cannot distinguish "paused" (track loaded, temporarily suspended) from "stopped" (nothing playing). Use a separate `AUDIO_PAUSED` atomic.

```rust
// In AudioCommand::Pause handler:
Ok(AudioCommand::Pause) => {
    sink.pause();
    AUDIO_PAUSED.store(true, Ordering::SeqCst);
    // DO NOT set AUDIO_PLAYING to false here!
    // AUDIO_PLAYING means "track is loaded and active", not "actively decoding"
}

// In AudioCommand::Resume handler:
Ok(AudioCommand::Resume) => {
    sink.play();
    AUDIO_PAUSED.store(false, Ordering::SeqCst);
    // AUDIO_PLAYING stays true
}

// PlaybackStatus and progress events must include BOTH fields:
pub struct PlaybackStatus {
    pub is_playing: bool,   // true = track loaded (playing or paused)
    pub is_paused: bool,    // true = currently paused
    // ...
}

// In get_playback_status and progress emit:
is_playing: is_playing && !is_paused,  // true only when actively decoding
is_paused,                              // true only when paused
```

Frontend must mirror both fields:
```typescript
interface PlayerState {
    isPlaying: boolean;  // actively playing
    isPaused: boolean;   // paused (track still loaded)
    // ...
}

// togglePlayPause must check both:
if (isPlaying) { await pausePlayback(); }
else if (isPaused) { await resumePlayback(); }
// else: nothing to play
```

### Frontend: Listen for Tauri Events
```typescript
import { listen } from '@tauri-apps/api/event';
// In initApp():
listen<PlaybackStatus>('playback-progress', (event) => {
    const { position_secs, duration_secs, is_playing, is_paused } = event.payload;
    player.update(p => ({
        ...p,
        progress: position_secs / (duration_secs || 1),
        isPlaying: is_playing,
        isPaused: is_paused || false,
    }));
});
```

Key patterns:
- Read file bytes with `fs::read()` before spawning thread (File is !Send)
- `play_track` needs `app_handle: tauri::AppHandle` parameter for `emit()` — add `use tauri::Emitter;`
- `sink.stop()` does NOT consume self (unlike `sink.detach()` which does) — use `sink.stop()` for clean stop
- `sink.detach()` takes `self` (moves ownership) — do NOT call it before `drop(sink)`
- Audio thread emits `playback-progress` events every 100ms when not paused

## lofty 0.19 API (Correct Usage)

### Required imports:
```rust
use lofty::file::{AudioFile, TaggedFileExt};
use lofty::tag::Accessor;
```

These are **traits** that must be in scope — compiler errors like "method `properties` not found" mean you forgot to import `AudioFile`, and "method `first_tag` not found" means you forgot `TaggedFileExt`.

### Reading a file:
```rust
let tagged_file = lofty::read_from_path(path)?;
let duration = tagged_file.properties().duration();  // needs AudioFile trait
let tag = tagged_file.primary_tag().or_else(|| tagged_file.first_tag());  // needs TaggedFileExt
```

### Tag accessor methods (Accessor trait):
```rust
tag.title()    // Option<Cow<'_, str>>
tag.artist()   // Option<Cow<'_, str>>
tag.album()    // Option<Cow<'_, str>>
tag.year()     // Option<u32>
tag.genre()    // Option<Cow<'_, str>>
tag.track()    // Option<u32>
tag.track_total() // Option<u32>
tag.disk()     // Option<u32>
tag.comment()  // Option<Cow<'_, str>>
```

**NOT** `tag.title()` returning `Option<String>` — it returns `Option<Cow<str>>`. Use `.map(|s| s.to_string())` to get owned strings.

### Extracting cover art:
```rust
for pic in tag.pictures() {  // &[Picture]
    if !pic.data().is_empty() {  // pic.data() -> &[u8]
        let ext = pic.mime_type()
            .and_then(|m| m.as_str().split('/').last())
            .unwrap_or("jpg");
        // Write pic.data() to a temp file
        break;
    }
}
```

**NOT** `tag.PICTURE()` or `tag.pICTURE()` — those don't exist. Use `tag.pictures()`.

### Probe API (alternatively):
```rust
let probing = lofty::probe::Probe::open(path)?;
let file_type = probing.file_type();  // Option<FileType>
let tagged_file = probing.read()?;    // TaggedFile
```

## directories-next 2.0 API

**No `music_dir()` method exists.** The correct method is `audio_dir()`:
```rust
let dirs = directories_next::UserDirs::new()?;
let music = dirs.audio_dir()?;  // Option<&Path>
```

## rusqlite Transactions

Mutability requirement — `Connection` for transactions needs `mut`:
```rust
let mut conn = db_conn()?;  // MUST be mut
let tx = conn.transaction()?;
// ... inserts ...
tx.commit()?;
```

Without `mut`, you get: `cannot borrow conn as mutable, as it is not declared as mutable`.

## Tauri lib name mismatch

`create-tauri-app` scaffolds `main.rs` with `tauri_app_lib::run()` but `Cargo.toml` uses a different lib name. Fix:
```rust
// WRONG (template default):
fn main() { tauri_app_lib::run() }

// CORRECT (must match [lib] name in Cargo.toml):
fn main() { cd_shelf_player_lib::run() }
```

When Cargo.toml has `[lib] name = "cd_shelf_player_lib"`, the crate is `cd_shelf_player_lib`.

## once_cell vs lazy_static

Prefer `once_cell::sync::Lazy` over `lazy_static!` for Tauri:
- Works with `Mutex` containing non-Send types (as long as the inner type IS Send)
- Cleaner syntax
- Add `once_cell = "1"` to Cargo.toml

```rust
static MY_STATE: once_cell::sync::Lazy<Mutex<MyState>> =
    once_cell::sync::Lazy::new(|| Mutex::new(MyState::new()));
```

## Cargo.toml for Audio + DB + Metadata

```toml
[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-opener = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
once_cell = "1"
rusqlite = { version = "0.31", features = ["bundled"] }
rodio = { version = "0.18", features = ["vorbis", "flac", "mp3", "wav"] }
crossbeam-channel = "0.5"
lofty = "0.19"
directories-next = "2"
walkdir = "2"
```

Note: lofty 0.19 default features include most audio format support. No need for explicit `features = ["mp3", "flac", ...]` unless you need exotic formats.

## rodio::Sink Method Pitfalls

1. **`sink.detach()` consumes `self`** — it takes `mut self` not `&mut self`. After calling `detach()`, you cannot use `sink` again (including `drop(sink)`). Use `sink.stop()` instead for controlled shutdown, which takes `&self`.
2. **`sink.sleep_until_end()` blocks the calling thread** — this prevents you from processing commands (pause/volume/stop) while audio plays. Use a `crossbeam_channel` command loop with `try_recv()` + `std::thread::sleep(Duration::from_millis(100))` instead.
3. **Atomic flags alone cannot control `rodio::Sink`** — `AUDIO_PLAYING.store(false)` does NOT stop audio playback. You must call `sink.stop()`, `sink.pause()`, `sink.play()`, `sink.set_volume()` FROM the thread that owns the Sink, typically via a channel.

## Subagent Pitfalls

When delegating Tauri Rust implementation to coding agents (Claude Code, Codex):
1. **They will produce broken API calls** — rodio, lofty, and directories-next APIs are non-obvious. Always verify with `cargo check`.
2. **Chinese/garbled characters** — Some models emit non-ASCII in code (e.g., `sink停止()` instead of `sink.stop()`). Audit diffs.
3. **They create module files but don't wire them** — `audio.rs`, `db.rs`, `library.rs` with `mod` declarations missing from `lib.rs`. Prefer single-file `lib.rs` for Tauri apps under ~800 lines.
4. **They invent APIs that don't exist** — `sha1::Sha1::album()`, `tag.pICTURE()`, `Sink::new()` (should be `Sink::try_new()`). Always verify.
5. **`cargo check` timeout** — First compile takes 3-5 minutes (webkit2gtk bindings). Plan for this in agent timeouts.

## Verification Checklist

After implementing Rust backend:
1. `cargo check` in `src-tauri/` — must pass with 0 errors
2. Check `src-tauri/src/main.rs` — lib name must match Cargo.toml
3. All `#[tauri::command]` functions must appear in `generate_handler![]`
4. Trait imports: `AudioFile`, `TaggedFileExt`, `Accessor` must be in scope
5. `OutputStream` must NOT be stored in any `Send`-requiring container
6. `rusqlite::Connection` for transactions must be `mut`