import 'dart:convert';
import 'dart:typed_data';

/// BLE wire-protocol constants and v2 (encrypted) frame builders.
///
/// This mirrors the CLAUDE.md wire protocol byte-for-byte. The signed message
/// and AAD layout is the "classic ERR:sig failure point" (CLAUDE.md
/// byte-agreement contract): DOMAIN as ASCII, exactly one version byte, the 32
/// nonce bytes as read, ciphertext length as 4-byte big-endian. The shared test
/// vectors in `tools_vectors/vectors.json` prove byte-agreement with the
/// firmware — never change this encoding without regenerating them.
class Protocol {
  Protocol._();

  // Nordic UART Service + one extra characteristic (128-bit UUIDs, CLAUDE.md wire protocol).
  static const String serviceUuid = '6E400001-B5A3-F393-E0A9-E50E24DCCA9E';
  static const String rxUuid = '6E400002-B5A3-F393-E0A9-E50E24DCCA9E'; // phone -> ESP
  static const String txUuid = '6E400003-B5A3-F393-E0A9-E50E24DCCA9E'; // ESP -> phone notify
  static const String nonceUuid = '6E400004-B5A3-F393-E0A9-E50E24DCCA9E'; // read

  /// Domain-separation tag, ASCII. Must equal the firmware DOMAIN exactly.
  static final Uint8List domain =
      Uint8List.fromList(ascii.encode('espscript-v1'));
  static const int version = 0x02; // protocol v2 (encrypt-to-device-key)

  static const int nonceLength = 32;
  static const int ephPubLength = 32;
  static const int aeadNonceLength = 24;
  static const int macLength = 16;
  static const int sigLength = 64;

  /// Per-frame overhead: eph_pub(32) + aead_nonce(24) + mac(16) + sig(64).
  static const int v2Overhead = ephPubLength + aeadNonceLength + macLength + sigLength;

  /// Max plaintext script length (ciphertext == plaintext length for a stream
  /// cipher). Bodies also live in the DB, which caps at the same size.
  static const int maxScript = 16384;

  // Manufacturer AD (CLAUDE.md (advertising: manufacturer AD)): company 0xFFFF, magic 0xC1 0xCA, then a
  // flags byte and 6 identity bytes. flutter_blue_plus keys manufacturerData by
  // the company id, so the value payload starts at the magic.
  static const int mfrCompanyId = 0xFFFF;
  static const List<int> mfrMagic = [0xC1, 0xCA];
  static const int mfrFlagAwaiting = 0x01;
  static const int mfrPayloadLength = 9; // magic(2) + flags(1) + id(6)
  static const int deviceIdLength = 6;

  /// AAD + signed-message prefix: `DOMAIN || 0x02 || nonce(32) || len(ct) BE4`.
  /// The device reconstructs this from its own nonce, so it must match exactly.
  static Uint8List v2Header(Uint8List nonce, int ciphertextLength) {
    if (nonce.length != nonceLength) {
      throw ArgumentError('nonce must be $nonceLength bytes, got ${nonce.length}');
    }
    final b = BytesBuilder();
    b.add(domain);
    b.addByte(version);
    b.add(nonce);
    b.add(_be4(ciphertextLength));
    return b.toBytes();
  }

  /// The Ed25519-signed message: `header || eph_pub || aead_nonce || ct || mac`.
  static Uint8List v2SignedMessage(Uint8List header, Uint8List ephPub,
      Uint8List aeadNonce, Uint8List ciphertext, Uint8List mac) {
    return (BytesBuilder()
          ..add(header)
          ..add(ephPub)
          ..add(aeadNonce)
          ..add(ciphertext)
          ..add(mac))
        .toBytes();
  }

  /// `frame = [len(body) BE4][ eph_pub || aead_nonce || ct || mac || sig ]`.
  static Uint8List v2Frame(Uint8List ephPub, Uint8List aeadNonce,
      Uint8List ciphertext, Uint8List mac, Uint8List sig) {
    if (ephPub.length != ephPubLength) throw ArgumentError('eph_pub must be $ephPubLength bytes');
    if (aeadNonce.length != aeadNonceLength) throw ArgumentError('aead_nonce must be $aeadNonceLength bytes');
    if (mac.length != macLength) throw ArgumentError('mac must be $macLength bytes');
    if (sig.length != sigLength) throw ArgumentError('sig must be $sigLength bytes');
    final body = (BytesBuilder()
          ..add(ephPub)
          ..add(aeadNonce)
          ..add(ciphertext)
          ..add(mac)
          ..add(sig))
        .toBytes();
    return (BytesBuilder()
          ..add(_be4(body.length))
          ..add(body))
        .toBytes();
  }

  /// True if a nonce read is usable: right length and not the all-zero
  /// "no active challenge" sentinel. Never sign against an all-zero nonce.
  static bool isValidNonce(List<int> nonce) {
    if (nonce.length != nonceLength) return false;
    return nonce.any((b) => b != 0);
  }

  static Uint8List _be4(int n) {
    final d = ByteData(4)..setUint32(0, n, Endian.big);
    return d.buffer.asUint8List();
  }
}
