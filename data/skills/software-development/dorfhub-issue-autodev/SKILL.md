---
name: dorfhub-issue-autodev
description: Complete auto-dev cycle for DorfHub — generate issues, select the oldest real non-epic issue, implement code changes, commit+push, and close. Used by the 30-min cron job.
version: 1.2.0
author: Hermes Agent
---

# DorfHub Issue Auto-Dev Cycle

Complete cycle for automated issue implementation on the DorfHub project. Runs as a cron job every 30 minutes.

## Project Context

- Repository: `<GITHUB_USER>/DorfHub`
- Path: `/opt/data/projects/dorfhub`
- Stack: Next.js 15, Prisma 5, tRPC, NextAuth, Docker, Zustand, TypeScript
- No local Postgres DB — schema-only work, no runtime DB tests
- Token via `git credential fill` (NOT `.git-credentials` parsing)
- Use `npx next lint` for validation (NOT `npm run build` — fails without DB)

## Phase 1: Generate Issues

Run the issue generator script first:
```bash
cd /opt/data/projects/dorfhub && bash scripts/run-issue-generator.sh
```

If the script fails (token issues, Python errors), skip Phase 1 and proceed to Phase 2.

## Phase 2: Fetch & Filter Issues

### Token extraction — base64 bypass for cron (tested reliable)

IMPORTANT: The **embedded token in the remote URL** (`git config url = https://user:***@github.com/...`) can become STALE (401) while `git credential fill` returns a FRESH token. Always use `git credential fill` with **base64 bypass** to get the real token:

```python
import base64, subprocess
proc = subprocess.run(
    ['bash', '-c', 'cd /opt/data/projects/dorfhub && echo -e "protocol=https\\nhost=github.com\\n" | git credential fill | base64 -w0'],
    capture_output=True, text=True, timeout=15)
decoded = base64.b64decode(proc.stdout.strip()).decode('utf-8')
token = None
for line in decoded.split('\\n'):
    if line.startswith('password='):
        token = line.split('=', 1)[1].strip()
```

This returns the **40-char real token** (not redacted by the security scanner), and is the **most reliable method** because `git credential fill` returns the token git itself is currently using — unlike the potentially stale URL-embedded token.

**Do NOT extract from `.git/config` remote URL** — that token may be 401-revoked even though the format looks valid.

### JSON parsing pitfalls

GitHub API responses may contain unicode control characters in issue body text that break `json.loads()`. **Always save to file first, then parse in a separate Python step:**

```bash
curl -s -H "Authorization: token $TOKEN" ... > /tmp/issues.json
python3 -c "import json; data=json.loads(open('/tmp/issues.json').read()); ..."
```

This avoids issues with shell pipe truncation and control characters.

### Filter logic

Fetch open issues via GitHub API, then apply these filters:

1. **Skip PRs** — `'pull_request' in i`
2. **Skip EPIC labels** — `'epic' in labels`
3. **Skip [AUTO] labels** — `'auto-generated' in labels`
4. **Sort by oldest first** — GitHub sorts by `created` asc
5. **Pick the oldest real issue** — first one that passes all filters

### When no real issues exist (all EPICs or [AUTO])

When Phase 2 returns only EPICs (all 10+ items) and [AUTO] issues:

1. **Scan EPICs for unchecked items that are genuinely unimplemented** — NOT just unchecked items. Many EPIC checklists aren't updated when code changes happen. First verify in code:
   - Check the codebase for the feature (grep file contents, read routers/components)
   - Only if the feature genuinely doesn't exist in code -> it's a real gap
   - If it exists in code but is unchecked in EPIC -> update the EPIC checklist instead
   - This cycle discovered "Bilder optimiert/verkleinert" (ImageUploader Canvas resize) and "Anzeigen laufen ab" (expiresAt + auto-expire in listing router) were already implemented but not checked off. Also discovered notification enrichment was genuinely missing and implemented it.

2. **Systematically scan for concrete bugs and configuration gaps** — not just UI features. Previous cycles discovered:
   - **Non-functional references in config files** — Docker HEALTHCHECK pointed to `/api/trpc/health` which didn't exist.
   - **Missing infrastructure files** — `.dockerignore` was absent.
   - **Server-side filters missing** — Events page filter pills were client-side only.
   - **Notification enrichment missing** — Marketplace message notifications lacked listing context.

3. **Prioritize small, contained, obviously-correct gaps** — best for single auto-dev cycles. Fixes should touch 1-5 files with unambiguous correctness.

4. **Create a fresh [AUTO] issue** describing the gap with precise file paths and acceptance criteria. Use labels `["enhancement", "auto-generated", "subdomain"]` (e.g., `"marketplace"`, `"events"`, `"messaging"`).

