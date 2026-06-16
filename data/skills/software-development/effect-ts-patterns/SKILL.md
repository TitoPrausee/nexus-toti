---
name: effect-ts-patterns
version: 1.2
description: Effect-TS v3 patterns and pitfalls for OpenCode Fusion. Includes TaskOrchestrator wave-based parallel execution pattern. — error channel narrowing, service definitions (Context.Tag vs Effect.Service Bun compat), TypeScript config, and Drizzle conventions
tags: [effect-ts, typescript, bun, monorepo, opencode-fusion]
diagram: |
  graph LR
      Schema["Schema"] --> Pipe["Pipe / gen"]
      Pipe --> Effect["Effect Runtime"]
      Effect --> ErrorCh["Error Channel"]
      ErrorCh --> Result((Result))
      style Schema fill:#16213e,stroke:#a78bfa,color:#fff
      style Pipe fill:#16213e,stroke:#22d3ee,color:#fff
      style Effect fill:#16213e,stroke:#34d399,color:#fff
      style ErrorCh fill:#16213e,stroke:#e94560,color:#fff
      style Result fill:#1a1a2e,stroke:#34d399,color:#fff
---

# Effect-TS Patterns for OpenCode Fusion

Common patterns and pitfalls when working with Effect-TS v3 in the OpenCode Fusion monorepo.

## Error Channel Type Narrowing

Effect-TS infers error channels strictly. A service interface requiring `Effect<A, LLMError, R>` will reject `Effect<A, string | LLMError, R>` — even a single string literal widens the whole channel.

### Pitfall 1: catch blocks returning string

```typescript
// BAD — widens error channel to string | LLMError
try {
  // ...
} catch {
  return "Unknown error"  // string infects the error channel
}

// GOOD — return the proper error class
} catch {
  return new LLMError("provider", "Failed to read error response")
}
```

### Pitfall 2: Effect.gen() infers `unknown` error channel

`Effect.gen()` infers its error channel as `unknown` because generator yields can throw anything. When the service interface requires a specific error type, you must narrow:

```typescript
// BAD — error channel inferred as unknown
static readonly Live = Layer.effect(MyService, Effect.gen(function* () {
  const result = yield* someEffect
  return result
}))

// GOOD — pipe with mapError to narrow
static readonly Live = Layer.effect(MyService, Effect.gen(function* () {
  const result = yield* someEffect
  return result
}).pipe(Effect.mapError((e) => e as LLMError)))
```

### Pitfall 3: Interface method return types must match exactly

When defining a `Context.Tag` service interface, the return types in the implementation must match precisely — including the error channel.

```typescript
// Interface says:
getAvailableModels: () => Effect.Effect<string[], LLMError>

// Implementation must not return Effect<string[], never, never>
// Ensure error channel is LLMError, not never.
```

## TypeScript Config for Bun + Effect-TS Monorepo

```json
{
  "moduleResolution": "bundler",
  "module": "ESNext",
  "downlevelIteration": true,
  "allowImportingTsExtensions": true,
  "noEmit": true,
  "skipLibCheck": true
}
```

- `allowImportingTsExtensions` + `noEmit` — Bun handles the build, tsc only typechecks
- `moduleResolution: "bundler"` — works better than `NodeNext` with Bun workspace setup
- `paths` in tsconfig does NOT work (relative path resolution breaks rootDir in child packages)
- Use `workspace:*` dependencies in package.json instead

## Service Definition Pattern

```typescript
import { Effect, Context, Layer } from "effect"

export class MyService extends Context.Tag("MyService")<
  MyService,
  {
    method: (param: string) => Effect.Effect<Result>
  }
>() {
  static readonly Live = Layer.succeed(MyService, {
    method: (param) => Effect.sync(() => {
      return { success: true, data: param }
    })
  })
}
```

## Drizzle Schema Conventions

- snake_case for DB columns (no redundant name strings)
- `text().primaryKey()` not `text("id").primaryKey()`
- `integer().notNull()` not `integer("created_at").notNull()`
- When adding a new table, update BOTH `schema.ts` AND `migrate.ts` — drizzle doesn't auto-sync
- Schema exports go through `db/index.ts` via `export * from "./schema.js"` — verify new tables are accessible

## Test Mock Layers for Effect-TS Services

When a service depends on other Effect-TS services (Context.Tag), tests must provide mock implementations via `Layer.sync()`:

```typescript
import { AgentLifecycle } from "../../agent-runtime/src/lifecycle.js"
import { AgentExecutor } from "../../agent-runtime/src/executor.js"

const MockAgentLifecycle = Layer.sync(AgentLifecycle, () => ({
  spawn: () => Effect.sync(() => ({ id: "mock", name: "mock", role: "developer" as const, status: "running" as const, spawnedAt: new Date(), lastHeartbeat: new Date() })),
  stop: () => Effect.sync(undefined),
  // ... all interface methods must be implemented
}))

const MockAgentExecutor = Layer.sync(AgentExecutor, () => ({
  execute: (task: string, role: string) => Effect.sync(() => ({ taskId: "mock", content: `Mock: ${task}`, toolCallsCount: 0, iterations: 1, usage: { promptTokens: 10, completionTokens: 10, totalTokens: 20 } })),
  // ... all interface methods
}))
```

Then wire into the test layer — use `Layer.provide()` for dependency chains and `Layer.mergeAll()` only for independent layers:

```typescript
// mergeAll is safe here: mocks don't depend on each other
const MockLayer = Layer.mergeAll(TestDbLayer, MockAgentLifecycle, MockAgentExecutor)

// TaskOrchestrator depends on mocks, so provide them explicitly
const OrchestratorLayer = TaskOrchestrator.Default.pipe(
  Layer.provide(MockLayer)
)

// Each service needs TestDbLayer wired via Layer.provide (they depend on DB)
// The resulting layers are independent of each other, so mergeAll is safe
const ServiceLayer = Layer.mergeAll(
  OrganizationService.Live.pipe(Layer.provide(TestDbLayer)),
  CommunicationService.Live.pipe(Layer.provide(TestDbLayer)),
  MeetingService.Live.pipe(Layer.provide(TestDbLayer)),
  OrchestratorLayer,
)

const TestLayer = TeamService.Default.pipe(
  Layer.provide(ServiceLayer)
)
```

