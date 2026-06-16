---
name: flutter-performance-optimization
description: Systematically optimize Flutter widget rebuild performance — add `const` to safe widget instantiations, wrap heavy areas in `RepaintBoundary`, and extract repeated widget subtrees. Uses Python scanning scripts for full codebase coverage.
version: 1.0.0
author: Hermes Agent
metadata:
  hermes:
    tags: [flutter, performance, widget-rebuilds, optimization, const-constructors]
    related_skills: [systematic-debugging, plan]
---

# Flutter Widget Rebuild Optimization

Use when tasked with "optimize widget rebuilds", "improve performance", or any issue about reducing unnecessary widget rebuilds in a Flutter codebase.

## Key Insights

**Most widget classes already have `const` constructors.** The real performance wins are in:
1. Adding `const` to widget **instantiations** inside `build()` methods (SizedBox, Icon, Divider, Center, Padding)
2. Wrapping heavy rebuild areas in `RepaintBoundary`
3. Extracting repeated inline widget trees into separate `StatelessWidget`s

## Step-by-Step

### 1. Scan for optimization targets

```bash
# Find files with build methods
grep -rln 'Widget build(' lib/ --include='*.dart'
# Count total
grep -rn 'Widget build(' lib/ --include='*.dart' | wc -l
```

Use a Python scanning script to find const-able patterns inside build methods:

```python
import os, re

os.chdir('/path/to/project')

result = subprocess.run(
    r"grep -rnE '^\s+Widget build\(' lib/ --include='*.dart'",
    shell=True, capture_output=True, text=True
)
builds = [b for b in result.stdout.strip().split('\n') if b]

for entry in builds:
    file = entry.split(':')[0]
    line_no = int(entry.split(':')[1])
    with open(file) as f:
        lines = f.read().split('\n')
    
    changes = []
    for i in range(line_no, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith('//') or 'const ' in stripped:
            continue
        # Detect const-able patterns
        if stripped in ['Divider(height: 1),', 'Divider(),']:
            changes.append((i+1, stripped))
        if re.match(r'^ {0,16}SizedBox\(', stripped) and 'child:' not in stripped:
            changes.append((i+1, stripped))
        if re.match(r'^ {0,16}Icon\(Icons\.', stripped):
            changes.append((i+1, stripped))
    
    if changes:
        print(f"\n=== {file} ===")
        for ln, txt in changes:
            print(f"  L{ln}: {txt[:80]}")
```

### 2. Apply const — SAFETY RULES

**ONLY add `const` when ALL arguments are compile-time constants:**

| Safe | NOT safe |
|------|----------|
| `SizedBox(width: 16)` | `SizedBox(width: isLarge ? 8 : 4)` |
| `SizedBox(height: 8)` | `SizedBox(height: bottom)` |
| `Icon(Icons.add, size: 20)` | `Icon(Icons.map, color: color)` |
| `Icon(Icons.restaurant_menu, color: AppColors.primary, size: 20)` | `Icon(icon, size: AppSpacing.iconSm)` |
| `Divider(height: 1)` | `SizedBox(child: nonConstWidget())` |
| `Center(child: const Text(...))` | `Padding() with dynamic content` |
| `const EdgeInsets.all(16)` | Any line with `isDark`, `widget.`, `.value`, `.withOpacity()`, function calls |

**Apply via `patch` tool:**

```
old_string:                Icon(Icons.map, color: AppColors.primary, size: 20),
new_string:                const Icon(Icons.map, color: AppColors.primary, size: 20),
```

### 3. Add RepaintBoundary

Wrap heavy rebuild areas to isolate repaint costs:

```dart
RepaintBoundary(
  child: AnimatedSwitcher(
    duration: const Duration(milliseconds: 300),
    child: pages[state.currentStep],
  ),
)
```

Good candidates:
- `AnimatedSwitcher` / `AnimatedCrossFade` content
- Tab content areas in `TabBarView`
- Large/expensive `ListView` items (wrap itemBuilder output)
- Gradient/animation-heavy widgets
- Page transitions

### 4. Check for missing widget class const constructors

```bash
grep -rnE 'extends (StatefulWidget|StatelessWidget|ConsumerWidget|ConsumerStatefulWidget)' lib/ --include='*.dart'
```

For each public class found, verify it has a `const` constructor (look for `const` + `super.key` or `const ClassName({` in the next ~10 lines). Missing const constructors mean the widget can never be const-instantiated by consumers.

Skip private classes (starting with `_`).

### 5. Extract repeated widget subtrees

If the same 10+ line widget pattern appears 3+ times, extract into a `StatelessWidget`.

Good candidates:
- Repeated `Container(...)` decoration patterns (same borderRadius, padding, border)
- Repeated `Row` + `Icon` + `Text` info blocks
- Repeated section label patterns
- Empty state / loading placeholders
- The `isDark ? Color(0xFF121212) : Colors.white` boilerplate in Scaffold/AppBar

### 6. Quick check for raw color hex codes vs AppColors constants

Many screen files use `const Color(0xFF121212)` (very dark background) and `const Color(0xFF1E1E1E)` (dark surface) instead of AppColors constants. These are usually in `isDark ? const Color(0xFF...) : ...` ternary expressions — not always worth changing if the values differ slightly, but worth noting.

```bash
grep -rn 'const Color(0xFF121212)' lib/ --include='*.dart'
```

### 7. Verify and commit

```bash
git diff --stat
git add -A
git commit -m "perf: optimize widget rebuilds with const constructors and RepaintBoundary"
git push origin main
```

## Pitfalls

- **Dynamic sizes:** `SizedBox(width: isLarge ? 8 : 4)` looks const-able but `isLarge` is a runtime variable — skip it
- **Nested const:** Don't add `const` to a widget wrapping a non-const child — Dart will reject it at compile time. Only add `const` when the entire subtree is const
- **Don't touch StatefulWidget constructors** that have `late final` fields — they need mutable initialization
- **Don't over-optimize tiny gains:** A single `const SizedBox(height: 4)` saves negligible memory. Focus on files with 20+ instantiations
- **Build methods > 200 lines** is usually a sign to extract widgets, not just add const
- **Avoid false positives:** Lines with `widget.`, `isDark`, local variables, or function calls are NEVER safe to const-ify
- **Patch carefully:** When using `patch`, include enough surrounding context for uniqueness. Lines like `Icon(Icons.add, ...)` may appear multiple times

## Verification

```bash
# Check diff is clean and focused
git diff --stat

# Confirm the number of build methods was reduced (extracted widgets)
grep -rn 'Widget build(' lib/ --include='*.dart' | wc -l

# Check for syntax errors by running dart analysis if available
which dart && dart analyze lib/ 2>&1 | head -30
```