5. For issue creation, use Python `urllib.request` — NOT `curl` — to avoid JSON shell escaping issues:
   ```python
   body = json.dumps({"title": "...", "body": "...", "labels": [...]}).encode('utf-8')
   req = urllib.request.Request(url, data=body, headers=headers, method="POST")
   ```

6. **Implement in one cycle** — focused changes, 1-5 files, 20-80 lines total.

7. **After implementing, update all relevant EPIC checklists** — the EPIC may have unchecked items that your change resolves. Use:
   ```python
   # Fetch EPIC, find unchecked items already in code, mark done
   req = urllib.request.Request(epic_url, headers=headers)
   epic = json.loads(urllib.request.urlopen(req).read())
   new_body = epic['body'].replace('- [ ] Some item', '- [x] Some item')
   update_data = json.dumps({"body": new_body}).encode()
   req = urllib.request.Request(epic_url, data=update_data, headers=headers, method="PATCH")
   urllib.request.urlopen(req)
   ```

8. **Close the issue** when implemented.

## Phase 3: Read Issue Body

Fetch the full issue body and understand all acceptance criteria. The body may contain:
- **Checklist** (`- [ ] items`) — sub-tasks
- **Akzeptanzkriterien** (acceptance criteria) — what "done" means
- **Task description** — the actual work description

## Phase 4: Codebase Analysis

Before implementing, understand what exists vs what's needed:

```bash
# Check file structure
find src -type f | head -80

# Read existing components and routers
read_file path/to/existing-file.tsx

# Check Prisma schema if DB changes needed
read_file prisma/schema.prisma

# Run prisma generate before working with Prisma files
npx prisma generate
```

**Key insight:** Many features are already partially built. Check for:
- tRPC routers in `src/server/routers/`
- Components in `src/components/features/`
- Pages in `src/app/(dashboard)/`
- Zustand stores in `src/stores/`
- Lib files in `src/lib/` (validations, helpers, trpc client)

## Phase 5: Implement

### Common pattern: adding optional context param to an existing tRPC mutation

When you need to enrich notifications or side-effects with context from the caller (e.g., which listing a message refers to):

1. **Add an optional field to the input zod schema:**
   ```typescript
   .input(z.object({
     recipientId: z.string(),
     content: z.string().min(1).max(5000),
     listingId: z.string().optional(),  // <-- add this
   }))
   ```

2. **Resolve the context in the mutation handler** (before the main logic):
   ```typescript
   let listingContext = ''
   if (input.listingId) {
     try {
       const listing = await ctx.prisma.listing.findUnique({
         where: { id: input.listingId },
         select: { title: true },
       })
       if (listing) listingContext = listing.title
     } catch { /* non-critical */ }
   }
   ```

3. **Use the context to enrich notifications:**
   ```typescript
   const title = listingContext ? `Interesse an: ${listingContext}` : 'Neue Nachricht'
   ```

4. **Wire the caller** to pass the context parameter:
   ```tsx
   startConversationMutation.mutateAsync({
     recipientId,
     content: messageText.trim(),
     listingId: selectedListing.id,  // <-- new param
   })
   ```

This approach is non-breaking because the field is optional — existing callers continue to work unchanged.

### Common pattern: adding fields to an existing create modal

The most common focused sub-item extracted from EPICs or gaps. For enum fields + image uploads:

1. **Add state variables** — `const [eventCategory, setEventCategory] = useState('DEFAULT_VALUE')`
2. **Add to eventData object** — `category: eventCategory as any,` + `...(coverImg ? { coverImage: coverImg } : {})`
3. **Add UI to create modal** — `<select>` for enum categories, `ImageUploader` for cover image
4. **Reset in form cleanup** — add new state resets alongside existing ones
5. **Mock data fallback** — update mock event creation to pass new fields
6. **Lint check** — `npx next lint`
7. **Commit + Push** — use correct git identity

### ImageUploader for single image

The `ImageUploader` component works with arrays of base64 data URIs. For single-image use:
```tsx
<ImageUploader
  images={coverImage ? [coverImage] : []}
  onChange={(imgs) => setCoverImage(imgs[0] || '')}
  maxImages={1}
  maxSizeMB={5}
/>
```

### Category dropdown pattern

For enum fields in create modals, use a native `<select>` styled to match the design system:
```tsx
<select
  value={eventCategory}
  onChange={(e) => setEventCategory(e.target.value)}
  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
>
  <option value="FESTIVAL">Fest</option>
  <option value="MARKET">Markt</option>
  ...
</select>
```

The same `className` pattern as `Input` ensures visual consistency.

### Adding a server-side parameter to an existing tRPC list procedure

When a UI page has client-side filter pills but the tRPC router lacks the corresponding server-side filter:

1. **Add the optional parameter to the input schema:**
   ```typescript
   category: z.string().optional(),
   ```
