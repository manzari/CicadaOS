package dev.manzari.cicadaos

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.bluetooth.BluetoothAdapter
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent

/**
 * Boot-watch: a PendingIntent-based BLE scan that survives app death
 * (CLAUDE.md). The OS delivers matching advertisements to [BootWatchReceiver] even
 * when our process is gone, so we can notify the user the moment a known ESP
 * boots (advertises the "awaiting script" manufacturer flag).
 *
 * NOTE: verify on a physical device. If PendingIntent scanning proves unreliable
 * on a target OEM, fall back to a foreground service while boot-watch is on.
 */
object BootWatch {
    const val COMPANY_ID = 0xFFFF
    val MAGIC = byteArrayOf(0xC1.toByte(), 0xCA.toByte())
    const val PREFS = "boot_watch"
    const val KEY_DEVICES = "device_ids"
    // One-time token proving an auto-push launch came from our own notification
    // PendingIntent, not an arbitrary co-installed app.
    const val KEY_AUTOPUSH_TOKEN = "autopush_token"
    private const val SCAN_ACTION = "dev.manzari.cicadaos.SCAN_RESULT"

    private fun scannerIntent(context: Context): PendingIntent {
        val intent = Intent(context, BootWatchReceiver::class.java).setAction(SCAN_ACTION)
        return PendingIntent.getBroadcast(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        )
    }

    @SuppressLint("MissingPermission")
    fun enable(context: Context, deviceIds: List<String>) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putStringSet(KEY_DEVICES, deviceIds.toSet()).apply()
        val scanner = BluetoothAdapter.getDefaultAdapter()?.bluetoothLeScanner ?: return
        // Match our manufacturer payload with the awaiting bit set:
        // data = magic(2) + flags; mask locks magic exactly + only the awaiting bit.
        val data = byteArrayOf(MAGIC[0], MAGIC[1], 0x01)
        val mask = byteArrayOf(0xFF.toByte(), 0xFF.toByte(), 0x01)
        val filter = ScanFilter.Builder()
            .setManufacturerData(COMPANY_ID, data, mask)
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER)
            .build()
        scanner.startScan(listOf(filter), settings, scannerIntent(context))
    }

    @SuppressLint("MissingPermission")
    fun disable(context: Context) {
        val scanner = BluetoothAdapter.getDefaultAdapter()?.bluetoothLeScanner ?: return
        scanner.stopScan(scannerIntent(context))
    }
}
