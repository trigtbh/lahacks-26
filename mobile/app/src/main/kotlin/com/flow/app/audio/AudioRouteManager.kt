package com.flow.app.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager

data class AudioRouteResult(
    val routedToPreferredDevice: Boolean,
    val message: String,
)

class AudioRouteManager(context: Context) {

    private val audioManager = context.getSystemService(AudioManager::class.java)

    fun routeToPreferredInput(): AudioRouteResult {
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        audioManager.isSpeakerphoneOn = false

        val preferred = audioManager.availableCommunicationDevices.firstOrNull { device ->
            device.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
                device.type == AudioDeviceInfo.TYPE_BLE_HEADSET ||
                device.type == AudioDeviceInfo.TYPE_WIRED_HEADSET ||
                device.type == AudioDeviceInfo.TYPE_USB_HEADSET
        }

        return if (preferred != null) {
            audioManager.setCommunicationDevice(preferred)
            try {
                @Suppress("DEPRECATION")
                audioManager.startBluetoothSco()
            } catch (_: Throwable) {
                // Best effort only.
            }
            AudioRouteResult(
                routedToPreferredDevice = true,
                message = "Routed audio to ${preferred.productName} (${deviceTypeName(preferred.type)})",
            )
        } else {
            AudioRouteResult(
                routedToPreferredDevice = false,
                message = "No Bluetooth/glasses audio route found; refusing device mic fallback",
            )
        }
    }

    fun clearRoute() {
        try {
            audioManager.clearCommunicationDevice()
        } catch (_: Throwable) {
            // ignore
        }
        try {
            @Suppress("DEPRECATION")
            audioManager.stopBluetoothSco()
        } catch (_: Throwable) {
            // ignore
        }
        audioManager.mode = AudioManager.MODE_NORMAL
    }

    private fun deviceTypeName(type: Int): String = when (type) {
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bluetooth_sco"
        AudioDeviceInfo.TYPE_BLE_HEADSET -> "ble_headset"
        AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wired_headset"
        AudioDeviceInfo.TYPE_USB_HEADSET -> "usb_headset"
        else -> "type_$type"
    }
}
