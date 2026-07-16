import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Encrypts secret script bodies at rest. The on-disk `body` column of a
/// secret script holds `enc:v1:<base64(nonce(12) || ciphertext || mac(16))>`
/// (AES-256-GCM); the key lives in platform secure storage, never in the DB.
///
/// [ScriptsRepository] applies this transparently, so the rest of the app still
/// sees plaintext bodies while nothing readable persists to the SQLite file.
class ScriptBodyCipher {
  static const marker = 'enc:v1:';
  static const _nonceLen = 12;
  static const _macLen = 16;

  final Future<List<int>> Function() _key;
  final AesGcm _algo = AesGcm.with256bits();

  ScriptBodyCipher(this._key);

  /// Backed by [FlutterSecureStorage]: generate-once a random 256-bit key.
  factory ScriptBodyCipher.secureStorage([FlutterSecureStorage? storage]) {
    final store = storage ??
        const FlutterSecureStorage(
          iOptions: IOSOptions(
              accessibility: KeychainAccessibility.first_unlock_this_device),
        );
    const keyName = 'script_db_key_hex';
    return ScriptBodyCipher(() async {
      var hex = await store.read(key: keyName);
      if (hex == null) {
        final rng = Random.secure();
        final bytes = List<int>.generate(32, (_) => rng.nextInt(256));
        hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
        await store.write(key: keyName, value: hex);
      }
      final h = hex;
      return List<int>.generate(
          h.length ~/ 2, (i) => int.parse(h.substring(i * 2, i * 2 + 2), radix: 16));
    });
  }

  bool isEncrypted(String stored) => stored.startsWith(marker);

  Future<String> encode(String plaintext) async {
    final key = await _key();
    final nonce = _algo.newNonce();
    final box = await _algo.encrypt(
      utf8.encode(plaintext),
      secretKey: SecretKey(key),
      nonce: nonce,
    );
    final blob = Uint8List.fromList([...box.nonce, ...box.cipherText, ...box.mac.bytes]);
    return marker + base64Encode(blob);
  }

  Future<String> decode(String stored) async {
    if (!isEncrypted(stored)) return stored;
    final blob = base64Decode(stored.substring(marker.length));
    final nonce = blob.sublist(0, _nonceLen);
    final mac = blob.sublist(blob.length - _macLen);
    final ct = blob.sublist(_nonceLen, blob.length - _macLen);
    final key = await _key();
    final clear = await _algo.decrypt(
      SecretBox(ct, nonce: nonce, mac: Mac(mac)),
      secretKey: SecretKey(key),
    );
    return utf8.decode(clear);
  }
}
