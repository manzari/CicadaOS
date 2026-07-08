import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../features/devices/device_detail_screen.dart';
import '../features/devices/devices_screen.dart';
import '../features/devices/key_screen.dart';
import '../features/push/push_screen.dart';
import '../features/scripts/editor_screen.dart';
import '../features/scripts/script_library_screen.dart';

final router = GoRouter(
  routes: [
    GoRoute(
      path: '/',
      builder: (context, state) => const ScriptLibraryScreen(),
    ),
    GoRoute(
      path: '/editor',
      builder: (context, state) {
        final id = state.uri.queryParameters['id'];
        return EditorScreen(scriptId: id == null ? null : int.tryParse(id));
      },
    ),
    GoRoute(
      path: '/devices',
      builder: (context, state) => const DevicesScreen(),
    ),
    GoRoute(
      path: '/device/:id',
      builder: (context, state) =>
          DeviceDetailScreen(deviceId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/key',
      builder: (context, state) => const KeyScreen(),
    ),
    GoRoute(
      // /push?device=<id>&script=<scriptId>&auto=1  (auto = boot-watch action)
      path: '/push',
      builder: (context, state) {
        final q = state.uri.queryParameters;
        return PushScreen(
          scriptId: int.tryParse(q['script'] ?? ''),
          deviceId: q['device'],
          auto: q['auto'] == '1',
        );
      },
    ),
  ],
  errorBuilder: (context, state) => Scaffold(
    appBar: AppBar(title: const Text('Not found')),
    body: Center(child: Text(state.error?.toString() ?? 'Unknown route')),
  ),
);