**Key insights**:
- Every `Context.Tag` service in the dependency graph must have either a `Live` or mock layer provided, or Effect will throw "Service not found" at runtime. Missing mocks cause cryptic fiber failures.
- `Layer.mergeAll()` is safe when all layers are independent (e.g., mocks that don't depend on each other). Use `Layer.provide()` when one layer depends on another.
- Pattern: **Wire dependencies first** (`Live.pipe(Layer.provide(Dep)))`, **merge independents second** (`Layer.mergeAll(...)`).

## Circular Dependency Resolution in Monorepo Packages

When two workspace packages depend on each other (A → B and B → A), bun/pnpm will silently resolve but TypeScript will fail. Fix strategy:

1. Determine the correct dependency direction (usually: "runtime/business logic" depends on "infrastructure", not vice versa)
2. Move files from the "wrong" package to the correct one (e.g., team tools that import from `agent-runtime` belong in `team`, not `agent-runtime`)
3. Update `package.json` dependencies to be one-directional
4. Update all import paths in moved files (e.g., `import { AgentTool } from "../executor.js"` → `import type { AgentTool } from "@opencode-fusion/agent-runtime"`)
5. Remove the reverse dependency from the other package's `package.json`
6. Add `exports` subpath entries in `package.json` for new modules

**Pattern**: A depends on B is fine. B depends on A is fine. A and B depending on each other is a build-time error. Move shared interfaces to a third "core" package if truly bidirectional.

## `Effect.either()` Returns `Either<unknown, unknown>`

```typescript
// BAD — can't access .right/.left without narrowing
const result = yield* Effect.either(someEffect)
if (result._tag === "Right") {
  // result.right is type `unknown` — no autocomplete!
}

// GOOD — pipe through Effect.mapError first, then Either matches typed values
const result = yield* Effect.either(
  someEffect.pipe(Effect.mapError(e => new KnownError(e)))
)
```

When the error channel is `unknown`, `Effect.either()` returns `Either<unknown, unknown>` and you lose all type info on `.right` / `.left`. Narrow the error channel before calling `.either()`.

## Wave-Based Parallel Task Execution Pattern

For orchestrating multiple agents/tasks with dependencies:

```typescript
// 1. Build a dependency graph
const pending = new Map(tasks.map(t => [t.id, t]))
const completed = new Map<string, OrchestratedResult>()

// 2. Execute in waves — each wave runs all tasks whose deps are satisfied
while (pending.size > 0) {
  const wave = findReadyTasks(pending, completed)  // tasks with all deps in `completed`
  if (wave.length === 0) throw new Error("Deadlock detected — circular dependencies")
  
  // 3. Run wave tasks in parallel via Effect.all
  const results = yield* Effect.all(
    wave.map(t => executeSingleTask(t, agentExecutor, agentLifecycle)),
    { concurrency: "unbounded" }
  )
  
  // 4. Merge results, advance wave
  for (const result of results) {
    completed.set(result.taskId, result)
    pending.delete(result.taskId)
  }
}
```

**Key design decisions**:
- Use `Effect.all` with `{ concurrency: "unbounded" }` for true parallel execution
- Deadlock detection: if no task in a wave has all deps met, something is circular
- Each task gets its own agent spawn → execute → stop lifecycle
- Results and status are persisted to SQLite for crash recovery

## Adding a New Service to an Existing Layer Tree

When integrating a new Effect-TS service (e.g., `SkillStore`) into an existing service tree (e.g., `MemoryService → MemoryBootService / MemorySearchService`):

### 1. Every parent service must yield the new dependency

If `MemoryBootService` and `MemorySearchService` both need `SkillStore`, then `MemoryService` (their parent) must include `SkillStore.Default` in its `dependencies` array — even if `MemoryService` itself never directly calls `SkillStore`. The dependency propagates down.

```typescript
// MemoryService must include SkillStore in deps even if it doesn't use it directly
static readonly Default = Layer.effect(MemoryService, Effect.gen(function* () {
  // ... MemoryService construction
})).pipe(
  Layer.provide(Layer.mergeAll(
    FactStore.Default,
    EpisodicMemory.Default,
    ProceduralMemory.Default,
    SkillStore.Default,  // ← Required because Boot and Search services need it
  ))
)
```

### 2. Wire the new service into dependent services

Each sub-service that uses the new service must:
- Yield it in their own `Effect.gen()` context
- Include it in their method signatures

```typescript
// MemoryBootService — now receives skills via SkillStore
static readonly Default = Layer.effect(MemoryBootService, Effect.gen(function* () {
  const skills = yield* SkillStore  // ← new dependency
  // ... format skills into boot context
}))
```

### 3. Export the new service from the package index

Don't forget to:
- Add `export * from "./skills/index.js"` to the package's `index.ts`
- Ensure the sub-module has its own `index.ts` that re-exports the service

## SQLite FTS5 with Drizzle ORM

Drizzle ORM does NOT natively support FTS5 virtual tables. The pattern:

### 1. Define FTS5 in raw SQL migrations

```typescript
// In migrate.ts — NOT in schema.ts
migrations.push(sql`
  CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    name, description, keywords, content='skills'
  )
`)
```

### 2. Add sync triggers

```typescript
migrations.push(sql`
  CREATE TRIGGER IF NOT EXISTS skills_fts_insert AFTER INSERT ON skills BEGIN
    INSERT INTO skills_fts(rowid, name, description, keywords)
    VALUES (new.id, new.name, new.description, new.keywords);
  END
`)
// Also add UPDATE and DELETE triggers
```

### 3. Query FTS5 via raw SQL — never Drizzle's query builder

```typescript
// GOOD — raw SQL for FTS5
const results = yield* Effect.tryPromise(() =>
  db.execute(sql`SELECT * FROM skills_fts WHERE skills_fts MATCH ${query}`)
)

// BAD — Drizzle can't query FTS5 virtual tables
// db.select().from(skillsFts).where(...)  ← won't work
```

### 4. Never combine FTS5 MATCH with Drizzle WHERE — causes double-WHERE bug

When filtering FTS5 results by an additional column (e.g., `agentId`), do NOT use Drizzle's `.where()` on top of the raw SQL `MATCH` — this produces `WHERE fts MATCH ? AND col = ? WHERE ...` (two WHERE clauses = SQLite syntax error):

```typescript
// BAD — double WHERE clause (Drizzle adds a second WHERE after your raw SQL WHERE)
const results = db.select()
  .from(sessionMessagesFts)
  .where(eq(sessionMessagesFts.role, "user"))  // Drizzle adds: WHERE role = 'user'
  .from(sql`session_messages_fts WHERE session_messages_fts MATCH ${query}`)
  // Result: SELECT ... WHERE session_messages_fts MATCH ? WHERE role = ?  ← SYNTAX ERROR

// GOOD — put all filters in the raw SQL WHERE clause
const stmt = db._.session.prepare(
  `SELECT * FROM session_messages_fts WHERE session_messages_fts MATCH ? AND role = ?`
)
const results = stmt.all(query, roleFilter)
```

**Key insight**: When using raw SQL for FTS5 MATCH, keep ALL filtering logic inside the raw SQL string. Never mix Drizzle's `.where()` with raw SQL that already has a WHERE clause.

### 5. Always wrap FTS5 in try/catch

FTS5 tables won't exist in `:memory:` test databases unless you explicitly run migrations. Always handle the case where FTS5 queries fail:

```typescript
try {
  const ftsResults = yield* Effect.tryPromise(() =>
    db.execute(sql`SELECT * FROM skills_fts WHERE skills_fts MATCH ${query}`)
  )
  // ... process results
} catch {
  // Fallback: search without FTS5
}
```

### 5. Still define a Drizzle schema entry for type reference

You CAN define a `skillsFts` table in `schema.ts` for type reference, but don't use it for queries:

```typescript
export const skillsFts = sqliteTable("skills_fts", {
  rowid: integer("rowid").primaryKey(),
  name: text("name"),
  description: text("description"),
  keywords: text("keywords"),
})
```

## Drizzle `eq()` Filter Limitation — Use `getAll()` Instead of Wildcards

When you need "all records" from a table, Drizzle's `eq(column, value)` does NOT support wildcard values like `"*"`:

```typescript
// BAD — eq() doesn't support wildcards
skills.getByAgent("*")  // Returns nothing — eq(agentId, "*") matches literal "*"

// GOOD — add a dedicated getAll() method
interface SkillStore {
  getAll: () => Effect.Effect<readonly Skill[]>
}

// Implementation
getAll: () => Effect.tryPromise(() => db.select().from(skills))
```

Pattern: When a service has both filtered (`getByX`) and unfiltered (`getAll`) access patterns, expose both as separate methods rather than trying to use a single method with a sentinel value.

## Layer Composition: Dependencies vs Independent Services

### Critical Pitfall: `Layer.mergeAll()` Does NOT Wire Dependencies

`Layer.mergeAll()` treats ALL layers as **independent** — it does NOT inject dependencies between them. If `ServiceB` depends on `ServiceA`, putting both in `Layer.mergeAll()` will cause a "Service not found" runtime error.

```typescript
// BAD — Layer.mergeAll does NOT wire ServiceA into ServiceB
// ServiceB's dependency on ServiceA is NOT satisfied
const TestLayer = Layer.mergeAll(
  ServiceA.Live,
  ServiceB.Live,  // ← depends on ServiceA, but mergeAll doesn't connect them!
)

// GOOD — Use Layer.provide() to satisfy dependencies bottom-up
const TestLayer = ServiceB.Live.pipe(
  Layer.provide(ServiceA.Live)  // ← ServiceA is provided to ServiceB
)

// GOOD — Effect.Service<>() "dependencies" array auto-wires
class MyService extends Effect.Service<MyService>("MyService") {
  constructor() { /* ... */ }
  static readonly dependencies = [ServiceA.Default, ServiceB.Default]  // auto-wired
}
```

**When to use mergeAll vs Layer.provide:**
- `Layer.mergeAll(A, B, C)` — only when A, B, C are truly independent (no cross-dependencies)
- `ServiceB.Live.pipe(Layer.provide(ServiceA.Live))` — when ServiceB depends on ServiceA
- `Effect.Service<>().dependencies` — the cleanest way; the service declares what it needs

### Sharing DB Instances in Tests

When multiple services share a database (e.g., SkillStore + SelfModelService both need DatabaseService), you must compose all layers into a **single dependency tree** before providing them to the program. Separate `Effect.provide()` calls create **separate in-memory SQLite instances**, causing data to vanish between services.

```typescript
// BAD — each Effect.provide() creates a separate in-memory DB
// SkillStore sees one DB, SelfModelService sees another
const result = await Effect.runPromise(
  program.pipe(
    Effect.provide(TestDbLayer),
    Effect.provide(SkillStore.Default),
    Effect.provide(SelfModelService.Default),
  )
)

// GOOD — compose services with their DB dependency first, merge independents second
const ServiceLayer = Layer.mergeAll(
  SkillStore.Default.pipe(Layer.provide(TestDbLayer)),
  SelfModelService.Default.pipe(Layer.provide(TestDbLayer)),
)

const TestLayer = PromptAssembler.Default.pipe(
  Layer.provide(ServiceLayer)
)

const result = await Effect.runPromise(
  program.pipe(Effect.provide(TestLayer))
)
```

**Why this happens:** `Effect.provide()` wraps each layer in a new context. In-memory (`:memory:`) SQLite databases are scoped to the layer that creates them. When you provide the DB layer multiple times, each provision creates a fresh empty database. Use `Layer.provide()` to wire dependencies, then `Layer.mergeAll()` only for truly independent services.

**Rule of thumb:** If two services must see the same data, their layers MUST share a single `DatabaseService` layer instance. Compose dependencies with `Layer.provide()` first, merge independents with `Layer.mergeAll()` second, then provide the whole tree once.

### Critical: Each `Effect.runPromise()` Call Gets a Fresh Layer (and Fresh In-Memory DB)

Even if you use the exact same `Layer` reference, **each `Effect.runPromise(program.pipe(Effect.provide(layer)))` call builds a fresh layer tree with a fresh in-memory SQLite instance**. Data inserted in one call is invisible to the next.

```typescript
// BAD — two separate runPromise calls, two separate in-memory DBs
// Setup inserts test data into DB #1
await Effect.runPromise(setupProgram.pipe(Effect.provide(TestDbLayer)))

// Sync reads from DB #2 (empty!); orphan test fails because setup data doesn't exist
await Effect.runPromise(syncProgram.pipe(Effect.provide(TestDbLayer)))

// GOOD — combine setup + sync into a single program, share one layer tree
const combinedProgram = Effect.gen(function* (_) {
  yield* _(setupEffects)   // inserts test data
  yield* _(syncEffects)    // sees the same data — same DB instance
})
await Effect.runPromise(combinedProgram.pipe(Effect.provide(TestDbLayer)))
```

**When this bites you**: Tests that insert data in one `runPromise` and then assert on it in a separate `runPromise` will silently see empty results for in-memory DBs. The fix is always to combine all operations that must share state into a single `Effect.runPromise` call.

**Does NOT affect persistent DBs** (file-backed SQLite, PostgreSQL) — the data survives across `runPromise` calls because it's on disk, not in the layer's scoped lifecycle.

## Effect-TS Stream Patterns for Real-Time Message Flow

Effect-TS v3 has 312+ Stream methods. Key patterns for gateway adapters (Telegram, WebSocket, CLI):

### Pattern 1: Queue → Stream bridge (external push → Stream pull)

When an external system (Telegram long poll, WebSocket) pushes messages imperatively, use a `Queue` as the bridge:

```typescript
const queue = yield* Queue.unbounded<GatewayEvent>()

// External producer (e.g., Telegram getUpdates loop)
yield* Effect.fork(
  Effect.forEach(events, (msg) => Queue.offer(queue, msg).pipe(Effect.delay("100 millis")))
    .pipe(Effect.tap(() => Queue.shutdown(queue)))  // Signal end of stream
)

// Consumer as Stream
const results = yield* Stream.fromQueue(queue).pipe(
  Stream.runCollect
)
```

**Key**: Call `Queue.shutdown(queue)` when the producer is done — otherwise the stream hangs forever waiting for more items.

### Pattern 2: Schedule-based polling (getUpdates pattern)

```typescript
const pollEffect = Effect.sync(() => {
  counter++
  return counter <= max ? Option.some(`update-${counter}`) : Option.none()
})

const results = yield* Stream.repeatEffectOption(pollEffect).pipe(
  Stream.schedule(Schedule.spaced("200 millis")),
  Stream.take(maxUpdates),
  Stream.runCollect
)
```

Use `Stream.repeatEffectOption` (not `repeatEffect`) — it stops on `Option.none()`, which is the natural "no more updates" signal.

### Pattern 3: Throttle / Rate limiting

Telegram API limits to ~30 msg/sec. Use `Stream.throttle`:

```typescript
Stream.fromIterable(messages).pipe(
  Stream.throttle({ cost: () => 1, units: 3, duration: "100 millis" })  // 3 per 100ms
)
```

### Pattern 4: Merge multiple sources (Telegram + WebSocket + CLI)

```typescript
const telegram = Stream.fromIterable(tgEvents)
const websocket = Stream.fromIterable(wsEvents)
const cli = Stream.fromIterable(cliEvents)

const merged = Stream.mergeAll([telegram, websocket, cli]).pipe(
  Stream.runCollect
)
```

### Pattern 5: Broadcast / Fan-out (one source → multiple sinks)

Use a Queue as a shared source, then create separate consumer streams. Each consumer gets a **subset** of items (not a copy of all items) — the Queue distributes items across consumers in round-robin fashion. For true broadcast (all consumers see all items), use `Stream.broadcast`:

```typescript
const stream = Stream.fromIterable(events)
const [s1, s2] = yield* stream.pipe(Stream.broadcast(2, 16))  // 2 consumers, buffer 16
```

### Pattern 6: Partition + Route (commands vs. messages)

⚠️ **Critical pitfall**: `Stream.partition()` returns a **tuple `[excluded, satisfying]`**, NOT an object `{ partitioned }`. It also **requires `Effect.scoped`** because it creates managed resources (Scope):

```typescript
// WRONG — partition returns a tuple, not { partitioned }
const { partitioned } = yield* Stream.partition(stream, pred)  // ❌ undefined

// WRONG — partition requires a Scope
const [commands, messages] = yield* Stream.partition(stream, pred)  // ❌ Service not found: effect/Scope

// CORRECT — destructure tuple AND use Effect.scoped
const program = Effect.gen(function* () {
  const [commands, messages] = yield* Stream.fromIterable(events).pipe(
    Stream.partition((event) => event._tag === "Command")
  )
  // commands = stream of events where predicate returned false (excluded)
  // messages = stream of events where predicate returned true (satisfying)
  return { commands, messages }
}).pipe(Effect.scoped)  // ← REQUIRED: partition creates scoped resources
```

**Naming gotcha**: `[excluded, satisfying]` means the FIRST stream contains items that DID NOT match the predicate, the SECOND contains items that DID match. This is counterintuitive — named from the perspective of the "exclusion" (left = excluded from satisfying, right = satisfying).

## Test Patterns for Gateway Adapters

When testing Effect-TS gateway adapters (like TelegramAdapter), follow the `agent-bridge.test.ts` pattern: **type/structural tests** that avoid the full AgentRuntime dependency tree.

### Problem: Full Layer Chain is Too Complex to Mock

AgentRuntime → LLMProvider → DatabaseService → ... is a deep chain. Mocking every service is fragile and verbose.

### Solution: Test Types and Structure Only

```typescript
// Type-level test — no Effect runtime needed
test("TelegramConfig has correct defaults", () => {
  const config: TelegramConfig = { ...DEFAULT_TELEGRAM_CONFIG }
  expect(config.pollInterval).toBe(1000)
  expect(config.maxMessageLength).toBe(4000)
})

// Structural test — verify service shape without running it
test("TelegramAdapter service interface is correct", () => {
  const adapter: TelegramAdapter = yield* TelegramAdapter
  expect(typeof adapter.start).toBe("function")
  expect(typeof adapter.stop).toBe("function")
})
```

### SessionService Integration Tests — Key Pitfall

`SessionService.create(agentId, parentId?, title?)` generates its own UUID via `generateId()`. You CANNOT pass a custom session ID:

```typescript
// WRONG — first arg is agentId, NOT sessionId; create() generates its own ID
const session = yield* sessions.create("telegram-12345-test", "telegram-user")
expect(session.id).toBe("telegram-12345-test")  // ❌ Gets a UUID instead

// CORRECT — use the returned session's id for subsequent operations
const session = yield* sessions.create("telegram-user-12345")
expect(session.agentId).toBe("telegram-user-12345")
expect(session.id).toBeDefined()  // UUID generated internally

// For setStatus, get, appendMessage — use session.id from the returned object
yield* sessions.setStatus(session.id, "active")
const updated = yield* sessions.get(session.id)
```

## Python/Bash String Escaping Pitfall for TypeScript Code Generation

When using Python's `execute_code` + heredoc to write TypeScript files containing template literals:

1. **Python triple-quoted strings escape backticks** as `\`` — they land in the TS file as `\`` instead of `` ` ``
2. **Bash heredoc strips `\n` escape sequences** — `\n` in a string literal becomes a literal newline
3. **Fix**: Use heredoc for the main file, then `patch()` for any `\n` sequences that need to remain as literal `\n` in the TypeScript source

```python
# Step 1: Write file via heredoc (avoids backtick escaping)
terminal(f"""cat > file.ts << 'HEREDOC'
const msg = `Hello ${name}`  # backticks preserved
HEREDOC""")

# Step 2: Patch escaped \n back to \\n  
patch(path="file.ts", old_string="welcomeMessage+'\\n'", new_string="welcomeMessage+'\\\\n'")
```

## Schema Validation: decodeUnknown + Effect.catchAll

Effect-TS Schema v3 requires careful handling of `ParseError`. The common pattern for validating unknown input (plugin manifests, API bodies, config files):

```typescript
// CORRECT — use Schema.decodeUnknown inside Effect.gen, catch with Effect.catchAll
const validateManifest = (input: unknown) =>
  Effect.gen(function* () {
    const decoded = yield* Schema.decodeUnknown(ManifestSchema)(input)
    return { valid: true as const, manifest: decoded, errors: [] }
  }).pipe(
    Effect.catchAll((e) =>
      Effect.succeed({
        valid: false as const,
        manifest: undefined,
        errors: [String(e)]  // e.toString() gives human-readable tree — NOT e.errors.map()
      })
    )
  )
```

**Gotchas**:
- `Schema.decodeUnknownSync` THROWS on invalid input — never use in Effect context
- `e.errors.map(e => e.message)` does NOT exist on `ParseError` — use `String(e)` or `e.toString()`
- `Schema.optional()` (lowercase) — NOT `Schema.Optional()` (capital O doesn't exist)
- Always use `as const` on discriminant values (`true as const`, `false as const`) so TypeScript narrows the union type correctly

## Effect.catchAll to Normalize Error Channels

When `Effect.gen()` wraps `Effect.tryPromise`, the error channel may widen to `unknown` even if `tryPromise` has a catch handler. This breaks service tag types like `Effect<A, never, never>`:

```typescript
// BAD — gen block infers error channel as unknown, breaks service type
scan: (dir) => Effect.gen(function* () {
  const entries = yield* Effect.tryPromise({
    try: () => fs.promises.readdir(dir, { withFileTypes: true }),
    catch: () => []  // catch handler doesn't prevent unknown error channel
  })
  return entries
})

// GOOD — pipe Effect.catchAll to normalize error channel
scan: (dir) => Effect.gen(function* () {
  const entries = yield* Effect.tryPromise({
    try: () => fs.promises.readdir(dir, { withFileTypes: true }),
    catch: () => []
  })
  return entries
}).pipe(Effect.catchAll(() => Effect.succeed([])))  // Normalizes error to never
```

**Rule**: When a service method must return `Effect<A, never, R>` but uses `Effect.gen` with operations that can fail, always `.pipe(Effect.catchAll(...))` at the end of the gen block.

## Cross-Package Import Avoidance (Monorepo moduleResolution)

In a Bun monorepo with `moduleResolution: "bundler"`, cross-package imports of **subpath internals** fail at test time even if tsc accepts them:

```typescript
// BAD — works in tsc, FAILS at bun test runtime
import { ToolRegistry } from "@toti/agent-runtime/tool-registry"

// WHY: Bun's resolver + moduleResolution setting can't resolve subpath
// exports for internal files across workspace packages
```

**Solutions** (pick one):
1. **Define a local interface** (duck-typing) in the consumer package and inject the dependency:
   ```typescript
   // In gateway: define local interface matching the shape you need
   interface PluginToolRegistry {
     registerPlugin(name: string, tool: any): Effect.Effect<void>
     unregisterBySource(source: string): Effect.Effect<void>
   }
   const PluginToolRegistry = Context.Tag("PluginToolRegistry")<PluginToolRegistry, PluginToolRegistry>()
   ```
2. **Export through the package's index.ts** — only import from `@toti/agent-runtime` (the main export), not subpaths
3. **Move shared types to `@toti/core`** — if both packages need the same type, it belongs in core

**Rule**: Gateway should NOT directly import agent-runtime internals. Use injected interfaces or core types.

## Topological Sort for Dependency-Aware Loading (Kahn's Algorithm)

For plugin systems, task scheduling, or any scenario needing dependency-ordered execution:

```typescript
function topologicalSort(items: Array<{ name: string; dependencies?: readonly string[] }>): string[] {
  const inDegree = new Map<string, number>()
  const graph = new Map<string, string[]>()

  for (const item of items) {
    if (!inDegree.has(item.name)) inDegree.set(item.name, 0)
    for (const dep of (item.dependencies ?? [])) {
      if (!inDegree.has(dep)) inDegree.set(dep, 0)
      inDegree.set(item.name, (inDegree.get(item.name) ?? 0) + 1)
      const adj = graph.get(dep) ?? []
      adj.push(item.name)
      graph.set(dep, adj)
    }
  }

  const queue: string[] = [...inDegree.entries()]
    .filter(([_, degree]) => degree === 0)
    .map(([name]) => name)
  const order: string[] = []

  while (queue.length > 0) {
    const current = queue.shift()!
    order.push(current)
    for (const neighbor of (graph.get(current) ?? [])) {
      const newDegree = (inDegree.get(neighbor) ?? 1) - 1
      inDegree.set(neighbor, newDegree)
      if (newDegree === 0) queue.push(neighbor)
    }
  }

  // If order.length < items.length, there's a cycle
  return order
}
```

**Properties**: O(V+E) time, detects cycles (if `order.length < items.length`), breadth-first so independent items at the same depth level can load in parallel.

## Union Type Narrowing to `never` After Exhaustive Literal Checks

When a variable has a union-of-literals type (e.g., `ToolName = "read" | "edit" | "bash" | ...`) and you exhaustively check each literal with `===`, TypeScript narrows the remaining type to `never`. This makes subsequent `.includes()` or other string methods impossible:

```typescript
// BAD — after all literal checks, `name` is `never`, so .includes() fails
type ToolName = "read" | "edit" | "bash" | "glob" | "grep" | "task" | "memory" | "memory_store" | "communication" | "meeting"
const getCategory = (tool: AgentTool): ToolCategory => {
  const name = tool.name  // type: ToolName
  if (name === "read" || name === "edit") return "file"  // narrows away "read" | "edit"
  if (name === "glob" || name === "grep") return "search"
  // ... all remaining literals checked
  // After exhaustive checks, name is `never`:
  if (name.includes("file")) return "file"  // ❌ Property 'includes' does not exist on type 'never'
}

// GOOD — widen to string before fallback heuristic checks
const getCategory = (tool: AgentTool): ToolCategory => {
  const name: string = tool.name  // Cast to string to prevent narrowing to never
  if (name === "read" || name === "edit") return "file"
  // ... literal checks still work on string
  if (name.includes("file")) return "file"  // ✅ .includes() works on string
}
```

**Rule**: When a function has exhaustive literal checks AND fallback heuristic `includes()`/`match()` checks, widen the variable to `string` before the heuristic section.

## Readonly Property Mutation — Use Spread+Override Pattern

When a TypeScript interface has `readonly` properties, you cannot directly mutate them. This happens commonly when building status objects that need to override a computed value:

```typescript
// BAD — Cannot assign to 'status' because it is a read-only property
interface BatchStatus {
  readonly status: "completed" | "failed" | "cancelled"
  readonly results: readonly BatchTaskResult[]
  // ...
}
const finalStatus = processResults(results)  // returns BatchStatus with status: "completed"
finalStatus.status = "failed"  // ❌ Cannot assign to 'status' because it is a read-only property

// GOOD — Spread and override
const finalStatus: BatchStatus = { ...processResults(results), status: "failed" }  // ✅
```

**Rule**: Never mutate `readonly` properties. Use object spread `{ ...obj, key: newValue }` to create a new object with the override.

## Union Type Missing Optional Field — Add Explicit `undefined`

When a result type is a union where one variant has `error?: string` and another doesn't, TypeScript can't see `.error` on the union:

```typescript
// BAD — success variant doesn't have `error`, so union type can't access it
interface SuccessResult {
  taskId: string
  content: string
  // ... no `error` field
}
interface ErrorResult {
  taskId: string
  content: string
  error: string
}
type Result = SuccessResult | ErrorResult

// Later: result.error  ❌ Property 'error' does not exist on type 'SuccessResult | ErrorResult'

// GOOD — add `error: undefined` to success variant so both have the field
interface SuccessResult {
  taskId: string
  content: string
  error: undefined  // ✅ Explicitly present, widens to `string | undefined` on the union
}

// Now: result.error  ✅ Type is `string | undefined`
```

**Rule**: When building discriminated/result unions where one variant has an optional field, add the field as `undefined` on the success variant to unify the type.

## `Effect.Service<>()()` vs `Context.Tag()` — Modern Pattern (⚠️ Bun Runtime Incompatibility)

Effect-TS v3 introduced `Effect.Service` as the preferred way to define services. It replaces the older `Context.Tag` + `Layer.effect` pattern and resolves multiple type issues. **However, `Effect.Service<>()()` CRSASHES in Bun runtime as of Bun 1.3.13 + effect@3.21.2** — use `Context.Tag` + `Layer.effect` instead.

### ⚠️ CRITICAL: Effect.Service Crashes in Bun

```typescript
// ❌ BROKEN in Bun — crashes with: TypeError: source is not an Object (evaluating 'circularManagedRuntime.TypeId in source')
// Error occurs in Effect.provide() when passing Effect.Service class as a Layer
export class MyService extends Effect.Service<MyService>()("MyService", {
  sync: () => ({ method: (x) => Effect.sync(() => true) })
}) {}

// Test runner: Effect.runPromise(effect.pipe(Effect.provide(MyService)))
// → TypeError at internal/layer.js:546 — circularManagedRuntime.TypeId check fails
```

This was tested with: `effect@3.21.2`, `bun@1.3.13`, `pptxgenjs@4.0.1`. All 16 test cases fail with this error. The `Context.Tag` + `Layer.effect` pattern works perfectly (316+ existing tests pass).

### ✅ WORKING — Context.Tag + Layer.effect (use this pattern!)

```typescript
// ✅ WORKS — Context.Tag + Layer.effect (proven in this project)
// Step 1: Define service interface
export interface MyServiceShape {
  readonly method: (x: string) => Effect.Effect<Result>
  readonly other: () => Effect.Effect<void>
}

// Step 2: Create Tag
export const MyService = Context.Tag("MyService")<MyServiceShape, MyServiceShape>()

// Step 3: Create Live layer
export const MyServiceLive = Layer.effect(MyService, Effect.gen(function* () {
  return MyService.of({
    method: (x) => Effect.sync(() => ({ ok: true })),
    other: () => Effect.sync(undefined),
  })
}))
```

### Test pattern for Context.Tag + Layer.effect

```typescript
// Always use Layer.effect with Effect.provide in tests
const run = <A, E>(effect: Effect.Effect<A, E, MyService>) =>
  Effect.runPromise(effect.pipe(Effect.provide(MyServiceLive)))

test("method works", async () => {
  const result = await run(Effect.gen(function* () {
    const service = yield* MyService
    return yield* service.method("test")
  }))
  expect(result.ok).toBe(true)
})
```

**When to use each pattern**:
- `Context.Tag` + `Layer.effect` — ✅ USE THIS. Works in Bun, proven in 316+ tests
- `Effect.Service<>()()` — ❌ BROKEN in Bun as of 1.3.13. May work in Node.js; needs further investigation
- `Layer.succeed()` — works for simple services with no Effect.gen needed

**Migration note**: The `AgentRuntime` in this project already uses `Effect.Service`. If Bun compat is needed, it should be migrated back to `Context.Tag` + `Layer.effect`. Other services (AgentExecutor, SessionLoop, etc.) should use `Context.Tag` from the start.

## Effect.tryPromise Return Type — Always `Effect.Effect<T, Error, never>`

`Effect.tryPromise` with a `catch` handler that returns `Error` produces `Effect.Effect<T, Error, never>`, NOT `Effect.Effect<T, never, never>`. If you annotate the function return type as `Effect.Effect<T>` (shorthand for `Effect.Effect<T, never, never>`), you get TS2322:

```typescript
// BAD — return type annotation is wrong
const apiCall = <T>(method: string, body: Record<string, unknown>): Effect.Effect<T> =>
  Effect.tryPromise({
    try: () => fetch(url),
    catch: (e) => new Error(String(e))  // Error in error channel
  })
// TS2322: Effect<T, Error, never> is not assignable to Effect<T, never, never>

// GOOD — include Error in return type
const apiCall = <T>(method: string, body: Record<string, unknown>): Effect.Effect<T, Error> =>
  Effect.tryPromise({
    try: () => fetch(url),
    catch: (e) => new Error(String(e))
  })
```

**Rule**: When a method uses `Effect.tryPromise` with a catch handler returning `Error`, the return type must be `Effect.Effect<T, Error>`, not `Effect.Effect<T>`. This pattern appears in all gateway adapters (Telegram, API server, etc.).

## Systematic TS Error Fixing in Effect-TS Monorepos

When facing 100+ TS errors in an Effect-TS v3 monorepo, use this systematic approach:

### 1. Trust `bun tsc --noEmit` as ground truth, NOT the IDE/linter

The linter may show errors from `node_modules` (drizzle-orm, bun-types) that `bun tsc --noEmit` does not report. The linter uses a different tsconfig resolution path. Always verify with:
```bash
export PATH=~/.bun/bin:$PATH && bun tsc --noEmit 2>&1 | grep 'error TS' | wc -l
```

### 2. Categorize errors by code and file

```bash
# Count by error code
bun tsc --noEmit 2>&1 | grep 'error TS' | sed 's/.*error /error /' | cut -d: -f1 | sort | uniq -c | sort -rn

# Count by file
bun tsc --noEmit 2>&1 | grep 'error TS' | sed 's/(.*//' | sort | uniq -c | sort -rn
```

### 3. Dominant error patterns and fixes

| Code | Count Pattern | Fix |
|------|--------------|-----|
| TS2345 | Effect requirement channel mismatch | Add `.pipe(Effect.provide(layer))` before `runPromise` |
| TS2322 | `unknown` not assignable to `never` | Add `.pipe(Effect.catchAll(...))` or `.pipe(Effect.mapError(...))` to narrow error channel |
| TS2322 | `Error` not assignable to `never` | Change return type from `Effect.Effect<T>` to `Effect.Effect<T, Error>` when using `tryPromise` |
| TS2339 | Property does not exist on type | Add missing method to service interface, or use the correct interface method name |
| TS7006 | Implicit `any` | Add explicit type annotations |

### 4. Fix order (highest impact first)

1. **tsconfig fixes** — `jsx: "react-jsx"`, `downlevelIteration: true`, `moduleResolution: "bundler"` (fixes 70+ errors at once)
2. **Typo fixes** — `Agentbridge` → `AgentBridge`, wrong method names
3. **Effect return type annotations** — `Effect.Effect<T>` → `Effect.Effect<T, Error>` for tryPromise users
4. **Effect.catchAll/mapError** — narrow `unknown` error channels to match service signatures
5. **CLI command Effect.provide** — satisfy requirement channels before running
6. **Missing interface methods** — add `execute`, `compress` etc. to service types

## Named-Key Interfaces vs `Record<string, T>` — Index Signature Compatibility

When a domain interface has specific named keys (like `TraitMap`) and a consumer expects `Record<string, number>`, TypeScript refuses the assignment because the named-key interface lacks an index signature.

```typescript
// Domain type with named keys (no index signature)
interface TraitMap {
  communication_style: number
  decisiveness: number
  caution: number
}

// Consumer expects Record<string, number>
interface SelfModelData {
  readonly traits: Record<string, number>  // ← TraitMap is NOT assignable here
}

// TS2345: Type 'TraitMap' is not assignable to type 'Record<string, number>'.
//   Index signature for type 'string' is missing in type 'TraitMap'.
```

### Solutions (ranked by preference)

**1. Widen the consumer** — Best when the consumer only iterates entries (`Object.entries()` works on both):
```typescript
interface SelfModelData {
  readonly traits: TraitMap | Record<string, number>  // ✅ Both accepted
}
```

**2. Import the domain type directly** — Cleanest when consumer and domain type are identical in shape:
```typescript
import { type TraitMap } from "@toti/memory"
interface SelfModelData {
  readonly traits: TraitMap  // ✅ Use the source type directly
}
```

**3. Add index signature to source** — Only if you genuinely want an open type:
```typescript
interface TraitMap {
  [key: string]: number  // ✅ Now assignable to Record<string, number>
  communication_style: number  // ⚠️ But allows TraitMap["randomKey"] which should be an error
  decisiveness: number
}
```

**4. Cast through `unknown`** — Last resort, only for tests:
```typescript
const personality = formatSelfModel(model as unknown as SelfModelData)  // ❌ Loses type safety
```

**Rule**: Always prefer widening the consumer over narrowing/casting the producer. `Object.entries()` works on both `TraitMap` and `Record<string, number>` at runtime, so the widened type has no behavioral implications.

## Frontmatter Parsing — `Record<string, unknown>` Field Typing

When parsing YAML frontmatter from Markdown files, the parsed values are `Record<string, unknown>`. Directly assigning these to typed fields causes TS2322:

```typescript
// BAD — frontmatter.name is `unknown`, not `string`
return {
  name: frontmatter.name ?? deriveNameFromPath(filePath),      // TS2322: '{}' is not assignable to 'string'
  description: frontmatter.description ?? "",                   // TS2322: '{}' is not assignable to 'string'
  category: frontmatter.category ?? null,                       // TS2322: '{} | null' not assignable to 'string | null'
}

// GOOD — wrap with String() / type guards
return {
  name: String(frontmatter.name ?? deriveNameFromPath(filePath)),
  description: String(frontmatter.description ?? ""),
  category: frontmatter.category != null ? String(frontmatter.category) : null,
}
```

**Rule**: When consuming `Record<string, unknown>` values, always explicitly convert to the target type. Use `String()`, `Number()`, or type guards — never rely on `??` alone, since it only handles `null`/`undefined`, not `unknown`.

## Wiring a New Service Dependency into an Existing Effect.Service Class

When integrating a new service (e.g., `SelfHealingService`) into an existing `Effect.Service` class (e.g., `AgentRuntime`), follow this precise sequence:

### 1. Add the import

```typescript
import { SelfHealingService, type SelfHealingConfig, type SelfHealingResult } from "./self-healing.js"
```

### 2. Yield the dependency in the class effect block

```typescript
// Inside Effect.gen(function* () { ... }) of the class body
const selfHealing = yield* SelfHealingService
```

### 3. Add to the `dependencies` array

```typescript
static readonly Default = AgentRuntime.toLayer.pipe(
  Layer.provideMerge(Layer.mergeAll(
    AgentLifecycle.Default,
    // ... other deps
    SelfHealingService.Live,  // ← Add here. Check: Live vs Default!
  }))
)
```

**Critical**: Check what the service exports — it may be `.Live`, `.Default`, or just a plain layer. Using the wrong name (e.g., `SelfHealingService.Default` when only `.Live` exists) causes `TS2339: Property 'Default' does not exist`.

### 4. Add the method that uses the new dependency

```typescript
runWithHealing: (agentId: string, task: string, role: AgentRole, config?: ...) =>
  Effect.gen(function* () {
    const healingResult = yield* selfHealing.executeWithHealing(task, role, agentId, config)
    // Map the service's result type to your return type
    return {
      content: healingResult.finalResult.content,  // NOT .result — check the actual field name!
      // ... other mappings
      attempts: healingResult.attempts,
      recovered: healingResult.recovered,
      recoveryStrategy: healingResult.recoveryStrategy,
    } satisfies AgentHealingResult
  }),
