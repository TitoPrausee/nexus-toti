---
name: mrpack-modpack-builder
title: .mrpack Modpack Builder
description: Build a Modrinth .mrpack from a curated mod list — auto-resolve versions, build manifest, ZIP it, and upload to GitHub Releases.
---

# .mrpack Modpack Builder

Build a complete Modrinth `.mrpack` with multiple mods, auto-resolve latest 1.21 Fabric versions, and upload to GitHub Releases.

## Prerequisites
- Modrinth API token (`MODRINTH_TOKEN`)
- GitHub credentials in `~/.git-credentials`
- Python 3 with `urllib` + `zipfile` (stdlib)

## Workflow

### 1. Define Mod List

Use verified **project IDs** (not slugs — slugs require a fragile search). Get IDs from Modrinth URLs or `/v2/search`:

```python
MODS = [
    ("Workers' Collective", "Q9XVN9Sv", existing_jar_obj),  # pre-resolved
    ("Fabric API", "P7dR8mSH", None),                       # resolve dynamically
    ("Sodium", "AANobbMI", None),
    ("Lithium", "gvQqBUqZ", None),
    ("Iris Shaders", "YL57xq9U", None),
    ("Continuity", "1IjD5062", None),
]
```

### 2. Resolve Latest Version for Each Mod

```python
def get_version_info(project_id, token):
    url = f"https://api.modrinth.com/v2/project/{project_id}/version"
    req = urllib.request.Request(url, headers={"Authorization": token})
    with urllib.request.urlopen(req) as resp:
        versions = json.loads(resp.read())

    for v in versions:
        game_vers = v.get("game_versions", [])
        loaders = v.get("loaders", [])
        if "1.21" in game_vers and "fabric" in loaders:
            for f in v.get("files", []):
                if f.get("primary"):
                    return f
            for f in v.get("files", []):
                fn = f["filename"]
                if fn.endswith(".jar") and "sources" not in fn and "dev" not in fn and "shadow" not in fn:
                    return f
    return None
```

**Key insights from trial & error:**
- Use `primary` flag first, fall back to first non-sources/dev/shadow `.jar`
- `"1.21"` in `game_versions` is the safest filter (catches 1.21.x patches)
- Some mods have wrong project IDs in older docs (e.g. LambDynamicLights is `yBW8D80W` NOT `yBW8IhtL`)

### 3. Build `modrinth.index.json` Manifest

```python
files_manifest = []
for name, pid, jar_obj in MODS:
    f = jar_obj or get_version_info(pid, TOKEN)
    if f:
        files_manifest.append({
            "path": f"mods/{f['filename']}",
            "hashes": {"sha1": f["hashes"]["sha1"], "sha512": f["hashes"]["sha512"]},
            "env": {"client": "required", "server": "required"},
            "downloads": [f["url"]],
            "fileSize": f["size"]
        })

index = {
    "formatVersion": 1,
    "game": "minecraft",
    "versionId": "1.21",
    "name": "My Modpack Name",
    "summary": "Short description",
    "files": files_manifest,
    "dependencies": {
        "minecraft": "1.21",
        "fabric-loader": ">=0.16.9"
    }
}
```

**Key field rules:**
- `versionId` = Minecraft version string (e.g. `"1.21"`)
- `path` always starts with `mods/`
- `hashes` MUST include both `sha1` and `sha512` (taken from Modrinth API response)
- `env`: both client and server `"required"` for gameplay mods
- `fileSize`: exact bytes from API's `size` field

### 4. Create .mrpack ZIP

```python
import zipfile, os, json

os.makedirs("/tmp/mrpack", exist_ok=True)
with open("/tmp/mrpack/modrinth.index.json", "w") as f:
    json.dump(index, f, indent=2, ensure_ascii=False)

mrpack_path = "my-modpack.mrpack"
with zipfile.ZipFile(mrpack_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write("/tmp/mrpack/modrinth.index.json", "modrinth.index.json")
```

**Important:** DO NOT compress the `overrides/` directory — the `.mrpack` is just the index + overrides. No mod jars inside — they're downloaded by the launcher from CDN URLs in the manifest.

### 5. Upload to GitHub Releases

```python
import json, os, subprocess, hashlib

# Read GitHub token from git-credentials
with open(os.path.expanduser("~/.git-credentials")) as f:
    line = f.read().strip()
    _, rest = line.split("//", 1)
    _, pw_and_host = rest.split(":", 1)
    GH_TOKEN = pw_and_host.split("@")[0]

REPO = "<GITHUB_USER>/your-repo"

# Get latest release
result = subprocess.run([
    "curl", "-s", f"https://api.github.com/repos/{REPO}/releases/latest"
], capture_output=True, text=True)
release = json.loads(result.stdout)
release_id = release["id"]

# Upload .mrpack as asset
subprocess.run([
    "curl", "-s", "-X", "POST",
    f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name=my-modpack.mrpack",
    "-H", f"Authorization: token {GH_TOKEN}",
    "-H", "Content-Type: application/zip",
    "--data-binary", "@my-modpack.mrpack"
])
```

