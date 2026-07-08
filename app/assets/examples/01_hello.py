# 01 -- Hello: centred title + subtitle, LED steady cyan. Non-blocking.
import cicada_ui

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

title = lv.label(scr)
title.set_text("CICADA")
title.set_style_text_color(lv.color_hex(0x00E5FF), 0)
title.align(lv.ALIGN.CENTER, 0, -14)

sub = lv.label(scr)
sub.set_text("signed + pushed over BLE")
sub.set_style_text_color(lv.color_hex(0x8899AA), 0)
sub.align(lv.ALIGN.CENTER, 0, 12)

ui.hex(0x00E5FF)
notify("hello on screen")
