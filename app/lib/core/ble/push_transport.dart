import 'dart:typed_data';

/// The BLE operations the push state machine needs, abstracted so the machine
/// can be unit-tested with a fake and the flutter_blue_plus binding stays thin.
abstract class PushTransport {
  /// Connect, request MTU 256, discover the NUS service + characteristics.
  Future<void> connect();

  /// Negotiated ATT MTU (23 until exchanged). Chunk size is min(mtu-3, 244).
  int get mtu;

  /// Enable TX notifications. MUST be called before [readNonce] (CLAUDE.md guardrails).
  Future<void> subscribeTx();

  /// Raw TX notification payloads (one event per notification).
  Stream<Uint8List> get txStream;

  /// Read the 32-byte NONCE characteristic.
  Future<Uint8List> readNonce();

  /// Write one RX chunk with write-without-response.
  Future<void> writeRx(Uint8List chunk);

  /// Completes if/when the link drops during a push.
  Future<void> get onDisconnected;

  /// Tear down subscriptions and disconnect.
  Future<void> dispose();
}