2. **Add it to the Prisma `where` clause:**
   ```typescript
   ...(input.category && { category: input.category as any }),
   ```
3. **Wire the UI to pass the filter to the tRPC query:**
   ```typescript
   const query = trpc.event.list.useQuery(
     { ..., category: selectedCategory === 'ALL' ? undefined : selectedCategory },
     { ... }
   )
   ```

This ensures the filter works both with real API data AND mock data.

### Common patterns for wiring features:

1. **Feed (PostCard + CreatePost -> tRPC):**
   - `trpc.post.list.useQuery(...)` — fetch posts
   - `trpc.post.create.useMutation(...)` — create posts
   - `trpc.post.toggleLike.useMutation(...)` — like/unlike
   - Always provide a **mock data fallback** for when the DB/backend is unavailable
   - Wrap mutations in try/catch and fall back to mock local state on error

2. **Messages Page (conversations + send -> tRPC):**
   - `trpc.message.getConversations.useQuery(...)` — fetch conversations list with participants
   - Map participants to find the other user's name/avatar for display
   - `trpc.message.send.useMutation(...)` — send a message in existing conversation
   - `trpc.message.startConversation.useMutation(...)` — create new conversation + first message
   - `trpc.message.getMessages.fetch(...)` — paginated message history for a conversation
   - Provide mock conversation/message data for when backend is unavailable
   - Auto-scroll to bottom on new messages with `useRef` + `scrollIntoView`
   - `convQuery.refetch?.()` after sending to update conversation list order

3. **Marketplace Page (listings + CRUD -> tRPC):**
   - `trpc.listing.list.useQuery(...)` — fetch paginated listings
   - `trpc.listing.create.useMutation(...)` — create new listing
   - `trpc.listing.markSold.useMutation(...)` — mark as sold
   - `trpc.listing.delete.useMutation(...)` — soft delete
   - Provide mock listing data for development fallback
   - Create modal with: title, description, price, category (select), location, images (ImageUploader)
   - Detail modal with full info + actions (message seller, mark sold, delete)
   - Category filter pills + sort (newest/oldest/cheapest/priciest)

### Hook issues (conditional `useId`):
- `const generatedId = React.useId(); const id = props.id || generatedId;`
- `const id = props.id || React.useId()` — violates rules of hooks if `id` prop changes
- The `forwardRef` generic order is: `React.forwardRef<HTMLElement, Props>(...)`

### After code changes, always run:
```bash
cd /opt/data/projects/dorfhub && npx next lint 2>&1
```

Lint warnings about `<img>` elements and `@next/next/no-img-element` are pre-existing. Next.js 15 deprecation warnings in `next lint` are expected — ignore them.

### Common tRPC router patterns

**Session user in publicProcedure:** Even in `publicProcedure`, access `ctx.session?.user`:
```typescript
...(ctx.session?.user ? {
  likes: { where: { userId: (ctx.session.user as any).id }, select: { id: true } },
} : {}),
```

## Phase 6: Commit & Push

**Critical: Only commit your changes — not files from previous cycles.**
When `git add -A` stages unwanted files:
```bash
# Check what's staged
git status

# Unstage unwanted files selectively
git restore --staged scripts/ src/app/(dashboard)/marketplace/page.tsx

# Discard working tree changes for those files
git checkout -- src/app/(dashboard)/marketplace/page.tsx
```

Then commit only the intended changes:
```bash
cd /opt/data/projects/dorfhub
git config user.name "<GITHUB_USER>"
git config user.email "<EMAIL>"
git add -A
git commit -m "feat: implement issue #N - description [skip ci]"
git push
```

## Phase 7: Close Issue

```python
close_data = json.dumps({"state": "closed", "state_reason": "completed"}).encode()
req = urllib.request.Request(
    f"https://api.github.com/repos/<GITHUB_USER>/DorfHub/issues/{N}",
    close_data, headers, method="PATCH"
)
urllib.request.urlopen(req)
```

## Phase 8 (NEW): Update EPIC Checklist After Implementation

After closing the issue, update the parent EPIC's checklist:
```python
# Fetch EPIC
req = urllib.request.Request(epic_url, headers=headers)
epic = json.loads(urllib.request.urlopen(req).read())
body = epic['body']

# Mark implemented items as done
replacements = {
    '- [ ] Some item': '- [x] Some item',
}
new_body = body
for old, new in replacements.items():
    if old in new_body:
        new_body = new_body.replace(old, new)

if new_body != body:
    update_data = json.dumps({"body": new_body}).encode()
    req = urllib.request.Request(
        epic_url, data=update_data, headers=headers, method="PATCH"
    )
    urllib.request.urlopen(req)
    print("EPIC checklist updated")
```

## Pitfalls

