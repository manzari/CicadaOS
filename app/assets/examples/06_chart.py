# 06 -- Live chart: a scrolling line chart of a simulated signal; LED tracks the sample.
# Timer-driven. Non-blocking.
import cicada_ui
import math

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

ch = lv.chart(scr)
ch.set_size(156, 210)
ch.center()
ch.set_type(lv.chart.TYPE.LINE)
ch.set_point_count(30)
ch.set_range(lv.chart.AXIS.PRIMARY_Y, 0, 100)
ch.set_style_bg_color(lv.color_hex(0x161A22), 0)
ch.set_style_border_width(0, 0)
ch.set_style_line_width(2, lv.PART.ITEMS)
ser = ch.add_series(lv.color_hex(0x00E5FF), lv.chart.AXIS.PRIMARY_Y)

st = {"t": 0.0}


def frame():
    st["t"] += 0.2
    y = int(50 + 45 * math.sin(st["t"]) * math.sin(st["t"] * 0.3))
    ch.set_next_value(ser, y)
    ui.rgb(0, int(2.4 * y), int(255 - 2.4 * y))


ui.every(150, frame)
notify("charting")
