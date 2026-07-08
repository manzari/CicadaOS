import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/database.dart';

class DeviceDetailScreen extends ConsumerWidget {
  final String deviceId;
  const DeviceDetailScreen({super.key, required this.deviceId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deviceStream = ref.watch(devicesRepoProvider).watchById(deviceId);
    final scriptsAsync = ref.watch(scriptsStreamProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Device')),
      body: StreamBuilder<Device?>(
        stream: deviceStream,
        builder: (context, snap) {
          final device = snap.data;
          if (device == null) {
            return const Center(child: Text('Device not found.'));
          }
          final scripts = scriptsAsync.value ?? const [];
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              ListTile(
                leading: const Icon(Icons.memory),
                title: Text(device.name ?? 'ESP ${device.id}'),
                subtitle: Text('ID: ${device.id}'),
                trailing: IconButton(
                  icon: const Icon(Icons.edit),
                  onPressed: () => _rename(context, ref, device),
                ),
              ),
              if (device.lastSeen != null)
                ListTile(dense: true, leading: const Icon(Icons.visibility), title: Text('Last seen: ${device.lastSeen}')),
              if (device.lastPairedAt != null)
                ListTile(dense: true, leading: const Icon(Icons.link), title: Text('Last paired: ${device.lastPairedAt}')),
              const Divider(height: 32),
              Text('Encryption key', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                'Scripts are encrypted to this device\'s X25519 public key. Set it '
                'from the value printed when the board was provisioned. Without it, '
                'pushes are refused.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              ListTile(
                dense: true,
                leading: Icon(device.x25519PubKey == null ? Icons.lock_open : Icons.lock,
                    color: device.x25519PubKey == null ? Colors.orange : Colors.green),
                title: Text(device.x25519PubKey == null
                    ? 'No key pinned'
                    : '${device.x25519PubKey!.substring(0, 16)}…'),
                trailing: IconButton(
                  icon: const Icon(Icons.key),
                  onPressed: () => _pinKey(context, ref, device),
                ),
              ),
              const Divider(height: 32),
              Text('Default script', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text('Pushed on boot when this ESP is detected.',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 12),
              DropdownButtonFormField<int?>(
                initialValue: scripts.any((s) => s.id == device.defaultScriptId)
                    ? device.defaultScriptId
                    : null,
                decoration: const InputDecoration(border: OutlineInputBorder()),
                items: [
                  const DropdownMenuItem<int?>(value: null, child: Text('None')),
                  ...scripts.map((s) => DropdownMenuItem<int?>(value: s.id, child: Text(s.name))),
                ],
                onChanged: (v) => ref.read(devicesRepoProvider).setDefaultScript(device.id, v),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: device.defaultScriptId == null
                    ? null
                    : () => context.push('/push?device=${device.id}&script=${device.defaultScriptId}'),
                icon: const Icon(Icons.upload),
                label: const Text('Push default now'),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _rename(BuildContext context, WidgetRef ref, Device device) async {
    final controller = TextEditingController(text: device.name ?? '');
    final name = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Rename device'),
        content: TextField(controller: controller, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, controller.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    if (name != null && name.isNotEmpty) {
      await ref.read(devicesRepoProvider).rename(device.id, name);
    }
  }

  Future<void> _pinKey(BuildContext context, WidgetRef ref, Device device) async {
    final controller = TextEditingController(text: device.x25519PubKey ?? '');
    final hex = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Pin X25519 public key'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            hintText: '64 hex chars',
            helperText: 'The device X25519 public key from provisioning',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim().toLowerCase()),
              child: const Text('Pin')),
        ],
      ),
    );
    if (hex == null) return;
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(hex)) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Key must be exactly 64 hex characters')));
      }
      return;
    }
    await ref.read(devicesRepoProvider).pinKey(device.id, hex);
  }
}
