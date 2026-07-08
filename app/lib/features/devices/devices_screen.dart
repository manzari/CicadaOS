import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/settings_repository.dart';
import '../boot_watch/boot_watch_service.dart';
import '../push/device_picker.dart';

class DevicesScreen extends ConsumerWidget {
  const DevicesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final devicesAsync = ref.watch(devicesStreamProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Devices'),
        actions: const [_BootWatchToggle()],
      ),
      body: devicesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (devices) {
          if (devices.isEmpty) {
            return const Center(
              child: Text('No known ESPs yet.\nTap Scan to discover one.',
                  textAlign: TextAlign.center),
            );
          }
          return ListView.separated(
            itemCount: devices.length,
            separatorBuilder: (_, _) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final d = devices[i];
              return ListTile(
                leading: const Icon(Icons.memory),
                title: Text(d.name ?? 'ESP ${d.id}'),
                subtitle: Text(d.id),
                trailing: d.defaultScriptId != null
                    ? const Icon(Icons.star, size: 18, color: Colors.amber)
                    : null,
                onTap: () => context.push('/device/${d.id}'),
              );
            },
          );
        },
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final id = await pickDevice(context, ref);
          if (id != null && context.mounted) context.push('/device/$id');
        },
        icon: const Icon(Icons.bluetooth_searching),
        label: const Text('Scan'),
      ),
    );
  }
}

/// Enables/disables the native background boot-watch, re-registering the current
/// set of known device ids whenever it is turned on.
class _BootWatchToggle extends ConsumerWidget {
  const _BootWatchToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsRepoProvider);
    return StreamBuilder<bool>(
      stream: settings.watchBool(SettingsRepository.kBootWatchEnabled),
      builder: (context, snap) {
        final enabled = snap.data ?? false;
        return Row(
          children: [
            const Tooltip(message: 'Notify on ESP boot', child: Icon(Icons.notifications_active_outlined)),
            Switch(
              value: enabled,
              onChanged: (v) async {
                await settings.setBool(SettingsRepository.kBootWatchEnabled, v);
                if (v) {
                  final ids = (await ref.read(devicesRepoProvider).getAll())
                      .map((d) => d.id)
                      .toList();
                  await BootWatchService.instance.enable(ids);
                } else {
                  await BootWatchService.instance.disable();
                }
              },
            ),
          ],
        );
      },
    );
  }
}