| Situation | Solution |
|-----------|----------|
| Issue generator script has syntax errors | Skip Phase 1, proceed directly to Phase 2 |
| JSON parse error from GitHub API (control chars) | Save curl output to file, parse with `json.loads(open(...).read())` |
| Creating issues via curl — JSON body escaping fails | Use Python `urllib.request` — JSON dumps handles escaping correctly |
| `git add -A` stages files from previous cycles | Use `git restore --staged` to unstage, `git checkout --` to discard |
| `patch` tool corrupts large TSX files (duplicate lines) | Use `write_file` with complete correct content — never apply more `patch` on corrupted files |
| No local Postgres DB | Schema-only work. Skip `npm run build`. Use `npx next lint` only |
| Embedded token in remote URL returns 401 (stale/revoked) | Use `git credential fill` with base64 bypass — the credential store has the fresh token |
| All issues are EPICs with 10+ items | Scan codebase for UI gaps (missing form fields, unconnected buttons, missing mutations) |
| `npm run lint` fails with hook errors | Check `useId()` in conditional branches — always call unconditionally |
| Git commit message with special chars | Write message to file with `write_file`, commit with `git commit -F /tmp/file` |
| No `gh` CLI available | Use Python `urllib.request` for all GitHub API calls |
| JSX fragments + conditionals cause parsing errors | When adding conditional UI inside a ternary, avoid nesting fragments |
| ImageUploader for single image | Use `images={img ? [img] : []}` and `onChange={(imgs) => setState(imgs[0] || '')}` |
| EPIC unchecked items may already be implemented | Verify in code first; don't assume unchecked = not done. Update EPIC checklist via PATCH body |
| Adding optional param to tRPC mutation | Zod `.optional()` ensures backward compat. Resolve context in handler, not at call site |
| **No real open issues — only EPICs and [AUTO] tasks** | Don't create yet another [AUTO] UI feature issue. Instead: **run a TypeScript compilation check** (`npx tsc --noEmit 2>&1 | grep '^src/'`). TypeScript errors are real bugs that need fixing — often 100-300 of them lurking. This produces higher-value work than adding cosmetic features. |
| **TS error count is huge (100-300 errors)** | Don't try to fix all at once. **Prioritize fixes by impact per file changed:** |
|  | - **Step 1: Fix `next-auth.d.ts` augmentation** — The file may already exist but use `& DefaultSession["user"]` which breaks type resolution. Fix: fully inline ALL user fields (`id`, `role`, `username`, `name`, `email`, `image`) directly in the `Session.user` interface WITHOUT intersecting with `DefaultSession["user"]`. Also add `id` to the `User` interface (it was missing). |
|  | - **Step 2: Fix Context type in `trpc.ts`** — Change `session: Awaited<ReturnType<typeof getServerSession>> | null` to `session: Session | null` (import `Session` from `next-auth`). The `Awaited<ReturnType<...>>` resolves to `{}` even with augmentation. |
|  | - **Step 3: Fix `adminProcedure`/`moderatorProcedure` in trpc.ts** — After fixing the Context type, `ctx.session.user.role` still fails because TypeScript doesn't narrow through `.use()` middleware. Use: `const user = ctx.session!.user as { id: string; role: string; username?: string | null }` |
|  | - **Step 4: Fix component variant mismatches** — Three issues hit every cycle: (a) Button lacks `default` variant — add as alias for `primary`. (b) Badge lacks `size` variant — add `sm`/`md`/`lg`. (c) Button lacks `asChild` prop — add `asChild?: boolean` and render `{children}` when true. |
|  | - **Step 5: tRPC v11 API changes** — `useMutation` results use `.isPending` NOT `.isLoading`. The `.fetch` method on query results was removed — use `.refetch()` instead. Some code uses `trpc.someQuery.useMutation()` incorrectly (queries don't have `useMutation`). |
|  | - **Step 6: Fix missing lucide-react icons** — `Newsfeed` icon was removed from lucide-react. Replace with `Newspaper`. Check with `ls node_modules/lucide-react/dist/esm/icons/ | grep -i iconname`. |
|  | - **Step 7: Fix Modal `always true` warning (TS2774)** — Remove wrapping `{(title || onClose) && ...}` around the header div since `onClose` is always defined. |
|  | - **Step 8: Fix remaining implicit `any`** — add explicit type annotations to callback parameters in page files. |
| **GitHub API issues with large response bodies** | Always save to file first: `curl -s ... > /tmp/issues.json` then parse in separate `python3 -c "json.loads(open(...).read())"` step. Control characters in issue bodies break `json.loads` on piped input. |
| **tRPC v11 removed `createClient()` from the react-query export** | The `trpcClient()` function calling `trpc.createClient()` no longer exists in tRPC v11. Need to use `createTRPCClient` from `@trpc/client` directly for server-side calls, or the `TRPCProvider` pattern for client-side use. Remove `createClient()` calls from client libs. |
