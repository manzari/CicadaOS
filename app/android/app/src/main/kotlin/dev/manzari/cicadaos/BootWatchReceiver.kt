package dev.manzari.cicadaos

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanResult
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Receives PendingIntent scan results and, for a known ESP advertising the
 * "awaiting script" flag, posts a high-priority notification whose action deep
 * links into the app to push that device's default script (auto=1).
 */
class BootWatchReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        @Suppress("DEPRECATION")
        val results: ArrayList<ScanResult> =
            intent.getParcelableArrayListExtra(BluetoothLeScanner.EXTRA_LIST_SCAN_RESULT)
                ?: return
        val known = context.getSharedPreferences(BootWatch.PREFS, Context.MODE_PRIVATE)
            .getStringSet(BootWatch.KEY_DEVICES, emptySet()) ?: emptySet()

        for (r in results) {
            val mfr = r.scanRecord?.getManufacturerSpecificData(BootWatch.COMPANY_ID) ?: continue
            if (mfr.size < 9) continue
            if (mfr[0] != BootWatch.MAGIC[0] || mfr[1] != BootWatch.MAGIC[1]) continue
            val awaiting = (mfr[2].toInt() and 0x01) != 0
            if (!awaiting) continue
            val id = mfr.copyOfRange(3, 9).joinToString("") { "%02x".format(it) }
            if (id in known) notifyBoot(context, id)
        }
    }

    private fun notifyBoot(context: Context, deviceId: String) {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "ESP boot", NotificationManager.IMPORTANCE_HIGH)
        )
        // Mint a one-time token, embed it in this (immutable) PendingIntent, and
        // store it. MainActivity only honours auto-push when the launch carries
        // the matching token, so a co-installed app that spoofs the extras cannot
        // trigger a silent push (Fix 8).
        val token = java.util.UUID.randomUUID().toString()
        context.getSharedPreferences(BootWatch.PREFS, Context.MODE_PRIVATE).edit()
            .putString(BootWatch.KEY_AUTOPUSH_TOKEN, token).apply()
        val launch = Intent(context, MainActivity::class.java).apply {
            putExtra("boot_watch_push_device", deviceId)
            putExtra("boot_watch_auto", true)
            putExtra("boot_watch_token", token)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pi = PendingIntent.getActivity(
            context, deviceId.hashCode(), launch,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val n = Notification.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("ESP $deviceId booted")
            .setContentText("Send its default script")
            .setAutoCancel(true)
            .setContentIntent(pi)
            .addAction(
                Notification.Action.Builder(null, "Send default script", pi).build()
            )
            .build()
        nm.notify(deviceId.hashCode(), n)
    }

    companion object {
        private const val CHANNEL = "boot_watch"
    }
}
