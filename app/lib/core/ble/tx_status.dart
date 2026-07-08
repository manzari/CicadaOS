import 'dart:convert';

/// Kinds of ASCII status the ESP notifies on TX (CLAUDE.md wire protocol).
enum TxKind {
  nonce, // fresh challenge available — re-read the NONCE char
  okVerified, // signature accepted, about to exec
  okDone, // terminal success
  out, // OUT:<text> emitted by the running script's notify()
  errSig,
  errFrame,
  errLen,
  errBusy,
  errNonce,
  errOther, // ERR:<traceback> or an unrecognised ERR
  unknown,
}

/// One parsed TX status line. Kept a standalone value type on purpose: a future
/// dashboard feature parses `OUT:` payloads (e.g. JSON) into live tiles, so the
/// status stream must not be welded to the push flow (plan "Later" note).
class TxStatus {
  final TxKind kind;
  final String raw;

  /// For [TxKind.out], the text after `OUT:`. For [TxKind.errOther], the reason
  /// after `ERR:`. Empty otherwise.
  final String payload;

  const TxStatus(this.kind, this.raw, this.payload);

  bool get isTerminal =>
      kind == TxKind.okDone || isError;

  bool get isError =>
      kind == TxKind.errSig ||
      kind == TxKind.errFrame ||
      kind == TxKind.errLen ||
      kind == TxKind.errBusy ||
      kind == TxKind.errNonce ||
      kind == TxKind.errOther;

  static TxStatus parse(List<int> bytes) {
    final raw = _decode(bytes);
    if (raw == 'NONCE') return TxStatus(TxKind.nonce, raw, '');
    if (raw == 'OK:verified') return TxStatus(TxKind.okVerified, raw, '');
    if (raw == 'OK:done') return TxStatus(TxKind.okDone, raw, '');
    if (raw.startsWith('OUT:')) {
      return TxStatus(TxKind.out, raw, raw.substring(4));
    }
    if (raw.startsWith('ERR:')) {
      final reason = raw.substring(4);
      switch (reason) {
        case 'sig':
          return TxStatus(TxKind.errSig, raw, reason);
        case 'frame':
          return TxStatus(TxKind.errFrame, raw, reason);
        case 'len':
          return TxStatus(TxKind.errLen, raw, reason);
        case 'busy':
          return TxStatus(TxKind.errBusy, raw, reason);
        case 'nonce':
          return TxStatus(TxKind.errNonce, raw, reason);
        default:
          return TxStatus(TxKind.errOther, raw, reason); // truncated traceback
      }
    }
    return TxStatus(TxKind.unknown, raw, '');
  }

  static String _decode(List<int> bytes) {
    try {
      return utf8.decode(bytes);
    } catch (_) {
      return latin1.decode(bytes); // never throw on a stray byte
    }
  }

  @override
  String toString() => raw;
}
