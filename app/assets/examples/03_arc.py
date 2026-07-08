# 03 -- Progress arc: an arc breathes 0->100%; LED fades blue->green with it. Non-blocking.
import cicada_ui

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

arc = lv.arc(scr)
arc.set_size(150, 150)
arc.center()
arc.set_rotation(270)
arc.set_bg_angles(0, 360)
arc.set_range(0, 100)
arc.remove_style(None, lv.PART.KNOB)          # no drag knob (board has no touch)
arc.set_style_arc_width(14, lv.PART.MAIN)
arc.set_style_arc_width(14, lv.PART.INDICATOR)
arc.set_style_arc_color(lv.color_hex(0x223040), lv.PART.MAIN)
arc.set_style_arc_color(lv.color_hex(0x00E5FF), lv.PART.INDICATOR)

pct = lv.label(scr)
pct.center()
pct.set_style_text_color(lv.color_hex(0xE6EDF3), 0)


def step(_a, v):
    arc.set_value(v)
    pct.set_text("%d%%" % v)
    ui.rgb(0, int(2.55 * v), int(255 - 2.55 * v))


a = lv.anim_t()
a.init()
a.set_var(arc)
a.set_values(0, 100)
a.set_duration(2200)
a.set_reverse_duration(2200)                   # v9: "playback" is now "reverse"
a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
a.set_custom_exec_cb(step)
a.start()

notify("arc animating")
