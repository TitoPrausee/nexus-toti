---
name: effect-ts-testing
description: Testing pattern for Effect-TS services using mock Layer.sync layers and in-memory SQLite. Used in OpenCode Fusion but applicable to any Effect-TS project.
version: 1.0.0
author: Toti
tags: [effect-ts, testing, mock, layer, sqlite, bun]
---

# Effect-TS Service Testing Pattern

## Overview

When testing Effect-TS services that depend on other services (DatabaseService, AgentLifecycle, etc.), you must provide mock implementations via `Layer.sync`. Without them, `Effect.runPromise` throws `Service not found` errors at runtime.

## The Pattern

### 1. In-Memory Database Layer

```typescript
import { Database } from "bun:sqlite"
import { drizzle } from "drizzle-orm/bun-sqlite"
import * as schema from "../../core/src/db/schema.js"
import { runMigrations } from "../../core/src/db/migrate.js"
import { DatabaseService } from "../../core/src/db/client.js"

const TestDbLayer = Layer.sync(DatabaseService, () => {
  const sql = new Database(":memory:")
  runMigrations(sql)
  const db = drizzle(sql, { schema })
  return { db, sql }
})
```

Key points:
- `:memory:` SQLite = fast, isolated, no file cleanup
- **Always** call `runMigrations(sql)` before creating the drizzle instance
- Pass `schema` to drizzle for relational query support

### 2. Mock Service Layers

For each service dependency that the system under test needs, create a mock:

```typescript
import { Effect, Layer } from "effect"
import { AgentLifecycle } from "../../agent-runtime/src/lifecycle.js"
import { AgentExecutor } from "../../agent-runtime/src/executor.js"

// Define mock data as a constant first (avoids LazyArg type errors)
const mockAgentInstance = {
  id: "mock-agent",
  name: "mock",
  role: "developer" as const,
  status: "running" as const,
  spawnedAt: new Date(),
  lastHeartbeat: new Date(),
}

// Mock returning Effect values — pass the VALUE directly, not a function
const MockAgentLifecycle = Layer.sync(AgentLifecycle, () => ({
  spawn: (_name: string, _role: string) => Effect.sync(mockAgentInstance),
  stop: (_agentId: string) => Effect.sync(undefined),
  heartbeat: (_agentId: string) => Effect.sync(undefined),
  get: (id: string) => Effect.sync(id === "mock-agent" ? mockAgentInstance : null),
  listRunning: () => Effect.sync([mockAgentInstance]),
}))

// Mock for services with config params
const mockExecutionResult = {
  taskId: "mock-task",
  content: "Mock result",
  toolCallsCount: 0,
  iterations: 1,
  usage: { promptTokens: 10, completionTokens: 10, totalTokens: 20 },
}

const MockAgentExecutor = Layer.sync(AgentExecutor, () => ({
  execute: (_task: string, _role: string, _config?: any) =>
    Effect.sync(mockExecutionResult),  // NOT Effect.sync(() => mockExecutionResult)
  registerTool: () => Effect.sync(undefined),
  listTools: () => Effect.sync([]),
}))
```

**Critical:** Mock methods must return `Effect.sync(value)` not `Effect.sync(() => value)`. The double-wrapper (`Effect.sync(() => ({...}))`) causes `op.effect_instruction_i0 is not a function` runtime errors in Effect-TS. Always pass the direct value to `Effect.sync()`.

**Also critical:** Mock method signatures must match the service interface exactly, including parameter names and counts. If the real method is `spawn(name: string, role: AgentRole)`, the mock must also accept two params — use `_name`, `_role` prefix for unused params. Missing params cause runtime type mismatches.

### 3. Compose Layers for the Test

```typescript
function createTestLayer() {
  const TestDbLayer = /* ... as above ... */

  const OrchestratorLayer = TaskOrchestrator.Default.pipe(
    Layer.provide(
      Layer.mergeAll(
        TestDbLayer,
        MockAgentLifecycle,
        MockAgentExecutor,
      )
    )
  )

  return TeamService.Default.pipe(
    Layer.provide(
      Layer.mergeAll(
        OrganizationService.Live.pipe(Layer.provide(TestDbLayer)),
        CommunicationService.Live.pipe(Layer.provide(TestDbLayer)),
        MeetingService.Live.pipe(Layer.provide(TestDbLayer)),
        OrchestratorLayer,
      )
    )
  )
}
```

