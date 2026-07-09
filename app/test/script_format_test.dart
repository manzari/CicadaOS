import 'dart:convert';

import 'package:cicadaos/data/script_format.dart';
import 'package:cicadaos/features/import_export/import_export_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('CicadaScriptFile', () {
    test('round-trips body byte-identically through .cicada JSON', () {
      const body = "notify('temp=25.1°C ✓')\nfor i in range(3):\n    notify(i)\n";
      final file = CicadaScriptFile(name: 'blink', body: body);
      final bytes = utf8.encode(file.toJsonString());
      final parsed = CicadaScriptFile.fromBytes(bytes);
      expect(parsed.name, 'blink');
      expect(parsed.body, body);
    });

    test('envelope shape matches the spec', () {
      final json = jsonDecode(CicadaScriptFile(name: 'x', body: 'y').toJsonString());
      expect(json['format'], 'cicada-script');
      expect(json['version'], 1);
      expect(json['name'], 'x');
      expect(json['body'], 'y');
      expect(json['modifiedAt'], isA<String>());
    });

    test('imports a bare .py as raw source named from the filename', () {
      final parsed = CicadaScriptFile.fromBytes(
        utf8.encode('led.toggle()\n'),
        filenameFallback: '/tmp/blinker.py',
      );
      expect(parsed.name, 'blinker');
      expect(parsed.body, 'led.toggle()\n');
    });

    test('a JSON blob that is not our format is treated as raw source', () {
      final parsed = CicadaScriptFile.fromBytes(utf8.encode('{"foo": 1}'));
      expect(parsed.body, '{"foo": 1}');
    });

    test('sanitises the export filename', () {
      expect(CicadaScriptFile(name: 'my/script:1', body: '').fileName, 'my_script_1.cicada');
      expect(CicadaScriptFile(name: '', body: '').fileName, 'script.cicada');
    });
  });

  group('uniqueName', () {
    test('suffixes on collision', () {
      final taken = {'blink', 'blink (2)'};
      expect(ImportExportService.uniqueName(taken, 'blink'), 'blink (3)');
      expect(ImportExportService.uniqueName(taken, 'fresh'), 'fresh');
      expect(ImportExportService.uniqueName({}, ''), 'imported');
    });
  });
}
