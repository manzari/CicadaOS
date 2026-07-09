# Building one firmware image: loader (BLE) + LVGL + ced25519

Goal: an `lvgl_micropython` (LVGL 9) image for the Waveshare **ESP32-S3-Touch-LCD-1.47**
(ESP32-S3R8, 16 MB flash / 8 MB octal PSRAM) that also carries the BLE loader (`main.py`)
and the native Ed25519 verifier (`ced25519/`), so the `examples/` scripts can drive the
**JD9853** panel, **AXS5106L** touch, and RGB LED. LVGL + touch are **purely additive** —
they touch none of the nonce/verify/exec path.

This targets kdschlosser's [`lvgl_micropython`](https://github.com/lvgl-micropython/lvgl_micropython),
the same binding the C6 build used (`machine.SPI.Bus` / `lcd_bus` / `task_handler`). Confirm
token spellings against `python3 make.py esp32 --help` first.

## TL;DR — what's easy vs what's the real unknown

| Piece | Effort | Why |
|-------|--------|-----|
| **ESP32-S3R8 target** | **easy** | `BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT` builds via `builder/esp32.py`'s PSRAM branch — the vendored MicroPython ships this board and enables NimBLE. |
| **JD9853 driver + pins** | **easy** | `DISPLAY=jd9853` is a built-in driver (`JD9853(DisplayDriver)`, same constructor as st7789). Pins are runtime (in `examples/cicada_ui.py`); the 34-col offset carries over from the ST7789 sibling and is confirmed by CircuitPython's board.c. |
| **AXS5106L touch** | **easy** | `INDEV=axs5106` is a built-in indev (`AXS5106(PointerDriver)`, addr `0x63`). `PointerDriver` self-registers with LVGL on construction — building it after the display is all the wiring needed. |
| Add `ced25519` C module | **easy** | The builder forwards extra user C modules; our `ced25519/micropython.cmake` works unchanged. |
| RAM budget | **easy (was the C6's real risk)** | 8 MB octal PSRAM. The C6's NimBLE+LVGL-share-512 KB-SRAM contention is **gone** — a full 172×320×2 (~110 KB) framebuffer fits trivially. |
| **JD9853 + AXS5106L integration** | **the real unknown** | Two reported friction points on this exact driver pair — see **Known issues** below. Budget ~½ day here. |

## Known issues to expect on this driver pair

- **I2C `driver_ng` conflict** ([#492](https://github.com/lvgl-micropython/lvgl_micropython/issues/492)):
  bringing up the AXS5106L I2C can surface `CONFLICT! driver_ng is not allowed to be used
  with this old driver`. This is the most likely first-boot blocker — resolve it before
  polishing UI.
- **JD9853 bring-up** ([#393](https://github.com/lvgl-micropython/lvgl_micropython/issues/393)):
  one report needed edits to `machine_uart.c` / `modesp32.h` during compile. Check the issue
  for the current state before assuming a clean build.
- **Colour order** is the one panel guess: `cicada_ui.py` starts at `BYTE_ORDER_BGR` (matching
  the ST7789 sibling + CircuitPython's `reverse_pixels_in_word=true`). If `07_selftest.py`
  shows red↔blue swapped, flip to `BYTE_ORDER_RGB`.

## How the build system wires user C modules (confirmed from source)

`builder/esp32.py` always injects LVGL itself as the top-level modules file:

```
USER_C_MODULES=../../../../../ext_mod/micropython.cmake
```

so you **cannot** just pass your own `USER_C_MODULES=` — it would be overwritten. Instead
the builder exposes an appendable `USER_C_MODULE` argument and, in its `user_c_module()`
step, `include()`s each one into `ext_mod/esp32_components.cmake` (which the top-level
LVGL cmake pulls in). Our module's existing tail —

```cmake
target_link_libraries(usermod INTERFACE usermod_ced25519)
```

— is exactly the shape that aggregation expects, so `ced25519/micropython.cmake` needs
**no changes**; it just gets `include()`d.

## Steps

### 0. Get the tree (in Docker, per project policy)

```bash
git clone https://github.com/lvgl-micropython/lvgl_micropython
cd lvgl_micropython
# make.py fetches lib/micropython + LVGL + ESP-IDF submodules on first run
```

### 1. Fill in `ced25519/` and keep it out of tree churn

Copy the four Monocypher sources into `firmware/ced25519/` per `ced25519/BUILD.md`
(the `optional/monocypher-ed25519.*` pair — SHA-512 `crypto_ed25519_check`, **not** the
BLAKE2b core). Monocypher is portable C — nothing arch-specific, so the RISC-V→Xtensa
move needs no changes here.

### 2. Build (S3 PSRAM variant + display + touch + ced25519)

```bash
python3 make.py esp32 clean \
    --flash-size=16 \
    --enable-jtag-repl=y \
    BOARD=ESP32_GENERIC_S3 \
    BOARD_VARIANT=SPIRAM_OCT \
    DISPLAY=jd9853 \
    INDEV=axs5106 \
    USER_C_MODULE=/abs/path/to/firmware/ced25519/micropython.cmake
```

`BOARD_VARIANT=SPIRAM_OCT` enables the R8's **octal** PSRAM — the wrong variant boots
without PSRAM (or not at all). With 8 MB PSRAM, let the driver auto-allocate framebuffers
(as `cicada_ui.py` does); no partial-buffer / `LV_MEM_SIZE` juggling needed. Add
`--partition-size=…` only if the default app partition doesn't hold LVGL + NimBLE +
Monocypher.

### 3. Flash + push

```bash
# from the host (needs USB serial): flashes firmware.bin, then copies the loader +
# verify/decrypt shims + display/touch helper + lifecycle UI:
firmware/tools/flash_lvgl.sh [PORT]
```

Then sign + push examples with `tools/push_script.py` as usual.

## Post-build verification checklist

At the REPL, all four legs must import:

```python
import ced25519     # native verifier linked in  (else ed25519.py falls back to slow pure-Python)
import lvgl         # LVGL binding present
import jd9853, axs5106   # display + touch drivers present
import bluetooth    # BLE stack present -> loader can advertise
```

**The one that actually proves the build is `import bluetooth` + a real advertise/connect.**
De-risk BLE-alongside-LVGL first with the coexistence smoke test — it brings up NimBLE
(the loader's real service + AD) *and* an animating LVGL screen, and logs heap headroom:

```bash
mpremote run tools/ble_lvgl_smoketest.py
```

Watch the `gc=` column: steady = fine, steadily falling = a leak. With PSRAM, SRAM
contention shouldn't bite — but confirm here anyway. Only once this is green is it worth
polishing the UI.

Then, functionally:

- `main.py` boots (it refuses the all-zero placeholder `PUBKEY` / `DEVICE_X25519_PRIV` —
  keep your real keys).
- `firmware/tests/test_flow.py` still green on the host (LVGL/touch don't touch that path).
- Push `examples/07_selftest.py` → screen cycles R/G/B/W → confirms wiring + colour order.
  If red↔blue are swapped, flip `color_byte_order` to `BYTE_ORDER_RGB` in `cicada_ui.py`.
- Touch: a tap should register (test with a pushed script that reads an LVGL button). If the
  I2C conflict (#492) fires at boot, touch init is caught and degrades to no-touch — the
  display + BLE still work; fix the I2C bus before relying on touch.
- RGB LED: this touch board has **none** (confirmed against Waveshare docs + the CircuitPython
  board def; the non-touch ESP32-S3-LCD-1.47 has one, this variant doesn't). `_LED_PIN` stays
  `None` in `cicada_ui.py` and LED cues are no-ops — nothing to wire.
- Verify timing: `ed25519_verify` should be single/double-digit ms (native), not seconds.

## Sources

- [Waveshare ESP32-S3-Touch-LCD-1.47](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-1.47) — board (JD9853 + AXS5106L, S3R8)
- CircuitPython board def (`waveshare_esp32_s3_touch_lcd_1_47`) — confirmed LCD/touch GPIOs
- [lvgl_micropython (kdschlosser)](https://github.com/lvgl-micropython/lvgl_micropython) — DISPLAY=jd9853, INDEV=axs5106
- [#393 JD9853 bring-up](https://github.com/lvgl-micropython/lvgl_micropython/issues/393) · [#492 I2C driver_ng conflict](https://github.com/lvgl-micropython/lvgl_micropython/issues/492)
