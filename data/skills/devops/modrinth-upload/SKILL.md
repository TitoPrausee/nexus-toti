---
name: modrinth-upload
title: Modrinth Upload
description: Upload Minecraft mods to Modrinth — project setup, icon generation/upload, gallery management, and version release via API.
---

# Modrinth Upload Workflow

Upload a Minecraft mod to Modrinth including project creation, icon generation/upload, gallery images, and JAR release in one workflow.

## Prerequisites

- Modrinth account (https://modrinth.com/register)
- API token from https://modrinth.com/settings/account (scope: "Upload Mod")
- Environment: `export MODRINTH_TOKEN="mrp_xxxxx"`

## Custom CLI Tool

The project includes a Python CLI tool at `/opt/data/home/bin/modrinth_upload`. Usage:

```bash
# Upload a new version
modrinth_upload upload \
  --project Q9XVN9Sv \
  --version "1.3.0" \
  --jar ./build/libs/mod-1.3.0.jar \
  --loaders fabric \
  --game-versions "1.21" \
  --changelog "Bug fixes and improvements"

# List your projects
modrinth_upload list
```

## Step-by-Step Upload

### 1. Build the JAR

```bash
cd ~/workers-collective
export JAVA_HOME=~/.local/java/jdk-21.0.11+10
export PATH=$JAVA_HOME/bin:$PATH
./gradlew build
```

JARs land in `build/libs/`. Use the newest version matching the release.

### 2. Generate an Icon (optional)

Use xAI Grok Imagen API for pixel-art style Minecraft icons:

```bash
# Generate image — DON'T pass model or size params, they don't exist for this team
curl -s -X POST "https://api.x.ai/v1/images/generations" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{"prompt": "A pixel-art Minecraft mod icon...", "n": 1}' | jq -r '.data[0].url'

# Download immediately (URLs expire!)
curl -sLo icon_original.jpeg "$URL"

# Convert to Modrinth-compatible icon (< 256 KiB)
ffmpeg -y -i icon_original.jpeg -vf "scale=256:256:flags=lanczos" -q:v 15 icon_small.jpg
```

**xAI Imagen quirks:**
- `model` parameter NOT supported — omit it entirely
- `size` parameter NOT supported — defaults to 1024×1024
- Token prefix is `xai-` (not `xai-team-...`)
- Output URL must be downloaded immediately — they expire

### 3. Upload Icon to Modrinth

**CRITICAL:** Raw binary body in PATCH request, NOT multipart. Requires `?ext=jpg` query parameter.

```bash
curl -s -X PATCH "https://api.modrinth.com/v2/project/$PROJECT_ID/icon?ext=jpg" \
  -H "Authorization: $MODRINTH_TOKEN" \
  -H "Content-Type: image/jpeg" \
  --data-binary @icon_small.jpg
```

**Gotchas (discovered through trial & error):**
- ❌ Multipart/form-data fails with "Content type error"
- ❌ PATCH `/v2/project/{id}` with icon in multipart fails — must use dedicated `/icon` endpoint
- ✅ Must include `?ext=jpg` (or `?ext=png`) in URL
- ✅ File must be < 256 KiB — use `ffmpeg -q:v 15` to compress
- ✅ Empty response (HTTP 200 with no body) = SUCCESS
- ✅ Verify via: `curl -H "Authorization: $TOKEN" "https://api.modrinth.com/v2/project/$ID" | jq '.icon_url'`

### 4. Delete Gallery Images

**CRITICAL:** Use the CDN webp URL (not raw_url, not .png/.jpeg) with `-G --data-urlencode` in query string. JSON body does NOT work.

```bash
# Get gallery URLs first - use the 'url' field, not 'raw_url'
curl -s "https://api.modrinth.com/v2/project/$PROJECT_ID" | python3 -c '
import json,sys
for g in json.load(sys.stdin).get("gallery", []):
    print(g["url"])  # these are the _350.webp CDN URLs
'

# Delete individual image - MUST use CDN webp URL + --data-urlencode
curl -s -X DELETE "https://api.modrinth.com/v2/project/$PROJECT_ID/gallery" \
  -H "Authorization: $MODRINTH_TOKEN" \
  -G --data-urlencode "url=https://cdn.modrinth.com/data/Q9XVN9Sv/images/xxxx_350.webp"

# HTTP 204 = success
```

**Gotchas (discovered through trial & error):**
- ❌ JSON body `{"urls": ["..."]}` fails with "Query deserialize error: missing field `url`"
- ❌ URL without `-G --data-urlencode` fails with "not part of project's gallery" (URL encoding needed)
- ❌ Using `raw_url` (.png/.jpeg) instead of the CDN `url` (_350.webp) fails — must use exact URL from project API response
- ❌ Trying to delete multiple images at once fails silently — delete ONE AT A TIME
- ✅ `-G --data-urlencode "url=..."` is the only working syntax
- ✅ The `url` field (not `raw_url`) from the project API is the exact CDN URL needed
- ✅ HTTP 204 (no body) = success
- ✅ Verify by re-fetching project and confirming `gallery` array is empty

### 5. Upload Gallery Images

**CRITICAL:** Raw binary body in POST request, NOT multipart. Metadata goes in query string.

```bash
curl -s -X POST "https://api.modrinth.com/v2/project/$PROJECT_ID/gallery?ext=jpeg&featured=false&title=My%20Image&description=Description%20here&ordering=0" \
  -H "Authorization: $MODRINTH_TOKEN" \
  -H "Content-Type: image/jpeg" \
  --data-binary @image.jpg
```

**Parameters (all in query string):**
| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `ext` | string | ✅ | Must match file type: `jpeg` or `png` |
| `featured` | bool | ✅ | `true` for first/main image |
| `title` | string | ✅ | URL-encoded |
| `description` | string | ❌ | Optional, URL-encoded |
| `ordering` | int | ❌ | Sort order (0 = first) |

**Gotchas (discovered through trial & error):**
- ❌ Multipart/form-data with `data` JSON field fails with "Query deserialize error: missing field `featured`"
- ❌ Sending `featured` inside multipart body fails regardless of format
- ✅ All metadata goes in query string, raw binary in body
- ✅ Files must be < 256 KiB
- ✅ Empty response (HTTP 200 with no body) = SUCCESS

### 5. Automated Publisher Script v5 — Echte CHANGELOG-Release-Notes

For fully automated releases that **extract the real changelog** (not "Automated release."). Uses Python to parse CHANGELOG.md directly, bypassing shell heredoc escaping issues. Handles Modrinth (ASCII-safe) and GitHub (full Unicode with emojis) separately.

**Key design decisions:**
- **Python parses CHANGELOG.md directly** — reads the file, extracts the newest entry via regex, outputs JSON. No shell heredoc escaping issues with emoji or special characters.
- **Dual output**: `github` field (full markdown with emojis), `modrinth` field (ASCII-only to avoid JSON encoding issues)
- **Python `os.environ`** for VERSION, PROJECT_ID, etc. — avoids shell variable expansion problems in Python strings
- **Token extraction from `~/.git-credentials`**: `python3 -c "with open(...)"` — avoids grep/sed fragile parsing
- **Auto-build**: rebuilds if JAR doesn't exist
- **Silent skip on duplicate GitHub release**: if curl returns error (tag exists), RELEASE_ID is empty → skips gracefully
- **`$$` PID suffix** on temp files prevents parallel-run collisions
- **Decoupled from cron prompt**: cron just calls `bash publisher.sh` — zero tokens in prompt text

```bash
#!/bin/bash
# workers-publisher.sh — Builds + Uploads to Modrinth + GitHub
# Extracts the REAL changelog from CHANGELOG.md
set -euo pipefail

PROJECT_DIR="/opt/data/home/workers-collective"
JAVA_HOME="/opt/data/home/.local/java/jdk-21.0.11+10"
export PATH="$JAVA_HOME/bin:$PATH"
MODRINTH_PROJECT="Q9XVN9Sv"
FABRIC_API_DEP="P7dR8mSH"

cd "$PROJECT_DIR"
VERSION=$(grep 'mod_version=' gradle.properties | cut -d= -f2)
JAR="build/libs/workers-collective-${VERSION}.jar"

# Export for Python subprocess
export VERSION MODRINTH_PROJECT FABRIC_API_DEP

# ─── CHANGELOG parsen (Python liest direkt, kein Shell-Escaping) ───
python3 -c "
import re, json
with open('CHANGELOG.md') as f:
    content = f.read()
# Find first ##[version] header until next ## or --- or end
match = re.search(r'^##\s*\[([^\]]+)\][^\n]*\n(.*?)(?=\n##\s|^---|\Z)', content, re.MULTILINE | re.DOTALL)
body = match.group(2).strip() if match else 'New release.'
# GitHub: full markdown with emojis
# Modrinth: ASCII-only (no emojis/umlauts — breaks JSON)
modrinth = ''.join(c for c in body if ord(c) < 128)
print(json.dumps({'github': body, 'modrinth': modrinth}, ensure_ascii=False))
" > /tmp/pub_changelog.json

# ─── JAR bauen (falls fehlend) ───
if [ ! -f "$JAR" ]; then
    chmod +x gradlew && ./gradlew clean build
fi
if [ ! -f "$JAR" ]; then exit 1; fi

# ─── Modrinth Upload ───
if [ -f ".env" ]; then
    source ".env"
    if [ -n "${MODRINTH_TOKEN:-}" ]; then
        export MODRINTH_TOKEN
        python3 -c "
import json, os
with open('/tmp/pub_changelog.json') as f:
    cdata = json.load(f)
data = {
    'name': 'v' + os.environ['VERSION'],
    'version_number': os.environ['VERSION'],
    'changelog': cdata['modrinth'].strip(),
    'dependencies': [{'project_id': os.environ['FABRIC_API_DEP'], 'dependency_type': 'required'}],
    'game_versions': ['1.21'],
    'version_type': 'release',
    'loaders': ['fabric'],
    'featured': True,
    'project_id': os.environ['MODRINTH_PROJECT'],
    'file_parts': ['jar']
}
print(json.dumps(data, ensure_ascii=False))
" > /tmp/modrinth_meta_$$.json

        curl -s -X POST \
            -H "Authorization: $MODRINTH_TOKEN" \
            -F "data=@/tmp/modrinth_meta_$$.json;type=application/json" \
            -F "jar=@$JAR" \
            "https://api.modrinth.com/v2/version"
        rm -f /tmp/modrinth_meta_$$.json
    fi
fi

# ─── GitHub Release ───
if [ -f ~/.git-credentials ]; then
    GH_TOKEN=$(python3 -c "
with open('/root/.git-credentials') as f:
    line = f.read().strip()
_, rest = line.split('//', 1)
_, pw_and_host = rest.split(':', 1)
print(pw_and_host.split('@')[0])
" 2>/dev/null || echo "")
    
    if [ -n "$GH_TOKEN" ]; then
        export GH_TOKEN
        JSON_BODY=$(python3 -c "
import json, os
with open('/tmp/pub_changelog.json') as f:
    cdata = json.load(f)
data = {
    'tag_name': 'v' + os.environ['VERSION'],
    'name': 'v' + os.environ['VERSION'],
    'body': cdata['github'].strip()
}
print(json.dumps(data, ensure_ascii=False))
")
        GH_RESP=$(curl -s -X POST \
            -H "Authorization: token $GH_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$JSON_BODY" \
            "https://api.github.com/repos/<GITHUB_USER>/workers-collective/releases")
        RELEASE_ID=$(echo "$GH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
        if [ -n "$RELEASE_ID" ]; then
            curl -s -X POST \
                -H "Authorization: token $GH_TOKEN" \
                -H "Content-Type: application/java-archive" \
                --data-binary "@$JAR" \
                "https://uploads.github.com/repos/<GITHUB_USER>/workers-collective/releases/$RELEASE_ID/assets?name=workers-collective-${VERSION}.jar"
        fi
    fi
fi

rm -f /opt/data/home/ready_to_commit.json /tmp/pub_changelog.json
```

**Critical pitfalls discovered:**
- **Shell heredocs with `<< 'PYEOF'`** prevent variable expansion → use `python3 -c "..."` with `os.environ` instead
- **Emoji in Modrinth JSON** causes "Invalid character '-' in base62 encoding" error → strip to ASCII with `''.join(c for c in body if ord(c) < 128)`
- **GitHub API accepts full Unicode** → use `ensure_ascii=False` in json.dumps
- **Shell var expansion inside `python3 -c "..."`** breaks with special chars → export env vars and use `os.environ`
- **Modrinth API expects `ensure_ascii=False`** — the older `ensure_ascii=True` (default) breaks umlauts and special chars

### 6. Update Project Metadata (SEO)

```bash
curl -s -X PATCH "https://api.modrinth.com/v2/project/$PROJECT_ID" \
  -H "Authorization: $MODRINTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Keyword-rich description here — used in search results",
    "body": "## Long markdown description...",
    "loaders": ["fabric"],
    "game_versions": ["1.21", "1.21.1", "1.21.2"],
    "categories": ["adventure", "economy", "game-mechanics"],
    "client_side": "required",
    "server_side": "required",
    "source_url": "https://github.com/YourUser/your-mod",
    "issues_url": "https://github.com/YourUser/your-mod/issues",
    "wiki_url": "https://github.com/YourUser/your-mod/wiki",
    "license_id": "MIT",
    "donation_urls": [
      {"id": "ko-fi", "platform": "Ko-fi", "url": "https://ko-fi.com/yourname"},
      {"id": "paypal", "platform": "Paypal", "url": "https://paypal.me/yourname"}
    ]
  }'
```

**Full list of updatable metadata fields:**
| Field | Type | Notes |
|-------|------|-------|
| `description` | string | Short one-liner (< 200 chars), used in search results |
| `body` | string | Full Markdown body (tables, headers, emoji, code blocks) |
| `categories` | array | Max 3 categories — use `adventure`, `economy`, `game-mechanics`, `social`, `storage`, `technology`, `decoration` |
| `loaders` | array | e.g. `["fabric"]` |
| `game_versions` | array | All compatible versions (must also update each released version separately) |
| `client_side` | string | `"required"`, `"optional"`, or `"unsupported"` |
| `server_side` | string | Same options |
| `source_url` | string | GitHub repo URL |
| `issues_url` | string | GitHub issues URL |
| `wiki_url` | string | GitHub wiki or docs URL |
| `license_id` | string | SPDX identifier (e.g. `"MIT"`) |
| `donation_urls` | array | Array of {id, platform, url} objects |
| `icon_url` | string | Read-only — use icon API endpoint to change |

**SEO optimization tips:**
- Keep `description` under 200 chars, front-load keywords (mod name, loader, version, key features)
- `body` supports full Markdown — use tables, code blocks, emoji for readability
- Max **3 categories** — picking more returns "length" validation error
- Must update both **project** AND **version** `game_versions` separately for version to be filterable
- Empty response = success

**Category list for mods:**
`adventure`, `cursed`, `decoration`, `economy`, `equipment`, `food`, `game-mechanics`, `library`, `magic`, `management`, `minigame`, `mobs`, `optimization`, `social`, `storage`, `technology`, `transportation`, `utility`, `worldgen`

### 6. Update Released Version's Game Versions

```bash
curl -s -X PATCH "https://api.modrinth.com/v2/version/$VERSION_ID" \
  -H "Authorization: $MODRINTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "game_versions": ["1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5", "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11"]
  }'
```

**Must update version `game_versions` separately from project `game_versions`** — the version-level field controls what players see in search filters.

### 6. Upload Version (JAR)

**Option A: Direct curl (recommended for reliability)**

The CLI tool has limitations (no sources JAR support, chokes on special chars in changelogs). Direct curl multipart is more reliable:

```bash
# Create metadata file with NO special characters in changelog
cat > metadata.json << 'METAEOF'
{
  "name": "v1.4.0",
  "version_number": "1.4.0",
  "changelog": "## v1.4.0 - Title\n\n### New\n- Feature one\n- Feature two",
  "dependencies": [],
  "game_versions": ["1.21","1.21.1"],
  "version_type": "release",
  "loaders": ["fabric"],
  "featured": true,
  "project_id": "Q9XVN9Sv",
  "file_parts": ["jar","sources"]
}
METAEOF

# CRITICAL: data field MUST come before file fields in multipart
curl -s -X POST \
  -H "Authorization: $MODRINTH_TOKEN" \
  -F "data=@metadata.json;type=application/json" \
  -F "jar=@build/libs/mod-1.4.0.jar" \
  -F "sources=@build/libs/mod-1.4.0-sources.jar" \
  "https://api.modrinth.com/v2/version"

# Clean up temp files
rm -f metadata.json
```

**CRITICAL ordering requirement:** `data` field MUST come BEFORE file fields in multipart upload. Reversing the order gives: `"Error with multipart data: data field must come before file fields"`.

**Changelog special chars:** Avoid Unicode emojis, § symbols, or smart quotes in the changelog JSON — they cause "Invalid character '-' in base62 encoding" errors due to JSON encoding issues in the CLI parser. Use plain ASCII (e.g. `-` instead of `—`, plain text instead of emoji).

**Dependencies MUST be declared on version upload — Modrinth does NOT read them from fabric.mod.json:** The mod's `fabric.mod.json` may declare `"fabric-api": "*"` as a required dependency, but that does NOT carry over to Modrinth. Each version uploaded via API gets `"dependencies": []` by default. To make the Modrinth launcher auto-install Fabric API:

1. **On upload:** Include dependencies in the metadata JSON:
```json
{
  "dependencies": [
    {"project_id": "P7dR8mSH", "dependency_type": "required"}
  ]
}
```
`P7dR8mSH` is Fabric API's Modrinth project ID (fixed, never changes).

2. **Cannot patch after upload:** Modrinth does NOT allow PATCH on a version's `dependencies` field. Returns empty response (silent fail). The fix is to **release a new minor version** with the proper dependencies declared.

**Multipart field ordering:** The `data` field MUST come BEFORE file fields. Reversing gives: "Error with multipart data: data field must come before file fields".

**Option B: CLI tool (simpler, no sources JAR)**

```bash
modrinth_upload upload \
  --project Q9XVN9Sv \
  --version "1.3.0" \
  --jar ./build/libs/mod-1.3.0.jar \
  --loaders fabric \
  --game-versions "1.21" \
  --changelog "Bug fixes and improvements"
```

Limitations: no `--sources` flag, special chars in changelog can break parsing.

### 7. Post-Upload Steps

#### Create a .mrpack (Modrinth Modpack) for Easy Distribution

A `.mrpack` file lets users import a complete, ready-to-play modpack with one click in the Modrinth launcher. It's a ZIP containing `modrinth.index.json` with file manifests that the launcher auto-downloads.

**⚠️ CRITICAL #1: Use the automated Python builder below.** Manual entry of hashes/sizes/URLs is error-prone. The builder resolves all mod versions dynamically from the Modrinth API.

**⚠️ CRITICAL #2 (transitive dependency pitfall): `.mrpack` files do NOT auto-resolve transitive dependencies.** If Mod A depends on Mod B, and you only list Mod A in your `.mrpack`, the Modrinth Launcher will NOT auto-install Mod B. You MUST explicitly list ALL transitive dependencies in the manifest. This is the #1 cause of "required dependency not installed" crash errors.

Real-world example: Roughly Enough Items (REI) depends on **Architectury API** (`lhGA9TYQ`) + **Cloth Config** (`9s6osm5g`). If you omit either, the game will crash with: `"Architectury API is a required dependency of Roughly Enough Items but it is not installed!"`

To discover what dependencies a mod needs, query its version endpoint:
```bash
curl -s "https://api.modrinth.com/v2/project/nfn13YXA/version" | python3 -c "
import json,sys
d = json.load(sys.stdin)
for v in d:
    if '1.21' in v.get('game_versions',[]) and 'fabric' in v.get('loaders',[]):
        for dep in v.get('dependencies', []):
            if dep['dependency_type'] == 'required':
                print(f'Required: {dep[\"project_id\"]}')
        break
"
```

Then verify the project name:
```bash
curl -s "https://api.modrinth.com/v2/project/lhGA9TYQ" | python3 -c "import json,sys; print(json.load(sys.stdin)['title'])"
# → "Architectury API"
```

**Verified project IDs for popular mods (Fabric 1.21):**

| Mod | Project ID | Notes |
|-----|------------|-------|
| Workers' Collective | `Q9XVN9Sv` | Your mod |
| Fabric API | `P7dR8mSH` | Always this ID |
| Sodium | `AANobbMI` | |
| Lithium | `gvQqBUqZ` | |
| Iris Shaders | `YL57xq9U` | NOT YL57x5iU — that's wrong! |
| Continuity | `1IjD5062` | |
| LambDynamicLights | `yBW8D80W` | NOT yBW8IhtL — that's wrong! |
| Presence Footsteps | `rcTfTZr3` | |
| Roughly Enough Items (REI) | `nfn13YXA` | ⚠️ Requires Architectury API + Cloth Config |
| Architectury API | `lhGA9TYQ` | Transitive dep of REI — include if REI is in pack |
| Cloth Config | `9s6osm5g` | Transitive dep of REI — include if REI is in pack |
| Xaero's Minimap | `1bokaNcj` |
| Xaero's World Map | `NcUtCpym` |
| Jade | `nvQzSEkH` |
| Mouse Tweaks | `aC3cM3Vq` |

**Automated .mrpack builder script (Python):**

Use this script to build a modpack. It queries the Modrinth API to get the latest 1.21 Fabric versions with correct hashes, sizes, and download URLs.

```python
import json, os, urllib.request, zipfile

TOKEN = os.environ.get("MODRINTH_TOKEN", "")
PROJECT_ID = "Q9XVN9Sv"  # Your mod's project ID

# Get latest version of your mod
req = urllib.request.Request(
    f"https://api.modrinth.com/v2/project/{PROJECT_ID}/version",
    headers={"Authorization": TOKEN}
)
with urllib.request.urlopen(req) as resp:
    versions = json.loads(resp.read())

latest = versions[0]
YOUR_MOD_JAR = None
for f in latest["files"]:
    fn = f["filename"]
    if fn.endswith(".jar") and "sources" not in fn and "dev" not in fn:
        YOUR_MOD_JAR = f
        break

# Define companion mods with verified project IDs
MODS = [
    ("Workers' Collective", PROJECT_ID, YOUR_MOD_JAR),
    ("Fabric API", "P7dR8mSH", None),
    ("Sodium", "AANobbMI", None),
    ("Lithium", "gvQqBUqZ", None),
    ("Iris Shaders", "YL57xq9U", None),
    ("Continuity", "1IjD5062", None),
    ("LambDynamicLights", "yBW8D80W", None),
    ("Presence Footsteps", "rcTfTZr3", None),
    ("Roughly Enough Items", "nfn13YXA", None),
    ("Architectury API", "lhGA9TYQ", None),  # Required by REI
    ("Cloth Config", "9s6osm5g", None),      # Required by REI
    ("Xaero's Minimap", "1bokaNcj", None),
    ("Xaero's World Map", "NcUtCpym", None),
    ("Jade", "nvQzSEkH", None),
    ("Mouse Tweaks", "aC3cM3Vq", None),
]

def get_latest_version(project_id, token):
    """Get the latest 1.21 Fabric JAR info for a project."""
    url = f"https://api.modrinth.com/v2/project/{project_id}/version"
    req = urllib.request.Request(url, headers={"Authorization": token})
    with urllib.request.urlopen(req) as resp:
        versions = json.loads(resp.read())
    for v in versions:
        game_vers = v.get("game_versions", [])
        loaders = v.get("loaders", [])
        if "1.21" in game_vers and "fabric" in loaders:
            # Prefer primary file, then first .jar
            for f in v.get("files", []):
                if f.get("primary"):
                    return f
            for f in v.get("files", []):
                fn = f["filename"]
                if fn.endswith(".jar") and "sources" not in fn and "dev" not in fn and "shadow" not in fn:
                    return f
    return None

files_manifest = []
for name, pid, jar_obj in MODS:
    f = jar_obj or get_latest_version(pid, TOKEN)
    if f:
        files_manifest.append({
            "path": f"mods/{f['filename']}",
            "hashes": {"sha1": f["hashes"]["sha1"], "sha512": f["hashes"]["sha512"]},
            "env": {"client": "required", "server": "required"},
            "downloads": [f["url"]],
            "fileSize": f["size"]
        })
        print(f"  ✓ {name} -> {f['filename']}")
    else:
        print(f"  ✗ {name} -> SKIPPED (no 1.21 Fabric version)")

index = {
    "formatVersion": 1,
    "game": "minecraft",
    "versionId": "1.21",
    "name": "Your Modpack Name",
    "summary": "Short description for the launcher",
    "files": files_manifest,
    "dependencies": {
        "minecraft": "1.21",
        "fabric-loader": ">=0.16.9"
    }
}

os.makedirs("/tmp/mrpack", exist_ok=True)
with open("/tmp/mrpack/modrinth.index.json", "w") as f:
    json.dump(index, f, indent=2, ensure_ascii=False)

mrpack_path = os.path.expanduser("~/your-project/your-modpack.mrpack")
with zipfile.ZipFile(mrpack_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write("/tmp/mrpack/modrinth.index.json", "modrinth.index.json")

print(f"\n✅ .mrpack created: {mrpack_path} ({os.path.getsize(mrpack_path)} bytes)")
```

**Upload .mrpack to GitHub Releases:**
```python
import json, os, subprocess

with open(os.path.expanduser("~/.git-credentials")) as f:
    line = f.read().strip()
    _, rest = line.split("//", 1)
    _, pw_and_host = rest.split(":", 1)
    GH_TOKEN = pw_and_host.split("@")[0]

REPO = "YourUser/your-repo"
result = subprocess.run([
    "curl", "-s",
    f"https://api.github.com/repos/{REPO}/releases/latest"
], capture_output=True, text=True)
release_id = json.loads(result.stdout).get("id")

subprocess.run([
    "curl", "-s", "-X", "POST",
    f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name=your-modpack.mrpack",
    "-H", f"Authorization: token {GH_TOKEN}",
    "-H", "Content-Type: application/zip",
    "--data-binary", "@your-modpack.mrpack"
])
```

**Known pitfalls:**
- ❌ **Wrong project IDs** — Always verify by querying the API: `curl -s "https://api.modrinth.com/v2/project/$ID" | python3 -c "import json,sys; print(json.load(sys.stdin)['title'])"`. The slug != project ID, and old IDs may be wrong (e.g., Iris changed from YL57x5iU to YL57xq9U).
- ❌ **Search API with facets** returns empty results for some queries. Always use direct project IDs + Versions endpoint.
- ✅ **`urllib` needs auth headers** for every project query. Without token you get rate-limited.
- ✅ **`ensure_ascii=False`** in json.dump preserves emoji and special chars in the modpack name/summary.
- ✅ **Modpack filename** should be descriptive: `workers-collective-experience-pack.mrpack`
- ✅ **Add a README badge** pointing to the `.mrpack` download URL on GitHub Releases.

**File format (for reference):**
```json
{
  "formatVersion": 1,
  "game": "minecraft",
  "versionId": "1.21",
  "name": "Your Modpack Name",
  "summary": "Short description",
  "files": [
    {
      "path": "mods/mod.jar",
      "hashes": {"sha1": "...", "sha512": "..."},
      "env": {"client": "required", "server": "required"},
      "downloads": ["https://cdn.modrinth.com/data/.../versions/.../file.jar"],
      "fileSize": 455558
    }
  ],
  "dependencies": {
    "minecraft": "1.21",
    "fabric-loader": ">=0.16.9"
  }
}
```

How users install it:
1. Download the .mrpack file
2. Double-click it (Modrinth launcher auto-opens) OR File → Import
3. Launcher automatically downloads all mods and sets up the instance

#### Update README Badge

After the upload succeeds, update the Modrinth badge from "Coming Soon" to "Download":

```bash
# Old: [![Modrinth](https://img.shields.io/badge/Modrinth-Coming_Soon-00d571?style=flat-square&logo=modrinth)](docs/MODRINTH_DEPLOY.md)
# New: [![Modrinth](https://img.shields.io/badge/Modrinth-Download-00d571?style=flat-square&logo=modrinth)](https://modrinth.com/project/workers-collective)
```

#### Token Storage Strategy

Save the Modrinth token in **two places** for reliability:

1. **Project-local `.env`** — for manual/batch operations:
   ```bash
   echo 'export MODRINTH_TOKEN="mrp_xxxxx"' > ~/workers-collective/.env
   chmod 600 ~/workers-collective/.env
   ```

2. **Central Hermes `.env`** — for cron jobs and subagents:
   ```bash
   grep -v "MODRINTH_TOKEN" ~/./.env > /tmp/env_tmp
   mv /tmp/env_tmp ~/./.env
   echo 'export MODRINTH_TOKEN="mrp_xxxxx"' >> ~/./.env
   chmod 600 ~/./.env
   ```

### 8. Project Approval & Moderation Fixes

**Cannot be done via API.** After uploading, the project may be in `draft` status. The user must visit the Modrinth web page and click "Request Approval" — attempting to PATCH `status: "approved"` returns `"unauthorized"`.

For projects in `withheld` status (taken down by moderators):

1. **Fix the issues** the moderator cited (visible in the Modrinth web interface under Messages or on the project page)
2. **Common moderation issues:**
   - **Donation URL misuse (Section 5.4):** Links must lead to correctly labeled, publicly available, directly project-related resources. Fix by PATCHing `donation_urls` to use project-specific URLs:
     ```bash
     curl -s -X PATCH "https://api.modrinth.com/v2/project/$PROJECT_ID" \
       -H "Authorization: $MODRINTH_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{
         "donation_urls": [
           {"id": "ko-fi", "platform": "Ko-fi", "url": "https://ko-fi.com/YOUR_PROJECT_PAGE"},
           {"id": "paypal", "platform": "Paypal", "url": "https://paypal.me/YOUR_USER"}
         ]
       }'
     ```
     Ko-fi tip: use the project-specific page (`ko-fi.com/PROJECT_ID` like `X8X41Z2JIR`) not the generic profile (`ko-fi.com/username`).
   - **Unrelated gallery images (Section 5.5):** All images must be relevant to the project and have a Title. AI-generated concept art that doesn't show real in-game content is often rejected. Fix by deleting offending images (see "Delete Gallery Images" section) and uploading real in-game screenshots.
3. **Request re-review:** User must click the moderation button on the project page — this cannot be automated via API.
4. The project's `status` changes from `withheld` -> `processing` -> `approved`.

**Approval status codes (read-only via API):**
| Status | Meaning |
|--------|---------|
| `draft` | Not yet submitted for review |
| `processing` | Submitted for review, awaiting moderation |
| `approved` | Publicly listed |
| `rejected` | Rejected by moderator (reason in `moderator_message`) |
| `unlisted` | Live but not in search results |
| `withheld` | Taken down by moderators |

When `requested_status` is `"approved"` and `status` is `"processing"`, the project is in the review queue. No further action needed.

## API Reference

| Endpoint | Method | Purpose | Body Format |
|----------|--------|---------|-------------|
| `/v2/project/{id}` | PATCH | Update metadata (description, body, loaders, versions) | JSON |
| `/v2/project/{id}/icon?ext=jpg` | PATCH | Upload icon | Raw binary (image/jpeg or image/png) |
| `/v2/project/{id}/gallery?ext=jpeg&...` | POST | Add gallery image | Raw binary + query params for metadata |
| `/v2/project/{id}/gallery` | DELETE | Delete gallery images | Query param `url` (CDN webp URL) |
| `/v2/version` | POST | Upload a new version (JAR) | Multipart/form-data |
| `/v2/user` | GET | Validate token & get user info | — |
| `/v2/user/projects` | GET | List your projects | — |

**Gallery Deletion (critical learnings from trial & error):**
- ❌ JSON body `{"urls": ["..."]}` fails with "Query deserialize error: missing field `url`"
- ❌ URL without `--data-urlencode` fails with "not part of project's gallery" (URL encoding needed)
- ❌ Using `raw_url` (.png/.jpeg) instead of the CDN `url` (_350.webp) fails — must use exact URL from project API response
- ✅ `-G --data-urlencode "url=..."` is the only working syntax
- ✅ HTTP 204 (no body) = success
- ✅ Verify by re-fetching project and confirming `gallery` array is empty

Useful debugging command when gallery delete fails:
```bash
# Get all gallery webp URLs
curl -s "https://api.modrinth.com/v2/project/$PROJECT_ID" | python3 -c '
import json,sys
for g in json.load(sys.stdin).get("gallery", []):
    print(g["url"])
'

# Delete — MUST use CDN webp URL
curl -s -X DELETE "https://api.modrinth.com/v2/project/$PROJECT_ID/gallery" \
  -H "Authorization: $MODRINTH_TOKEN" \
  -G --data-urlencode "url=https://cdn.modrinth.com/data/.../xxxx_350.webp"
```

**Pitfalls**

- **Dependencies CANNOT be patched post-upload**: Each version's `dependencies` field is immutable after upload (Modrinth returns empty response/silent fail on PATCH). The fix is to **release a new minor version** with dependencies declared correctly from the start.
- **Modrinth does NOT read fabric.mod.json dependencies**: Even if your mod declares `"fabric-api": "*"` in `fabric.mod.json`, Modrinth ignores it. Each uploaded version gets `"dependencies": []` by default. You must explicitly add `{"project_id": "P7dR8mSH", "dependency_type": "required"}` in the upload metadata. Fabric API's Modrinth project ID is always `P7dR8mSH`.
- **Multipart field ordering**: In the version upload request, `data` field MUST come before file fields. Reversing gives: `"Error with multipart data: data field must come before file fields"`.
- **CLI tool limitations**: `modrinth_upload` CLI has no `--sources` flag, and Unicode/special characters in changelogs can cause `"Invalid character '-' in base62 encoding"` parsing errors. Use plain ASCII changelogs or bypass the CLI with direct curl.
- **Icon format**: JPG is smaller but must be < 256 KiB. Use `ffmpeg -q:v 15` for quality/size balance (result: ~10-40 KB).
- **Gallery images**: Same 256 KiB limit, scale to ~640px with `ffmpeg -vf "scale=min(640,iw):min(640,ih)" -q:v 15`.
- **xAI Imagen quirks**: No `model` or `size` params. Defaults to 1024×1024. Token prefix is `xai-`.
- **Version upload metadata**: Must include `file_parts: ["jar"]` (the name matches the multipart form field, not the file extension) in the JSON data inside multipart body. If you use the form field name `jar=@file.jar`, then `file_parts: ["jar"]`.
- **Game versions**: Must match exactly (e.g. `"1.21"` not `"1.21.1"`).
- **Icon endpoint**: First multipart attempt fails with "Content type error" — raw binary is the only working approach.
- **Gallery endpoint**: Multipart attempts fail with "missing field `featured`" — all metadata goes in URL query params.
- **Empty response = success**: Modrinth API returns 200 with no body on success for PATCH operations. Don't parse JSON.
