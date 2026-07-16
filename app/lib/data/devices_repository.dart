import 'package:drift/drift.dart';

import 'database.dart';

/// Known-ESP registry. Devices appear here when scanned and are enriched with a
/// per-device default script and pairing timestamps.
class DevicesRepository {
  final AppDatabase _db;
  DevicesRepository(this._db);

  Stream<List<Device>> watchAll() {
    final q = _db.select(_db.devices)
      ..orderBy([(t) => OrderingTerm(expression: t.lastSeen, mode: OrderingMode.desc)]);
    return q.watch();
  }

  Future<List<Device>> getAll() => _db.select(_db.devices).get();

  Future<Device?> getById(String id) =>
      (_db.select(_db.devices)..where((t) => t.id.equals(id))).getSingleOrNull();

  Stream<Device?> watchById(String id) =>
      (_db.select(_db.devices)..where((t) => t.id.equals(id))).watchSingleOrNull();

  /// Record a scan sighting, creating the row on first sight. Never clobbers a
  /// user-set name with null.
  Future<void> upsertSeen(String id, {String? name, DateTime? at}) async {
    final now = at ?? DateTime.now();
    await _db.into(_db.devices).insertOnConflictUpdate(
          DevicesCompanion(
            id: Value(id),
            name: name == null ? const Value.absent() : Value(name),
            lastSeen: Value(now),
          ),
        );
  }

  Future<void> rename(String id, String name) async {
    await (_db.update(_db.devices)..where((t) => t.id.equals(id)))
        .write(DevicesCompanion(name: Value(name)));
  }

  /// Pin the device's X25519 public key (64-hex) at provisioning. Scripts are
  /// encrypted to this key; a device without one cannot be pushed to.
  Future<void> pinKey(String id, String x25519PubKeyHex) async {
    await _db.into(_db.devices).insertOnConflictUpdate(
          DevicesCompanion(id: Value(id), x25519PubKey: Value(x25519PubKeyHex)),
        );
  }

  Future<void> markPaired(String id, {DateTime? at}) async {
    await (_db.update(_db.devices)..where((t) => t.id.equals(id)))
        .write(DevicesCompanion(lastPairedAt: Value(at ?? DateTime.now())));
  }

  /// Set (or clear, with null) the default script pushed on boot for this device.
  Future<void> setDefaultScript(String id, int? scriptId) async {
    await (_db.update(_db.devices)..where((t) => t.id.equals(id)))
        .write(DevicesCompanion(defaultScriptId: Value(scriptId)));
  }

  Future<void> delete(String id) async {
    await (_db.delete(_db.devices)..where((t) => t.id.equals(id))).go();
  }
}
