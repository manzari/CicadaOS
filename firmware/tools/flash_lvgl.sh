#!/usr/bin/env bash
# Flash the LVGL+BLE firmware to the Waveshare ESP32-S3-Touch-LCD-1.47, then copy
# the device-side Python (loader + verify/decrypt shims + display helper). RUN ON
# THE HOST — needs USB serial access to the board, which a container can't see.
#
# Prereqs on host:  pip install esptool mpremote
# Usage:            ./flash_lvgl.sh [PORT]     (PORT default: auto-detect)
#
# The firmware image is the merged single-file build produced in Docker
# (BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT):
#   ~/cicada-lvgl-build/.../build-ESP32_GENERIC_S3-SPIRAM_OCT/firmware.bin  (flash at 0x0)
set -euo pipefail

PORT="${1:-}"                       # e.g. /dev/ttyACM0 (S3 USB-serial-JTAG); empty = auto
CHIP="esp32s3"
BIN="${FW_BIN:-$HOME/cicada-lvgl-build/lvgl_micropython/lib/micropython/ports/esp32/build-ESP32_GENERIC_S3-SPIRAM_OCT/firmware.bin}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"    # firmware/

[ -f "$BIN" ] || { echo "firmware not found: $BIN"; exit 1; }

port_args=(); mpr_port=()
if [ -n "$PORT" ]; then port_args=(--port "$PORT"); mpr_port=("connect" "$PORT"); fi

echo ">> Erasing flash (wipes old stock-MP filesystem + partition layout)…"
esptool --chip "$CHIP" "${port_args[@]}" erase_flash

echo ">> Writing firmware.bin @ 0x0 …"
esptool --chip "$CHIP" "${port_args[@]}" -b 460800 \
  --before default_reset --after hard_reset \
  write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \
  0x0 "$BIN"

echo ">> Waiting for the board to re-enumerate…"
sleep 3

echo ">> Copying device-side Python (loader + verify/decrypt shims + display helper)…"
mpremote "${mpr_port[@]}" fs cp "$HERE/main.py" "$HERE/ed25519.py" "$HERE/cryptobox.py" :
mpremote "${mpr_port[@]}" fs cp "$HERE/examples/cicada_ui.py" :cicada_ui.py
mpremote "${mpr_port[@]}" fs cp "$HERE/lifecycle_ui.py" :lifecycle_ui.py

echo ">> Sanity: confirm the native modules are present…"
mpremote "${mpr_port[@]}" exec "import lvgl, lcd_bus, jd9853, i2c, axs5106, task_handler, bluetooth; print('modules OK')"

cat <<'DONE'

Flashed + provisioned. Next:
  # prove BLE + LVGL coexist (owns BLE; runs instead of the loader):
  mpremote run firmware/tools/ble_lvgl_smoketest.py
  # or push an example over BLE via tools/push_script.py

Note: the prod firmware.bin includes native ced25519 (verify ~240 ms vs tens of
seconds pure-Python). Confirm with:
  mpremote exec "import ced25519; from ed25519 import NATIVE; print('native', NATIVE)"
The S3R8 has 8 MB PSRAM, so LVGL framebuffers + NimBLE fit comfortably; grow the
app partition only if the default doesn't hold LVGL + NimBLE + Monocypher.
End-to-end target: signed push -> OK:done, --bad-sig -> ERR:sig, --replay -> ERR:sig.
DONE
