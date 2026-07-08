import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/ble/scanner.dart';
import '../../data/database.dart';

/// Present a scan-and-pick sheet; resolves to the chosen 6-byte device id (hex)
/// or null if dismissed. Sighted devices are recorded to the DB.
Future<String?> pickDevice(BuildContext context, WidgetRef ref) {
  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _DevicePickerSheet(ref: ref),
  );
}

class _DevicePickerSheet extends StatefulWidget {
  final WidgetRef ref;
  const _DevicePickerSheet({required this.ref});

  @override
  State<_DevicePickerSheet> createState() => _DevicePickerSheetState();
}

class _DevicePickerSheetState extends State<_DevicePickerSheet> {
  final _scanner = EspScanner();
  String? _error;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    try {
      await _scanner.start(timeout: const Duration(seconds: 15));
    } catch (e) {
      setState(() => _error = 'Scan failed: $e\nCheck Bluetooth & location permissions.');
    }
  }

  @override
  void dispose() {
    _scanner.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final devicesAsync = widget.ref.watch(devicesStreamProvider);
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      expand: false,
      builder: (context, scroll) {
        return Column(
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Choose an ESP', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            ),
            if (_error != null)
              Padding(padding: const EdgeInsets.all(16), child: Text(_error!, style: const TextStyle(color: Colors.red))),
            Expanded(
              child: StreamBuilder<List<DiscoveredEsp>>(
                stream: _scanner.results(),
                builder: (context, snap) {
                  final live = snap.data ?? const [];
                  // record sightings
                  for (final e in live) {
                    widget.ref.read(devicesRepoProvider).upsertSeen(e.deviceId, name: e.advName);
                  }
                  final liveIds = live.map((e) => e.deviceId).toSet();
                  final known = (devicesAsync.value ?? <Device>[])
                      .where((d) => !liveIds.contains(d.id))
                      .toList();
                  return ListView(
                    controller: scroll,
                    children: [
                      if (live.isNotEmpty) const _SectionHeader('Nearby'),
                      ...live.map(_liveTile),
                      if (known.isNotEmpty) const _SectionHeader('Known (not in range)'),
                      ...known.map(_knownTile),
                      if (live.isEmpty && known.isEmpty)
                        const Padding(
                          padding: EdgeInsets.all(24),
                          child: Center(child: Text('Scanning for ESPs…')),
                        ),
                    ],
                  );
                },
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _liveTile(DiscoveredEsp e) {
    return ListTile(
      leading: Icon(e.awaiting ? Icons.bolt : Icons.memory, color: e.awaiting ? Colors.amber : null),
      title: Text(e.advName ?? 'ESP ${e.deviceId}'),
      subtitle: Text('${e.deviceId} · ${e.rssi} dBm${e.awaiting ? ' · awaiting script' : ''}'),
      onTap: () => Navigator.pop(context, e.deviceId),
    );
  }

  Widget _knownTile(Device d) {
    return ListTile(
      leading: const Icon(Icons.memory, color: Colors.grey),
      title: Text(d.name ?? 'ESP ${d.id}'),
      subtitle: Text(d.id),
      enabled: true,
      onTap: () => Navigator.pop(context, d.id),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String text;
  const _SectionHeader(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: Text(text, style: Theme.of(context).textTheme.labelLarge),
      );
}
