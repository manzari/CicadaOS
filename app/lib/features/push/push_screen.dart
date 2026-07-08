import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/ble/fbp_transport.dart';
import '../../core/ble/push_controller.dart';
import '../../core/ble/scanner.dart';
import '../../core/ble/tx_status.dart';
import '../../core/hex.dart';
import '../../data/database.dart';

class PushScreen extends ConsumerStatefulWidget {
  final int? scriptId;
  final String? deviceId;
  final bool auto;

  const PushScreen({super.key, this.scriptId, this.deviceId, this.auto = false});

  @override
  ConsumerState<PushScreen> createState() => _PushScreenState();
}

class _LogLine {
  final String text;
  final TxKind? kind;
  _LogLine(this.text, this.kind);
}

class _PushScreenState extends ConsumerState<PushScreen> {
  final List<_LogLine> _log = [];
  double? _progress;
  bool _running = false;
  bool? _success;
  Script? _script;

  @override
  void initState() {
    super.initState();
    _loadThen();
  }

  Future<void> _loadThen() async {
    var scriptId = widget.scriptId;
    // Boot-watch enters with only a device — resolve its default script.
    if (scriptId == null && widget.deviceId != null) {
      final device = await ref.read(devicesRepoProvider).getById(widget.deviceId!);
      scriptId = device?.defaultScriptId;
    }
    if (scriptId != null) {
      _script = await ref.read(scriptsRepoProvider).getById(scriptId);
    }
    if (mounted) setState(() {});
    if (widget.auto && _script != null) _run();
  }

  void _append(String text, [TxKind? kind]) {
    setState(() => _log.add(_LogLine(text, kind)));
  }

  Future<void> _run() async {
    if (_running) return;
    final script = _script;
    final deviceId = widget.deviceId;
    if (script == null || deviceId == null) {
      _append('Missing script or device.', TxKind.errOther);
      return;
    }
    setState(() {
      _running = true;
      _success = null;
      _progress = null;
      _log.clear();
    });

    final scanner = EspScanner();
    FbpTransport? transport;
    try {
      _append('Scanning for $deviceId…');
      final esp = await scanner.findById(deviceId);
      if (esp == null) {
        _append('Device not found / out of range.', TxKind.errOther);
        setState(() => _success = false);
        return;
      }
      await scanner.stop();

      final device = await ref.read(devicesRepoProvider).getById(deviceId);
      final keyHex = device?.x25519PubKey;
      if (keyHex == null || keyHex.length != 64) {
        _append('No pinned encryption key for this device — provision it first.',
            TxKind.errOther);
        setState(() => _success = false);
        return;
      }

      transport = FbpTransport(esp.device);
      final controller = PushController(
        transport,
        ref.read(signerProvider),
        devicePubKey: hexDecode(keyHex),
      );
      controller.events.listen((e) {
        if (e.progress != null) setState(() => _progress = e.progress);
        _append(e.message, e.status?.kind);
      });

      final ok = await controller.run(_scriptBytes(script.body));
      setState(() => _success = ok);
      if (ok) {
        await ref.read(devicesRepoProvider).markPaired(deviceId);
      }
    } on PushException catch (e) {
      _append(e.message, TxKind.errOther);
      setState(() => _success = false);
    } catch (e) {
      _append('Failed: $e', TxKind.errOther);
      setState(() => _success = false);
    } finally {
      await scanner.stop();
      await transport?.dispose();
      setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = _script?.name ?? 'Push';
    return Scaffold(
      appBar: AppBar(
        title: Text('Push: $title'),
        bottom: _running && _progress != null
            ? PreferredSize(
                preferredSize: const Size.fromHeight(4),
                child: LinearProgressIndicator(value: _progress),
              )
            : (_running
                ? const PreferredSize(
                    preferredSize: Size.fromHeight(4),
                    child: LinearProgressIndicator(),
                  )
                : null),
      ),
      body: Column(
        children: [
          if (_success != null) _resultBanner(_success!),
          Expanded(
            child: _log.isEmpty
                ? const Center(child: Text('Ready to push.'))
                : ListView.builder(
                    padding: const EdgeInsets.all(12),
                    itemCount: _log.length,
                    itemBuilder: (_, i) => _logRow(_log[i]),
                  ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _running ? null : _run,
        icon: const Icon(Icons.play_arrow),
        label: Text(_success == null ? 'Push' : 'Retry'),
        backgroundColor: _running ? Theme.of(context).disabledColor : null,
      ),
    );
  }

  Widget _resultBanner(bool ok) {
    return Container(
      width: double.infinity,
      color: ok ? Colors.green.withValues(alpha: 0.15) : Colors.red.withValues(alpha: 0.15),
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Icon(ok ? Icons.check_circle : Icons.error, color: ok ? Colors.green : Colors.red),
          const SizedBox(width: 12),
          Text(ok ? 'Script ran on the ESP' : 'Push failed',
              style: const TextStyle(fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Widget _logRow(_LogLine line) {
    Color? color;
    if (line.kind == TxKind.out) color = Colors.blueGrey;
    if (line.kind == TxKind.okVerified || line.kind == TxKind.okDone) color = Colors.green;
    if (line.kind != null && line.kind.toString().contains('err')) color = Colors.red;
    final isOut = line.kind == TxKind.out;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Text(
        isOut ? '» ${line.text}' : line.text,
        style: TextStyle(fontFamily: 'monospace', color: color, fontSize: 13),
      ),
    );
  }

  Uint8List _scriptBytes(String body) {
    // Sign & push the exact UTF-8 bytes shown in the editor.
    return const Utf8Encoder().convert(body);
  }
}
