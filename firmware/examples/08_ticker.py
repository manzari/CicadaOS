# 08 -- Ticker: a scrolling marquee headline + a soft LED heartbeat. Non-blocking.
import cicada_ui

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

msg = lv.label(scr)
msg.set_long_mode(lv.label.LONG_MODE.SCROLL_CIRCULAR)
msg.set_width(160)
msg.set_text("  CICADA -- ephemeral signed code over BLE -- no script is ever stored  ")
msg.set_style_text_color(lv.color_hex(0x00E5FF), 0)
msg.align(lv.ALIGN.CENTER, 0, 0)

# LED heartbeat: fade a green pulse up and down.
st = {"v": 0, "dir": 12}


def beat():
    st["v"] += st["dir"]
    if st["v"] >= 255:
        st["v"], st["dir"] = 255, -12
    elif st["v"] <= 0:
        st["v"], st["dir"] = 0, 12
    ui.rgb(0, st["v"], 0)


ui.every(30, beat)
notify("ticker running")
