import 'package:cicadaos/data/database.dart';
import 'package:cicadaos/data/examples_seeder.dart';
import 'package:cicadaos/data/scripts_repository.dart';
import 'package:cicadaos/data/settings_repository.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // rootBundle asset loading requires an initialized binding.
  TestWidgetsFlutterBinding.ensureInitialized();

  late AppDatabase db;
  late ScriptsRepository scripts;
  late SettingsRepository settings;
  late ExamplesSeeder seeder;

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    scripts = ScriptsRepository(db);
    settings = SettingsRepository(db);
    seeder = ExamplesSeeder(scripts, settings);
  });

  tearDown(() => db.close());

  test('seedOnFirstBoot loads every catalog example, once', () async {
    await seeder.seedOnFirstBoot();
    final all = await scripts.getAll();
    expect(all.length, ExamplesSeeder.catalog.length);
    expect(
      all.map((s) => s.name).toSet(),
      ExamplesSeeder.catalog.map((e) => e.$2).toSet(),
    );
    // Bodies come from the real bundled assets, not placeholders.
    final hello = all.firstWhere((s) => s.name == '01 · Hello');
    expect(hello.body, contains('import cicada_ui'));

    // Second boot is a no-op (flag set) — no duplicates.
    await seeder.seedOnFirstBoot();
    expect((await scripts.getAll()).length, ExamplesSeeder.catalog.length);
  });

  test('restore re-adds a deleted example without touching user scripts',
      () async {
    await seeder.seedOnFirstBoot();
    final mine = await scripts.create(name: 'mine', body: 'x = 1');
    final ticker = (await scripts.getAll())
        .firstWhere((s) => s.name == '08 · Ticker');
    await scripts.delete(ticker.id);

    final added = await seeder.restore();
    expect(added, 1);
    final names = (await scripts.getAll()).map((s) => s.name).toList();
    expect(names, contains('08 · Ticker'));
    expect(names, contains('mine'));
    // The surviving user script keeps its original id (not recreated).
    expect(await scripts.getById(mine.id), isNotNull);
  });

  test('restore is idempotent when nothing is missing', () async {
    await seeder.seedOnFirstBoot();
    expect(await seeder.restore(), 0);
  });

  test('examples sort with 01 at the top of the library', () async {
    await seeder.seedOnFirstBoot();
    final ordered = await scripts.getAll(); // modifiedAt desc
    expect(ordered.first.name, '01 · Hello');
    expect(ordered.last.name, ExamplesSeeder.catalog.last.$2);
  });
}
