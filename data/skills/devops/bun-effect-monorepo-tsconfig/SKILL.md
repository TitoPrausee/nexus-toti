---
name: bun-effect-monorepo-tsconfig
description: TypeScript configuration for Bun + Effect-TS monorepos. Fixes module resolution, downlevelIteration, workspace deps, and tsconfig pitfalls.
version: 1.0
---

# Bun + Effect-TS Monorepo TypeScript Configuration

## Trigger
When setting up or fixing TypeScript in a Bun monorepo that uses Effect-TS, especially when `tsc --noEmit` fails with module resolution errors, `downlevelIteration` errors, or `skipLibCheck` issues.

## Key Configuration (tsconfig.base.json)

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "downlevelIteration": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "noEmit": true,
    "lib": ["ES2022"],
    "types": ["bun"],
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "sourceMap": true,
    "resolveJsonModule": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true
  }
}
```

## Critical Settings Explained

1. **`moduleResolution: "bundler"`** — Required for Bun. `NodeNext`/`Node16` fails to resolve workspace packages that export `.ts` files via `package.json` `exports` field.

2. **`module: "ESNext"`** — Must match `moduleResolution: "bundler"`. `NodeNext` is incompatible with `bundler`.

3. **`allowImportingTsExtensions: true` + `noEmit: true`** — Required pair. Bun runs `.ts` files directly. `noEmit` is required when `allowImportingTsExtensions` is true. Since Bun handles compilation, `tsc` is only for type checking.

4. **`downlevelIteration: true`** — Effect-TS uses `yield*` on services (which are iterables). Without this, TS emits error TS2802.

5. **`skipLibCheck: true`** — Essential. `drizzle-orm`, `bun-types`, `effect` have hundreds of `.d.ts` conflicts (SingleStore, MySQL, Gel, etc.). These are upstream bugs.

6. **`types: ["bun"]`** — Use `bun` types, NOT `@types/bun` or `bun-types` separately.

7. **Do NOT use `declaration: true`** or `declarationMap: true` — Conflicts with `noEmit: true`.

## Do NOT Use `paths` for Monorepo Workspace Resolution

`paths` in `tsconfig.base.json` causes `rootDir` conflicts when child packages extend the base. Paths resolve relative to child dir, not monorepo root.

## Workspace Dependencies Must Be Explicit

Each package must declare ALL workspace dependencies in its `package.json`:

```json
{
  "dependencies": {
    "@opencode-fusion/core": "workspace:*",
    "@opencode-fusion/agent-runtime": "workspace:*"
  }
}
```

If missing, `bun install` won't create the symlink and `tsc` fails. Run `bun install` after adding deps.

## Package-Level tsconfig.json

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "__tests__"]
}
```

## Effect-TS Context.Tag Pattern

```typescript
// Keep Tag string and type parameter CONSISTENT (case-sensitive!)
export class AgentBridge extends Context.Tag("AgentBridge")<AgentBridge, { ... }>() {
  static readonly Live = Layer.effect(AgentBridge, Effect.gen(function* () { ... }))
  static readonly Default = AgentBridge.Live
}
```

Pitfall: Mixing `Agentbridge` (lowercase b) vs `AgentBridge` (uppercase B).

## Build vs Typecheck vs Run

- **Typecheck**: `tsc --noEmit` only
- **Build**: Use Bun's bundler, NEVER `tsc --emit`
- **Run**: `bun run src/index.ts` directly

## Common Error → Fix Table

| Error | Fix |
|-------|-----|
| Cannot find workspace module with moduleResolution hint | Change to `moduleResolution: "bundler"` + add missing workspace dep |
| TS2802: can only be iterated through with downlevelIteration | Add `downlevelIteration: true` |
| Property X not on type `{}` | Cast: `(ws.data as { sessionId: string }\|undefined)?.sessionId` |
| `verified: number` not assignable to `boolean` | Use `!!params.verified` for insert, `row.verified === true` for read |
| Bun.serve `host` not in type | Use `hostname` instead of `host` |
| TS6059: rootDir conflict with paths | Remove `paths`, use workspace deps instead |

## Breaking Circular Dependencies in Workspace Monorepos

If package A imports from package B and B imports from A, the cycle must be broken:
1. Identify which direction the **core** dependency should flow
2. Move integration/glue code (tools, orchestrators) **downstream** to the package that depends on both
3. Remove the upstream dep from `package.json`, add the correct direction
4. Fix all import paths in moved files
5. Update `exports` in downstream `package.json` for new subpath entries

**Real example**: `agent-runtime` had `@opencode-fusion/team` dep for task/meeting/communication tools. Moved those 3 tool files to `team/src/tools/`, flipped to `team → agent-runtime`, updated imports from `../executor.js` to `@opencode-fusion/agent-runtime`.

## Adding New DB Tables

After adding a table to `core/src/db/schema.ts` and the CREATE TABLE to `migrate.ts`:
- `export * from "./schema.js"` in `db/index.ts` covers it for compiled code
- BUT `bun test` loads `.ts` directly — stale `dist/` can cause `Export named 'X' not found`
- Fix: `rm -rf packages/core/dist .turbo` then rebuild, or ensure no stale dist exists

## Effect-TS `Effect.either` Pattern

`Effect.either()` returns `Either<Error, Success>` with `_tag: "Left" | "Right"`:
```typescript
const result = yield* Effect.either(someEffect)
if (result._tag === "Left") {
  // result.left is the error
} else {
  // result.right is the success value
}
```
Never assume `Effect.either` returns the raw type.

## TaskOrchestrator Wave Pattern (dependency-resolved parallel execution)

1. Create all tasks in DB with status "queued"
2. Loop: find tasks whose `dependencyIds` are all in "completed" set → sort by priority descending
3. Execute that wave via `Effect.all(effects, { concurrency: "inherit" })` for true parallelism
4. Collect results, add completed IDs to set, remove from remaining
5. If no tasks are ready but remaining > 0 → deadlock, fail them all
6. Repeat until remaining is empty or max waves reached

## Verification

```bash
bun run typecheck   # Typecheck all packages
bun test            # Run tests
npx tsc --noEmit    # Check specific package
```