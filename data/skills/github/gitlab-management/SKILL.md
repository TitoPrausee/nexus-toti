---
name: gitlab-management
description: Manage GitLab projects, issues, milestones, and merge requests via the REST API. Handles auth with PRIVATE-TOKEN and covers project discovery, issue CRUD, label management, and milestone linking.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [GitLab, Issues, Project-Management, Milestones, API]
    related_skills: [github-issues, github-repo-management]
---

# GitLab Management via REST API

Manage GitLab.com or self-hosted GitLab projects, issues, milestones, and MRs via the REST API using curl.

## Prerequisites

- GitLab Personal Access Token with `api` scope
- Store in environment or memory for reuse

### Auth Setup

```bash
# From memory: username <GITHUB_USER>e (triple 'e'), user ID 28680845
# For gitlab.com:
GL_TOKEN="glpat-XXXXXXXXXX"
GL_HOST="https://gitlab.com"

# For self-hosted:
# GL_HOST="https://gitlab.example.com"

# Test auth:
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" "$GL_HOST/api/v4/user" | python3 -c "import sys,json; u=json.load(sys.stdin); print(f'Authed as: {u[\"username\"]} (ID: {u[\"id\"]})')"
```

**Key difference from GitHub:** GitLab uses `PRIVATE-TOKEN` header, not `Authorization: token Bearer`.

## PITFALL: Global Issues Endpoint Unreliable

**The global `/api/v4/issues` endpoint can return 500 errors.** Always query issues per-project instead:

```bash
# BAD - can return 500:
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" "$GL_HOST/api/v4/issues?state=opened"

# GOOD - query per project:
PROJECT_ID=77898597
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" "$GL_HOST/api/v4/projects/$PROJECT_ID/issues?state=opened&per_page=100"
```

## 1. Discovering Projects

### List Your Projects

```bash
# By user ID
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/users/28680845/projects?per_page=50&membership=true" | \
  python3 -c "
import sys, json
for p in json.load(sys.stdin):
    desc = (p.get('description') or '')[:60]
    print(f'{p[\"id\"]:10}  {p[\"path_with_namespace\"]:50}  {desc}')
"
```

**PITFALL: `description` can be `null`.** Always use `(p.get('description') or '')` — not just `p.get('description', '')` since the key exists but value is `null`.

### List Projects Under Another User/Group

```bash
# ts420126 account (secondary account)
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/users/<USER_ID>/projects?per_page=50" | python3 -c "..."
```

### Get Project ID from Path

```bash
# URL-encoded path works as project ID in GitLab API
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/ts420126%2Fmedo" | \
  python3 -c "import sys,json; p=json.load(sys.stdin); print(p['id'])"
```

## 2. Issues

### List Open Issues

```bash
PROJECT_ID=77898597
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues?state=opened&per_page=100" | \
  python3 -c "
import sys, json
for i in json.load(sys.stdin):
    labels = ', '.join(i.get('labels', [])) or '-'
    milestone = (i.get('milestone') or {})
    ms_title = milestone.get('title', '-') if milestone else '-'
    print(f'  #{i[\"iid\"]:5}  [{labels:40}]  ms:{ms_title:20}  {i[\"title\"][:60]}')
"
```

**Note:** GitLab uses `iid` (project-scoped) not `id` (global). Use `iid` for all project-scoped operations.

### Pagination

```bash
# Page 1
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues?state=opened&per_page=100&page=1"

# Page 2
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues?state=opened&per_page=100&page=2"
```

Check `X-Next-Page` header for more pages.

### View Single Issue

```bash
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues/42" | \
  python3 -c "
import sys, json
i = json.load(sys.stdin)
print(f'#{i[\"iid\"]}: {i[\"title\"]}')
print(f'State: {i[\"state\"]}  Author: {i[\"author\"][\"username\"]}')
labels = ', '.join(i.get('labels', []))
print(f'Labels: {labels}')
print(f'Milestone: {(i.get(\"milestone\") or {}).get(\"title\", \"-\")}')
print(f'\\n{i.get(\"description\", \"\")}')
"
```

### Create Issue

```bash
curl -s -X POST --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues" \
  -d '{
    "title": "Implement user authentication",
    "description": "## Description\nAdd JWT-based auth.\n\n## Acceptance Criteria\n- Login endpoint works\n- Token refresh works",
    "labels": "feature,backend,priority::P1",
    "milestone_id": 5
  }'
```

**Labels are comma-separated strings** in GitLab (not arrays like GitHub).

### Bulk Create Issues

**PITFALL: Shell escaping with JSON + German Umlauts is a nightmare.** When creating many issues programmatically, write each payload to a temp file and use `-d @/tmp/payload.json` instead of inline `-d '...'`:

```bash
# GOOD: Write to file, then send
echo '{"title":"Kalender: Urlaube und Abwesenheiten","description":"Wechselseitig eintragen","labels":"Organisation"}' > /tmp/issue.json
curl -s -X POST --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues" \
  -H "Content-Type: application/json" \
  -d @/tmp/issue.json

# BAD: Inline JSON with umlauts fails in shell
curl ... -d '{"title":"Freizuschaltende Dienste und Ordner klären"}'  # kären gets mangled
```

