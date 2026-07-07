# 04 -- Rainbow: RGB LED walks the colour wheel; screen shows the live swatch + hex.
# Timer-driven, so it keeps running after OK:done. Non-blocking.
import cicada_ui

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x000000)

sw = lv.obj(scr)
sw.set_size(150, 150)
sw.align(lv.ALIGN.CENTER, 0, -22)
sw.set_style_radius(75, 0)
sw.set_style_border_width(0, 0)

lab = lv.label(scr)
lab.align(lv.ALIGN.CENTER, 0, 92)
lab.set_style_text_color(lv.color_hex(0xFFFFFF), 0)

st = {"i": 0}


def tick():
    r, g, b = ui.wheel(st["i"])
    ui.rgb(r, g, b)
    sw.set_style_bg_color(lv.color_hex((r << 16) | (g << 8) | b), 0)
    lab.set_text("#%02X%02X%02X" % (r, g, b))
    st["i"] = (st["i"] + 2) & 0xFF


ui.every(40, tick)
notify("rainbow running")
