import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../protocol.dart';
import 'signer.dart';

/// Builds a v2 (encrypted) frame: encrypt the script TO the device's pinned
/// X25519 key, then sign the encrypted blob with the app's Ed25519 key.
///
///   shared     = X25519(ephemeral_priv, device_pub)
///   key        = BLAKE2b-512(shared || eph_pub || device_pub)[:32]
///   ct, mac    = XChaCha20-Poly1305(key, aead_nonce, aad=v2Header, script)
///   sig        = Ed25519(v2SignedMessage)
///
/// A passive sniffer sees only ciphertext, and a rogue peripheral without the
/// device private key cannot decrypt it. The primitives are the IETF
/// XChaCha20-Poly1305 / X25519 / BLAKE2b that firmware/cryptobox.py and vendored
/// Monocypher implement, so the four sides agree byte-for-byte (proved by the
/// shared vectors).
class ScriptSealer {
  final Signer signer;
  final X25519 _x = X25519();
  final Xchacha20 _aead = Xchacha20.poly1305Aead();
  final Blake2b _blake = Blake2b();
  final Random _rng;

  ScriptSealer(this.signer, {Random? rng}) : _rng = rng ?? Random.secure();

  /// AEAD key = BLAKE2b-512(shared || eph_pub || device_pub) truncated to 32 B.
  Future<Uint8List> _kdf(List<int> shared, List<int> ephPub, List<int> devPub) async {
    final h = await _blake.hash([...shared, ...ephPub, ...devPub]);
    return Uint8List.fromList(h.bytes.sublist(0, 32));
  }

  Uint8List _randomBytes(int n) =>
      Uint8List.fromList(List<int>.generate(n, (_) => _rng.nextInt(256)));

  /// Seal + sign a script into a length-prefixed frame ready to write to RX.
  /// [ephemeral] and [aeadNonce] are injectable so tests can pin the output;
  /// production passes neither (a fresh ephemeral keypair + random nonce/push).
  Future<Uint8List> seal(
    Uint8List script,
    Uint8List nonce,
    Uint8List devicePubKey, {
    SimpleKeyPair? ephemeral,
    Uint8List? aeadNonce,
  }) async {
    if (devicePubKey.length != Protocol.ephPubLength) {
      throw ArgumentError('device X25519 key must be ${Protocol.ephPubLength} bytes');
    }
    ephemeral ??= await _x.newKeyPair();
    final ephPub = Uint8List.fromList((await ephemeral.extractPublicKey()).bytes);
    final sharedKey = await _x.sharedSecretKey(
      keyPair: ephemeral,
      remotePublicKey: SimplePublicKey(devicePubKey, type: KeyPairType.x25519),
    );
    final shared = await sharedKey.extractBytes();
    final key = await _kdf(shared, ephPub, devicePubKey);

    final an = aeadNonce ?? _randomBytes(Protocol.aeadNonceLength);
    if (an.length != Protocol.aeadNonceLength) {
      throw ArgumentError('aead_nonce must be ${Protocol.aeadNonceLength} bytes');
    }
    final header = Protocol.v2Header(nonce, script.length);
    final box = await _aead.encrypt(
      script,
      secretKey: SecretKey(key),
      nonce: an,
      aad: header,
    );
    final ct = Uint8List.fromList(box.cipherText);
    final mac = Uint8List.fromList(box.mac.bytes);

    final signed = Protocol.v2SignedMessage(header, ephPub, an, ct, mac);
    final sig = await signer.signMsg(signed);
    return Protocol.v2Frame(ephPub, an, ct, mac, sig);
  }
}