**PITFALL: `json.dumps()` with `ensure_ascii=False` in Python still breaks when piped to shell via `-d '{...}'`.** Semicolons, quotes, and special chars in descriptions get misinterpreted. Always use temp file approach.

**PITFALL: Project discovery requires `?search=` parameter — don't guess project IDs.** Use:
```bash
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects?search=fsu-connect-info" | \
  python3 -c "import sys,json; [print(f'ID: {p[\"id\"]}, path: {p[\"path_with_namespace\"]}') for p in json.load(sys.stdin)]"
```

### Update Issue

```bash
# Add labels
curl -s -X PUT --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues/42" \
  -d '{"labels": "feature,backend,priority::P1,in-progress"}'

# Close issue
curl -s -X PUT --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues/42" \
  -d '{"state_event": "close"}'

# Reopen
curl -s -X PUT --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues/42" \
  -d '{"state_event": "reopen"}'
```

### Comment on Issue

```bash
curl -s -X POST --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues/42/notes" \
  -d '{"body": "Root cause identified in auth middleware. Working on fix."}'
```

## 3. Milestones

### List Milestones

```bash
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/milestones?state=active" | \
  python3 -c "
import sys, json
for m in json.load(sys.stdin):
    print(f'  !{m[\"id\"]:5}  {m[\"title\"]:30}  {m[\"state\"]:10}  due:{m.get(\"due_date\",\"-\")}')
"
```

### Create Milestone

```bash
curl -s -X POST --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/milestones" \
  -d '{
    "title": "Sprint 4",
    "description": "Device Gateway integration",
    "due_date": "2026-05-15"
  }'
```

### Link Issue to Milestone

```bash
# When creating an issue:
"milestone_id": 5

# When updating an existing issue:
curl -s -X PUT --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/issues/42" \
  -d '{"milestone_id": 5}'
```

## 4. Labels

### List Labels

```bash
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/labels" | \
  python3 -c "
import sys, json
for l in json.load(sys.stdin):
    print(f'  {l[\"name\"]:30}  {l.get(\"description\", \"\")[:60]}')
"
```

### Create Label

```bash
curl -s -X POST --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/labels" \
  -d '{
    "name": "in-progress",
    "color": "#428bca",
    "description": "Currently being worked on"
  }'
```

**Note:** GitLab requires `color` (hex) when creating labels.

## 5. Merge Requests

### List Open MRs

```bash
curl -s --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/merge_requests?state=opened" | \
  python3 -c "
import sys, json
for mr in json.load(sys.stdin):
    print(f'  !{mr[\"iid\"]:5}  {mr[\"title\"][:70]}  ({mr[\"source_branch\"]} -> {mr[\"target_branch\"]})')
"
```

### Create MR

```bash
curl -s -X POST --header "PRIVATE-TOKEN: $GL_TOKEN" \
  "$GL_HOST/api/v4/projects/$PROJECT_ID/merge_requests" \
  -d '{
    "source_branch": "feature/auth",
    "target_branch": "main",
    "title": "feat: implement JWT authentication",
    "description": "Closes #42"
  }'
```

## 6. Scoped Labels (GitLab-specific)

GitLab supports scoped labels like `priority::P1`, `component::backend`, `sprint::3`. Issues can only have ONE value per scope (unlike GitHub where multiple labels of the same "category" can coexist).

This is actually useful — it enforces mutual exclusion. Use it for:
- `priority::P0` / `priority::P1` / `priority::P2`
- `sprint::0` / `sprint::1` / `sprint::2` / `sprint::3`
- `component::frontend` / `component::backend` / `component::gateway`
- `effort::S` / `effort::M` / `effort::L` / `effort::XL`
- `type::feature` / `type::bug` / `type::documentation` / `type::spike` / `type::testing`

## Quick Reference

| Action | Endpoint |
|--------|----------|
| List issues | `GET /projects/:id/issues?state=opened` |
| View issue | `GET /projects/:id/issues/:iid` |
| Create issue | `POST /projects/:id/issues` |
| Update issue | `PUT /projects/:id/issues/:iid` |
| Close issue | `PUT /projects/:id/issues/:iid` + `state_event=close` |
| Comment | `POST /projects/:id/issues/:iid/notes` |
| List milestones | `GET /projects/:id/milestones` |
| Create milestone | `POST /projects/:id/milestones` |
| List MRs | `GET /projects/:id/merge_requests?state=opened` |
| Create MR | `POST /projects/:id/merge_requests` |
| List labels | `GET /projects/:id/labels` |

## Key Differences from GitHub API

| Aspect | GitHub | GitLab |
|--------|--------|--------|
| Auth header | `Authorization: token $TOKEN` | `PRIVATE-TOKEN: $TOKEN` |
| Issue ID | `number` (global per repo) | `iid` (project-scoped) |
| Labels | Array of strings | Comma-separated string |
| Scoped labels | Not native | Native, mutually exclusive |
| Global issues | Works (`/search/issues`) | Unreliable (`/issues` → 500) |
| Null handling | Usually empty string | Often `null` explicitly |
| MR vs PR | `pull_requests` | `merge_requests` |
| Project ID | `owner/repo` string | Numeric ID or URL-encoded path |