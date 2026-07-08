import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/database.dart';
import '../import_export/import_export_service.dart';
import '../push/device_picker.dart';

class ScriptLibraryScreen extends ConsumerStatefulWidget {
  const ScriptLibraryScreen({super.key});

  @override
  ConsumerState<ScriptLibraryScreen> createState() => _ScriptLibraryScreenState();
}

class _ScriptLibraryScreenState extends ConsumerState<ScriptLibraryScreen> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final scriptsAsync = ref.watch(scriptsStreamProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Scripts'),
        actions: [
          IconButton(
            tooltip: 'Import',
            icon: const Icon(Icons.file_open_outlined),
            onPressed: _import,
          ),
          IconButton(
            tooltip: 'Devices',
            icon: const Icon(Icons.memory),
            onPressed: () => context.push('/devices'),
          ),
          IconButton(
            tooltip: 'Signing key',
            icon: const Icon(Icons.key),
            onPressed: () => context.push('/key'),
          ),
          PopupMenuButton<String>(
            onSelected: (v) {
              if (v == 'restore') _restoreExamples();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(
                value: 'restore',
                child: ListTile(
                  leading: Icon(Icons.auto_awesome_outlined),
                  title: Text('Restore examples'),
                ),
              ),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: SearchBar(
              hintText: 'Search scripts',
              leading: const Icon(Icons.search),
              onChanged: (v) => setState(() => _query = v),
            ),
          ),
          Expanded(
            child: scriptsAsync.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('Error: $e')),
              data: (scripts) {
                final filtered = _query.isEmpty
                    ? scripts
                    : scripts
                        .where((s) =>
                            s.name.toLowerCase().contains(_query.toLowerCase()) ||
                            s.body.toLowerCase().contains(_query.toLowerCase()))
                        .toList();
                if (filtered.isEmpty) {
                  return Center(
                    child: Text(
                      scripts.isEmpty ? 'No scripts yet.\nTap + to create one.' : 'No matches.',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  );
                }
                return ListView.separated(
                  itemCount: filtered.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, i) => _tile(filtered[i]),
                );
              },
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push('/editor'),
        icon: const Icon(Icons.add),
        label: const Text('New'),
      ),
    );
  }

  Widget _tile(Script s) {
    final firstLine = s.body.split('\n').firstWhere((l) => l.trim().isNotEmpty, orElse: () => '');
    return ListTile(
      title: Text(s.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(firstLine, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontFamily: 'monospace')),
      onTap: () => context.push('/editor?id=${s.id}'),
      trailing: PopupMenuButton<String>(
        onSelected: (v) => _onAction(v, s),
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'push', child: ListTile(leading: Icon(Icons.upload), title: Text('Push to…'))),
          PopupMenuItem(value: 'duplicate', child: ListTile(leading: Icon(Icons.copy), title: Text('Duplicate'))),
          PopupMenuItem(value: 'share', child: ListTile(leading: Icon(Icons.ios_share), title: Text('Share'))),
          PopupMenuItem(value: 'delete', child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Delete'))),
        ],
      ),
    );
  }

  Future<void> _onAction(String action, Script s) async {
    final repo = ref.read(scriptsRepoProvider);
    switch (action) {
      case 'push':
        final deviceId = await pickDevice(context, ref);
        if (deviceId != null && mounted) {
          context.push('/push?device=$deviceId&script=${s.id}');
        }
        break;
      case 'duplicate':
        await repo.duplicate(s.id);
        break;
      case 'share':
        await ImportExportService.shareScript(s);
        break;
      case 'delete':
        await _confirmDelete(s);
        break;
    }
  }

  Future<void> _confirmDelete(Script s) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Delete "${s.name}"?'),
        content: const Text('This also clears it as any device\'s default script.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (ok == true) {
      await ref.read(scriptsRepoProvider).delete(s.id);
    }
  }

  Future<void> _restoreExamples() async {
    final added = await ref.read(examplesSeederProvider).restore();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(added == 0
            ? 'All examples already present.'
            : 'Restored $added example${added == 1 ? '' : 's'}.'),
      ),
    );
  }

  Future<void> _import() async {
    final file = await ImportExportService.pickFile();
    if (file == null || !mounted) return;
    final repo = ref.read(scriptsRepoProvider);
    final script = await ImportExportService.importAsNew(repo, file);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Imported "${script.name}"')),
    );
    context.push('/editor?id=${script.id}');
  }
}
