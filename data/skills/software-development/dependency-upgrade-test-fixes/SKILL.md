---
name: dependency-upgrade-test-fixes
description: Systematic fixes for test file compilation errors after upgrading Riverpod, Mocktail, gotrue, or postgrest. 7 known patterns with exact fixes.
version: 1.0.0
author: <GITHUB_USER>
---

# Dependency Upgrade Test Fixes

When `dart analyze test/unit/` or `flutter test` shows **compilation errors** (not logic failures) after a dependency upgrade, check these patterns.

These errors occur because test files are tightly coupled to specific API versions of Riverpod, Mocktail, gotrue, and postgrest — and these packages have breaking changes between major versions.

## 1. `valueOrNull` not found (Riverpod 3.x)

**Error:** `The getter 'valueOrNull' isn't defined for the type 'AsyncValue<T>'`

**Cause:** Riverpod 3.2.1+ removed `.valueOrNull`. Only `.value` exists (throws `AsyncValueIsLoadingException` if no value).

**Fix:** Replace `state.valueOrNull` with `state.value` and cast if needed, or guard with `state.hasValue`:
```dart
// Before
expect(state.valueOrNull, isNull);

// After
expect(state.hasValue, isTrue);
expect(state.value, isNull); // or state.value as MyType
```

## 2. `returnValue` in Mocktail `noSuchMethod` not supported (Mocktail 1.0)

**Error:** `The named parameter 'returnValue' isn't defined`

**Cause:** Mocktail 1.0.0 dropped the `returnValue` named parameter from `noSuchMethod()`. Only `returnValueForMissingStub` remains.

**Fix:** Implement the getter/method directly instead of using `noSuchMethod`:
```dart
// ❌ Fails
@override
Map<String, dynamic>? get data => super.noSuchMethod(
      Invocation.getter(#data),
      returnValue: <String, dynamic>{},
    );

// ✅ Works
@override
Map<String, dynamic>? get data => <String, dynamic>{};
```

## 3. `const` model constructors with `DateTime` fields

**Error:** `Cannot invoke a non-'const' constructor where a const expression is expected`

**Cause:** `DateTime()` is not a const constructor. If a model class has `required DateTime createdAt`, using `const Model(createdAt: DateTime(...))` fails.

**Fix:** Change `const` to `final` and use a variable for the DateTime:
```dart
// ❌ Fails
const recipe = CommunityRecipe(
  id: 'r1',
  createdAt: DateTime(2026, 5, 10), // NOT const
);

// ✅ Works  
final now = DateTime(2026, 5, 10);
final recipe = CommunityRecipe(
  id: 'r1',
  createdAt: now,
);
```

## 4. Gotrue `User` is sealed — not mockable (gotrue 2.x)

**Error:** `The argument type 'MockUser' can't be assigned to the parameter type 'User?'`

**Cause:** Gotrue 2.x made `User` a sealed class. `Mock implements User` is now illegal.

**Fix options:**
- Rewrite tests to avoid mocking `User` directly
- Test only the `AuthResponse` contract without inspecting `.user`
- Use `null as dynamic` for now-inaccessible parameters like `Ref`:
  ```dart
  service = AuthRepository(mockSupabaseClient, null as dynamic);
  ```

## 5. Postgrest `select()` parameter count changed (postgrest 2.x)

**Error:** `Too many positional arguments: 1 expected, but 2 found`

**Cause:** Postgrest 2.x `SupabaseQueryBuilder.select()` takes only **one** positional parameter (`String? columns`), not two.

**Fix:** Use only one argument:
```dart
// ❌ Fails
when(() => mockQueryBuilder.select(any(), any()))
    .thenReturn(mockFilterBuilder);

// ✅ Works
when(() => mockQueryBuilder.select(any()))
    .thenReturn(mockFilterBuilder);
```

## 6. Postgrest return type changes `FilterBuilder` → `TransformBuilder` (postgrest 2.x)

**Error:** `Can't be assigned to parameter type 'Answer<PostgrestTransformBuilder<PostgrestMap>>'`

**Cause:** Postgrest 2.x replaced `PostgrestFilterBuilder<T>` with `PostgrestTransformBuilder<PostgrestMap>` for `.eq()`, `.single()`, `.insert()` return types.

**Fix:** Use two separate mock classes:
```dart
class MockPostgrestFilter extends Mock implements PostgrestFilterBuilder<dynamic> {}
class MockPostgrestTransform extends Mock implements PostgrestTransformBuilder<PostgrestMap> {}
```

Then wire method returns to the appropriate mock:
```dart
when(() => mockQueryBuilder.select(any()))
    .thenReturn(mockTransform); // was mockFilterBuilder
when(() => mockTransform.eq('id', any(named: 'value')))
    .thenReturn(mockTransform);
when(() => mockTransform.single())
    .thenAnswer((_) async => userJson);
```

