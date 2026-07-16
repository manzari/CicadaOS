import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persistence for the Ed25519 private key *seed* (32 bytes, hex). The seed is
/// the only secret in the whole app; it must live in platform-encrypted secure
/// storage and never touch the DB, logs, exports, or shares (CLAUDE.md security model).
abstract class KeyStore {
  Future<String?> readSeedHex();
  Future<void> writeSeedHex(String seedHex);
  Future<void> delete();
}

/// Keychain (iOS) / EncryptedSharedPreferences (Android) backed store.
class SecureKeyStore implements KeyStore {
  static const _key = 'ed25519_seed_hex';
  final FlutterSecureStorage _storage;

  SecureKeyStore([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              // ThisDeviceOnly: the seed is excluded from transferable device
              // backups, so it can't be lifted from an iTunes/Finder backup and
              // restored onto another device.
              iOptions: IOSOptions(
                  accessibility: KeychainAccessibility.first_unlock_this_device),
            );

  @override
  Future<String?> readSeedHex() => _storage.read(key: _key);

  @override
  Future<void> writeSeedHex(String seedHex) =>
      _storage.write(key: _key, value: seedHex);

  @override
  Future<void> delete() => _storage.delete(key: _key);
}

/// In-memory store for unit tests (no platform channels).
class InMemoryKeyStore implements KeyStore {
  String? _seed;
  InMemoryKeyStore([this._seed]);

  @override
  Future<String?> readSeedHex() async => _seed;

  @override
  Future<void> writeSeedHex(String seedHex) async => _seed = seedHex;

  @override
  Future<void> delete() async => _seed = null;
}
