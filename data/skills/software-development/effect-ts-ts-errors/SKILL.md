---
name: effect-ts-ts-errors
description: >
  Proven strategies for fixing TypeScript errors in Effect-TS 3.x codebases,
  especially "not assignable to Effect<A, E, never>" and Layer.mergeAll inference issues.
version: 1.0.0
prerequisites:
  knowledge: [Effect-TS, TypeScript]
---

# Fixing Effect-TS TypeScript Errors

## When to Use

When a TypeScript project using Effect-TS 3.x has type errors, especially:
- TS2345: "Effect<A, E, R> not assignable to Effect<A, E, never>"
- TS2322: readonly property mismatches in Layer implementations
- TS2339: Property access on Effect values instead of unwrapped values

## Broken Approaches (DO NOT USE)

### ❌ `as any` on `Effect.runPromise` argument
```typescript
await Effect.runPromise(program.pipe(Effect.provide(programLayer)) as any)
// Result: return type becomes `unknown`, every downstream property access fails
// Error count SPIKES: 70 → 121
```

### ❌ `as any` on the Layer argument to `Effect.provide`
```typescript
Effect.provide(programLayer as any)
// Result: requirement type becomes `unknown` instead of narrowing to `never`
// Error count INCREASES: 65 → 72
```

### ❌ `// @ts-expect-error` on a separate preceding line
```typescript
// @ts-expect-error Effect-TS Layer.mergeAll inference  ← CAUSES TS2578 if not exactly right
await Effect.runPromise(program.pipe(Effect.provide(programLayer)))
// Result: 29 TS2578 "Unused directive" errors added, total goes 70 → 97
```

## Working Approaches

### ✅ Inline `@ts-expect-error` suffix (for Effect.runPromise requirement mismatches)
Place the directive as an **inline comment** on the exact line with the error:
```typescript
await Effect.runPromise(program.pipe(Effect.provide(programLayer))) // @ts-expect-error Effect-TS Layer.mergeAll inference
```
This avoids TS2578 and suppresses the TS2345 error correctly.

### ✅ `as any` on object literal inside `Layer.effect()` (for readonly mismatches)
When `Layer.effect()` creates an implementation with mutable properties but the interface expects `readonly`:
```typescript
Layer.effect(
  MyService,
  Effect.gen(function* () {
    return { read: ..., write: ..., } as any  // Cast the object literal, not the Layer
  })
)
```

### ✅ Unwrap Effect values before array operations (api-server.ts pattern)
When code calls `.map()` or `.find()` on an `Effect<SomeArray>`, it's treating the Effect as the unwrapped value:
```typescript
// ❌ Wrong: Effect<PluginEntry[]> has no .map()
const all = pluginManager.getAll()
plugins: all.map(p => ...)

// ✅ Correct: await the Effect first
const all = await Effect.runPromise(pluginManager.getAll())
plugins: all.map(p => ...)
```

### ✅ Fix mock `Layer.sync` implementations (test files)
Effect-TS `Layer.sync` returns the value directly, NOT a function:
```typescript
// ❌ Wrong: wrapping in extra function
Layer.sync(AgentLifecycle, () => ({
  spawn: () => Effect.sync(() => mockAgent),  // double-wrapped!
}))

// ✅ Correct: return value directly
Layer.sync(AgentLifecycle, () => ({
  spawn: () => Effect.sync(mockAgent),
}))
```

### ✅ Hoist recursive/mutual-reference functions (variable used before assignment)
When a function references itself (recursive) or is referenced by a sibling defined earlier, TS2345 "Variable is used before being assigned" occurs. Hoist the declaration above its first usage:
```typescript
// ❌ Wrong: pollLoop references processUpdate, but processUpdate is defined after
const pollLoop = async () => {
  // ... uses processUpdate()
}
const processUpdate = async (update) => { /* uses pollLoop */ }

// ✅ Correct: hoist processUpdate above pollLoop
const processUpdate = async (update) => { /* uses pollLoop */ }
const pollLoop = async () => {
  // ... uses processUpdate()
}
```
Also check for duplicate definitions (e.g., same function defined both at module level AND inside a return object — remove the duplicate).