```

**Key pitfalls**:
- **Field names** — Always verify the actual interface field names. `SelfHealingResult` uses `finalResult` (not `result`). Using the wrong name passes tsc but crashes at runtime.
- **Parameter order** — The service method signature may differ from what you expect. `executeWithHealing(task, role, agentId, config?)` — task first, then role, then agentId. Read the actual interface, don't guess.
- **`satisfies`** — Use `satisfies ReturnType` on the return object to catch missing/extra fields at compile time, rather than just type annotation.

### 5. Export new types from the package index

If you define a new type (e.g., `AgentHealingResult`) in the modified file, it's automatically exported via `export * from "./runtime.js"` in index.ts. Verify that it appears in the barrel export.

### 6. Write integration tests that avoid the full layer tree

When `AgentRuntime.Default` depends on 8+ services (some requiring LLM providers, DB connections, etc.), providing the full layer tree in tests is impractical. Instead, test the **mapping logic** directly:

```typescript
// Test the service method and mapping separately, not the full AgentRuntime
const MockSelfHealingService = Layer.succeed(SelfHealingService, {
  executeWithHealing: () => Effect.sync(() => mockHealingResult),
  // ... all interface methods must be implemented
})

const program = Effect.gen(function* () {
  const healing = yield* SelfHealingService
  const healingResult = yield* healing.executeWithHealing("test task", "developer", "agent-1")
  // Simulate the mapping done by runWithHealing
  const mapped: AgentHealingResult = {
    content: healingResult.finalResult.content,
    // ... map all fields
    attempts: healingResult.attempts,
    recovered: healingResult.recovered,
    recoveryStrategy: healingResult.recoveryStrategy,
  }
  return mapped
})

