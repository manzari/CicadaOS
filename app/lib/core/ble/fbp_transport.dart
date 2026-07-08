import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import '../protocol.dart';
import 'push_transport.dart';

/// flutter_blue_plus binding of [PushTransport]. Deliberately thin: all sequence
/// logic lives in PushController; this only maps to the plugin's API.
class FbpTransport implements PushTransport {
  final BluetoothDevice device;

  late BluetoothCharacteristic _rx;
  late BluetoothCharacteristic _tx;
  late BluetoothCharacteristic _nonce;

  final _disconnected = Completer<void>();
  StreamSubscription<BluetoothConnectionState>? _connSub;
  int _mtu = 23;

  FbpTransport(this.device);

  @override
  int get mtu => _mtu;

  @override
  Future<void> get onDisconnected => _disconnected.future;

  @override
  Future<void> connect() async {
    // License.nonprofit: this is a personal, non-commercial companion app.
    // mtu:null so we control the MTU request ourselves (plan: request 256).
    await device.connect(
      license: License.nonprofit,
      mtu: null,
      timeout: const Duration(seconds: 15),
    );
    try {
      _mtu = await device.requestMtu(256);
    } catch (_) {
      _mtu = device.mtuNow; // iOS negotiates automatically
    }

    // Watch for drops only after we're connected (avoids the initial emit).
    _connSub = device.connectionState.listen((s) {
      if (s == BluetoothConnectionState.disconnected && !_disconnected.isCompleted) {
        _disconnected.complete();
      }
    });

    final services = await device.discoverServices();
    final svc = services.firstWhere(
      (s) => s.uuid == Guid(Protocol.serviceUuid),
      orElse: () => throw StateError('NUS service not found on device'),
    );
    _rx = _find(svc, Protocol.rxUuid);
    _tx = _find(svc, Protocol.txUuid);
    _nonce = _find(svc, Protocol.nonceUuid);
  }

  BluetoothCharacteristic _find(BluetoothService svc, String uuid) {
    return svc.characteristics.firstWhere(
      (c) => c.uuid == Guid(uuid),
      orElse: () => throw StateError('characteristic $uuid not found'),
    );
  }

  @override
  Future<void> subscribeTx() => _tx.setNotifyValue(true);

  @override
  Stream<Uint8List> get txStream =>
      _tx.onValueReceived.map((v) => Uint8List.fromList(v));

  @override
  Future<Uint8List> readNonce() async =>
      Uint8List.fromList(await _nonce.read());

  @override
  Future<void> writeRx(Uint8List chunk) =>
      _rx.write(chunk, withoutResponse: true);

  @override
  Future<void> dispose() async {
    await _connSub?.cancel();
    _connSub = null;
    try {
      await device.disconnect();
    } catch (_) {}
    if (!_disconnected.isCompleted) _disconnected.complete();
  }
}
