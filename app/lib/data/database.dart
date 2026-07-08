import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

part 'database.g.dart';

/// MicroPython scripts. Bodies live in the DB (≤16 KB by protocol). A body
/// flagged [isSecret] is stored encrypted at rest (Fix 6): the on-disk column
/// holds ciphertext, and [ScriptsRepository] transparently decrypts on read.
class Scripts extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get name => text().withLength(min: 1, max: 128)();
  TextColumn get body => text()();
  BoolColumn get isSecret => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get modifiedAt => dateTime()();
}

/// Known ESPs. `id` is the 6-byte manufacturer identity as hex (stable across
/// phones and reboots, unlike an iOS peripheral UUID). Deleting a script nulls
/// any device that pointed at it as its default (onDelete: setNull).
class Devices extends Table {
  TextColumn get id => text()(); // 12-hex device id
  TextColumn get name => text().nullable()();
  // Pinned X25519 public key (64-hex), stored at provisioning. Scripts are
  // encrypted to it (Fix 3); a device with no pinned key cannot be pushed to.
  TextColumn get x25519PubKey => text().nullable()();
  DateTimeColumn get lastSeen => dateTime().nullable()();
  DateTimeColumn get lastPairedAt => dateTime().nullable()();
  IntColumn get defaultScriptId =>
      integer().nullable().references(Scripts, #id, onDelete: KeyAction.setNull)();

  @override
  Set<Column> get primaryKey => {id};
}

/// Simple key-value settings (e.g. bootWatchEnabled).
class Settings extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {key};
}

@DriftDatabase(tables: [Scripts, Devices, Settings])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  /// In-memory database for unit tests.
  AppDatabase.forTesting(super.e);

  @override
  int get schemaVersion => 2;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (m) => m.createAll(),
        onUpgrade: (m, from, to) async {
          if (from < 2) {
            // v2: encrypt-to-device-key (pinned key) + secret-body-at-rest.
            await m.addColumn(devices, devices.x25519PubKey);
            await m.addColumn(scripts, scripts.isSecret);
          }
        },
        beforeOpen: (details) async {
          // Required for the Devices.defaultScriptId setNull cascade to fire.
          await customStatement('PRAGMA foreign_keys = ON');
        },
      );
}

LazyDatabase _openConnection() {
  return LazyDatabase(() async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(dir.path, 'cicadaos.sqlite'));
    return NativeDatabase.createInBackground(file);
  });
}
