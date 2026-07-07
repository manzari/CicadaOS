# 05 -- Bike dashboard: a wobbling speed arc + draining battery bar. LED = battery colour.
# Timer-driven. Non-blocking.
import cicada_ui
import math

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

spd = lv.arc(scr)
spd.set_size(150, 150)
spd.align(lv.ALIGN.TOP_MID, 0, 14)
spd.set_rotation(135)
spd.set_bg_angles(0, 270)
spd.set_range(0, 45)
spd.remove_style(None, lv.PART.KNOB)
spd.set_style_arc_width(12, lv.PART.MAIN)
spd.set_style_arc_width(12, lv.PART.INDICATOR)
spd.set_style_arc_color(lv.color_hex(0x223040), lv.PART.MAIN)
spd.set_style_arc_color(lv.color_hex(0x00E5FF), lv.PART.INDICATOR)

spd_txt = lv.label(scr)
spd_txt.align(lv.ALIGN.TOP_MID, 0, 72)
spd_txt.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
spd_txt.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)

batt = lv.bar(scr)
batt.set_size(150, 18)
batt.align(lv.ALIGN.BOTTOM_MID, 0, -44)
batt.set_range(0, 100)

batt_txt = lv.label(scr)
batt_txt.align(lv.ALIGN.BOTTOM_MID, 0, -68)
batt_txt.set_style_text_color(lv.color_hex(0x8899AA), 0)

st = {"t": 0.0, "batt": 100.0}


def frame():
    st["t"] += 0.08
    v = int(22 + 20 * math.sin(st["t"]))          # simulated speed 2..42 km/h
    spd.set_value(v)
    spd_txt.set_text("%d\nkm/h" % v)

    st["batt"] = max(0.0, st["batt"] - 0.2)
    b = int(st["batt"])
    batt.set_value(b, 0)                          # 0 = LV_ANIM_OFF
    batt_txt.set_text("battery %d%%" % b)

    col = 0x00FF66 if b > 50 else (0xFFAA00 if b > 20 else 0xFF2222)
    batt.set_style_bg_color(lv.color_hex(col), lv.PART.INDICATOR)
    ui.hex(col)


ui.every(120, frame)
notify("dashboard live")
