import 'package:drift/drift.dart';

import 'database.dart';

/// Key-value app settings. Small, typed accessors over the Settings table.
class SettingsRepository {
  static const kBootWatchEnabled = 'bootWatchEnabled';
  static const kExamplesSeeded = 'examplesSeeded';

  final AppDatabase _db;
  SettingsRepository(this._db);

  Future<String?> getString(String key) async {
    final row = await (_db.select(_db.settings)..where((t) => t.key.equals(key)))
        .getSingleOrNull();
    return row?.value;
  }

  Future<void> setString(String key, String value) async {
    await _db.into(_db.settings).insertOnConflictUpdate(
          SettingsCompanion(key: Value(key), value: Value(value)),
        );
  }

  Future<bool> getBool(String key, {bool defaultValue = false}) async {
    final v = await getString(key);
    if (v == null) return defaultValue;
    return v == '1' || v.toLowerCase() == 'true';
  }

  Future<void> setBool(String key, bool value) =>
      setString(key, value ? '1' : '0');

  Stream<bool> watchBool(String key, {bool defaultValue = false}) {
    return (_db.select(_db.settings)..where((t) => t.key.equals(key)))
        .watchSingleOrNull()
        .map((row) => row == null ? defaultValue : (row.value == '1' || row.value.toLowerCase() == 'true'));
  }
}
