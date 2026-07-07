# ble_lvgl_smoketest.py -- prove NimBLE + LVGL coexist on the ESP32-S3-Touch-LCD-1.47.
#
# A leg of the LVGL firmware build to confirm (see ../BUILD_LVGL.md): that the BLE
# stack runs *alongside* LVGL. The S3R8's 8 MB PSRAM should remove the SRAM
# contention that made this the C6's real risk, but confirm it anyway -- this
# brings up BOTH and leaves them running so you can watch for OOM, heap
# leak/fragmentation, or render corruption before investing in the real UI.
#
# It is NOT a pushed/signed script -- it OWNS the BLE stack, so it runs INSTEAD of
# the loader. Run it directly on a board flashed with the LVGL+BLE+ced25519 image:
#
#     mpremote run firmware/tools/ble_lvgl_smoketest.py
#
# It reuses main.py's real NUS service + manufacturer advertising payload, so the
# companion app's scanner/boot-watch sees it exactly like a real unit. Connect,
# write bytes to the RX characteristic, disconnect -- all while LVGL animates.
#
# What to watch:
#   * REPL "free after LVGL" / "free after BLE" -> headroom cost of each stack.
#   * The gc= column every 5 s -> post-collect free. Steadily falling = a leak.
#   * Screen keeps animating + BLE state updates while connected = coexistence OK.
#   * LED: blue breathe = advertising, solid green = connected, white blip = RX write.

import gc
import time
import bluetooth

import cicada_ui                       # display + LED + LVGL TaskHandler (validated)
import main                            # reuse the loader's REAL service + AD payload

_NAME = main.DEVICE_NAME

print("smoketest: free at start   =", gc.mem_free())

# ---- LVGL half -------------------------------------------------------------
ui = cicada_ui.boot()
lv = ui.lv
print("smoketest: free after LVGL =", gc.mem_free())

scr = ui.screen(0x0A0A12)

title = lv.label(scr)
title.set_text("BLE + LVGL smoke")
title.set_style_text_color(lv.color_hex(0x00E5FF), 0)
title.align(lv.ALIGN.TOP_MID, 0, 6)

state_lbl = lv.label(scr)
state_lbl.align(lv.ALIGN.TOP_MID, 0, 34)

heap_lbl = lv.label(scr)
heap_lbl.set_style_text_color(lv.color_hex(0xE6EDF3), 0)
heap_lbl.align(lv.ALIGN.TOP_MID, 0, 60)

heap_bar = lv.bar(scr)
heap_bar.set_size(150, 12)
heap_bar.align(lv.ALIGN.TOP_MID, 0, 84)
heap_bar.set_range(0, 100)

io_lbl = lv.label(scr)
io_lbl.set_style_text_color(lv.color_hex(0x8899AA), 0)
io_lbl.align(lv.ALIGN.TOP_MID, 0, 104)

evt_lbl = lv.label(scr)
evt_lbl.set_style_text_color(lv.color_hex(0x8899AA), 0)
evt_lbl.align(lv.ALIGN.TOP_MID, 0, 126)

# A perpetual arc animation: keeps LVGL rendering between BLE events, so the test
# actually stresses coexistence instead of sitting idle.
load = lv.arc(scr)
load.set_size(64, 64)
load.align(lv.ALIGN.BOTTOM_MID, 0, -12)
load.remove_style(None, lv.PART.KNOB)
load.set_bg_angles(0, 360)
load.set_range(0, 100)
_spin = lv.anim_t()
_spin.init()
_spin.set_var(load)
_spin.set_values(0, 100)
_spin.set_duration(1200)
_spin.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
_spin.set_custom_exec_cb(lambda _a, v: load.set_value(v))
_spin.start()

# ---- BLE half (the real loader service + advertising) ----------------------
state = {"conn": None, "connects": 0, "writes": 0, "evt": "boot"}

ble = bluetooth.BLE()
ble.active(True)
ble.config(gap_name=_NAME)
((_tx, _rx, _nh),) = ble.gatts_register_services((main._SERVICE,))
ble.gatts_set_buffer(_rx, 1024, True)

_adv = main._adv_payload(_NAME)
_dev_id = main._device_id()


def _advertise():
    resp = main._resp_payload(main._UART, _dev_id, True)   # advertise "awaiting"
    ble.gap_advertise(100_000, adv_data=_adv, resp_data=resp)


def _irq(event, data):
    # Cheap only -- no LVGL/LED here (that stays in render(), one LVGL context).
    if event == main._IRQ_CENTRAL_CONNECT:
        conn, _, _ = data
        state["conn"] = conn
        state["connects"] += 1
        state["evt"] = "connect"
        ble.gap_advertise(None)
    elif event == main._IRQ_CENTRAL_DISCONNECT:
        conn, _, _ = data
        state["conn"] = None
        state["evt"] = "disconnect"
        _advertise()
    elif event == main._IRQ_GATTS_WRITE:
        conn, attr = data
        if attr == _rx:
            state["writes"] += 1
            state["evt"] = "rx %dB" % len(ble.gatts_read(_rx))
            try:                                           # echo under LVGL load
                ble.gatts_notify(state["conn"], _tx, b"ack:%d" % state["writes"])
            except Exception:
                pass


ble.irq(_irq)
_advertise()
print("smoketest: free after BLE  =", gc.mem_free(), "-- advertising as", _NAME)

# ---- render (LVGL context, via LVGL timer) ---------------------------------
_total = gc.mem_alloc() + gc.mem_free()
mon = {"free": gc.mem_free(), "min": gc.mem_free(), "t": 0, "pulse": 0, "seen_wr": 0}


def render():
    conn = state["conn"] is not None
    if state["writes"] != mon["seen_wr"]:      # RX just arrived -> white blip
        mon["seen_wr"] = state["writes"]
        ui.hex(0xFFFFFF)
    elif conn:
        ui.hex(0x00FF66)                       # connected -> solid green
    else:
        mon["pulse"] = (mon["pulse"] + 40) % 510
        b = mon["pulse"] if mon["pulse"] < 255 else 510 - mon["pulse"]
        ui.rgb(0, 0, b)                        # advertising -> blue breathe

    state_lbl.set_text("CONNECTED" if conn else "ADVERTISING")
    state_lbl.set_style_text_color(lv.color_hex(0x00FF66 if conn else 0x3399FF), 0)
    heap_lbl.set_text("free %dK  min %dK" % (mon["free"] // 1024, mon["min"] // 1024))
    heap_bar.set_value(int(100 * mon["free"] / _total), 0)   # 0 = LV_ANIM_OFF
    io_lbl.set_text("conn %d   wr %d" % (state["connects"], state["writes"]))
    evt_lbl.set_text("evt: %s" % state["evt"])


ui.every(250, render)

# ---- monitor (normal context: heap + REPL log; no LVGL calls here) ---------
print("smoketest: running. Ctrl-C to stop. total heap =", _total)
while True:
    f = gc.mem_free()
    mon["free"] = f
    if f < mon["min"]:
        mon["min"] = f
    mon["t"] += 1
    if mon["t"] % 5 == 0:
        gc.collect()
        print("t=%4ds  free=%6d  min=%6d  gc=%6d  conns=%d  writes=%d  evt=%s"
              % (mon["t"], f, mon["min"], gc.mem_free(),
                 state["connects"], state["writes"], state["evt"]))
    time.sleep_ms(1000)
