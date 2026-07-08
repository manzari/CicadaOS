import 'dart:async';
import 'dart:collection';
import 'dart:math' as math;
import 'dart:typed_data';

import '../crypto/box.dart';
import '../crypto/signer.dart';
import '../protocol.dart';
import 'push_transport.dart';
import 'tx_status.dart';

enum PushPhase {
  connecting,
  subscribing,
  readingNonce,
  signing,
  writing,
  awaitingResult,
  done, // terminal success
  failed, // terminal failure
}

/// One observable step in a push. The UI renders these as a live log plus a
/// phase indicator; [progress] is 0..1 during the writing phase.
class PushEvent {
  final PushPhase phase;
  final String message;
  final double? progress;
  final TxStatus? status; // set when the event carries a parsed TX line

  const PushEvent(this.phase, this.message, {this.progress, this.status});

  bool get isTerminal => phase == PushPhase.done || phase == PushPhase.failed;
  bool get isSuccess => phase == PushPhase.done;
}

class PushException implements Exception {
  final String message;
  PushException(this.message);
  @override
  String toString() => message;
}

/// Drives one script push over a [PushTransport], mirroring the reference
/// `tools/push_script.py`: connect → subscribe TX → read (non-zero) NONCE →
/// sign → frame → chunked write-without-response → stream TX until OK:done/ERR.
///
/// Every step is emitted on [events]; [run] resolves true on OK:done and throws
/// [PushException] on any error (bad nonce, ERR:*, disconnect, timeout).
class PushController {
  final PushTransport transport;
  final Signer signer;
  final ScriptSealer sealer;

  /// The target device's pinned X25519 public key (32 bytes). The script is
  /// encrypted to it, so a rogue peripheral answering the connection gets
  /// ciphertext it cannot read.
  final Uint8List devicePubKey;
  final Duration nonceTimeout;
  final Duration resultTimeout;

  final _events = StreamController<PushEvent>.broadcast();
  bool _finished = false;
  Future<void>? _dc; // cached disconnect signal for the duration of a run

  PushController(
    this.transport,
    this.signer, {
    required this.devicePubKey,
    ScriptSealer? sealer,
    this.nonceTimeout = const Duration(seconds: 6),
    this.resultTimeout = const Duration(seconds: 20),
  }) : sealer = sealer ?? ScriptSealer(signer);

  Stream<PushEvent> get events => _events.stream;

  void _emit(PushPhase phase, String message, {double? progress, TxStatus? status}) {
    if (!_events.isClosed) {
      _events.add(PushEvent(phase, message, progress: progress, status: status));
    }
  }

  Future<bool> run(Uint8List script) async {
    if (script.length > Protocol.maxScript) {
      throw PushException(
          'script too large: ${script.length} bytes (max ${Protocol.maxScript})');
    }
    _TxQueue? queue;
    _dc = transport.onDisconnected;
    try {
      _emit(PushPhase.connecting, 'Connecting…');
      await _guard(transport.connect());

      _emit(PushPhase.subscribing, 'Subscribing to status…');
      await _guard(transport.subscribeTx());
      // Subscribe to TX BEFORE reading the nonce so we never miss the re-arm.
      queue = _TxQueue(transport.txStream);

      _emit(PushPhase.readingNonce, 'Reading challenge…');
      final nonce = await _obtainNonce(queue);

      _emit(PushPhase.signing, 'Encrypting & signing…');
      final frame = await sealer.seal(script, nonce, devicePubKey);

      _emit(PushPhase.writing, 'Sending frame…', progress: 0);
      await _writeFrame(frame);

      _emit(PushPhase.awaitingResult, 'Waiting for result…');
      return await _awaitResult(queue);
    } on PushException catch (e) {
      _emit(PushPhase.failed, e.message);
      rethrow;
    } catch (e) {
      _emit(PushPhase.failed, 'Push failed: $e');
      throw PushException('$e');
    } finally {
      _finished = true;
      await queue?.cancel();
      await _events.close();
    }
  }

  /// Read the NONCE char; if it reads all-zero (no active challenge), wait for a
  /// NONCE notification and re-read once before giving up.
  Future<Uint8List> _obtainNonce(_TxQueue queue) async {
    var nonce = await _guard(transport.readNonce());
    if (Protocol.isValidNonce(nonce)) return nonce;

    // Drain any already-queued NONCE, else wait for the next one.
    final waited = await _waitFor(queue, (s) => s.kind == TxKind.nonce, nonceTimeout);
    if (!waited) {
      throw PushException('no active challenge (nonce stayed zero)');
    }
    nonce = await _guard(transport.readNonce());
    if (!Protocol.isValidNonce(nonce)) {
      throw PushException('nonce still invalid after re-read');
    }
    return nonce;
  }