## Add to README

Add a badge linking to the GitHub Release asset:

```markdown
[![Modpack](https://img.shields.io/badge/📦_Download_Complete_Pack-8B0000?style=for-the-badge)](https://github.com/USER/REPO/releases/download/vX.X.X/my-modpack.mrpack)
```

## Full Example Script

See the complete working script at `/opt/data/home/workers-collective/` or the conversation history. Key patterns:

```python
# 1. Get latest Workers' Collective version
# 2. Define 13-mod list with verified project IDs
# 3. Resolve each mod's latest 1.21 Fabric JAR
# 4. Build manifest with sha1/sha512/size/downloads
# 5. Create ZIP
# 6. Upload to GitHub Releases
# 7. Update README with download badge + setup guide
```

## ⚠️ CRITICAL: Transitive Dependencies

**The Modrinth launcher does NOT resolve transitive dependencies.** It ONLY installs mods listed in the .mrpack manifest. You MUST include ALL transitive dependencies explicitly.

Example: REI (Roughly Enough Items) requires BOTH of these to start:
- **Architectury API** (`lhGA9TYQ`)
- **Cloth Config** (`9s6osm5g`)

Always use `GET /v2/version/{version_id}` to check each mod's `dependencies` field and include ALL `required` dependencies in your manifest. Missing one = game crash on launch.

## ✅ Verification Steps (RUN BEFORE SHIPPING)

After building the .mrpack, ALWAYS verify:

1. **Download every JAR** using the CDN URL from the manifest
2. **Verify SHA1 checksums** match (detects corrupt/manipulated files)
3. **Extract `fabric.mod.json`** from each JAR and read:
   - `depends.minecraft` — ensure version constraint matches your target
   - `depends.fabric-loader` — ensure loader version is compatible
   - `conflicts` — check for known mod conflicts
4. **Count entries** in each JAR ZIP (non-empty = valid)
5. **Cross-check:** every mod that declares `depends` on another mod in your pack must have that dependency listed in the .mrpack

## Game Version Pitfalls

- Some mods list `"1.21"` in their `game_versions` field but their JAR filename says `+mc1.21.1`. These usually work fine for 1.21 — the Modrinth API is authoritative, not the filename.
- **Mixing 1.21 and 1.21.1 mods** can cause crashes. Prefer mods that have ONLY `"1.21"` in their game_versions (no `"1.21.1"`). If unavailable, mods with `"1.21"` AND `"1.21.1"` are usually safe.
- Use `"1.21" in game_versions` as the filter, NOT `game_versions == ["1.21"]`.

## Pitfalls (discovered through trial & error)

| Issue | Cause | Fix |
|-------|-------|-----|
| `HTTP 404` on version endpoint | Wrong project ID (Iris is `YL57xq9U` not `YL57x5iU`) | Verify IDs via `GET /v2/project/{id}` |
| `HTTP 400` on search | Search API returns empty for some queries | Use project IDs directly, not slugs |
| No 1.21 version found | Mod only has 1.20 or 1.22 versions | Remove from pack or use closest match |
| Wrong hashes | Copied from wrong source | Always take `sha1` and `sha512` from Modrinth API response |
| Modpack doesn't install | Missing `env` field for client/server | Always include `"env": {"client": "required", "server": "required"}` |
| Game crashes on launch | Missing transitive deps (Architectury/Cloth Config for REI) | Check each mod's dependency list and include ALL `required` deps |
| Wrong LambDynamicLights ID | `yBW8IhtL` is WRONG, correct is `yBW8D80W` | Verify all project IDs before building |

## Verified Modrinth Project IDs (1.21 Fabric)

| Mod | Project ID |
|-----|-----------|
| Workers' Collective | `Q9XVN9Sv` |
| Fabric API | `P7dR8mSH` |
| Sodium | `AANobbMI` |
| Lithium | `gvQqBUqZ` |
| Iris Shaders | `YL57xq9U` |
| Continuity | `1IjD5062` |
| LambDynamicLights | `yBW8D80W` |
| Presence Footsteps | `rcTfTZr3` |
| Roughly Enough Items (REI) | `nfn13YXA` |
| Xaero's Minimap | `1bokaNcj` |
| Xaero's World Map | `NcUtCpym` |
| Jade | `nvQzSEkH` |
| Mouse Tweaks | `aC3cM3Vq` |