**Key insight:** Each `XService.Live` needs `TestDbLayer` provided individually UNLESS it's nested through `Default`. The `Default` layer may also need its own dependencies provided before being merged.

### 4. Run Tests with Effect.runPromise

```typescript
describe("MyService", () => {
  let testLayer: Layer.Layer<MyService>

  beforeEach(() => {
    testLayer = createTestLayer()
  })

  test("does something", async () => {
    const program = Effect.gen(function* () {
      const service = yield* MyService
      return yield* service.someMethod("arg")
    })

    const result = await Effect.runPromise(
      program.pipe(Effect.provide(testLayer))
    )

    expect(result).toBe("expected")
  })
})
```

## Shared DB Instances in Layer Composition

When multiple services in a test share a database (e.g., `SkillStore` + `SelfModelService` both need `DatabaseService`), you MUST compose all layers into a single tree before providing to the program. Separate `Effect.provide()` calls create **separate in-memory SQLite instances** — data written by one service vanishes from another's perspective.

```typescript
// BAD — each Effect.provide() creates a separate in-memory DB
const result = await Effect.runPromise(
  program.pipe(
    Effect.provide(TestDbLayer),       // DB instance #1
    Effect.provide(SkillStore.Default), // DB instance #2
    Effect.provide(SelfModelService.Default), // DB instance #3
  )
)
// SkillStore writes to DB #2, PromptAssembler reads from DB #3 — empty!

// GOOD — compose into a single layer tree, provide once
const SharedDbLayer = Layer.mergeAll(
  TestDbLayer,
  SkillStore.Default,
  SelfModelService.Default,
)

const TestLayer = PromptAssembler.Default.pipe(
  Layer.provide(SharedDbLayer)
)

const result = await Effect.runPromise(
  program.pipe(Effect.provide(TestLayer))
)
// Now all services share the same in-memory DB instance
```

**Root cause:** `Effect.provide()` wraps each layer in a new context. In-memory SQLite databases are scoped to the layer that creates them. Multiple provisions = multiple fresh empty databases.

## Bottom-Up Layer Composition for Deep Dependency Chains

When services have **transitive dependencies** (e.g., `BatchRunner → SkillAutoLoader → SkillStore → DatabaseService`), you CANNOT simply use `XService.Default` and provide all layers flat. Effect-TS `Layer.provide()` only resolves the **immediate** dependency — transitive dependencies must be explicitly wired **bottom-up**.

```typescript
// WRONG: Flat provision — SkillStore is never provided to SkillAutoLoader
const layer = BatchRunner.Default
  .pipe(
    Layer.provide(AgentExecutor.Default),
    Layer.provide(SkillAutoLoader.Default),  // ← Missing SkillStore!
  )

// RIGHT: Build bottom-up, each layer gets its own deps first
const { SkillStoreLayer, SkillAutoLoaderLayer, PromptAssemblerLayer } = createDBLayer()

const ExecutorLayer = AgentExecutor.Live.pipe(
  Layer.provide(mockLLM),
  Layer.provide(PromptAssemblerLayer),
  Layer.provide(SubagentService.Default),  // self-contained (no deps)
  Layer.provide(AgentLifecycle.Default),   // self-contained (uses Map internally)
)

return BatchRunner.Live.pipe(
  Layer.provide(ExecutorLayer),
  Layer.provide(PermissionService.Default),
  Layer.provide(ToolRegistry.Default),
  Layer.provide(PromptAssemblerLayer),
  Layer.provide(SkillAutoLoaderLayer),  // Now includes SkillStore → DatabaseService
)
```

**Why this matters**: `SkillAutoLoader.Default = SkillAutoLoader.Live` (no `dependencies` array). At runtime, `yield* SkillStore` inside `SkillAutoLoader.Live` will throw `Service not found: SkillStore` unless SkillStore is provided **beneath** the SkillAutoLoader layer. `Layer.provide()` chains the dependency — it doesn't merge across the graph.

**Rule of thumb**: For any `XService.Default` that does NOT contain a `static dependencies` field, check its source file for `yield*` to find what services it needs, then provide those **before** composing into the parent layer.

