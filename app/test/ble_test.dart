import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:cicadaos/core/ble/adv.dart';
import 'package:cicadaos/core/ble/push_controller.dart';
import 'package:cicadaos/core/ble/push_transport.dart';
import 'package:cicadaos/core/ble/tx_status.dart';
import 'package:cicadaos/core/crypto/key_store.dart';
import 'package:cicadaos/core/crypto/signer.dart';
import 'package:cicadaos/core/protocol.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

/// Scriptable fake transport: successive nonce reads, recorded writes, and a
/// manual TX event injector.
class FakeTransport implements PushTransport {
  @override
  int mtu;
  final List<Uint8List> nonceReads;
  final List<Uint8List> writes = [];
  final _tx = StreamController<Uint8List>.broadcast();
  final _dc = Completer<void>();
  int _idx = 0;
  bool disposed = false;

  FakeTransport({this.mtu = 256, required this.nonceReads});

  @override
  Future<void> connect() async {}
  @override
  Future<void> subscribeTx() async {}
  @override
  Stream<Uint8List> get txStream => _tx.stream;
  @override
  Future<Uint8List> readNonce() async =>
      nonceReads[math.min(_idx++, nonceReads.length - 1)];
  @override
  Future<void> writeRx(Uint8List chunk) async =>
      writes.add(Uint8List.fromList(chunk));
  @override
  Future<void> get onDisconnected => _dc.future;
  @override
  Future<void> dispose() async => disposed = true;

  void emit(String s) => _tx.add(Uint8List.fromList(utf8.encode(s)));
  void drop() {
    if (!_dc.isCompleted) _dc.complete();
  }

  Uint8List reassembled() {
    final b = BytesBuilder();
    for (final w in writes) {
      b.add(w);
    }
    return b.toBytes();
  }
}

Uint8List _bytes(String s) => Uint8List.fromList(utf8.encode(s));

