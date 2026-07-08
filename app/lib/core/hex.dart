import 'dart:typed_data';

/// Minimal lowercase hex codec. Kept dependency-free and used everywhere a raw
/// key / nonce / id needs a stable string form (secure storage, provisioning UI).
String hexEncode(List<int> bytes) {
  final sb = StringBuffer();
  for (final b in bytes) {
    sb.write((b & 0xFF).toRadixString(16).padLeft(2, '0'));
  }
  return sb.toString();
}

Uint8List hexDecode(String s) {
  final clean = s.trim().replaceAll(RegExp(r'\s'), '');
  if (clean.length.isOdd) {
    throw FormatException('hex string must have an even length', s);
  }
  final out = Uint8List(clean.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(clean.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return out;
}
