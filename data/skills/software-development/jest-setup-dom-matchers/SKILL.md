---
name: jest-setup-dom-matchers
description: Fix Jest + @testing-library/jest-dom setup where custom matchers (toHaveAttribute, toHaveClass, toHaveStyle) fail because jest-dom loaded too early in setupFiles instead of setupFilesAfterEnv.
version: 1.0.0
---

# Jest + jest-dom: Setup Files Pitfall & Fix

## The Problem

Custom matchers from `@testing-library/jest-dom` (e.g., `toHaveAttribute`, `toHaveClass`, `toHaveStyle`) throw "is not a function" at runtime even though the package is installed.

**Symptoms:**
```
TypeError: expect(...).toHaveAttribute is not a function
TypeError: expect(...).toHaveClass is not a function
TypeError: expect(...).toHaveStyle is not a function
```

## Root Cause

Jest has **two different setup phases**:

| Config key | When it runs | `expect` available? |
|---|---|---|
| `setupFiles` | Before test framework initializes | ❌ No |
| `setupFilesAfterEnv` | After test framework (and `expect`) is initialized | ✅ Yes |

If `@testing-library/jest-dom` is loaded in `setupFiles` (via `require()` or a file listed there), it calls `expect.extend()` before `expect` exists. The import silently fails — jest-dom matchers are never registered.

**Common misconfiguration:**
```javascript
// jest.config.cjs — ❌ WRONG
module.exports = {
  setupFiles: ['./jest-setup.cjs'],          // jest-dom loaded here = broken
  setupFilesAfterEnv: ['@testing-library/jest-dom'], // ← also wrong if jest-dom is also in the .cjs file
};
```

```javascript
// jest-setup.cjs — ❌ WRONG
require('@testing-library/jest-dom');         // expect doesn't exist yet
```

## The Fix

**Split the setup into two files:**

### File 1: `jest-setup.cjs` (pre-framework — `setupFiles`)
Only pre-framework polyfills. No jest-dom imports.

```javascript
// jest-setup.cjs — ONLY pre-framework mocks
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: function(query) {
    return {
      matches: false,
      media: query,
      onchange: null,
      addListener: function() {},
      removeListener: function() {},
      addEventListener: function() {},
      removeEventListener: function() {},
      dispatchEvent: function() { return false; },
    };
  },
});
```

### File 2: `jest-setup-after.cjs` (post-framework — `setupFilesAfterEnv`)
This is where jed-dom goes.

```javascript
// jest-setup-after.cjs
require('@testing-library/jest-dom');
```

### Config

```javascript
// jest.config.cjs
module.exports = {
  // ... other config ...
  setupFiles: ['./jest-setup.cjs'],                // ← pre-framework only
  setupFilesAfterEnv: ['./jest-setup-after.cjs'],   // ← jest-dom here
};
```

## Verification

Run a test that uses jest-dom matchers:

```bash
npx jest --testPathPatterns='<TestName>' --no-coverage
```

Expected output:
```
Test Suites: 1 passed, 1 total
Tests:       N passed, N total
```

## Prevention Checklist

When adding `@testing-library/jest-dom` to a project:

- [ ] Is `require('@testing-library/jest-dom')` in **`setupFilesAfterEnv`** (not `setupFiles`)?
- [ ] Are there separate files for pre-framework mocks (`matchMedia`, `requestAnimationFrame`, etc.) vs post-framework setup?
- [ ] After any jest config change, run a test that uses `toHaveAttribute`, `toHaveClass`, or `toHaveStyle` to confirm matchers are registered