const result = await Effect.runPromise(
  program.pipe(Effect.provide(MockSelfHealingService))
)
```

**Why not test `AgentRuntime` directly?** — `AgentRuntime.Default` needs `AgentLifecycle.Default`, `PermissionService.Default`, `SubagentService.Default`, `AgentExecutor.Default`, `PromptAssembler.Default`, `ToolRegistry.Default`, `SessionLoop.Default`, `SkillAutoLoader.Default`, AND `SelfHealingService.Live`. You'd need to mock 8+ services plus their transitive deps (LLM providers, DB). The mapping test above validates the actual integration logic without the full layer tree.

## JSON-Serialized Columns in Drizzle + Effect-TS Services

When a Drizzle table stores typed data as a JSON text column (e.g., `items: text("items").default("[]")` for an array of typed objects), you need careful conversion between the DB row type and the domain type:

### Problem: Drizzle text columns are `string`, but domain types expect rich objects

```typescript
// Drizzle schema: items stored as JSON text
items: text("items").notNull().default("[]"),  // DB type: string

// Domain type: items is a typed array
items: z.array(SprintItem)  // Domain type: SprintItem[]
```

### Solution: Parse in `rowToDomain` function inside the service

```typescript
function rowToSprint(row: typeof sprints.$inferSelect): Sprint {
  // Parse JSON text column and map each item to properly typed objects
  const items: SprintItem[] = (JSON.parse(row.items) as Array<Record<string, unknown>>).map((item) => ({
    taskId: item.taskId as string,
    status: item.status as SprintItem["status"],
    assignedToId: item.assignedToId as string | undefined,
    storyPoints: item.storyPoints as number | undefined,
    completedAt: item.completedAt ? new Date(item.completedAt as string) : undefined,
  }))
  return {
    id: row.id,
    items,  // Properly typed array
    // ... other fields
  }
}
```

### Key conversion rules:
- **Zod `z.date()` fields** stored as `text()` → convert with `new Date(row.field)` on read, `date.toISOString()` on write
- **Optional DB fields** (`goal: text("goal")` without `.notNull()`) → use `row.goal ?? undefined` (converts `null` to `undefined`)
- **JSON arrays** → `JSON.parse()` then map each item to the domain type, casting individual fields
- **Date fields in JSON items** (e.g., `SprintItem.completedAt`) → parse string back to `Date` during mapping: `item.completedAt ? new Date(item.completedAt as string) : undefined`
- **Nullable numeric fields** (`velocity: integer("velocity")`) → use `row.velocity ?? undefined`

### Writing updates: serialize back to JSON

```typescript
const updatedItems = items.map((item) => ({
  ...item,
  status: "completed" as SprintItem["status"],
  completedAt: new Date().toISOString(),  // Date → ISO string for JSON storage
}))
db.update(sprints)
  .set({ items: JSON.stringify(updatedItems), updatedAt: now().toISOString() })
  .where(eq(sprints.id, id))
  .run()
