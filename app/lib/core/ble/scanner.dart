import 'dart:async';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import '../protocol.dart';
import 'adv.dart';

/// A scanned CicadaOS ESP: the BLE handle plus its decoded identity.
class DiscoveredEsp {
  final BluetoothDevice device;
  final CicadaAdv adv;
  final String? advName;
  final int rssi;

  const DiscoveredEsp(this.device, this.adv, this.advName, this.rssi);

  String get deviceId => adv.deviceId;
  bool get awaiting => adv.awaiting;
}

/// Scans for ESPs advertising the NUS service and decodes our manufacturer AD.
/// iOS can only background-filter by service UUID, so we filter on the service
/// and parse the manufacturer identity from each result.
class EspScanner {
  /// Stream of currently-visible ESPs, deduplicated by device id (latest wins).
  Stream<List<DiscoveredEsp>> results() {
    return FlutterBluePlus.scanResults.map((list) {
      final byId = <String, DiscoveredEsp>{};
      for (final r in list) {
        final adv = CicadaAdv.fromManufacturerData(r.advertisementData.manufacturerData);
        if (adv == null) continue;
        byId[adv.deviceId] = DiscoveredEsp(
          r.device,
          adv,
          r.advertisementData.advName.isEmpty ? null : r.advertisementData.advName,
          r.rssi,
        );
      }
      return byId.values.toList();
    });
  }

  Future<void> start({Duration? timeout}) async {
    if (FlutterBluePlus.isScanningNow) return;
    await FlutterBluePlus.startScan(
      withServices: [Guid(Protocol.serviceUuid)],
      timeout: timeout,
      androidScanMode: AndroidScanMode.lowLatency,
    );
  }

  Future<void> stop() async {
    if (FlutterBluePlus.isScanningNow) await FlutterBluePlus.stopScan();
  }

  /// Find a specific device by its 6-byte id within [window]; null if not seen.
  Future<DiscoveredEsp?> findById(String deviceId, {Duration window = const Duration(seconds: 8)}) async {
    final completer = Completer<DiscoveredEsp?>();
    late StreamSubscription sub;
    sub = results().listen((esps) {
      for (final e in esps) {
        if (e.deviceId == deviceId && !completer.isCompleted) {
          completer.complete(e);
        }
      }
    });
    await start(timeout: window);
    final found = await completer.future
        .timeout(window, onTimeout: () => null);
    await sub.cancel();
    return found;
  }
}
