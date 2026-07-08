import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:re_editor/re_editor.dart';
import 'package:re_highlight/languages/python.dart';
import 'package:re_highlight/styles/atom-one-dark.dart';

import '../../app/providers.dart';
import '../import_export/import_export_service.dart';
import '../push/device_picker.dart';

class EditorScreen extends ConsumerStatefulWidget {
  final int? scriptId;
  const EditorScreen({super.key, this.scriptId});

  @override
  ConsumerState<EditorScreen> createState() => _EditorScreenState();
}

class _EditorScreenState extends ConsumerState<EditorScreen> {
  final _code = CodeLineEditingController();
  final _nameController = TextEditingController();
  Timer? _debounce;
  bool _loaded = false;

  String get _draftKey => 'draft:${widget.scriptId ?? 'new'}';

  @override
  void initState() {
    super.initState();
    _load();
    _code.addListener(_onChanged);
  }

  Future<void> _load() async {
    final settings = ref.read(settingsRepoProvider);
    final raw = await settings.getString(_draftKey);
    // Empty string means "draft cleared on save" — treat as no draft so we fall
    // back to the stored body instead of showing a blank editor.
    final draft = (raw != null && raw.isNotEmpty) ? raw : null;
    if (widget.scriptId != null) {
      final s = await ref.read(scriptsRepoProvider).getById(widget.scriptId!);
      _nameController.text = s?.name ?? '';
      // A saved draft is newer than the stored body — prefer it.
      _code.text = draft ?? s?.body ?? '';
    } else {
      _code.text = draft ?? '';
    }
    setState(() => _loaded = true);
  }

  void _onChanged() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () {
      // Persist the draft to the DB so it survives process death.
      ref.read(settingsRepoProvider).setString(_draftKey, _code.text);
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _code.removeListener(_onChanged);
    _code.dispose();
    _nameController.dispose();
    super.dispose();
  }

  Future<int?> _save() async {
    final name = _nameController.text.trim().isEmpty ? 'untitled' : _nameController.text.trim();
    final body = _code.text;
    final repo = ref.read(scriptsRepoProvider);
    int id;
    if (widget.scriptId != null) {
      await repo.updateScript(widget.scriptId!, name: name, body: body);
      id = widget.scriptId!;
    } else {
      id = (await repo.create(name: name, body: body)).id;
    }
    await ref.read(settingsRepoProvider).setString(_draftKey, ''); // clear draft
    return id;
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return PopScope(
      canPop: true,
      child: Scaffold(
        appBar: AppBar(
          title: TextField(
            controller: _nameController,
            decoration: const InputDecoration(
              hintText: 'Script name',
              border: InputBorder.none,
            ),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          actions: [
            if (widget.scriptId != null)
              IconButton(
                tooltip: 'Share',
                icon: const Icon(Icons.ios_share),
                onPressed: _share,
              ),
            IconButton(
              tooltip: 'Save',
              icon: const Icon(Icons.save_outlined),
              onPressed: () async {
                final messenger = ScaffoldMessenger.of(context);
                await _save();
                messenger.showSnackBar(const SnackBar(content: Text('Saved')));
              },
            ),
          ],
        ),
        body: CodeEditor(
          controller: _code,
          wordWrap: false,
          style: CodeEditorStyle(
            fontSize: 14,
            fontFamily: 'monospace',
            codeTheme: CodeHighlightTheme(
              languages: {'python': CodeHighlightThemeMode(mode: langPython)},
              theme: atomOneDarkTheme,
            ),
          ),
        ),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: _pushFlow,
          icon: const Icon(Icons.upload),
          label: const Text('Push to…'),
        ),
      ),
    );
  }

  Future<void> _share() async {
    final id = await _save();
    if (id == null) return;
    final s = await ref.read(scriptsRepoProvider).getById(id);
    if (s != null) await ImportExportService.shareScript(s);
  }

  Future<void> _pushFlow() async {
    final id = await _save(); // always push the saved bytes
    if (id == null || !mounted) return;
    final deviceId = await pickDevice(context, ref);
    if (deviceId != null && mounted) {
      context.push('/push?device=$deviceId&script=$id');
    }
  }
}
