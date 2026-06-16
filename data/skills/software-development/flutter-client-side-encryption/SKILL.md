---
name: flutter-client-side-encryption
description: Implement AES-256-CBC client-side encryption in Flutter for DSGVO-compliant local storage (SharedPreferences). Key generation, random IV per encryption, backward compatibility, and integration with existing OfflineService patterns.
---

# Flutter Client-Side AES-256 Encryption (DSGVO)

## When to Use

- You need to encrypt locally cached/offline data in a Flutter app (SharedPreferences, Hive, etc.)
- DSGVO Art. 5(1)(f) requires "Integrität und Vertraulichkeit" for personal data at rest
- Backend already has encryption, but **client-side offline caches** (food logs, shopping lists, meal plans) are stored in plaintext
- Any Flutter app storing PII locally on device

## Architecture

```
SharedPreferences
├── local_encryption_key  (base64, 32 bytes = 44 chars) — generated once
├── offline_cache_food_log (iv_base64:cipher_base64) — AES-256-CBC
├── offline_cache_shopping_list (iv_base64:cipher_base64)
├── offline_cache_meal_plan (iv_base64:cipher_base64)
└── offline_cache_sync_queue (plain JSON — metadata only, no PII)
```

- **Key:** Random 256-bit (32 bytes), generated via `Key.fromSecureRandom(32)` on first app start, stored in SharedPreferences
- **IV:** Fresh random 128-bit (16 bytes) **per encryption operation** — never reuse
- **Storage format:** `IV_base64 + ':' + CIPHER_base64`
- **Cipher:** AES-256-CBC with PKCS7 padding

## Implementation Steps

### 1. Add dependency

```yaml
# pubspec.yaml
dependencies:
  encrypt: ^5.0.3   # AES-256 via PointyCastle
```

### 2. Create LocalEncryptionService

```dart
import 'dart:convert';
import 'package:encrypt/encrypt.dart' as encrypt;
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class LocalEncryptionService {
  static const String _prefsKeyStorageKey = 'local_encryption_key';
  static final LocalEncryptionService _instance = LocalEncryptionService._();
  static LocalEncryptionService get instance => _instance;
  LocalEncryptionService._();

  encrypt.Key? _key;
  bool _initialized = false;

  Future<void> init() async {
    if (_initialized) return;
    final prefs = await SharedPreferences.getInstance();

    // Load existing key or generate a new one
    final storedKey = prefs.getString(_prefsKeyStorageKey);
    if (storedKey != null && storedKey.length >= 44) {
      _key = encrypt.Key.fromBase64(storedKey);
    } else {
      _key = encrypt.Key.fromSecureRandom(32);
      await prefs.setString(_prefsKeyStorageKey, _key!.base64);
    }

    _initialized = true;
    debugPrint('LocalEncryptionService: AES-256-CBC initialized');
  }

  Future<String> encryptString(String plainText) async {
    if (plainText.isEmpty) return plainText;
    await _ensureInitialized();

    final iv = encrypt.IV.fromSecureRandom(16); // fresh IV each time!
    final encrypter = encrypt.Encrypter(
      encrypt.AES(_key!, mode: encrypt.AESMode.cbc),
    );
    final encrypted = encrypter.encrypt(plainText, iv: iv);
    return '${iv.base64}:${encrypted.base64}';
  }

  Future<String> decryptString(String cipherText) async {
    if (cipherText.isEmpty || !cipherText.contains(':')) return cipherText;
    await _ensureInitialized();

    try {
      final parts = cipherText.split(':');
      if (parts.length != 2) return cipherText;

      final iv = encrypt.IV.fromBase64(parts[0]);
      final encrypted = encrypt.Encrypted.fromBase64(parts[1]);
      final encrypter = encrypt.Encrypter(
        encrypt.AES(_key!, mode: encrypt.AESMode.cbc),
      );
      return encrypter.decrypt(encrypted, iv: iv);
    } catch (e) {
      debugPrint('LocalEncryptionService: decryption failed: $e');
      return cipherText; // fallback for legacy plaintext data
    }
  }

  Future<String> encryptJsonList(List<Map<String, dynamic>> list) async {
    return encryptString(jsonEncode(list));
  }

  Future<List<Map<String, dynamic>>?> decryptToJsonList(String cipherText) async {
    final decrypted = await decryptString(cipherText);
    try {
      final data = jsonDecode(decrypted);
      if (data is List) return data.cast<Map<String, dynamic>>();
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<void> _ensureInitialized() async {
    if (!_initialized) await init();
    if (_key == null) throw StateError('Not initialized');
  }
}
```

### 3. Integrate with OfflineService

In your offline caching service:

```dart
// Inside OfflineService.init():
await LocalEncryptionService.instance.init();

// Cache with encryption:
Future<void> cacheFoodLog(List<FoodLogEntry> entries) async {
  final prefs = await SharedPreferences.getInstance();
  final encrypted = await LocalEncryptionService.instance.encryptJsonList(
    entries.map((e) => e.toJson()).toList(),
  );
  await prefs.setString('offline_cache_food_log', encrypted);
}

// Read with decryption (with graceful fallback):
Future<List<FoodLogEntry>> getCachedFoodLog() async {
  final prefs = await SharedPreferences.getInstance();
  final encrypted = prefs.getString('offline_cache_food_log');
  if (encrypted == null || encrypted.isEmpty) return [];

  final list = await LocalEncryptionService.instance.decryptToJsonList(encrypted);
  if (list == null) return [];

  return list.map((e) => FoodLogEntry.fromJson(e)).toList();
}
```

## Key Design Decisions

| Decision | Why |
|---|---|
| **Random key per installation** | Key changes on reinstall → old data unrecoverable (acceptable for cache) |
| **Key in SharedPreferences** | Not 100% secure (rooted devices), but prevents casual access. For higher security, use `flutter_secure_storage` for key storage |
| **IV prepended to ciphertext** | No separate IV storage needed; self-contained encrypted payload |
| **Fallback on decrypt failure** | Allows legacy plaintext data to still be read after upgrade (abwärtskompatibel) |
| **Sync queue unencrypted** | Only contains action metadata (type, timestamp), no PII — no encryption overhead |

## Pitfalls

- **DO NOT use the same IV for multiple encryptions** — AES-CBC leaks patterns. Always use `IV.fromSecureRandom(16)` fresh each time.
- **Key loss = data loss** — if `SharedPreferences` is cleared or app data wiped, cached encrypted data is unrecoverable.
- **Thread safety** — the service is a singleton; calls from different isolates could race. Use a mutex if needed.
- **Legacy data** — if upgrading from plaintext storage, the `decryptString` fallback (`return cipherText` on failure) handles it gracefully.
- **`encrypt` package** uses PointyCastle internally — no extra native dependencies needed for AES.
- For production apps on rooted/jailbroken devices, consider `flutter_secure_storage` + Android Keystore/iOS Keychain for the encryption key.
