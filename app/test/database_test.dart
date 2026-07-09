import 'package:cicadaos/data/database.dart';
import 'package:cicadaos/data/devices_repository.dart';
import 'package:cicadaos/data/script_body_cipher.dart';
import 'package:cicadaos/data/scripts_repository.dart';
import 'package:cicadaos/data/settings_repository.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late AppDatabase db;
  late ScriptsRepository scripts;
  late DevicesRepository devices;
  late SettingsRepository settings;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    // Foreign keys must be on for the setNull cascade (beforeOpen runs lazily).
    await db.customStatement('PRAGMA foreign_keys = ON');
    scripts = ScriptsRepository(db);
    devices = DevicesRepository(db);
    settings = SettingsRepository(db);
  });

  tearDown(() => db.close());

  group('scripts CRUD', () {
    test('create/read/update/delete', () async {
      final s = await scripts.create(name: 'blink', body: "notify('hi')");
      expect(s.name, 'blink');
      expect((await scripts.getById(s.id))!.body, "notify('hi')");

      await scripts.updateScript(s.id, body: "notify('bye')");
      expect((await scripts.getById(s.id))!.body, "notify('bye')");

      await scripts.delete(s.id);
      expect(await scripts.getById(s.id), isNull);
    });

    test('search matches name and body', () async {
      await scripts.create(name: 'temperature', body: 'x = 1');
      await scripts.create(name: 'blink', body: 'led.toggle()');
      expect((await scripts.search('temp')).map((e) => e.name), ['temperature']);
      expect((await scripts.search('toggle')).map((e) => e.name), ['blink']);
      expect((await scripts.search('')).length, 2);
    });

    test('duplicate produces an incrementing "copy" name', () async {
      final a = await scripts.create(name: 'blink', body: 'b');
      final c1 = await scripts.duplicate(a.id);
      expect(c1.name, 'blink copy');
      final c2 = await scripts.duplicate(c1.id);
      expect(c2.name, 'blink copy 2');
    });
  });

  group('secret scripts encrypted at rest (Fix 6)', () {
    // Fixed 32-byte key so the test is deterministic (prod uses secure storage).
    ScriptsRepository secretRepo() =>
        ScriptsRepository(db, cipher: ScriptBodyCipher(() async => List<int>.filled(32, 7)));

    Future<String> rawBody(int id) async {
      final row = await (db.select(db.scripts)..where((t) => t.id.equals(id)))
          .getSingle();
      return row.body;
    }

    test('secret body is ciphertext on disk but plaintext via the repo', () async {
      final repo = secretRepo();
      const secret = "API_KEY = 'sk-super-secret-value'";
      final s = await repo.create(name: 'keys', body: secret, isSecret: true);

      final onDisk = await rawBody(s.id);
      expect(onDisk.startsWith(ScriptBodyCipher.marker), isTrue);
      expect(onDisk.contains('sk-super-secret'), isFalse,
          reason: 'the secret must not be readable in the SQLite file');

      expect(s.body, secret, reason: 'create() returns decrypted plaintext');
      expect((await repo.getById(s.id))!.body, secret);
      expect((await repo.getAll()).single.body, secret);
    });

    test('non-secret bodies stay plaintext', () async {
      final repo = secretRepo();
      final s = await repo.create(name: 'plain', body: 'x = 1');
      expect(await rawBody(s.id), 'x = 1');
    });

    test('setSecret encrypts an existing body; toggling back decrypts', () async {
      final repo = secretRepo();
      final s = await repo.create(name: 'k', body: 'TOKEN=abc');
      await repo.setSecret(s.id, true);
      expect((await rawBody(s.id)).contains('TOKEN=abc'), isFalse);
      expect((await repo.getById(s.id))!.body, 'TOKEN=abc');
      await repo.setSecret(s.id, false);
      expect(await rawBody(s.id), 'TOKEN=abc');
    });

    test('updating a secret body re-encrypts it', () async {
      final repo = secretRepo();
      final s = await repo.create(name: 'k', body: 'v1', isSecret: true);
      await repo.updateScript(s.id, body: 'v2-secret');
      expect((await rawBody(s.id)).contains('v2-secret'), isFalse);
      expect((await repo.getById(s.id))!.body, 'v2-secret');
    });
  });

  group('devices', () {
    test('upsertSeen inserts then updates without clobbering name', () async {
      await devices.upsertSeen('a1b2c3d4e5f6', name: 'Front wheel');
      await devices.upsertSeen('a1b2c3d4e5f6'); // later sighting, no name
      final d = await devices.getById('a1b2c3d4e5f6');
      expect(d!.name, 'Front wheel');
    });

    test('setDefaultScript stores the FK and pairing timestamp', () async {
      final s = await scripts.create(name: 'blink', body: 'b');
      await devices.upsertSeen('aa', name: 'esp');
      await devices.setDefaultScript('aa', s.id);
      await devices.markPaired('aa');
      final d = await devices.getById('aa');
      expect(d!.defaultScriptId, s.id);
      expect(d.lastPairedAt, isNotNull);
    });
  });

  test('deleting a script nulls any device default referencing it', () async {
    final s = await scripts.create(name: 'blink', body: 'b');
    await devices.upsertSeen('aa', name: 'esp');
    await devices.setDefaultScript('aa', s.id);
    expect((await devices.getById('aa'))!.defaultScriptId, s.id);

    await scripts.delete(s.id);

    expect((await devices.getById('aa'))!.defaultScriptId, isNull,
        reason: 'onDelete setNull must clear the dangling default');
  });

  group('settings KV', () {
    test('bool round-trips with default', () async {
      expect(await settings.getBool(SettingsRepository.kBootWatchEnabled), isFalse);
      await settings.setBool(SettingsRepository.kBootWatchEnabled, true);
      expect(await settings.getBool(SettingsRepository.kBootWatchEnabled), isTrue);
    });
  });
}
