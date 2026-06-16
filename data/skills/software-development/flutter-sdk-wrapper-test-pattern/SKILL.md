---
name: flutter-sdk-wrapper-test-pattern
description: Pattern for testing Flutter services that wrap native SDKs with static methods — create an injectable wrapper interface, refactor to dependency injection, and test with mocktail.
version: 1.0.0
author: Hermes Agent
metadata:
  hermes:
    tags: [flutter, testing, mocktail, dependency-injection, native-sdk, testability]
    related_skills: [test-driven-development, systematic-debugging]
---

# Flutter SDK Wrapper Test Pattern

## Problem

You have a Dart service class that calls static methods on a native Flutter SDK:

```dart
class RevenueCatService {
  Future<PremiumEntitlement> getPremiumStatus() async {
    final info = await Purchases.getCustomerInfo(); // Static call ❌
    return _extractEntitlement(info);
  }
}
```

**This is untestable.** You cannot mock static methods. The test would need:
- A real device (native SDKs crash on `dart test`)
- A real RevenueCat API key
- A real Apple/Google account

## Solution: Wrapper Interface + Constructor Injection

### Step 1: Define an abstract wrapper

Create a new file alongside the service, e.g. `purchases_wrapper.dart`:

```dart
import 'dart:async';
import 'package:purchases_flutter/purchases_flutter.dart';

abstract class PurchasesWrapper {
  void configure(PurchasesConfiguration configuration);
  Future<CustomerInfo> getCustomerInfo();
  Future<Offerings> getOfferings();
  Future<CustomerInfo> purchasePackage(Package package);
  Future<CustomerInfo> restorePurchases();
  Future<void> logOut();
  Future<void> logIn(String appUserId);
  StreamSubscription<CustomerInfo> addCustomerInfoUpdateListener(
    void Function(CustomerInfo) listener,
  );
}
```

### Step 2: Create a production implementation

In the same file:

```dart
class DefaultPurchasesWrapper implements PurchasesWrapper {
  @override
  void configure(PurchasesConfiguration configuration) {
    Purchases.configure(configuration);
  }

  @override
  Future<CustomerInfo> getCustomerInfo() => Purchases.getCustomerInfo();

  @override
  Future<Offerings> getOfferings() => Purchases.getOfferings();

  // ... etc for all methods
}
```

### Step 3: Refactor the service to accept the wrapper

```dart
class RevenueCatService {
  final PurchasesWrapper _purchases;

  // Default to production wrapper, accept custom for testing
  RevenueCatService({PurchasesWrapper? purchases})
      : _purchases = purchases ?? DefaultPurchasesWrapper();

  // Now all calls go through _purchases instead of static Purchases
  Future<PremiumEntitlement> getPremiumStatus() async {
    final info = await _purchases.getCustomerInfo(); // Mockable ✅
    return _extractEntitlement(info);
  }
}
```

### Step 4: Test with Mocktail

```dart
class MockPurchasesWrapper extends Mock implements PurchasesWrapper {}

void main() {
  late MockPurchasesWrapper mockPurchases;
  late RevenueCatService service;

  setUp(() {
    mockPurchases = MockPurchasesWrapper();
    service = RevenueCatService(purchases: mockPurchases);
  });

  group('getPremiumStatus', () {
    test('returns active entitlement when premium is active', () async {
      when(() => mockPurchases.getCustomerInfo())
          .thenAnswer((_) async => mockCustomerInfo);
      
      final result = await service.getPremiumStatus();

      expect(result.isActive, isTrue);
      verify(() => mockPurchases.getCustomerInfo()).called(1);
    });

    test('handles error gracefully', () async {
      when(() => mockPurchases.getCustomerInfo())
          .thenThrow(Exception('Network error'));
      
      // Service should catch and return fallback, not propagate
      final result = await service.getPremiumStatus();
      expect(result.isActive, isFalse);
    });
  });
}
```

## Key Considerations

### 1. Keep the wrapper minimal
- Only wrap methods the service actually uses
- Don't expose the full SDK API — you'll maintain less
- Rename methods if the SDK names are awkward

### 2. Handle callback/listener types
If the SDK has listener registration, return a `StreamSubscription`:

```dart
StreamSubscription<CustomerInfo> addCustomerInfoUpdateListener(
  void Function(CustomerInfo) listener,
);
```

Test with:
```dart
class MockStreamSubscription<T> extends Mock implements StreamSubscription<T> {}

when(() => mockPurchases.addCustomerInfoUpdateListener(any()))
    .thenAnswer((_) => MockStreamSubscription<CustomerInfo>());
```

### 3. Constructor or setter injection
- **Constructor injection** (preferred): `RevenueCatService({PurchasesWrapper? purchases})` 
- The default parameter means production code doesn't change

### 4. Export the wrapper from the barrel file
```dart
// In the module's barrel file (e.g., premium.dart):
export 'data/services/purchases_wrapper.dart';
```

This makes imports cleaner in tests:
```dart
import 'package:myapp/features/premium/premium.dart';
// instead of deep imports
```

### 5. `PurchasesError` is real — use it directly
When testing error paths for `PurchasesError` (not a mocked exception), instantiate it directly:

```dart
final error = PurchasesError(
  code: PurchasesErrorCode.networkError,
  message: 'Network issue',
  userCancelled: false,
  underlyingErrorMessage: '',
);
when(() => mockPurchases.purchasePackage(any())).thenThrow(error);
```

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Forgetting `registerFallbackValue` for matchers | Use `any()` or register in `setUp` |
| `StreamSubscription` has too many methods | Use `Mock implements StreamSubscription<T>` with `noSuchMethod` fallback or explicit mock |
| Wrapper too large | Only wrap what the service uses. Resist "wrap everything" temptation |
| `thenReturn` vs `thenAnswer` confusion | Use `thenAnswer` for `Future` returning methods; `thenReturn` for sync |
| Mocking `Package` type for `purchasePackage` | Use `any()` matcher and verify the wrapper was called, or use `captureAny` |
| Wrapper becomes a maintenance burden | Update when adding SDK features — one change per new feature is fine |

## When to Use This Pattern

- **Always** when wrapping a native Flutter SDK with static methods
- When the SDK has no built-in test/mock support
- When you need to test error paths (network failure, purchase cancellation)
- When your CI runs `dart test` without a device/emulator

## When NOT to Use

- Simple value objects / data models — test directly
- SDKs that already provide mock support
- Code that only runs in production and never needs unit tests
