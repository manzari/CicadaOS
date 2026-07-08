# 02 -- Status card: device stats in a rounded panel; LED green = healthy. Non-blocking.
import cicada_ui
import machine
import gc

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

card = lv.obj(scr)
card.set_size(150, 190)
card.center()
card.set_style_radius(16, 0)
card.set_style_bg_color(lv.color_hex(0x161A22), 0)
card.set_style_border_color(lv.color_hex(0x00E5FF), 0)
card.set_style_border_width(2, 0)
card.set_style_pad_all(12, 0)

gc.collect()
freq = machine.freq() // 1_000_000
free = gc.mem_free() // 1024

lbl = lv.label(card)
lbl.set_text("ESP32-C6\n\nCPU  %d MHz\nRAM  %d KB free\nLVGL live" % (freq, free))
lbl.set_style_text_color(lv.color_hex(0xE6EDF3), 0)
lbl.center()

ui.hex(0x00FF66)
notify("cpu=%dMHz free=%dKB" % (freq, free))
