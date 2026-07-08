import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../hex.dart';
import 'key_store.dart';

/// Owns the app's single Ed25519 identity: generate-once, persist the seed in
/// [KeyStore], expose the raw public key for firmware provisioning, and sign the
/// protocol `msg`. Signatures are raw 64-byte R||S — never DER (CLAUDE.md wire protocol).
///
/// The private key never leaves this class: there is no getter for the seed
/// beyond what [KeyStore] holds, and nothing here logs or exports it.
class Signer {
  final KeyStore _store;
  final Ed25519 _algo = Ed25519();
  KeyPair? _cached;

  Signer(this._store);

  Future<bool> hasKey() async => (await _store.readSeedHex()) != null;

  /// Ensure a keypair exists, generating and persisting one on first use.
  Future<void> ensureKey() async => _keyPair();

  /// Drop the identity entirely (e.g. user re-provisions). The old public key
  /// stops verifying against any firmware still holding it.
  Future<void> reset() async {
    await _store.delete();
    _cached = null;
  }

  Future<KeyPair> _keyPair() async {
    if (_cached != null) return _cached!;
    var seedHex = await _store.readSeedHex();
    if (seedHex == null) {
      final fresh = await _algo.newKeyPair();
      final seed = await fresh.extractPrivateKeyBytes();
      seedHex = hexEncode(seed);
      await _store.writeSeedHex(seedHex);
    }
    _cached = await _algo.newKeyPairFromSeed(hexDecode(seedHex));
    return _cached!;
  }

  /// Raw 32-byte public key (the encoded point A) for firmware `PUBKEY`.
  Future<Uint8List> publicKey() async {
    final pk = await (await _keyPair()).extractPublicKey() as SimplePublicKey;
    return Uint8List.fromList(pk.bytes);
  }

  Future<String> publicKeyHex() async => hexEncode(await publicKey());

  /// Sign an already-built protocol message. Returns raw 64-byte R||S. The v2
  /// message is assembled by [ScriptSealer] (over the encrypted blob).
  Future<Uint8List> signMsg(Uint8List msg) async {
    final sig = await _algo.sign(msg, keyPair: await _keyPair());
    return Uint8List.fromList(sig.bytes);
  }
}