  Future<void> _writeFrame(Uint8List frame) async {
    final step = math.min(transport.mtu - 3, 244);
    final chunk = step < 1 ? 20 : step;
    for (var i = 0; i < frame.length; i += chunk) {
      final end = math.min(i + chunk, frame.length);
      await _guard(transport.writeRx(Uint8List.sublistView(frame, i, end)));
      _emit(PushPhase.writing, 'Sending frame…', progress: end / frame.length);
    }
  }

  Future<bool> _awaitResult(_TxQueue queue) async {
    while (true) {
      final status = await _nextStatus(queue, resultTimeout);
      switch (status.kind) {
        case TxKind.nonce:
          continue; // re-arm for the next push — ignore mid-run
        case TxKind.okVerified:
          _emit(PushPhase.awaitingResult, 'Signature verified', status: status);
          continue;
        case TxKind.out:
          _emit(PushPhase.awaitingResult, status.payload, status: status);
          continue;
        case TxKind.okDone:
          _emit(PushPhase.done, 'Done ✓', status: status);
          return true;
        default:
          if (status.isError) {
            _emit(PushPhase.failed, _errorText(status), status: status);
            throw PushException(_errorText(status));
          }
          // Unknown line: surface it, keep waiting.
          _emit(PushPhase.awaitingResult, status.raw, status: status);
      }
    }
  }

  String _errorText(TxStatus s) {
    switch (s.kind) {
      case TxKind.errSig:
        return 'Rejected: bad signature (ERR:sig)';
      case TxKind.errFrame:
        return 'Rejected: malformed frame (ERR:frame)';
      case TxKind.errLen:
        return 'Rejected: frame too large (ERR:len)';
      case TxKind.errBusy:
        return 'Rejected: ESP busy (ERR:busy)';
      case TxKind.errNonce:
        return 'Rejected: stale challenge (ERR:nonce)';
      default:
        return 'Script error: ${s.payload}';
    }
  }

  // --- await helpers that also fail fast on disconnect ---------------------

  // The disconnect branch completes with a *value* (a flag flip), never a throw,
  // so a late-completing loser can't surface as an uncaught async error.
  Future<T> _guard<T>(Future<T> op) async {
    var disconnected = false;
    final result = await Future.any<T?>([
      op.then<T?>((v) => v),
      _dc!.then<T?>((_) {
        disconnected = true;
        return null;
      }),
    ]);
    if (disconnected) throw PushException('disconnected');
    return result as T;
  }

  Future<TxStatus> _nextStatus(_TxQueue queue, Duration timeout) async {
    var outcome = 0; // 0 = got event, 1 = disconnected, 2 = timeout
    TxStatus? got;
    await Future.any<void>([
      queue.next().then((v) => got = v),
      _dc!.then((_) => outcome = 1),
      Future<void>.delayed(timeout).then((_) {
        if (got == null) outcome = 2;
      }),
    ]);
    if (outcome == 1) throw PushException('disconnected');
    if (outcome == 2 || got == null) throw PushException('timed out waiting for ESP');
    return got!;
  }

  Future<bool> _waitFor(
      _TxQueue queue, bool Function(TxStatus) test, Duration timeout) async {
    final deadline = Duration(milliseconds: timeout.inMilliseconds);
    final sw = Stopwatch()..start();
    while (sw.elapsed < deadline) {
      final remaining = deadline - sw.elapsed;
      final TxStatus status;
      try {
        status = await _nextStatus(queue, remaining);
      } on PushException {
        return false; // timeout or disconnect
      }
      if (test(status)) return true;
    }
    return false;
  }

  bool get isFinished => _finished;
}

/// A minimal pull-queue over the TX stream: buffers notifications that arrive
/// before we ask for them, so the "subscribe before read nonce" ordering holds.
class _TxQueue {
  final Queue<TxStatus> _buffer = Queue();
  final Queue<Completer<TxStatus>> _waiters = Queue();
  StreamSubscription<List<int>>? _sub;

  _TxQueue(Stream<List<int>> src) {
    _sub = src.listen((bytes) {
      final s = TxStatus.parse(bytes);
      if (_waiters.isNotEmpty) {
        _waiters.removeFirst().complete(s);
      } else {
        _buffer.add(s);
      }
    });
  }

  Future<TxStatus> next() {
    if (_buffer.isNotEmpty) return Future.value(_buffer.removeFirst());
    final c = Completer<TxStatus>();
    _waiters.add(c);
    return c.future;
  }

  Future<void> cancel() async {
    await _sub?.cancel();
    _sub = null;
  }
}