```

## Effect-TS Service with Synchronous Drizzle Operations

When building services that perform Drizzle ORM operations against an in-memory SQLite database, use `Effect.sync()` instead of `Effect.tryPromise()`. Drizzle's `.run()`, `.all()`, `.get()` methods are synchronous with `bun:sqlite`:

```typescript
export class SprintSimulationService extends Context.Tag("SprintSimulationService")<
  SprintSimulationService,
  {
    readonly createSprint: (params: CreateSprintParams) => Effect.Effect<Sprint>
    readonly getSprint: (id: string) => Effect.Effect<Sprint | null>
    // ... other methods
  }
>() {
  static readonly Live = Layer.effect(
    SprintSimulationService,
    Effect.gen(function* () {
      const { db } = yield* DatabaseService

      return {
        // Synchronous DB operations → wrap in Effect.sync()
        createSprint: (params) =>
          Effect.sync(() => {
            const id = generateId()
            const nowStr = now().toISOString()
            db.insert(sprints).values({ id, ... }).run()
            return rowToSprint({ id, ... })  // Use helper to convert DB row → domain type
          }),

        getSprint: (id) =>
          Effect.sync(() => {
            const rows = db.select().from(sprints).where(eq(sprints.id, id)).all()
            if (rows.length === 0) return null
            return rowToSprint(rows[0])
          }),
      }
    })
  )
}
```

### Test Pattern for Services Using DatabaseService

```typescript
import { Database } from "bun:sqlite"
import { drizzle } from "drizzle-orm/bun-sqlite"
import * as schema from "../../core/src/db/schema.js"
import { runMigrations } from "../../core/src/db/migrate.js"
import { DatabaseService } from "../../core/src/db/client.js"

