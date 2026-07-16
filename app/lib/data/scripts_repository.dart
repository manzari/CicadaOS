import 'package:drift/drift.dart';

import 'database.dart';
import 'script_body_cipher.dart';

/// CRUD for the local script library. When a [ScriptBodyCipher] is provided,
/// bodies of scripts flagged `isSecret` are encrypted at rest: the SQLite
/// file holds ciphertext, while every value returned here is decrypted plaintext.
class ScriptsRepository {
  final AppDatabase _db;
  final ScriptBodyCipher? cipher;
  ScriptsRepository(this._db, {this.cipher});

  Stream<List<Script>> watchAll() {
    final q = _db.select(_db.scripts)
      ..orderBy([(t) => OrderingTerm(expression: t.modifiedAt, mode: OrderingMode.desc)]);
    return q.watch().asyncMap(_decodeAll);
  }

  Future<List<Script>> getAll() async {
    final q = _db.select(_db.scripts)
      ..orderBy([(t) => OrderingTerm(expression: t.modifiedAt, mode: OrderingMode.desc)]);
    return _decodeAll(await q.get());
  }

  Future<Script?> getById(int id) async {
    final s = await (_db.select(_db.scripts)..where((t) => t.id.equals(id)))
        .getSingleOrNull();
    return s == null ? null : _decode(s);
  }

  Future<List<Script>> search(String query) async {
    if (query.trim().isEmpty) return getAll();
    final like = '%${query.trim()}%';
    // Secret bodies are ciphertext on disk, so a body LIKE can only match
    // plaintext (non-secret) bodies; names always match.
    final q = _db.select(_db.scripts)
      ..where((t) => t.name.like(like) | t.body.like(like))
      ..orderBy([(t) => OrderingTerm(expression: t.modifiedAt, mode: OrderingMode.desc)]);
    return _decodeAll(await q.get());
  }

  Future<Script> create(
      {required String name, required String body, bool isSecret = false, DateTime? at}) async {
    final now = at ?? DateTime.now();
    final id = await _db.into(_db.scripts).insert(ScriptsCompanion.insert(
          name: name,
          body: await _encodeBody(body, isSecret),
          isSecret: Value(isSecret),
          createdAt: now,
          modifiedAt: now,
        ));
    return (await getById(id))!;
  }

  /// Update name and/or body, bumping modifiedAt. Preserves the secrecy flag,
  /// re-encrypting a new body when the script is secret.
  Future<void> updateScript(int id, {String? name, String? body, DateTime? at}) async {
    String? storedBody;
    if (body != null) {
      final current = await (_db.select(_db.scripts)..where((t) => t.id.equals(id)))
          .getSingleOrNull();
      storedBody = await _encodeBody(body, current?.isSecret ?? false);
    }
    await (_db.update(_db.scripts)..where((t) => t.id.equals(id))).write(
      ScriptsCompanion(
        name: name == null ? const Value.absent() : Value(name),
        body: storedBody == null ? const Value.absent() : Value(storedBody),
        modifiedAt: Value(at ?? DateTime.now()),
      ),
    );
  }

  /// Flip the secret flag, re-encoding the stored body to match.
  Future<void> setSecret(int id, bool secret) async {
    final s = await getById(id); // decoded plaintext
    if (s == null) return;
    await (_db.update(_db.scripts)..where((t) => t.id.equals(id))).write(
      ScriptsCompanion(
        isSecret: Value(secret),
        body: Value(await _encodeBody(s.body, secret)),
      ),
    );
  }

  Future<Script> duplicate(int id, {DateTime? at}) async {
    final src = await getById(id); // decoded plaintext
    if (src == null) throw StateError('script $id not found');
    return create(name: _copyName(src.name), body: src.body, isSecret: src.isSecret, at: at);
  }

  Future<void> delete(int id) async {
    await (_db.delete(_db.scripts)..where((t) => t.id.equals(id))).go();
  }

  Future<String> _encodeBody(String body, bool isSecret) async {
    if (isSecret && cipher != null) return cipher!.encode(body);
    return body;
  }

  Future<Script> _decode(Script s) async {
    if (cipher != null && s.isSecret && cipher!.isEncrypted(s.body)) {
      return s.copyWith(body: await cipher!.decode(s.body));
    }
    return s;
  }

  Future<List<Script>> _decodeAll(List<Script> rows) async {
    return [for (final s in rows) await _decode(s)];
  }

  static String _copyName(String name) {
    final m = RegExp(r'^(.*) copy( (\d+))?$').firstMatch(name);
    if (m == null) return '$name copy';
    final n = m.group(3) == null ? 2 : int.parse(m.group(3)!) + 1;
    return '${m.group(1)} copy $n';
  }
}
