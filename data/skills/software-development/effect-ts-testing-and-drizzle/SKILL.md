---
name: effect-ts-testing-and-drizzle
description: Testing patterns for Effect-TS services with Drizzle ORM and SQLite. Covers the critical Drizzle field-name gotcha, shared-layer composition, and silent no-op pitfalls.
version: 1.0.0
author: Toti Agent
license: MIT
metadata:
  hermes:
    tags: [effect-ts, drizzle, testing, sqlite, debugging]
    related_skills: [test-driven-development, effect-ts-patterns]
---

# Effect-TS Testing Patterns & Drizzle ORM Gotchas

## Context
For the OpenCode Fusion project (Bun + Effect-TS + Drizzle ORM + SQLite). These patterns apply broadly to any Effect-TS + Drizzle stack.

## Critical: Drizzle ORM Field Name Mapping

### The Bug Pattern
Drizzle ORM returns **JavaScript camelCase field names** when using `db.select().from(table).all()`, NOT the SQL snake_case column names.

Schema definition:
```ts
export const decisions = sqliteTable("decisions", {
  biasFlags: text("bias_flags").notNull().default("[]"),  // JS: biasFlags, SQL: bias_flags
  createdAt: text("created_at").notNull(),                 // JS: createdAt, SQL: created_at
})
```

When reading rows, Drizzle returns:
```ts
{ biasFlags: '["overconfidence"]', createdAt: '2026-05-06...' }
```

### The Gotcha
`parseRow` functions that access `row.bias_flags` or `row.created_at` will get `undefined`, silently falling through to defaults like `?? "[]"`, producing empty data. This is a **silent data corruption bug** — everything writes correctly but reads back wrong. This caused `detectBiases()` to always return `[]` in production.

### Correct parseRow Pattern
```ts
function parseRow(row: any): DecisionEntry {
  return {
    biasFlags: JSON.parse(row.biasFlags ?? "[]"),     // ✅ camelCase JS field name
    createdAt: new Date(row.createdAt),                 // ✅ camelCase JS field name
  }
}
```

### How to Debug
If any DB-read feature returns empty/unexpected data:
1. Insert a row with known data via the ORM
2. Read it back with `db.select().from(table).all()`
3. `console.log("Row keys:", Object.keys(rows[0]))` — shows actual key names
4. Compare with your `parseRow` key accesses

## Effect-TS Layer Composition for Tests

### The Problem
Merging layers with `Layer.merge` or piping `Layer.provide` separately creates **separate DB instances** — each service gets its own in-memory SQLite, so data written by one service is invisible to another.

### The Pattern: Shared TestDbLayer
```ts
function createTestLayer() {
  const TestDbLayer = Layer.sync(DatabaseService, () => {
    const sql = new Database(":memory:")
    runMigrations(sql)
    const db = drizzle(sql, { schema })
    return { db, sql }
  })

  const MetacogLayer = MetacognitionService.Live.pipe(Layer.provide(TestDbLayer))
  const MotivationLayer = MotivationEngine.Live.pipe(Layer.provide(TestDbLayer))

  const ReflectionLayer = SelfReflectionService.Live.pipe(
    Layer.provide(MetacogLayer),
    Layer.provide(MotivationLayer),
  )

  return ReflectionLayer
}
```

Key: All dependency layers are built from the **same** `TestDbLayer` instance, so they share one DB connection.

## Silent No-Op Pattern

Services that check `if (existing.length === 0) return` before making adjustments silently no-op when `getOrCreate` hasn't been called first. When tests fail with "no effect" symptoms, check whether the prerequisite creation call exists.

Fix pattern — call `getOrCreate` before any adjust/update method:
```ts
yield* motivation.getOrCreate(agentId)  // Ensure row exists first
yield* motivation.adjustImprovement(agentId, boost, reason)
```