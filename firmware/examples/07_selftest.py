# 07 -- Bring-up self-test: flood the screen R/G/B/W while the LED matches, to verify
# wiring and colour order. BLOCKING (~3s) -- it holds the exec, so it forces its own
# redraws and no other script can be pushed until it returns OK:done.
import cicada_ui
import time

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x000000)

banner = lv.label(scr)
banner.center()
banner.set_style_text_color(lv.color_hex(0x000000), 0)

for name, col in (("RED", 0xFF0000), ("GREEN", 0x00FF00),
                  ("BLUE", 0x0000FF), ("WHITE", 0xFFFFFF)):
    scr.set_style_bg_color(lv.color_hex(col), 0)
    banner.set_text(name)
    ui.hex(col)
    lv.refr_now(None)                 # blocking loop -> draw now instead of waiting
    time.sleep_ms(700)

ui.off()
scr.set_style_bg_color(lv.color_hex(0x0A0A12), 0)
banner.set_style_text_color(lv.color_hex(0x00FF66), 0)
banner.set_text("self-test OK")
lv.refr_now(None)
notify("selftest done")