void main() {
  group('TxStatus.parse', () {
    test('classifies every documented status', () {
      expect(TxStatus.parse(_bytes('NONCE')).kind, TxKind.nonce);
      expect(TxStatus.parse(_bytes('OK:verified')).kind, TxKind.okVerified);
      expect(TxStatus.parse(_bytes('OK:done')).kind, TxKind.okDone);
      final out = TxStatus.parse(_bytes('OUT:temp=25.1'));
      expect(out.kind, TxKind.out);
      expect(out.payload, 'temp=25.1');
      expect(TxStatus.parse(_bytes('ERR:sig')).kind, TxKind.errSig);
      expect(TxStatus.parse(_bytes('ERR:frame')).kind, TxKind.errFrame);
      expect(TxStatus.parse(_bytes('ERR:len')).kind, TxKind.errLen);
      expect(TxStatus.parse(_bytes('ERR:busy')).kind, TxKind.errBusy);
      expect(TxStatus.parse(_bytes('ERR:nonce')).kind, TxKind.errNonce);
      final tb = TxStatus.parse(_bytes('ERR:Traceback line'));
      expect(tb.kind, TxKind.errOther);
      expect(tb.payload, 'Traceback line');
    });

    test('terminal / error flags', () {
      expect(TxStatus.parse(_bytes('OK:done')).isTerminal, isTrue);
      expect(TxStatus.parse(_bytes('ERR:sig')).isError, isTrue);
      expect(TxStatus.parse(_bytes('OUT:x')).isTerminal, isFalse);
      expect(TxStatus.parse(_bytes('NONCE')).isTerminal, isFalse);
    });
  });

  group('CicadaAdv.fromManufacturerData', () {
    test('parses id + awaiting bit', () {
      final payload = [0xC1, 0xCA, 0x01, 0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6];
      final adv = CicadaAdv.fromManufacturerData({0xFFFF: payload})!;
      expect(adv.deviceId, 'a1b2c3d4e5f6');
      expect(adv.awaiting, isTrue);
    });

    test('cleared awaiting bit', () {
      final adv = CicadaAdv.fromManufacturerData({
        0xFFFF: [0xC1, 0xCA, 0x00, 1, 2, 3, 4, 5, 6]
      })!;
      expect(adv.awaiting, isFalse);
    });

    test('rejects wrong company / magic / short payload', () {
      expect(CicadaAdv.fromManufacturerData({0x004C: [0xC1, 0xCA, 0, 1, 2, 3, 4, 5, 6]}), isNull);
      expect(CicadaAdv.fromManufacturerData({0xFFFF: [0x00, 0x00, 0, 1, 2, 3, 4, 5, 6]}), isNull);
      expect(CicadaAdv.fromManufacturerData({0xFFFF: [0xC1, 0xCA, 0]}), isNull);
    });
  });

  group('PushController (v2 encrypted push)', () {
    late Signer signer;
    // Seed from the shared vectors so signatures are deterministic.
    const seedHex = '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f';
    late SimpleKeyPair deviceKeyPair; // stands in for the ESP's X25519 key
    late Uint8List devicePub;

    setUp(() async {
      signer = Signer(InMemoryKeyStore(seedHex));
      deviceKeyPair = await X25519()
          .newKeyPairFromSeed(List<int>.generate(32, (i) => (i * 3 + 7) & 0xFF));
      devicePub = Uint8List.fromList((await deviceKeyPair.extractPublicKey()).bytes);
    });

    Uint8List validNonce() => Uint8List.fromList(List.generate(32, (i) => i + 1));

    PushController make(FakeTransport t) =>
        PushController(t, signer, devicePubKey: devicePub);

    // Decrypt + verify a captured frame the way the firmware would: check the
    // Ed25519 signature over the encrypted blob, then X25519 + XChaCha20-Poly1305.
    Future<Uint8List> recover(Uint8List frame, Uint8List nonce) async {
      final body = Uint8List.sublistView(frame, 4); // strip length prefix
      final ephPub = Uint8List.sublistView(body, 0, 32);
      final aeadNonce = Uint8List.sublistView(body, 32, 56);
      final sig = Uint8List.sublistView(body, body.length - 64);
      final mac = Uint8List.sublistView(body, body.length - 80, body.length - 64);
      final ct = Uint8List.sublistView(body, 56, body.length - 80);

      final header = Protocol.v2Header(nonce, ct.length);
      final signed = Protocol.v2SignedMessage(header, ephPub, aeadNonce, ct, mac);
      final pub = SimplePublicKey(await signer.publicKey(), type: KeyPairType.ed25519);
      final sigOk = await Ed25519()
          .verify(signed, signature: Signature(sig, publicKey: pub));
      expect(sigOk, isTrue, reason: 'frame signature must verify with the app pubkey');

      final sharedKey = await X25519().sharedSecretKey(
          keyPair: deviceKeyPair,
          remotePublicKey: SimplePublicKey(ephPub, type: KeyPairType.x25519));
      final shared = await sharedKey.extractBytes();
      final keyBytes = (await Blake2b().hash([...shared, ...ephPub, ...devicePub]))
          .bytes
          .sublist(0, 32);
      final clear = await Xchacha20.poly1305Aead().decrypt(
        SecretBox(ct, nonce: aeadNonce, mac: Mac(mac)),
        secretKey: SecretKey(keyBytes),
        aad: header,
      );
      return Uint8List.fromList(clear);
    }

    test('happy path: verified → OUT → done, frame decrypts to the script', () async {
      final nonce = validNonce();
      final t = FakeTransport(nonceReads: [nonce]);
      final c = make(t);
      final phases = <PushPhase>[];
      final outs = <String>[];
      c.events.listen((e) {
        phases.add(e.phase);
        if (e.status?.kind == TxKind.out) outs.add(e.message);
        if (e.phase == PushPhase.awaitingResult && e.message == 'Waiting for result…') {
          t.emit('OK:verified');
          t.emit('OUT:hi from script');
          t.emit('OK:done');
        }
      });

      final script = _bytes("notify('hi from script')");
      final ok = await c.run(script);

      expect(ok, isTrue);
      expect(phases.last, PushPhase.done);
      expect(outs, ['hi from script']);

      final frame = t.reassembled();
      // Nothing on the wire reveals the plaintext.
      expect(String.fromCharCodes(frame).contains('notify'), isFalse,
          reason: 'script must not appear in cleartext on the wire');
      expect(await recover(frame, nonce), script);
    });

    test('10 KB script survives chunking and decrypts intact', () async {
      final nonce = validNonce();
      final t = FakeTransport(mtu: 256, nonceReads: [nonce]);
      final c = make(t);
      c.events.listen((e) {
        if (e.phase == PushPhase.awaitingResult && e.message == 'Waiting for result…') {
          t.emit('OK:done');
        }
      });

      final script = _bytes('n=0\n' * 2600); // ~10 KB
      expect(script.length, greaterThan(10000));
      final ok = await c.run(script);
      expect(ok, isTrue);

      final chunkMax = math.min(256 - 3, 244);
      expect(t.writes.length, greaterThan(1));
      for (final w in t.writes) {
        expect(w.length, lessThanOrEqualTo(chunkMax));
      }
      expect(await recover(t.reassembled(), nonce), script);
    });

    test('ERR:sig surfaces a clean failure', () async {
      final t = FakeTransport(nonceReads: [validNonce()]);
      final c = make(t);
      c.events.listen((e) {
        if (e.phase == PushPhase.awaitingResult && e.message == 'Waiting for result…') {
          t.emit('ERR:sig');
        }
      });
      await expectLater(
        c.run(_bytes('x=1')),
        throwsA(isA<PushException>().having((e) => e.message, 'message', contains('bad signature'))),
      );
    });

    test('all-zero nonce: waits for NONCE notify, then re-reads a valid one', () async {
      final zero = Uint8List(32);
      final good = validNonce();
      final t = FakeTransport(nonceReads: [zero, good]);
      final c = make(t);
      c.events.listen((e) {
        if (e.phase == PushPhase.readingNonce) {
          // firmware publishes a fresh challenge shortly after connect
          t.emit('NONCE');
        }
        if (e.phase == PushPhase.awaitingResult && e.message == 'Waiting for result…') {
          t.emit('OK:done');
        }
      });
      final ok = await c.run(_bytes('x=1'));
      expect(ok, isTrue);
      // The frame is bound to the *good* (re-read) nonce.
      expect(await recover(t.reassembled(), good), _bytes('x=1'));
    });

    test('disconnect mid-push fails cleanly, no crash', () async {
      final t = FakeTransport(nonceReads: [validNonce()]);
      final c = make(t);
      c.events.listen((e) {
        if (e.phase == PushPhase.awaitingResult && e.message == 'Waiting for result…') {
          t.drop(); // link drops before any result
        }
      });
      await expectLater(
        c.run(_bytes('x=1')),
        throwsA(isA<PushException>().having((e) => e.message, 'm', contains('disconnected'))),
      );
    });
  });
}
