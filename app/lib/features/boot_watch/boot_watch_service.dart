import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Dart side of the native boot-watch (Task 8, Android). Registers the known
/// device ids to watch and relays the "an ESP booted → push its default" action
/// back into the app as a navigation event.
///
/// iOS: background service-UUID scanning is best-effort and unavailable when the
/// user force-quits the app — the platform channel simply no-ops there for now.
class BootWatchService {
  BootWatchService._();
  static final BootWatchService instance = BootWatchService._();

  static const _channel = MethodChannel('cicadaos/boot_watch');

  void Function(String deviceId, bool auto)? _onPush;

  /// Wire the push callback and drain any cold-start launch intent.
  Future<void> attach(void Function(String deviceId, bool auto) onPush) async {
    _onPush = onPush;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'onBootPush') {
        final m = (call.arguments as Map).cast<String, dynamic>();
        _onPush?.call(m['device'] as String, (m['auto'] as bool?) ?? true);
      }
    });
    try {
      final launch = await _channel.invokeMethod('consumeLaunch');
      if (launch is Map) {
        _onPush?.call(launch['device'] as String, (launch['auto'] as bool?) ?? true);
      }
    } on MissingPluginException {
      // iOS / unsupported platform — ignore.
    }
  }

  Future<void> enable(List<String> deviceIds) async {
    await _requestNotificationPermission();
    try {
      await _channel.invokeMethod('enable', {'deviceIds': deviceIds});
    } on MissingPluginException {
      // no-op off Android
    }
  }

  Future<void> disable() async {
    try {
      await _channel.invokeMethod('disable');
    } on MissingPluginException {
      // no-op off Android
    }
  }

  Future<void> _requestNotificationPermission() async {
    final android = FlutterLocalNotificationsPlugin()
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    await android?.requestNotificationsPermission();
  }
}
