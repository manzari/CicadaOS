import 'dart:convert';

/// The `.cicada` import/export envelope (plan "Script file format"):
/// `{"format":"cicada-script","version":1,"name":..,"body":..,"modifiedAt":..}`.
/// Bare `.py` is also accepted on import (name = filename).
class CicadaScriptFile {
  static const formatId = 'cicada-script';
  static const formatVersion = 1;
  static const extension = 'cicada';
  static const mimeType = 'application/x-cicada-script';

  final String name;
  final String body;
  final DateTime? modifiedAt;

  const CicadaScriptFile({required this.name, required this.body, this.modifiedAt});

  String toJsonString() {
    return const JsonEncoder.withIndent('  ').convert({
      'format': formatId,
      'version': formatVersion,
      'name': name,
      'body': body,
      'modifiedAt': (modifiedAt ?? DateTime.now()).toUtc().toIso8601String(),
    });
  }

  /// Suggested export filename, sanitised.
  String get fileName {
    final safe = name.replaceAll(RegExp(r'[^A-Za-z0-9._ -]'), '_').trim();
    return '${safe.isEmpty ? 'script' : safe}.$extension';
  }

  /// Parse imported bytes. A `.cicada` JSON envelope is preferred; anything that
  /// isn't valid JSON with our format id is treated as raw MicroPython source
  /// (bare `.py`), named from [filenameFallback].
  factory CicadaScriptFile.fromBytes(List<int> bytes, {String? filenameFallback}) {
    final text = _decode(bytes);
    final trimmed = text.trimLeft();
    if (trimmed.startsWith('{')) {
      try {
        final map = jsonDecode(text);
        if (map is Map && map['format'] == formatId && map['body'] is String) {
          return CicadaScriptFile(
            name: (map['name'] as String?)?.trim().isNotEmpty == true
                ? map['name'] as String
                : _nameFromFile(filenameFallback),
            body: map['body'] as String,
            modifiedAt: DateTime.tryParse(map['modifiedAt'] as String? ?? ''),
          );
        }
      } catch (_) {
        // fall through to raw-source handling
      }
    }
    return CicadaScriptFile(name: _nameFromFile(filenameFallback), body: text);
  }

  static String _nameFromFile(String? path) {
    if (path == null || path.trim().isEmpty) return 'imported';
    var base = path.split(RegExp(r'[/\\]')).last;
    final dot = base.lastIndexOf('.');
    if (dot > 0) base = base.substring(0, dot);
    return base.isEmpty ? 'imported' : base;
  }

  static String _decode(List<int> bytes) {
    try {
      return utf8.decode(bytes);
    } catch (_) {
      return latin1.decode(bytes);
    }
  }
}
