---
name: vitest-monorepo-setup
description: >
  Add vitest test infrastructure to npm/Bun workspace monorepos — shared, web (React/Next.js),
  and API packages. Covers version alignment, config files, jsdom setup, and common pitfalls.
version: 1.0.0
---

# Vitest Monorepo Setup

## When to Use

- Adding vitest to a workspace monorepo (npm workspaces, Bun workspaces, or turbo)
- Setting up React component tests with @testing-library/react + jsdom
- Adding test scripts to packages that previously had no tests
- Any time you see `vitest` version mismatches or `Failed to resolve import` errors in monorepos

## Procedure

### 1. Install vitest at workspace ROOT, not in individual packages

**Pitfall**: Installing vitest in a workspace package (`bun add -d vitest` inside `packages/shared/`) creates a local copy that conflicts with the root version. You'll see `No handler function exported from worker.js` errors or version mismatches.

**Fix**: Remove local installs and add vitest to the root package.json:

```bash
# Remove local vitest if accidentally installed
cd packages/shared && bun remove vitest

# Install at root (use bun for bun projects, npm for npm projects)
cd /repo/root && bun add -d vitest   # or: npm install -D vitest -w .
```

The workspace packages reference the hoisted root version via their `test` script.

### 2. Add `test` script to each workspace package

```json
// packages/shared/package.json
{
  "scripts": {
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  }
}
```

### 3. Create root vitest.config.ts

```typescript
// vitest.config.ts (root)
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/src/**/__tests__/**/*.test.{ts,tsx}"],
  },
});
```

### 4. For React/Next.js web packages — add jsdom + testing-library

```bash
cd packages/web
bun add -d vitest @testing-library/react @testing-library/jest-dom jsdom @vitejs/plugin-react
```

Then create a `vitest.config.ts` in the web package:

```typescript
// packages/web/vitest.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      // Add workspace package aliases
      "@my-org/shared": path.resolve(__dirname, "../shared/src"),
    },
  },
});
```

Create the setup file:

```typescript
// packages/web/src/__tests__/setup.ts
import "@testing-library/jest-dom/vitest";
```

**Pitfall**: The setup file MUST use `@testing-library/jest-dom/vitest` (not just `@testing-library/jest-dom`) for vitest integration.

### 5. Import paths from `__tests__/` to source

**Pitfall**: Tests in `src/__tests__/` importing from `src/components/` or `src/lib/` must use `../` (one level up), NOT `../../` (two levels up). Both directories are siblings under `src/`:

```
src/
  __tests__/Badge.test.tsx   → import { Badge } from "../components/Badge"
  components/Badge.tsx
  lib/api.ts
```

Wrong: `from "../../components/Badge"` — this resolves to the parent of `src/`, not to `components/`.

### 6. German/Special characters in test assertions

When testing German UI components, use the actual Unicode characters, not ASCII approximations:

- ✅ `"Präsenz"` (with ä)
- ❌ `"Praesenz"` (ASCII approximation)
- ✅ `"Veröffentlicht"` (with ö, ä)
- ❌ `"Veroffentlicht"` (without umlauts)

The source code uses real Unicode, so assertions must match exactly.

### 7. Run tests from root

```bash
# All packages
npx vitest run

# Single package (if vitest workspace is NOT configured)
cd packages/shared && npx vitest run

# Single package via npm workspaces
npm run test --workspace=packages/shared
```

### 8. Common assertion patterns for React components

```typescript
// Render and query by accessible label
const input = screen.getByLabelText("Email");

// Check attributes
expect(input).toHaveAttribute("type", "email");
expect(input).toHaveAttribute("aria-invalid", "true");

// Check role-based queries
expect(screen.getByRole("button", { name: /suchen/i })).toBeInTheDocument();
expect(screen.getByRole("search")).toBeInTheDocument();

// Check CSS classes (on container)
const { container } = render(<Badge variant="vorlesung" />);
expect(container.querySelector("span")?.className).toContain("bg-blue-100");

// Unmount between iterations to avoid DOM collision
for (const item of items) {
  const { unmount } = render(<Component variant={item} />);
  expect(screen.getByText(item.label)).toBeInTheDocument();
  unmount();
}
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `No handler function exported from worker.js` | Vitest version mismatch (local vs root) | Remove local vitest, install at root only |
| `Failed to resolve import "../../components/X"` | Wrong relative path from `__tests__/` | Use `../components/X` (one level up) |
| `Cannot find package 'bun:test'` | Running `bun test` in a vitest-configured project | Use `vitest run` or `npm test` instead |
| `'body' is of type 'unknown'` | Hono `res.json()` returns unknown in tests | Add type assertion: `(await res.json()) as ExpectedType` |
| `ReferenceError: document is not defined` | Missing jsdom environment | Ensure vitest.config.ts has `environment: "jsdom"` |
| vitest reports `0 test files` | `simple=true` in config or wrong include pattern | Check `include` glob matches your test file paths |

## Minimum Viable Test Setup Checklist

- [ ] vitest installed at workspace root
- [ ] `test` script in each package's package.json
- [ ] Root `vitest.config.ts` with correct include glob
- [ ] Web package: `vitest.config.ts` with react plugin + jsdom + setup file
- [ ] Web package: `@testing-library/jest-dom/vitest` in setup
- [ ] Import paths use `../` not `../../` from `__tests__/`
- [ ] `npx vitest run` passes all tests from repo root