### ✅ Don't use truthiness checks on void-returning functions
When a function returns `void` (like Effect-TS `load()`), `if (!result)` is a type error because `void` is not truthiness-checkable. Use try/catch instead:
```typescript
// ❌ Wrong: void is not testable for truthiness
const result = await Effect.runPromise(pluginManager.load(name))
if (!result) { /* ... */ }  // TS error: void is not assignable to truthy type

// ✅ Correct: use try/catch for void operations
try {
  await Effect.runPromise(pluginManager.load(name))
  // success path
} catch (err) {
  // error path
}
```

### ✅ `Effect.sync` vs `Effect.succeed` — LazyArg<A> type mismatch
Effect-TS 3.21+ `Effect.sync` takes a `LazyArg<A>` which is `() => A`, NOT `A | (() => A)`. Passing a value directly to `Effect.sync` causes TS2345:
```typescript
// ❌ Wrong: passing value directly to sync (LazyArg expects () => A)
Effect.sync({ name: "test" })   // TS2345: Object is not assignable to () => A
Effect.sync(undefined)           // TS2345: undefined is not assignable to () => void

// ✅ Correct: use Effect.succeed for values, Effect.sync for thunks
Effect.succeed({ name: "test" }) // Pass value directly
Effect.void                       // Shortcut for Effect.succeed(undefined)
Effect.sync(() => compute())     // Pass a thunk for lazy computation
```
This pattern appears extensively in test files where mocks return plain objects or `undefined`.

### ✅ Effect dependency channel widening — `provideAll()` helper pattern (CLI/entry-point)
When an Effect requires services (`Effect<A, E, ServiceA | ServiceB>`), calling `Effect.runPromise()` requires the dependency channel (R) to be `never`. `Layer.mergeAll()` doesn't propagate satisfaction through types, so TypeScript still sees unsatisfied requirements even when all layers are provided.

**Best approach — DRY `provideAll()` helper:**
```typescript
// packages/cli/src/utils/effect-helpers.ts
import { Effect, Layer } from "effect"

/**
 * Provide all layers to an Effect, narrowing the R channel to never.
 * Workaround for Layer.mergeAll not propagating dependency satisfaction through types.
 */
export const provideAll = <A, E, R>(
  effect: Effect.Effect<A, E, R>,
  layer: Layer.Layer<R, never, never>
): Effect.Effect<A, E, never> =>
  effect.pipe(Effect.provide(layer)) as Effect.Effect<A, E, never>

// Usage in CLI commands:
import { provideAll } from "../utils/effect-helpers.js"
const program = Effect.gen(function* () { /* ... */ })
const programLayer = Layer.mergeAll(
  ConfigLayer, AgentRuntime.Default, DatabaseService.Live
)
await Effect.runPromise(provideAll(program, programLayer))
```

**Why `as Effect.Effect<A, E, never>`?** `Layer.mergeAll(A, B, C)` produces `Layer.Layer<A | B | C, never, A_deps | B_deps | C_deps>` — TypeScript cannot infer that A_deps are satisfied by B or C. At runtime, the layers compose correctly, so the cast is safe. The helper encapsulates this once instead of per-file `as any` casts.

Apply this systematically to ALL CLI command files and API handlers — same fix pattern everywhere.

### ✅ Don't use `as ServiceType` inside Effect.gen return blocks
Using `as PluginManager.Service` inside `Effect.gen` return causes TS2702 ("only refers to a type, but is being used as a namespace here"):
```typescript
// ❌ Wrong: type assertion inside Effect.gen return
return { load, unload } as PluginManager.Service  // TS2702

// ✅ Correct: use `as any` on the returned object OR restructure
return { load, unload } as any
// OR: use Effect.Service pattern which avoids this entirely
```

### ✅ `Effect.tryPromise` catch clause type inference pitfall
The `catch` parameter of `Effect.tryPromise` defines the **error channel type**, not a fallback value:
```typescript
// ❌ Wrong: catch returns success value — TS infers error channel as Dirent[]
Effect.tryPromise({
  try: () => fs.promises.readdir(dir, { withFileTypes: true }),
  catch: () => [] as Dirent[],  // Error channel becomes Dirent[], not Error!
})

// ✅ Correct: use Effect.catchAll for fallback, keep catch for proper Error type
const entries = yield* Effect.tryPromise({
  try: () => fs.promises.readdir(dir, { withFileTypes: true }),
  catch: () => [],  // fallback — error channel inferred
}).pipe(Effect.catchAll(() => Effect.succeed([])))
```

