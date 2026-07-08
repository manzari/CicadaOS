import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/providers.dart';
import 'app/router.dart';
import 'features/boot_watch/boot_watch_service.dart';
import 'features/import_export/incoming_share.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: CicadaOSApp()));
}

class CicadaOSApp extends ConsumerStatefulWidget {
  const CicadaOSApp({super.key});

  @override
  ConsumerState<CicadaOSApp> createState() => _CicadaOSAppState();
}

class _CicadaOSAppState extends ConsumerState<CicadaOSApp> {
  @override
  void initState() {
    super.initState();
    // First launch: seed the library with the bundled example scripts.
    ref.read(examplesSeederProvider).seedOnFirstBoot();
    // Listen for scripts shared/opened from other apps (Task 5).
    IncomingShare.instance.attach(ref);
    // Boot-watch: an ESP booted → jump straight into an auto-push of its default.
    BootWatchService.instance.attach((deviceId, auto) {
      router.go('/push?device=$deviceId${auto ? '&auto=1' : ''}');
    });
  }

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF2E7D32); // cicada green
    return MaterialApp.router(
      title: 'CicadaOS',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark),
        useMaterial3: true,
      ),
      routerConfig: router,
    );
  }
}
