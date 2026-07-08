import 'package:flutter/services.dart' show rootBundle;

import 'scripts_repository.dart';
import 'settings_repository.dart';

/// Seeds the bundled example scripts (see `assets/examples/`) into the library.
/// Runs once on first boot, and again on demand via "Restore examples".
class ExamplesSeeder {
  static const _dir = 'assets/examples';

  /// Curated (asset file, library name), in display order.
  static const List<(String, String)> catalog = [
    ('01_hello.py', '01 · Hello'),
    ('02_status.py', '02 · Status card'),
    ('03_arc.py', '03 · Progress arc'),
    ('04_rainbow.py', '04 · Rainbow'),
    ('05_dashboard.py', '05 · Bike dashboard'),
    ('06_chart.py', '06 · Live chart'),
    ('07_selftest.py', '07 · Self-test'),
    ('08_ticker.py', '08 · Ticker'),
    ('09_serial.py', '09 · Serial monitor'),
  ];

  final ScriptsRepository _scripts;
  final SettingsRepository _settings;
  ExamplesSeeder(this._scripts, this._settings);

  /// On the very first launch, populate the empty library with the examples.
  Future<void> seedOnFirstBoot() async {
    if (await _settings.getBool(SettingsRepository.kExamplesSeeded)) return;
    await restore();
    await _settings.setBool(SettingsRepository.kExamplesSeeded, true);
  }

  /// Add any catalog examples not already present (matched by name). Existing
  /// user scripts are never touched; deleted examples are brought back.
  /// Returns the number of scripts added.
  Future<int> restore() async {
    final existing = (await _scripts.getAll()).map((s) => s.name).toSet();
    final base = DateTime.now();
    var added = 0;
    for (var i = 0; i < catalog.length; i++) {
      final (file, name) = catalog[i];
      if (existing.contains(name)) continue;
      final body = await rootBundle.loadString('$_dir/$file');
      // Newest modifiedAt sorts to the top, so offset so 01 lands first.
      await _scripts.create(
        name: name,
        body: body,
        at: base.add(Duration(seconds: catalog.length - i)),
      );
      added++;
    }
    return added;
  }
}