## Module-Level State and Test Isolation

Services using module-level `Map` or `Set` (like BatchRunner's `batchStore`) persist state **across test cases**. This means a test that expects `listBatches().length === 2` will fail if a prior test already added entries.

**Solutions**:
1. **Resilient assertions**: Use `toContain(id)` instead of `toHaveLength(n)` to be independent of prior state
2. **Test helper**: Add a `resetStore()` method to the service for test cleanup
3. **Effect.Ref**: Replace module-level mutable state with `Effect.Ref` inside the service, which is scoped to the Layer lifecycle and resets per test

## E2E Test Pattern: Mock LLM Provider for Full Pipeline Tests

For end-to-end tests that exercise the full agent pipeline (tool loading → LLM call → response parsing → self-healing), use a mock LLM provider that returns canned responses:

```typescript
import { Effect, Layer, Config } from "effect"
import { LLMProvider } from "../src/llm/provider.js"

// Mock returns deterministic responses based on input patterns
const MockLLMProvider = Layer.sync(LLMProvider, () => ({
  complete: (prompt: string) =>
    Effect.sync(() => {
      if (prompt.includes("analyze")) return JSON.stringify({ analysis: "mock" })
      if (prompt.includes("heal")) return JSON.stringify({ healed: true })
      return "Mock LLM response"
    }),
}))
```

**Key patterns for E2E tests:**
1. **Mock at the LLM boundary** — don't mock internal services, mock the LLM provider that everything else depends on
2. **Effect.throw vs Effect.fail** — `Effect.throw(() => new Error(...))` causes **unrecoverable defects** that bypass `Effect.catchAll` / `Effect.catchTag`. For testable error handling, always use `Effect.fail()` or `Effect.fail(new SomeError(...))`. Only use `Effect.throw` if you explicitly want to test defect handling (unrecoverable errors).
3. **Effect.runPromise returns `unknown`** — the TypeScript return type is `unknown`, so assertions on result properties need type narrowing: `expect((result as any).someProperty).toBe(...)`
4. **SelfHealingService API**: use `executeWithHealing` and `classifyError` (actual API). There is no `heal()` method.
5. **DEFAULT_HEALING_CONFIG** has `maxRetries` and `retryBaseDelayMs` but NOT a `strategies` array. Don't assert on `.strategies`.

## Common Pitfalls

1. **`Service not found` error** = Missing mock layer. Every service in the dependency graph must have a layer provided, either real or mock.
2. **`op.effect_instruction_i0 is not a function` runtime error** = Mock uses `Effect.sync(() => value)` (double-wrap) instead of `Effect.sync(value)`. In Effect-TS, `Effect.sync()` expects a thunk that returns the value, but inside a `Layer.sync` mock, the method itself already wraps in `Effect.sync()`, so pass the value directly.
3. **Mock method param signature mismatch** = If the real method has `spawn(name, role)` but the mock only has `spawn()`, Effect-TS will crash at runtime. Always match the full parameter signature, prefixing unused params with `_` (e.g., `_name`, `_role`).
4. **`Effect<..., unknown, ...>` type errors** = Mock returns don't match service signature. Use `Effect.sync()` for sync returns, `Effect.tryPromise()` for async.
5. **When to use `test.skip`** = If an Effect-TS Layer composition causes runtime errors that can't be resolved with mock wiring alone (e.g., `AgentExecutor` returning complex typed `ExecutionResult` through `Effect.either`), skip the test with a TODO comment and test it as an integration test with real service layers instead.
6. **`Layer.merge` vs `Layer.mergeAll`** = `merge` takes 2 args, `mergeAll` takes an array/record. Use `mergeAll` for 3+ layers.
7. **Stale `dist/` cache** = If schema changes aren't reflected, delete `packages/core/dist/` and rebuild. Bun loads `.ts` directly in tests but some tooling reads compiled `.js`.
8. **Circular dependencies** = If package A imports from package B and B imports from A, move shared types to a third package or use Service Tag injection instead of direct imports.
9. **`Schema.Optional` doesn't exist** — the correct function is `Schema.optional()` (lowercase). `Schema.Optional` will throw `TypeError: Schema.Optional is not a function`. For struct fields: `Schema.Struct({ name: Schema.optional(Schema.String) })`.
10. **`XService.Default` vs `XService.Live`** — `Default` is often just an alias for `Live` (no dependency list). Check the source: if it says `static readonly Default = XService.Live`, then `Default` has NO built-in dependency wiring. You must still provide all transitive deps manually via `Layer.provide()`.
11. **`replace_all` rename trap** — When using `replace_all=true` to rename `FooLayer` → `MockFooLayer`, the replacement also matches the **declaration** `const FooLayer = ...` turning it into `const MockFooLayer = ...`. Then your next reference to `MockFooLayer` doesn't exist. Always check that the string you're replacing from isn't part of a declaration that should keep its original name, or use targeted (non-replace_all) patches instead.

## Testing Services with Layer.succeed for Simple Mocks

When a service depends on other services but you only need simple static mock returns (no DB, no stateful logic), use `Layer.succeed` instead of `Layer.sync`. This is cleaner and avoids unnecessary `Effect.sync()` wrapping:

```typescript
import { Layer } from "effect"
import { PromptAssembler } from "../src/prompt-assembler.js"
import { SkillLoader, type SkillLoaderResult } from "../src/skills/skill-loader.js"
import { SelfModelService, type SelfModel } from "@toti/memory"

// Define mock data as plain objects
const mockSkillResult: SkillLoaderResult = {
  resolved: [
    { skill: { id: "s1", name: "git-workflow", ... }, matchScore: 0.8, matchedKeywords: ["git"] },
  ],
  skillContext: "## Skills\n- git-workflow: Use conventional commits",
  estimatedTokens: 30,
}

const mockSelfModel: SelfModel = {
  id: "sm1", agentId: "developer",
  traits: { communication_style: 0.3, decisiveness: 0.7, ... },
  strengths: ["fast iteration"], weaknesses: [],
  identityStatement: "A pragmatic developer",
  ...
}

// Layer.succeed for services that don't need Effect wiring
const MockSkillLoader = Layer.succeed(SkillLoader, {
  load: () => Effect.sync(() => mockSkillResult),
  loadByNames: () => Effect.sync(() => ({ resolved: [], skillContext: "", estimatedTokens: 0 })),
  defaultConfig: () => ({ maxSkills: 5, minMatchScore: 0.2, maxTokenBudget: 2000, includeCategoryHeaders: true }),
})

const MockSelfModelService = Layer.succeed(SelfModelService, {
  getOrCreate: () => Effect.sync(() => mockSelfModel),
  updateTraits: () => Effect.sync(() => mockSelfModel),
  recordStrength: () => Effect.sync(undefined as any),
  recordWeakness: () => Effect.sync(undefined as any),
  getIdentityStatement: () => Effect.sync(() => "A pragmatic developer"),
})

// Compose test layer — wire Default with mock dependencies
const TestLayer = PromptAssembler.Default.pipe(
  Layer.provide(MockSkillLoader),
  Layer.provide(MockSelfModelService),
)

// Run tests
test("assembles prompt with role section", async () => {
  const program = Effect.gen(function* () {
    const assembler = yield* PromptAssembler
    return yield* assembler.assemble("developer", "Fix the login bug")
  })
  const result = await Effect.runPromise(program.pipe(Effect.provide(TestLayer)))
  expect(result.systemPrompt).toContain("Developer agent")
  expect(result.sections.some(s => s.label === "role")).toBe(true)
})
```

**Key points:**
- `Layer.succeed` for simple mocks (no Effect.gen, no yield* needed)
- `Layer.provide` chains to inject mock dependencies
- Use `XService.Default` for the service under test (it uses `Layer.effect` internally with yield*)
- Mock data objects declared as module-level constants for reuse across tests

**Testing config toggles** — When a service has config options that change behavior (e.g., `includeSelfModel: false`), test both paths:

```typescript
test("includes personality section when includeSelfModel is true", async () => {
  const result = await Effect.runPromise(
    program.pipe(Effect.provide(TestLayer))
  )
  expect(result.sections.some(s => s.label === "personality")).toBe(true)
})

test("excludes personality section when includeSelfModel is false", async () => {
  const result = await Effect.runPromise(
    program.pipe(Effect.provide(TestLayer))
  )
  // Same layer, different config override
  expect(result.sections.some(s => s.label === "personality")).toBe(false)
})
```

**TypeScript `possibly undefined` in tests** — When using `.find()` to get an option, even after `expect(x).toBeDefined()`, TypeScript can't narrow the type. Use non-null assertion `x!.property` instead of `x.property`:

```typescript
// ❌ TS18048: 'roleOption' is possibly 'undefined'
expect(roleOption.defaultValue).toBe("developer")

// ✅ Non-null assertion after assertion guard
expect(roleOption).toBeDefined()
expect(roleOption!.defaultValue).toBe("developer")
```

## Circular Dependency Resolution

When two packages have circular imports:
1. **Identify** which imports are actually needed (often just type imports)
2. **Move** the implementation to the package that should own it
3. **Reverse** the dependency direction so the dependency graph is a DAG
4. Example: `agent-runtime` imported `OrganizationService` from `team` just for 3 tool files → moved those tools to `team`, removed the dependency

In this project specifically, the direction is:
```
core → memory → agent-runtime → team → gateway
```
No back-edges allowed.

## Testing Pure Effect-TS Services Directly (No Layer Machinery)

When a `Context.Tag` service has **no dependencies** (pure computation, `Effect.sync` methods, no `yield*` for other services), testing through `Effect.gen` + `yield* Tag` + `Effect.provide(Layer)` produces a cascade of TS2802 and TS2345 type errors:

- **TS2802**: `Type 'typeof SpecPlanner' can only be iterated through when using '--downlevelIteration'` — caused by `yield* SpecPlanner` on a `Context.Tag`
- **TS2345**: `Argument of type 'Effect<SpecPlan, any, any>' is not assignable to parameter of type 'Effect<SpecPlan, any, never>'` — the requirement channel doesn't narrow
- **TS2339**: `Property 'Live' does not exist on type 'typeof SpecPlanner'` — when the Layer is exported separately

**Solution**: Call the service factory function directly and wrap individual method calls in `Effect.runPromise()`:

```typescript
// ❌ WRONG — causes TS2802/TS2345 cascade
import { SpecPlanner, SpecPlannerLive } from "../src/spec-planner.js"

describe("SpecPlanner", () => {
  const planner = SpecPlannerLive  // or SpecPlanner.Live
  test("parses spec", () => {
    const program = Effect.gen(function* () {
      const spec = yield* SpecPlanner       // TS2802 here
      const plan = yield* spec.parseSpec(input)  // OK
      return plan
    }).pipe(Effect.provide(planner))
    const plan = Effect.runPromise(program) as Promise<SpecPlan>  // TS2345 here
  })
})

// ✅ CORRECT — direct factory call, skip Effect context entirely
import { SpecPlannerServiceLive, type SpecPlan } from "../src/spec-planner.js"

describe("SpecPlanner", () => {
  const planner = SpecPlannerServiceLive()  // Direct factory call

  // Helper to run Effects without context
  async function run<T>(effect: Effect.Effect<T>): Promise<T> {
    return Effect.runPromise(effect as any) as Promise<T>
  }

  test("parses spec into tasks", async () => {
    const plan = await run(planner.parseSpec(SIMPLE_SPEC))
    expect(plan.title).toBe("My Project Spec")
    expect(plan.tasks.length).toBeGreaterThanOrEqual(3)
  })
})
```

**Key points:**
- Export the factory function (`SpecPlannerServiceLive`) as a named export alongside the `Context.Tag` class
- The factory returns the service interface object directly — no Effect wrapping needed to access it
- Use `as any` cast in the `run()` helper to suppress the TS2345 requirement-channel mismatch
- Methods still return `Effect.Effect<T>`, so you still call `Effect.runPromise()` — just on the method result, not on a composed program
- This pattern only works for services with no dependencies (pure computation). For services requiring other services (DB, etc.), use the full Layer composition pattern above

**When to use this pattern vs. full Layer composition:**
- **Direct factory call**: Service uses `Effect.sync()` for all methods, no `yield*` for external services, no state (like SpecPlanner parsing markdown into structured data)
- **Full Layer composition**: Service depends on DatabaseService, ConfigService, or other Effect-TS services that must be provided via Layers