## 8. Focus traversal API — `traversalOrder` removed from `Focus` (Flutter 3.41+)

**Error:** `The named parameter 'traversalOrder' isn't defined` and `The name 'OrdinalSortKey' isn't a class`

**Cause:** Flutter 3.41 removed the `traversalOrder` parameter from the `Focus` widget constructor. `OrdinalSortKey` was also removed from the Focus API (it still exists for `Semantics.sortKey` but not for focus ordering).

**Fix:** Use `FocusTraversalOrder(order: NumericFocusOrder(n))` wrapping `Focus` instead:

```dart
// ❌ Fails in Flutter 3.41+
Focus(
  traversalOrder: const OrdinalSortKey(1),
  child: AppPrimaryButton(text: 'First', onPressed: () {}),
)

// ✅ Works
FocusTraversalOrder(
  order: const NumericFocusOrder(1),
  child: Focus(
    child: AppPrimaryButton(text: 'First', onPressed: () {}),
  ),
)
```

> **Note:** `OrdinalSortKey` still exists in `package:flutter/src/semantics/semantics.dart` and is valid for `Semantics(sortKey: OrdinalSortKey(...))`. Only the Focus `traversalOrder` parameter is removed.

## 9. `PostgrestSelectFilterBuilder` class removed (postgrest 2.x)

**Error:** `Classes and mixins can only implement other classes and mixins` and `The method 'eq' isn't defined for the type 'MockPostgrestSelectFilterBuilder'`

**Cause:** `PostgrestSelectFilterBuilder` was removed in postgrest 2.x. The `select()` method now returns `PostgrestFilterBuilder<PostgrestList>` directly.

**Fix:** Change `MockPostgrestSelectFilterBuilder` to implement `PostgrestFilterBuilder<PostgrestList>`:

```dart
// ❌ Fails — class doesn't exist
class MockPostgrestSelectFilterBuilder extends Mock implements PostgrestSelectFilterBuilder {}

// ✅ Works — use FilterBuilder directly with PostgrestList
class MockPostgrestSelectFilterBuilder extends Mock implements PostgrestFilterBuilder<PostgrestList> {}
```

Then `eq()`, `single()`, etc. are already defined on `PostgrestFilterBuilder`, so mock wiring continues to work:

```dart
when(() => mockSelectFilterBuilder.eq('id', any(named: 'value')))
    .thenReturn(mockSelectFilterBuilder);
when(() => mockSelectFilterBuilder.single())
    .thenAnswer((_) async => userJson);
```

## 10. `integration_test` package unavailable in test environment

**Error:** `Target of URI doesn't exist: 'package:integration_test/integration_test.dart'` and `Undefined name 'IntegrationTestWidgetsFlutterBinding'`

**Cause:** The `integration_test` package is typically only available on device/emulator test runners and may not be in `dev_dependencies` in `pubspec.yaml`. It's not available in standard `flutter test` environments.

**Fix:** Remove the import and comment out the binding call. These tests are placeholder/spec files that only run on device:

```dart
// ❌ Fails
import 'package:integration_test/integration_test.dart';
// ...
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

// ✅ Works
// import removed
void main() {
  // IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  // Note: integration_test not in dev_dependencies — device-level E2E only
```

## 7. Missing Riverpod import

**Error:** `The function 'ProviderContainer' isn't defined`

**Cause:** Test file uses `ProviderContainer` but doesn't import `flutter_riverpod`.

**Fix:** Add the import:
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
```

## Diagnostic Workflow

When encountering test compilation errors after deps upgrade:

```bash
# 1. Analyze all unit test files
dart analyze test/unit/

# 2. Extract unique file paths from errors
dart analyze test/unit/ 2>&1 | grep "error - " | grep "test/unit/" | \
  sed 's/.*test\/unit\/\(.*\):[0-9]*:[0-9]* - .*/\1/' | sort -u

# 3. For each file, check which of the 7 patterns apply
dart analyze path/to/test.dart

# 4. Fix, then re-analyze
dart analyze path/to/test.dart | grep "error found"  # Should show 0
```

## Common Package Versions

| Package | Breaking Version | Key Change |
|---------|-----------------|------------|
| flutter_riverpod | 3.3.x | `ProviderContainer` still works, `valueOrNull` removed |
| riverpod | 3.2.x | `valueOrNull` removed |
| mocktail | 1.0.0 | `returnValue` param removed from `noSuchMethod` |
| gotrue | 2.x | `User` is sealed class |
| postgrest | 2.x | `select()` takes 1 param, `TransformBuilder` replaces `FilterBuilder` |

## Related Skills

- systematic-debugging — general debugging methodology
- flutter-sdk-wrapper-test-pattern — testing Flutter services
