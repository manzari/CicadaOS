import '../hex.dart';
import '../protocol.dart';

/// Identity + boot state decoded from an ESP's manufacturer advertisement data
/// (CLAUDE.md (advertising: manufacturer AD)). The 6-byte [deviceId] is stable across phones and reboots
/// and is the primary key we store devices under.
class CicadaAdv {
  final String deviceId; // 12-hex
  final bool awaiting; // no valid script has run since the ESP booted

  const CicadaAdv(this.deviceId, this.awaiting);

  /// Parse from flutter_blue_plus `AdvertisementData.manufacturerData`, keyed by
  /// company id. Returns null for any advertisement that isn't one of ours.
  static CicadaAdv? fromManufacturerData(Map<int, List<int>> data) {
    final payload = data[Protocol.mfrCompanyId];
    if (payload == null || payload.length < Protocol.mfrPayloadLength) return null;
    if (payload[0] != Protocol.mfrMagic[0] || payload[1] != Protocol.mfrMagic[1]) {
      return null;
    }
    final flags = payload[2];
    final id = payload.sublist(3, 3 + Protocol.deviceIdLength);
    return CicadaAdv(
      hexEncode(id),
      (flags & Protocol.mfrFlagAwaiting) != 0,
    );
  }
}
