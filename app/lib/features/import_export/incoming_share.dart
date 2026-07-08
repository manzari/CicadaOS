import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_handler/share_handler.dart';

import '../../app/providers.dart';
import '../../app/router.dart';
import '../../data/script_format.dart';
import 'import_export_service.dart';

/// Handles scripts shared into the app from other apps / opened from Files
/// (Task 5). Imports them and jumps to the editor so the user sees the result.
class IncomingShare {
  IncomingShare._();
  static final IncomingShare instance = IncomingShare._();

  bool _attached = false;

  Future<void> attach(WidgetRef ref) async {
    if (_attached) return;
    _attached = true;
    final handler = ShareHandler.instance;
    final initial = await handler.getInitialSharedMedia();
    if (initial != null) await _handle(ref, initial);
    handler.sharedMediaStream.listen((m) => _handle(ref, m));
  }

  Future<void> _handle(WidgetRef ref, SharedMedia media) async {
    final repo = ref.read(scriptsRepoProvider);
    int? lastId;

    for (final a in media.attachments ?? const []) {
      if (a == null) continue;
      try {
        final bytes = await File(a.path).readAsBytes();
        final file = CicadaScriptFile.fromBytes(bytes, filenameFallback: a.path);
        lastId = (await ImportExportService.importAsNew(repo, file)).id;
      } catch (_) {
        // skip anything unreadable; never crash on a bad share
      }
    }

    final text = media.content?.trim() ?? '';
    if (lastId == null && text.isNotEmpty) {
      final file = CicadaScriptFile(name: 'shared', body: text);
      lastId = (await ImportExportService.importAsNew(repo, file)).id;
    }

    if (lastId != null) {
      router.go('/editor?id=$lastId');
    }
  }
}
