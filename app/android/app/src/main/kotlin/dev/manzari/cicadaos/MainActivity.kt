package dev.manzari.cicadaos

import android.content.Context
import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "cicadaos/boot_watch"
    private var methodChannel: MethodChannel? = null
    private var pendingLaunch: Map<String, Any>? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val ch = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
        methodChannel = ch
        ch.setMethodCallHandler { call, result ->
            when (call.method) {
                "enable" -> {
                    val ids = call.argument<List<String>>("deviceIds") ?: emptyList()
                    BootWatch.enable(this, ids)
                    result.success(null)
                }
                "disable" -> {
                    BootWatch.disable(this)
                    result.success(null)
                }
                // Returns a cold-start boot-watch launch (device/auto) once.
                "consumeLaunch" -> {
                    val l = pendingLaunch
                    pendingLaunch = null
                    result.success(l)
                }
                else -> result.notImplemented()
            }
        }
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val device = intent?.getStringExtra("boot_watch_push_device") ?: return
        // Fix 8: default auto=false, and only honour it when the launch carries
        // the one-time token our own notification PendingIntent set. This blocks
        // any co-installed app from driving a silent auto-push via the exported
        // activity — an unqualified external launch at most opens the push screen.
        val prefs = getSharedPreferences(BootWatch.PREFS, Context.MODE_PRIVATE)
        val expected = prefs.getString(BootWatch.KEY_AUTOPUSH_TOKEN, null)
        val token = intent.getStringExtra("boot_watch_token")
        val trusted = expected != null && token != null && token == expected
        if (trusted) {
            prefs.edit().remove(BootWatch.KEY_AUTOPUSH_TOKEN).apply() // one-time use
        }
        val auto = trusted && intent.getBooleanExtra("boot_watch_auto", false)
        val launch = mapOf("device" to device, "auto" to auto)
        pendingLaunch = launch
        methodChannel?.invokeMethod("onBootPush", launch)
    }
}
