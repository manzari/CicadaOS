# Device-side helper for the CicadaOS LVGL examples.
#
# Copy this onto the ESP32-S3 flash next to main.py (e.g. `mpremote fs cp
# cicada_ui.py :cicada_ui.py`). It is NOT pushed or signed and holds no secrets
# -- it only brings up the JD9853 display + AXS5106L touch (and, if present, the
# onboard RGB LED) and caches them as singletons so every pushed script reuses
# one display/LVGL instance.
#
# Requires an lvgl_micropython build (LVGL 9) for ESP32-S3 built with
# DISPLAY=jd9853 INDEV=axs5106, which provides machine.SPI.Bus / lcd_bus /
# jd9853 / i2c / axs5106 / task_handler. See BUILD_LVGL.md.
#
# Board: Waveshare ESP32-S3-Touch-LCD-1.47 (JD9853 172x320 + AXS5106L touch).

import machine
import lcd_bus
import jd9853
import i2c
import axs5106
import task_handler
import lvgl as lv

# ---- Waveshare ESP32-S3-Touch-LCD-1.47 pin map ----
# LCD (JD9853, SPI)
_SCK, _MOSI, _DC, _CS, _RST, _BL = 38, 39, 45, 21, 40, 46
# Touch (AXS5106L, I2C). INT (GPIO48) is unused -- the driver polls.
_SDA, _SCL, _TP_RST, _TP_INT = 42, 41, 47, 48
_TP_FREQ = 400_000
# This board has NO onboard RGB LED (unlike the non-touch ESP32-S3-LCD-1.47 and
# the old C6 board -- the touch variant uses those pins for the AXS5106L). LED
# cues are therefore no-ops: ui.rgb()/hex()/off() short-circuit when _LED_PIN is
# None. Only set a GPIO here if a future board revision adds an external WS2812.
_LED_PIN = None
_W, _H = 172, 320
# The 172-wide glass is centred in the controller's 240-column RAM -> offset 34.
_OFFSET_X, _OFFSET_Y = 34, 0

_state = None


def boot():
    """Init (once) and return the cached UI handle."""
    global _state
    if _state is not None:
        return _state

    if not lv.is_initialized():
        lv.init()

    # --- display (JD9853 over SPI) ---
    spi = machine.SPI.Bus(host=1, mosi=_MOSI, miso=-1, sck=_SCK)
    bus = lcd_bus.SPIBus(spi_bus=spi, freq=40_000_000, dc=_DC, cs=_CS)
    disp = jd9853.JD9853(
        data_bus=bus,
        display_width=_W,
        display_height=_H,
        reset_pin=_RST,
        reset_state=jd9853.STATE_LOW,    # RST is active-low; default HIGH holds it in reset -> black
        backlight_pin=_BL,
        offset_x=_OFFSET_X,
        offset_y=_OFFSET_Y,
        color_space=lv.COLOR_FORMAT.RGB565,
        color_byte_order=jd9853.BYTE_ORDER_RGB,   # RGB confirmed: green text read pink (not purple) under inversion
        rgb565_byte_swap=True,
    )
    disp.set_power(True)
    disp.init()
    disp.set_color_inversion(True)   # panel is inverted: near-black bg was showing white -> INVON
    disp.set_backlight(100)

    # --- touch (AXS5106L over I2C) ---
    # AXS5106 subclasses PointerDriver, which registers itself with LVGL on
    # construction and binds to the active display -- so building it AFTER the
    # display is all the wiring needed. A dead/absent panel must not take the
    # loader (BLE) down, so failures degrade to no-touch.
    touch = None
    try:
        tp_bus = i2c.I2C.Bus(host=0, scl=_SCL, sda=_SDA, freq=_TP_FREQ,
                             use_locks=False)
        tp_dev = i2c.I2C.Device(bus=tp_bus, dev_id=axs5106.I2C_ADDR, reg_bits=8)
        touch = axs5106.AXS5106(tp_dev, reset_pin=_TP_RST)
    except Exception:
        touch = None

    # TaskHandler runs lv.task_handler() in the background, so a pushed script can
    # build a UI, return (OK:done), and the screen keeps rendering / animating.
    th = task_handler.TaskHandler()

    led = None
    if _LED_PIN is not None:
        try:
            import neopixel
            led = neopixel.NeoPixel(machine.Pin(_LED_PIN), 1)
        except Exception:
            led = None

    _state = _UI(disp, th, led, touch)
    return _state


class _UI:
    def __init__(self, disp, th, led, touch=None):
        self.lv = lv
        self.disp = disp
        self.th = th
        self.led = led
        self.touch = touch
        self.bright = 0.30          # WS2812 master scale -- full white is retina-searing
        self._timers = []
        self._pending = None        # off-screen surface built by screen(atomic=True)

    # ---- screen ----
    def screen(self, bg=0x0A0A12, atomic=False):
        """Fresh full-screen surface: stop the previous script's timers, wipe its
        widgets (which also cancels their animations), return a clean root.

        atomic=True builds onto a brand-new OFF-screen surface instead of the live
        one -- nothing is flushed to the panel until present() swaps it in as a
        single frame. That is what stops the partial-frame tearing the loader
        showed on every stage change (widgets flashing their default LVGL style
        before _flat() ran). Default (atomic=False) keeps the in-place behaviour
        pushed scripts rely on."""
        for t in self._timers:
            try:
                t.delete()
            except Exception:
                pass
        self._timers = []
        if atomic:
            scr = lv.obj()          # parentless -> a screen; stays inactive until present()
            self._pending = scr
        else:
            scr = lv.screen_active()
            scr.clean()
            self._pending = None
        scr.set_style_bg_color(lv.color_hex(bg), 0)
        scr.set_style_bg_opa(lv.OPA.COVER, 0)
        return scr

    def present(self):
        """Swap in the surface built by the last atomic screen() call as one frame,
        then drop the screen it replaced. No-op if nothing is pending. The retired
        screen's DELETE event fires here, so a loader guards this behind its
        repaint flag to avoid mistaking it for a pushed-script takeover."""
        scr = self._pending
        if scr is None:
            return
        self._pending = None
        old = lv.screen_active()
        lv.screen_load(scr)
        if old is not None and old is not scr:
            try:
                old.delete()
            except Exception:
                pass

    def every(self, period_ms, cb):
        """Register a background timer that this UI cleans up on the next screen()."""
        t = lv.timer_create(lambda _t: cb(), period_ms, None)
        self._timers.append(t)
        return t

    # ---- RGB LED (no-op until _LED_PIN is set + wired) ----
    def rgb(self, r, g, b):
        if self.led is None:
            return
        k = self.bright
        # This board's WS2812 uses RGB order; MicroPython's neopixel assumes GRB,
        # so swap R<->G here to compensate (else red displays as green).
        self.led[0] = (int(g * k), int(r * k), int(b * k))
        self.led.write()

    def hex(self, color):
        self.rgb((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF)

    def off(self):
        if self.led is None:
            return
        self.led[0] = (0, 0, 0)
        self.led.write()

    @staticmethod
    def wheel(pos):
        """0..255 -> (r,g,b) around the colour wheel."""
        pos &= 0xFF
        if pos < 85:
            return (255 - pos * 3, pos * 3, 0)
        if pos < 170:
            pos -= 85
            return (0, 255 - pos * 3, pos * 3)
        pos -= 170
        return (pos * 3, 0, 255 - pos * 3)