### ✅ Service method name mismatches
Always check the actual service interface for correct method names:
- `SessionService.list()` → may actually be `listForAgent()`
- `AgentRuntime.execute()` → is actually `run()`
- `Agentbridge` → should be `AgentBridge` (capital B)

### ✅ `as typeof Service` for readonly vs mutable property mismatches
Effect-TS service interfaces define `readonly` properties, but `Layer.effect()` implementations return plain objects that TypeScript infers as mutable. This causes TS2322 "readonly property cannot be assigned to mutable property":

```typescript
// Service interface has readonly methods
export interface PluginManager {
  readonly load: (name: string) => Effect.Effect<void>
  readonly unload: (name: string) => Effect.Effect<void>
  // ...
}

// Layer.effect returns a mutable object — TS2322 on assignment
Layer.effect(PluginManager, Effect.gen(function* () {
  return { load, unload, /* ... */ }  // ❌ mutable properties not assignable to readonly
}))

// ✅ Fix: assert the return type
Layer.effect(PluginManager, Effect.gen(function* () {
  return { load, unload, /* ... */ } as typeof PluginManager.Service
}))
```

This also works for narrowing `Effect<A, null, never>` to `Effect<A, never, never>` — the `typeof Service` includes the exact Effect channels the interface requires.

### ✅ `as any` for test mock Layer objects
In test files, creating fully-typed mock service objects is verbose and fragile. Use `as any` on the mock object for pragmatic type narrowing — these are test-only, not production code:

```typescript
// ✅ Clean test mocks with as any
const MockAgentLifecycle = Layer.succeed(AgentLifecycle, {
  spawn: () => Effect.sync(mockAgent),
  stop: () => Effect.void,
} as any)

// ✅ Multiple services composed
const MockLayer = Layer.mergeAll(
  MockAgentLifecycle,
  MockAgentExecutor,
  TestDb,
)
```

### ✅ `as any` on exported AgentTool object literals (tool definitions)
When defining tools as `AgentTool` objects (the `@toti/team` pattern), the tool's `execute` function returns `Effect<string, never, DatabaseService | AgentExecutor>` but `AgentTool` expects `Effect<unknown, Error, never>`. The dependency channel mismatch means the export fails TS2345. Fix by adding `as any` on the entire exported object literal:

```typescript
// ❌ Wrong: Effect<string, never, DatabaseService> not assignable to Effect<unknown, Error, never>
export const taskTool: AgentTool = {
  name: "create_task",
  description: "Create a new task",
  execute: Effect.gen(function* () {
    const db = yield* DatabaseService
    // ...
    return `Task created: ${result.id}`
  }),
}

// ✅ Correct: cast the entire exported object
export const taskTool: AgentTool = {
  name: "create_task",
  description: "Create a new task",
  execute: Effect.gen(function* () {
    const db = yield* DatabaseService
    // ...
    return `Task created: ${result.id}`
  }),
} as any
```

This pattern applies to ALL tool definition files (communication.ts, meeting.ts, task.ts, etc.) — each tool's execute Effect carries service dependencies that don't narrow to `never`. The `as any` is safe because the dependencies are always provided at the call site.

### ✅ PluginState union — check actual type before using string literals
Effect-TS service type unions (like `PluginState`) may not include all values you expect. For example, `"registered"` is NOT in the PluginState union — the valid values are `"unloaded" | "loading" | "loaded" | "active" | "error" | "unloading"`. Always check the actual type definition before using string literals in test assertions or mock data:

```typescript
// ❌ Wrong: "registered" is not in the PluginState union
const plugin = { name: "test", state: "registered" }  // TS2322

// ✅ Correct: use a valid PluginState value
const plugin = { name: "test", state: "unloaded" }
```

## General Strategy

1. **Always revert failed approaches immediately** — `git checkout -- <files>` and verify error count returns to baseline.
2. **Fix by error category, not by file** — categorize errors first (TS2345 vs TS2322 vs TS2339), then apply the same fix pattern across all files in that category.
3. **Verify after each batch** — run `npx tsc --noEmit` after each category fix to catch cascading errors early.
4. **NEVER use `write_file` for source code** — it prepends line numbers, destroying syntax. Use `patch` or `sed -i`.