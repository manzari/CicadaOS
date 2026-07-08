# 09 -- Serial monitor: read+write a UART and show every incoming line on the LCD.
# Timer-driven. Non-blocking.
#
# WIRING (Waveshare ESP32-C6-LCD-1.47). The LCD SPI (6,7,14,15,21,22) and the
# WS2812 (8) are taken by cicada_ui; everything else on the header is free. This
# uses UART1 on GPIO0/1 -- neither is a C6 strapping pin (those are 4,5,8,9,15)
# nor the USB-JTAG REPL (12/13), so UART1 here is fully independent of the console:
#
#     TX = GPIO0  (device -> peer)      RX = GPIO1  (peer -> device)   GND common
#
# Free alternates if you'd rather: 2,3,16,17,18,19,20,23 (any two; the C6 GPIO
# matrix routes a UART to almost any pin).
#
# Try it: wire a USB-TTL adapter (its TX->our RX=1, its RX->our TX=0, GND-GND),
# open it at 115200 8N1, and type. Each line shows on screen and is echoed back.

import machine
import cicada_ui

TX_PIN, RX_PIN, BAUD = 0, 1, 115200

ui = cicada_ui.boot()
lv = ui.lv
scr = ui.screen(0x0A0A12)

# ---- UART ----
uart = machine.UART(1, baudrate=BAUD, tx=TX_PIN, rx=RX_PIN, timeout=0)
uart.write("CICADA serial monitor ready @ %d 8N1\r\n" % BAUD)

# ---- UI: title, counters, scrolling log ----
title = lv.label(scr)
title.set_text("UART1  %d 8N1\nTX=%d  RX=%d" % (BAUD, TX_PIN, RX_PIN))
title.set_style_text_color(lv.color_hex(0x00E5FF), 0)
title.align(lv.ALIGN.TOP_MID, 0, 6)

stat = lv.label(scr)
stat.set_style_text_color(lv.color_hex(0x8899AA), 0)
stat.align(lv.ALIGN.TOP_MID, 0, 40)

log = lv.textarea(scr)
log.set_size(164, 236)
log.align(lv.ALIGN.BOTTOM_MID, 0, -6)
log.set_text("")
log.set_style_bg_color(lv.color_hex(0x121620), 0)
log.set_style_text_color(lv.color_hex(0xC8D2DC), 0)

MAX_CHARS = 1800
st = {"rx": 0, "tx": len("CICADA serial monitor ready\r\n"), "part": "", "n": 0}


def show(text):
    log.add_text(text)               # append at cursor -> textarea auto-scrolls
    st["n"] += len(text)
    if st["n"] > MAX_CHARS:           # bound growth: keep only the recent tail
        tail = log.get_text()[-MAX_CHARS // 2:]
        log.set_text(tail)
        st["n"] = len(tail)


def poll():
    while uart.any():
        chunk = uart.read()
        if not chunk:
            break
        text = chunk.decode()
        st["rx"] += len(chunk)
        show(text)
        # Echo every complete line back to the peer, prefixed.
        st["part"] += text
        while "\n" in st["part"]:
            line, st["part"] = st["part"].split("\n", 1)
            reply = "> %s\r\n" % line.strip("\r")
            uart.write(reply)
            st["tx"] += len(reply)
    stat.set_text("rx %d B   tx %d B" % (st["rx"], st["tx"]))
    ui.rgb(0, 40, 0) if st["rx"] else ui.rgb(20, 20, 0)


def heartbeat():
    msg = "tick\r\n"
    uart.write(msg)
    st["tx"] += len(msg)


ui.every(50, poll)          # drain the RX FIFO ~20x/s
ui.every(3000, heartbeat)   # periodic write so "TX" is visible with no peer
notify("serial monitor live")
