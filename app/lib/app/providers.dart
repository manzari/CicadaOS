import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/crypto/key_store.dart';
import '../core/crypto/signer.dart';
import '../data/database.dart';
import '../data/devices_repository.dart';
import '../data/examples_seeder.dart';
import '../data/script_body_cipher.dart';
import '../data/scripts_repository.dart';
import '../data/settings_repository.dart';

/// Single app database, closed with the ProviderScope.
final databaseProvider = Provider<AppDatabase>((ref) {
  final db = AppDatabase();
  ref.onDispose(db.close);
  return db;
});

final scriptsRepoProvider = Provider<ScriptsRepository>((ref) => ScriptsRepository(
      ref.watch(databaseProvider),
      cipher: ScriptBodyCipher.secureStorage(),
    ));

final devicesRepoProvider = Provider<DevicesRepository>(
    (ref) => DevicesRepository(ref.watch(databaseProvider)));

final settingsRepoProvider = Provider<SettingsRepository>(
    (ref) => SettingsRepository(ref.watch(databaseProvider)));

final examplesSeederProvider = Provider<ExamplesSeeder>((ref) => ExamplesSeeder(
      ref.watch(scriptsRepoProvider),
      ref.watch(settingsRepoProvider),
    ));

/// The app's Ed25519 identity, backed by platform secure storage.
final signerProvider = Provider<Signer>((ref) => Signer(SecureKeyStore()));

final scriptsStreamProvider = StreamProvider(
    (ref) => ref.watch(scriptsRepoProvider).watchAll());

final devicesStreamProvider = StreamProvider(
    (ref) => ref.watch(devicesRepoProvider).watchAll());

final publicKeyHexProvider = FutureProvider<String>(
    (ref) => ref.watch(signerProvider).publicKeyHex());