function createTestLayer() {
  const TestDbLayer = Layer.sync(DatabaseService, () => {
    const sql = new Database(":memory:")
    runMigrations(sql)
    const db = drizzle(sql, { schema })
    return { db, sql }
  })

  return SprintSimulationService.Default.pipe(
    Layer.provide(TestDbLayer)
  )
}

// Each test creates its own layer (fresh DB)
describe("SprintSimulationService", () => {
  let testLayer: Layer.Layer<SprintSimulationService>
  beforeEach(() => { testLayer = createTestLayer() })

  test("create a sprint", async () => {
    const program = Effect.gen(function* () {
      const sprints = yield* SprintSimulationService
      const sprint = yield* sprints.createSprint({ name: "Sprint 1", projectId: "p1" })
      return sprint
    })
    const result = await Effect.runPromise(program.pipe(Effect.provide(testLayer)))
    expect(result.name).toBe("Sprint 1")
  })
})
```

**Critical**: Each `Effect.runPromise` call with a fresh layer creates a fresh in-memory DB. This is why each test must combine all operations into a single `Effect.gen` + single `Effect.runPromise` call. Data from one test is invisible to another.

### Adding a New Table: Both schema.ts AND migrate.ts

When adding a new Drizzle table to this project:

1. **Add the table definition to `schema.ts`** before the FTS section marker:
   ```typescript
   // --- My New Table ---
   export const myTable = sqliteTable("my_table", {
     id: text("id").primaryKey(),
     // ...
   })
   ```

2. **Add the CREATE TABLE SQL to `migrate.ts`** in the `INITIAL_SCHEMA` string (this project uses a single migration, not incremental):
   ```typescript
   // In the INITIAL_SCHEMA string, BEFORE FTS5 virtual tables:
   CREATE TABLE IF NOT EXISTS my_table (
     id TEXT PRIMARY KEY,
     -- ...
   );
   ```

   **Pitfall**: The FTS section marker is `// --- FTS5 Virtual Tables (Full-Text Search) ---`, NOT `// --- FTS Tables ---`. Searching for the wrong marker causes the patch to fail.

