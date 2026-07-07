# LVGL + RGB-LED example scripts

MicroPython scripts you can **sign and push over BLE** (see `../tools/push_script.py`)
to drive the display, touch, and onboard RGB LED of a **Waveshare ESP32-S3-Touch-LCD-1.47**.

Each script is independently pushable and self-contained except for a shared device-side
helper, `cicada_ui.py`, which brings up the panel + LED once and caches it.

## Prerequisite: an LVGL-enabled firmware build

These scripts call `import lvgl` / `lcd_bus` / `jd9853` / `axs5106` / `task_handler` and use
`machine.SPI.Bus`. **Stock MicroPython does not have those** — they come from
[`lvgl_micropython`](https://github.com/lvgl-micropython/lvgl_micropython) (LVGL 9).

The loader in `../main.py` must therefore be rebuilt on the `lvgl_micropython` base with:

- the BLE stack (`bluetooth`) — already required by the loader,
- the native Ed25519 C module (`../ced25519/`, via `USER_C_MODULES`) — see `../ced25519/BUILD.md`,
- the JD9853 SPI display driver (`DISPLAY=jd9853`) + AXS5106L touch (`INDEV=axs5106`) + `neopixel`.

Full build steps are in `../BUILD_LVGL.md`.

Until the firmware is rebuilt this way, pushing these scripts returns `ERR:ImportError`.
Everything security-critical (nonce/verify/exec) is unchanged — LVGL is purely additive.

## Board pin map (Waveshare ESP32-S3-Touch-LCD-1.47)

| Function | GPIO | | Function | GPIO |
|----------|------|-|----------|------|
| LCD SCLK | 38 | | LCD DC   | 45 |
| LCD MOSI | 39 | | LCD RST  | 40 |
| LCD CS   | 21 | | LCD BL   | 46 |
| Touch SDA | 42 | | Touch SCL | 41 |
| Touch RST | 47 | | Touch INT | 48 |
| **RGB LED** | **none on this board** | | | |

Panel: JD9853, **172×320**, RGB565. The 172-wide glass sits centred in the controller's
240-column RAM, so `cicada_ui.py` sets a **column offset of 34**. Touch is AXS5106L over
I2C (addr `0x63`). **This touch variant has no onboard RGB LED** (the non-touch
ESP32-S3-LCD-1.47 does; the touch model reuses those pins for the AXS5106L), so the
examples' LED cues are no-ops — they run screen-only.
(LCD/touch pins confirmed against the CircuitPython board definition — see Sources.)

## Deploy

```bash
# 1. Flash the helper alongside main.py (once). It is NOT signed — no secrets in it.
mpremote fs cp cicada_ui.py :cicada_ui.py

# 2. Sign + push an example over BLE (from the host, needs BlueZ; see ../tools/README.md).
python3 ../tools/push_script.py 01_hello.py
```

The companion Flutter app can import these into its script library the same way it does
any other `.py`.

## The examples

| File | What it shows |
|------|---------------|
| `01_hello.py`     | Centred label + subtitle, steady cyan LED. |
| `02_status.py`    | Rounded status card (CPU/RAM), green "healthy" LED. |
| `03_arc.py`       | Arc that breathes 0→100%, LED fades blue→green with it (LVGL animation). |
| `04_rainbow.py`   | LED walks the colour wheel; on-screen swatch + live hex (LVGL timer). |
| `05_dashboard.py` | Faux bike dash: speed arc + draining battery bar, LED = battery colour. |
| `06_chart.py`     | Scrolling live line chart, LED tracks the latest sample. |
| `07_selftest.py`  | Bring-up: floods screen R/G/B/W with matching LED — verifies wiring/colour order. |
| `08_ticker.py`    | Scrolling marquee headline + soft green LED heartbeat. |
| `09_serial.py`    | UART1 monitor: shows every incoming line on-screen, echoes lines back + a heartbeat write (TX=0, RX=1). |

## How they behave on-device

- **Persistence.** `cicada_ui.boot()` inits the display + LVGL **once** and caches it in
  `sys.modules`; re-pushes reuse the same instance (LVGL can't be re-`init()`ed).
- **Background rendering.** `task_handler.TaskHandler()` runs `lv.task_handler()` in the
  background, so a script can build a UI, return `OK:done`, and the screen keeps
  animating. `ui.every(ms, cb)` timers therefore **outlive** the push.
- **No stacking.** `ui.screen()` deletes the previous script's timers and wipes its
  widgets (which cancels their animations) before returning a clean root — so pushing a
  new example cleanly replaces the last one.
- **Blocking vs not.** All are non-blocking except `07_selftest.py`, which holds the exec
  ~3s (calling `lv.refr_now()` to draw); no other script can be pushed until it finishes.
- **LED brightness.** WS2812 full white is blinding, so `ui.bright` scales it to 0.30.
- **Hardware quirks (all handled in `cicada_ui.py`).** The panel needs `reset_state=STATE_LOW`
  (active-low RST — without it the screen stays black); colour order starts at `BYTE_ORDER_BGR`
  (flip to `BYTE_ORDER_RGB` if `07_selftest.py` shows red↔blue swapped). There is no RGB LED,
  so `ui.rgb()`/`hex()`/`off()` are no-ops (the R↔G swap only matters if a WS2812 is added).
  Touch init is wrapped
  so an I2C fault degrades to no-touch without taking BLE/display down (see `../BUILD_LVGL.md`
  "Known issues" for the AXS5106L I2C `driver_ng` conflict).

## Sources

- [Waveshare ESP32-S3-Touch-LCD-1.47 wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-1.47)
- CircuitPython board def `waveshare_esp32_s3_touch_lcd_1_47` (`board.c` / `pins.c`) — confirmed LCD + touch GPIOs
- [lvgl_micropython (kdschlosser) — LVGL 9 binding, DISPLAY=jd9853 / INDEV=axs5106](https://github.com/lvgl-micropython/lvgl_micropython)
