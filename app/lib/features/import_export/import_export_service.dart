import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../data/database.dart';
import '../../data/script_format.dart';
import '../../data/scripts_repository.dart';

/// Import/export of `.cicada` (and bare `.py`) scripts (Task 5).
class ImportExportService {
  /// Export a script as a `.cicada` file and hand it to the system share sheet.
  /// Secret scripts are never exported in cleartext (Fix 6): sharing one throws.
  static Future<void> shareScript(Script s) async {
    if (s.isSecret) {
      throw StateError('refusing to export a secret script in cleartext');
    }
    final file =
        CicadaScriptFile(name: s.name, body: s.body, modifiedAt: s.modifiedAt);
    final dir = await getTemporaryDirectory();
    final path = p.join(dir.path, file.fileName);
    await File(path).writeAsString(file.toJsonString());
    await SharePlus.instance.share(ShareParams(
      files: [
        XFile(path, mimeType: CicadaScriptFile.mimeType, name: file.fileName)
      ],
      subject: s.name,
    ));
  }

  /// Let the user pick a script file from storage; parse it. Null if cancelled.
  static Future<CicadaScriptFile?> pickFile() async {
    final res = await FilePicker.platform.pickFiles(withData: true);
    if (res == null || res.files.isEmpty) return null;
    final pf = res.files.first;
    final bytes = pf.bytes ??
        (pf.path != null ? await File(pf.path!).readAsBytes() : null);
    if (bytes == null) return null;
    return CicadaScriptFile.fromBytes(bytes, filenameFallback: pf.name);
  }

  /// Create a script from an imported file, giving it a collision-free name.
  static Future<Script> importAsNew(
      ScriptsRepository repo, CicadaScriptFile file) async {
    final existing = (await repo.getAll()).map((e) => e.name).toSet();
    return repo.create(name: uniqueName(existing, file.name), body: file.body);
  }

  /// "name", then "name (2)", "name (3)", … until unused.
  static String uniqueName(Set<String> taken, String desired) {
    final base = desired.trim().isEmpty ? 'imported' : desired.trim();
    if (!taken.contains(base)) return base;
    for (var i = 2;; i++) {
      final candidate = '$base ($i)';
      if (!taken.contains(candidate)) return candidate;
    }
  }
}