3. **Add Zod types to `types/index.ts`** for the domain model

4. **Export the new service** from the package's `index.ts`

5. **Run tests** with `bun test` to verify — in-memory DB tests automatically get the new table via `runMigrations(sql)`

## Pitfalls

- `declaration` and `declarationMap` in tsconfig are incompatible with `noEmit: true` — remove them
- drizzle-orm and bun-types may have declaration mismatches — `skipLibCheck: true` handles this
- Always verify with `bun run typecheck | grep "packages/YOUR_PACKAGE"` after fixes
- When `bun test` says "Export named 'X' not found", it may be loading stale `.js` files from `dist/` — delete `dist/` and `.turbo/` cache, then re-test
- `moduleResolution: "bundler"` is required for Bun monorepo subpath imports — without it, `@opencode-fusion/package/subpath` fails in tsc
- Moving files between workspace packages requires updating: (1) import paths, (2) `package.json` exports, (3) dependency direction, (4) moving test fixtures
- `Effect.Service<>()()` crashes in Bun runtime (v1.3.13 + effect@3.21.2) with `TypeError: source is not an Object` — use `Context.Tag` + `Layer.effect` instead
- When `Effect.provide()` receives an `Effect.Service` class directly instead of a `Layer`, Bun's runtime fails at `circularManagedRuntime.TypeId` check — always provide `MyServiceLive` (a Layer), not `MyService` (the class)
- `Record<string, T>` is NOT assignable FROM an interface with named keys (e.g., `TraitMap`) unless the interface has an explicit index signature `[key: string]: T` — see "Named-Key Interfaces vs Record<string, T>" below
- When YAML/JSON frontmatter is parsed as `Record<string, unknown>`, field values are `unknown` — always wrap with `String()` or `Number()` before assigning to typed fields
- **`test.skipIf` currying syntax** — `test.skipIf(true(` is missing the closing paren before the callback. Correct: `test.skipIf(true)("test name", async () => { ... })`. The `skipIf` method returns a curried function — it must be called as `skipIf(condition)(name, fn)`, not `skipIf(condition(name, fn)`. This bug causes a parse error `Expected ) but found test` and is easy to miss visually.
- **`as unknown as T` for mock type narrowing** — When creating mock objects for Effect-TS services in tests, partial mocks may not satisfy all required properties. `as T` fails if the object is missing fields; `as unknown as T` bypasses the type check. Use sparingly — only in test mocks where you intentionally omit irrelevant methods. Example: `Layer.succeed(SkillAutoLoader, SkillAutoLoader.of({ autoLoad: () => Effect.succeed({ matchedTriggers: [], autoLoadContext: "", estimatedTokens: 0 } as unknown as AutoLoadResult) }))`
- **Wiring services into Effect.Service classes: always check `.Live` vs `.Default`** — Services may export `.Default` or `.Live` (not both). Using the wrong name causes `TS2339`. Check the source file before adding to the dependencies array.
- **SelfHealingService.executeWithHealing parameter order is `(task, role, agentId, config?)`** — NOT `(agentId, task, config)`. And `SelfHealingResult` uses `finalResult` (not `result`). Always read the actual interface definition before implementing the mapping layer."