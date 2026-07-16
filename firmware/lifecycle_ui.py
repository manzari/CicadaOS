# lifecycle_ui.py -- loader status display for the S3-Touch-LCD-1.47: protocol state
# told as a cicada life cycle. Flash next to main.py + cicada_ui.py:
#   mpremote fs cp lifecycle_ui.py :lifecycle_ui.py
# Called from the main loop only (never the BLE IRQ). Once a pushed script
# paints its own UI (detected via the root's DELETE event) the loader goes
# screen-silent until reboot and keeps LED-only cues. Every public method
# swallows display errors: a broken panel must never take BLE down.

import math
import lvgl as lv
import cicada_ui

_W, _H = 172, 320
_CX = _W // 2

_NIGHT = 0x060A08
_SKY = 0x2C4A63       # boot-cinematic dusk sky; fades to _NIGHT as the egg is laid
_SOIL = (0x201509, 0x180F06, 0x100A04)
_STONE = 0x2B2013
_SURFACE = 0x2E4023
_CHITIN = 0xC98A2B
_HUSK_DK = 0x7A5218
_CYAN = 0x00E5FF
_MINT = 0xBFE8A0
_GREEN = 0x59D163
_HUSK = 0xEADFC8
_EYE = 0xD8352A
_ALARM = 0xE8442E
_DIM = 0x71808C
_RAIL_OFF = 0x22303A


# Shared one-shot-cinematic maths (boot + hatch): a clamped 0..1 ramp over a
# frame window, smoothstep easing, and a linear RGB tween.
def _seg(f, a, b):
    if f <= a:
        return 0.0
    if f >= b:
        return 1.0
    return (f - a) / (b - a)


def _ease(t):                             # smoothstep
    return t * t * (3.0 - 2.0 * t)


def _mix(c0, c1, t):
    r = int((c0 >> 16 & 255) + ((c1 >> 16 & 255) - (c0 >> 16 & 255)) * t)
    g = int((c0 >> 8 & 255) + ((c1 >> 8 & 255) - (c0 >> 8 & 255)) * t)
    b = int((c0 & 255) + ((c1 & 255) - (c0 & 255)) * t)
    return (r << 16) | (g << 8) | b


def autodetect():
    """A display handle or None; never raises (dead panel != dead loader)."""
    try:
        return _Lifecycle(cicada_ui.boot())
    except Exception:
        return None


class _Lifecycle:
    def __init__(self, ui):
        self._ui = ui
        self._owns = True        # loader owns the panel until a script repaints
        self._detect = True      # DELETE-event takeover detection available
        self._repaint = False    # True while rebuilding our own screen
        self._stage = None
        self._molt = None        # (crack bar, label) live handles

    # ---- panel ownership ----
    def _on_delete(self, e):
        if not self._repaint:
            self._owns = False

    def _present(self):
        # Swap the off-screen build in as one frame. The retired screen's root
        # DELETE fires inside present(); the repaint guard keeps it from reading
        # as a pushed-script takeover (which is a DELETE while not repainting).
        self._repaint = True
        try:
            self._ui.present()
        except Exception:
            pass
        finally:
            self._repaint = False

    def _begin(self, stage, idx, color):
        self._stage = stage
        self._molt = None
        self._repaint = True
        try:
            scr = self._ui.screen(_NIGHT, atomic=True)
        finally:
            self._repaint = False
        root = self._flat(lv.obj(scr))
        root.set_size(_W, _H)
        root.set_pos(0, 0)
        try:
            root.add_event_cb(self._on_delete, lv.EVENT.DELETE, None)
        except Exception:
            self._detect = False
        self._rail(root, idx, color)
        return root

    # ---- shared parts ----
    @staticmethod
    def _flat(o, color=None, radius=0):
        o.set_style_border_width(0, 0)
        o.set_style_pad_all(0, 0)
        o.set_style_radius(radius, 0)
        o.set_style_bg_opa(255 if color is not None else 0, 0)
        if color is not None:
            o.set_style_bg_color(lv.color_hex(color), 0)
        try:
            o.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
            o.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except Exception:
            pass
        return o

    def _rail(self, parent, idx, color):
        # 5 instar dots climbing the left edge: egg at the bottom, adult on top
        for i in range(5):
            s = 10 if i == idx else 6
            d = self._flat(lv.obj(parent), color if i <= idx else _RAIL_OFF,
                           radius=s)
            d.set_size(s, s)
            d.set_pos(14 - s // 2, _H - (22 + i * 16) - s // 2)

    def _text(self, parent, s, color, align, y):
        l = lv.label(parent)
        l.set_text(s)
        l.set_style_text_color(lv.color_hex(color), 0)
        l.align(align, 0, y)
        return l

    def _ground(self, parent, y):
        h = _H - y
        soil = self._flat(lv.obj(parent), _SOIL[0])
        soil.set_size(_W, h)
        soil.set_pos(0, y)
        for frac, c in ((0.45, _SOIL[1]), (0.75, _SOIL[2])):
            band = self._flat(lv.obj(parent), c)
            band.set_size(_W, h - int(h * frac))
            band.set_pos(0, y + int(h * frac))
        for sx, sy in ((28, 26), (120, 48), (66, 74), (146, 22), (94, 104)):
            if sy < h - 8:
                st = self._flat(lv.obj(parent), _STONE, radius=3)
                st.set_size(7, 4)
                st.set_pos(sx, y + sy)
        line = self._flat(lv.obj(parent), _SURFACE)
        line.set_size(_W, 2)
        line.set_pos(0, y)

    def _nymph_body(self, parent):
        c = self._flat(lv.obj(parent))
        c.set_size(64, 44)
        body = self._flat(lv.obj(c), _CHITIN, radius=12)
        body.set_size(44, 24)
        body.align(lv.ALIGN.LEFT_MID, 0, -2)
        head = self._flat(lv.obj(c), _HUSK_DK, radius=9)
        head.set_size(18, 18)
        head.align(lv.ALIGN.RIGHT_MID, 0, -2)
        eye = self._flat(lv.obj(c), 0x120C05, radius=2)
        eye.set_size(4, 4)
        eye.align(lv.ALIGN.RIGHT_MID, -4, -7)
        for i in range(3):
            leg = self._flat(lv.obj(c), _HUSK_DK)
            leg.set_size(10, 2)
            leg.align(lv.ALIGN.BOTTOM_LEFT, 5 + i * 15, 0)
        return c

    def _anim(self, var, v0, v1, dur, cb, reverse=True):
        a = lv.anim_t()
        a.init()
        a.set_var(var)
        a.set_values(v0, v1)
        a.set_duration(dur)
        if reverse:
            a.set_reverse_duration(dur)
        a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
        a.set_custom_exec_cb(cb)
        a.start()

    def _led(self, color):
        try:
            self._ui.hex(color)
        except Exception:
            pass

    # ---- stages (loader-facing facade) ----
    def _egg_scene(self, root, detail, breathe=True):
        # The resting egg-on-a-twig tableau shared by egg() and the boot finale,
        # so the intro can dissolve into a byte-identical egg card (see boot()).
        self._text(root, "E G G", _HUSK, lv.ALIGN.TOP_MID, 18)
        self._text(root, "waking", _DIM, lv.ALIGN.TOP_MID, 42)
        gy = 150
        egg = self._flat(lv.obj(root), _HUSK, radius=11)
        egg.set_size(20, 30)
        egg.set_pos(_CX - 10, gy - 30)
        if breathe:
            def _breathe(a, v):
                try:
                    egg.set_style_opa(v, 0)
                except Exception:
                    pass
            self._anim(egg, 90, 255, 1400, _breathe)
        self._ground(root, gy)
        self._text(root, "unit " + detail, _DIM, lv.ALIGN.BOTTOM_MID, -14)
        return egg

    def egg(self, detail):
        try:
            self._led(0x201808)
            if not self._owns:
                return
            root = self._begin("egg", 0, _HUSK)
            self._egg_scene(root, detail)
            self._present()
        except Exception:
            pass

    def hatch(self, detail):
        # One-shot egg -> nymph transition, played once after the egg hold. The
        # egg wobbles, a crack opens, the shell splits into two halves that part
        # and fall away, and a nymph crawls out onto the grassline then burrows
        # down. The first frame matches the egg card and the last frame matches
        # nymph(connected=False), so both hand-offs are seamless.
        try:
            self._led(0x201808)
            if not self._owns:
                return
            self._stage = "hatch"
            self._molt = None
            self._repaint = True
            try:
                scr = self._ui.screen(_NIGHT, atomic=True)
            finally:
                self._repaint = False
            root = self._flat(lv.obj(scr))
            root.set_size(_W, _H)
            root.set_pos(0, 0)
            try:
                root.add_event_cb(self._on_delete, lv.EVENT.DELETE, None)
            except Exception:
                self._detect = False

            gy = 150
            self._ground(root, gy)
            self._text(root, "unit " + detail, _DIM, lv.ALIGN.BOTTOM_MID, -14)

            # Crossfading titles: egg card out, nymph card in.
            eggt = [self._text(root, "E G G", _HUSK, lv.ALIGN.TOP_MID, 18),
                    self._text(root, "waking", _DIM, lv.ALIGN.TOP_MID, 42)]
            nymt = [self._text(root, "N Y M P H", _CHITIN, lv.ALIGN.TOP_MID, 18),
                    self._text(root, "listening for a push", _DIM,
                               lv.ALIGN.TOP_MID, 42)]
            for c in nymt:
                c.set_style_opa(0, 0)

            # Instar rail crossfade: the lit egg dot (0) hands off to the nymph
            # rail (dot 0 dimmed to size 6, dot 1 lit at size 10).
            def _dot(idx, size, color):
                d = self._flat(lv.obj(root), color, radius=size)
                d.set_size(size, size)
                d.set_pos(14 - size // 2, _H - (22 + idx * 16) - size // 2)
                return d
            eggr = [_dot(0, 10, _HUSK)]
            nymr = [_dot(0, 6, _CHITIN), _dot(1, 10, _CHITIN)]
            for d in nymr:
                d.set_style_opa(0, 0)

            # The egg (fades at the split) with two shell halves that part and
            # fall, plus a dark crack that opens down the middle first.
            egg = self._flat(lv.obj(root), _HUSK, radius=11)
            egg.set_size(20, 30)
            egg.set_pos(_CX - 10, gy - 30)
            shl = self._flat(lv.obj(root), _HUSK, radius=6)
            shl.set_size(12, 30)
            shr = self._flat(lv.obj(root), _HUSK, radius=6)
            shr.set_size(12, 30)
            for s in (shl, shr):
                s.set_style_opa(0, 0)
            crack = self._flat(lv.obj(root), _NIGHT, radius=1)
            crack.set_size(2, 0)
            crack.set_style_opa(0, 0)

            # The emerging nymph, parked at the egg and burrowed down to rest.
            nym = self._nymph_body(root)
            nym.set_pos(_CX - 32, gy - 30)
            nym.set_style_opa(0, 0)

            self._present()

            _F = 68
            _REST = gy + 92                       # nymph(connected=False) depth
            st = {"f": 0}

            def _tick():
                try:
                    f = st["f"]
                    if f <= _F:
                        st["f"] = f + 1
                    try:
                        self._led(_mix(0x201808, 0x2A1C06, _seg(f, 20, 60)))
                    except Exception:
                        pass
                    for c in eggt:
                        c.set_style_opa(int(255 * (1.0 - _seg(f, 8, 26))), 0)
                    for c in nymt:
                        c.set_style_opa(int(255 * _seg(f, 30, 50)), 0)
                    for d in eggr:
                        d.set_style_opa(int(255 * (1.0 - _seg(f, 20, 38))), 0)
                    for d in nymr:
                        d.set_style_opa(int(255 * _seg(f, 34, 54)), 0)
                    wob = int(2.5 * math.sin(f * 0.6)) if f < 26 else 0
                    ch = int(30 * _seg(f, 16, 26))
                    crack.set_size(2, ch)
                    crack.set_pos(_CX - 1 + wob, gy - 30)
                    crack.set_style_opa(int(255 * (_seg(f, 16, 24)
                                                   * (1.0 - _seg(f, 26, 32)))), 0)
                    if f < 26:                    # shell whole, wobbling
                        egg.set_style_opa(255, 0)
                        egg.set_pos(_CX - 10 + wob, gy - 30)
                    else:                         # split: halves part and fall
                        egg.set_style_opa(0, 0)
                        part = _ease(_seg(f, 26, 48))
                        dx = int(18 * part)
                        dy = int(14 * part)
                        o = int(255 * (1.0 - _seg(f, 34, 50)))
                        shl.set_style_opa(o, 0)
                        shr.set_style_opa(o, 0)
                        shl.set_pos(_CX - 10 - dx, gy - 30 + dy)
                        shr.set_pos(_CX - 2 + dx, gy - 30 + dy)
                    nym.set_style_opa(int(255 * _seg(f, 28, 46)), 0)
                    ny = (gy - 30) + int((_REST - (gy - 30)) * _ease(_seg(f, 44, 66)))
                    nym.set_pos(_CX - 32, ny + int(2 * math.sin(f * 0.8)))
                except Exception:
                    pass

            _tick()
            self._ui.every(40, _tick)
        except Exception:
            pass

    def boot(self, detail):
        # One-shot boot cinematic, played before the egg card: a dusk sky titled
        # "CicadaOS", a cicada gliding from the top of frame down toward the
        # ground while the title dissolves and the camera pans until the horizon
        # sits mid-screen, then the cicada lays the egg on the grassline. Every moving
        # part is repositioned each tick from a single frame counter, and the
        # final frame is built to match egg() so the hand-off is seamless.
        try:
            self._led(0x201808)
            if not self._owns:
                return
            self._stage = "boot"
            self._molt = None
            self._repaint = True
            try:
                scr = self._ui.screen(_SKY, atomic=True)
            finally:
                self._repaint = False
            root = self._flat(lv.obj(scr))
            root.set_size(_W, _H)
            root.set_pos(0, 0)
            root.set_style_bg_color(lv.color_hex(_SKY), 0)
            root.set_style_bg_opa(255, 0)
            try:
                root.add_event_cb(self._on_delete, lv.EVENT.DELETE, None)
            except Exception:
                self._detect = False

            title = self._text(root, "CicadaOS", _HUSK, lv.ALIGN.TOP_MID, 70)
            sub = self._text(root, "loader", _MINT, lv.ALIGN.TOP_MID, 96)

            # World (ground + egg), parked below the screen and panned up
            # into view as the camera descends. Built in egg-card coordinates so
            # ground/egg land exactly where egg() draws them.
            _PAN = 210
            gy = 150
            world = self._flat(lv.obj(root))
            world.set_size(_W, _H)
            world.set_pos(0, _PAN)
            self._ground(world, gy)
            egg = self._flat(lv.obj(world), _HUSK, radius=11)
            egg.set_size(20, 30)
            egg.set_pos(_CX - 10, gy - 30)
            egg.set_style_opa(0, 0)               # laid late in the timeline

            # Egg-card chrome, screen-fixed and faded in at the very end so the
            # swap into egg() adds nothing. Each element is faded on its own leaf
            # (no reliance on parent-opa cascade).
            chrome = [
                self._text(root, "E G G", _HUSK, lv.ALIGN.TOP_MID, 18),
                self._text(root, "waking", _DIM, lv.ALIGN.TOP_MID, 42),
                self._text(root, "unit " + detail, _DIM, lv.ALIGN.BOTTOM_MID, -14),
            ]
            for i in range(5):                    # instar rail, egg dot lit (idx 0)
                s = 10 if i == 0 else 6
                d = self._flat(lv.obj(root), _HUSK if i == 0 else _RAIL_OFF,
                               radius=s)
                d.set_size(s, s)
                d.set_pos(14 - s // 2, _H - (22 + i * 16) - s // 2)
                chrome.append(d)
            for c in chrome:
                try:
                    c.set_style_opa(0, 0)
                except Exception:
                    pass

            # The gliding cicada (screen-fixed descent; the world rises to meet it).
            cic = self._flat(lv.obj(root))
            cic.set_size(46, 26)
            wl = self._flat(lv.obj(cic), _HUSK, radius=8)
            wl.set_size(18, 12)
            wl.set_pos(2, 2)
            wl.set_style_bg_opa(150, 0)
            wr = self._flat(lv.obj(cic), _HUSK, radius=8)
            wr.set_size(18, 12)
            wr.set_pos(26, 2)
            wr.set_style_bg_opa(150, 0)
            cbody = self._flat(lv.obj(cic), _CHITIN, radius=7)
            cbody.set_size(16, 22)
            cbody.align(lv.ALIGN.CENTER, 0, 2)
            chead = self._flat(lv.obj(cic), _HUSK_DK, radius=5)
            chead.set_size(10, 10)
            chead.align(lv.ALIGN.TOP_MID, 0, 0)
            cic.set_pos(_CX - 23, 6)

            self._present()

            _F = 105
            st = {"f": 0}

            def _tick():
                try:
                    f = st["f"]
                    if f <= _F:
                        st["f"] = f + 1
                    # dusk sky darkens into the egg card's night
                    root.set_style_bg_color(
                        lv.color_hex(_mix(_SKY, _NIGHT, _seg(f, 24, 88))), 0)
                    # title dissolves as the cicada glides past it
                    to = int(255 * (1.0 - _seg(f, 28, 58)))
                    title.set_style_opa(to, 0)
                    sub.set_style_opa(to, 0)
                    # camera pans the world up until the horizon is mid-screen
                    world.set_y(int(_PAN * (1.0 - _ease(_seg(f, 18, 86)))))
                    # cicada descends toward the grassline with a gentle sway + wingbeat
                    cy = 6 + (92 - 6) * _ease(_seg(f, 12, 84))
                    sway = int(7 * math.sin(f * 0.3))
                    cic.set_pos(int(_CX - 23 + sway), int(cy))
                    fw = 18 if (f // 2) % 2 == 0 else 11
                    wl.set_size(fw, 12)
                    wr.set_size(fw, 12)
                    wr.set_pos(44 - fw, 2)
                    # the egg is laid onto the grassline
                    egg.set_style_opa(int(255 * _seg(f, 78, 98)), 0)
                    # cicada lifts away off the top of frame once the egg is down
                    lift = _seg(f, 90, 105)
                    cic.set_y(int(92 - 126 * lift))
                    try:
                        cic.set_style_opa(int(255 * (1.0 - lift)), 0)
                    except Exception:
                        pass
                    # egg-card chrome fades in for a seamless hand-off to egg()
                    co = int(255 * _seg(f, 86, 105))
                    for c in chrome:
                        c.set_style_opa(co, 0)
                except Exception:
                    pass

            _tick()
            self._ui.every(40, _tick)
        except Exception:
            pass

    def nymph(self, connected, detail, awaiting):
        try:
            self._led(_CYAN if connected else 0x2A1C06)
            if not self._owns:
                return
            root = self._begin("nymph", 1, _CHITIN)
            self._text(root, "N Y M P H", _CHITIN, lv.ALIGN.TOP_MID, 18)
            gy = 150
            self._ground(root, gy)
            ny = gy + 16 if connected else gy + 92
            body = self._nymph_body(root)
            body.set_pos(_CX - 32, ny)

            def dig(a, v):
                try:
                    body.set_y(v)
                except Exception:
                    pass
            self._anim(body, ny - 2, ny + 2, 800, dig)
            if connected:
                self._text(root, "challenge " + detail, _CYAN,
                           lv.ALIGN.TOP_MID, 42)
                self._text(root, "phone linked", _DIM, lv.ALIGN.BOTTOM_MID, -14)
                dot = self._flat(lv.obj(root), _CYAN, radius=4)
                dot.set_size(8, 8)
                dot.set_pos(_CX - 4, gy - 26)
            else:
                self._text(root, "listening for a push", _DIM,
                           lv.ALIGN.TOP_MID, 42)
                self._text(root, "unit " + detail, _DIM,
                           lv.ALIGN.BOTTOM_MID, -14)
                ring = self._flat(lv.obj(root))
                ring.set_style_border_width(2, 0)
                ring.set_style_border_color(lv.color_hex(_CYAN), 0)
                ring.set_style_radius(32767, 0)

                def call(a, v):
                    try:
                        ring.set_size(v, v)
                        ring.set_pos(_CX - v // 2, gy - 34 - v // 2)
                        ring.set_style_border_opa(max(0, 255 - v * 4), 0)
                    except Exception:
                        pass
                self._anim(ring, 8, 56, 1600, call, reverse=False)
            self._present()
        except Exception:
            pass

    def molting(self, got, need):
        try:
            self._led(_MINT)
            if not self._owns:
                return
            if self._stage == "molt" and self._molt is not None:
                self._molt_update(got, need)
                return
            root = self._begin("molt", 2, _MINT)
            self._text(root, "M O L T I N G", _MINT, lv.ALIGN.TOP_MID, 18)
            lbl = self._text(root, "", _DIM, lv.ALIGN.TOP_MID, 42)
            self._ground(root, 236)
            husk = self._flat(lv.obj(root), _HUSK_DK, radius=26)
            husk.set_size(64, 128)
            husk.set_pos(_CX - 32, 88)
            crack = lv.bar(root)
            crack.set_size(8, 112)
            crack.set_pos(_CX - 4, 96)
            crack.set_range(0, 100)
            crack.set_style_bg_color(lv.color_hex(0x241708), 0)
            crack.set_style_bg_opa(255, 0)
            crack.set_style_radius(4, 0)
            crack.set_style_bg_color(lv.color_hex(_MINT), lv.PART.INDICATOR)
            crack.set_style_radius(4, lv.PART.INDICATOR)
            self._text(root, "shell splitting", _DIM, lv.ALIGN.BOTTOM_MID, -14)
            self._molt = (crack, lbl)
            self._molt_update(got, need)
            self._present()
        except Exception:
            pass

    def _molt_update(self, got, need):
        try:
            crack, lbl = self._molt
            if need > 0:
                pct = min(100, got * 100 // need)
                crack.set_value(pct, 0)
                lbl.set_text("receiving %d%%  -  %d B" % (pct, got))
            else:
                crack.set_value(4, 0)
                lbl.set_text("receiving")
        except Exception:
            pass

    def emergence(self):
        try:
            self._led(0xB0FFC0)
            if not self._owns:
                return
            root = self._begin("emergence", 3, _MINT)
            self._text(root, "E M E R G E N C E", _MINT, lv.ALIGN.TOP_MID, 18)
            self._text(root, "verifying signature", _DIM, lv.ALIGN.TOP_MID, 42)
            self._ground(root, 276)
            wl = self._wing(root, True)
            wr = self._wing(root, False)
            body = self._flat(lv.obj(root), _MINT, radius=15)
            body.set_size(30, 74)
            body.set_pos(_CX - 15, 128)
            head = self._flat(lv.obj(root), _MINT, radius=11)
            head.set_size(22, 22)
            head.set_pos(_CX - 11, 112)
            for dx in (-11, 11):
                eye = self._flat(lv.obj(root), _EYE, radius=3)
                eye.set_size(6, 6)
                eye.set_pos(_CX + dx - 3, 118)

            def unfurl(a, v):
                try:
                    wl.set_value(v)
                    wr.set_value(v)
                except Exception:
                    pass
            self._anim(body, 0, 110, 1100, unfurl)
            self._present()
        except Exception:
            pass

    def _wing(self, parent, left):
        w = lv.arc(parent)
        w.set_size(84, 84)
        w.set_pos(_CX - 84 - 2 if left else _CX + 2, 128)
        w.set_rotation(50 if left else 20)
        w.set_bg_angles(0, 110)
        w.set_range(0, 110)
        w.set_value(0)
        w.remove_style(None, lv.PART.KNOB)
        w.set_style_arc_opa(0, lv.PART.MAIN)
        w.set_style_bg_opa(0, lv.PART.MAIN)          # arc widget bg is opaque by default here -> hide the square
        w.set_style_border_width(0, lv.PART.MAIN)
        w.set_style_arc_width(7, lv.PART.INDICATOR)
        w.set_style_arc_color(lv.color_hex(_HUSK), lv.PART.INDICATOR)
        w.set_style_arc_opa(150, lv.PART.INDICATOR)
        return w

    def adult(self):
        try:
            self._led(_GREEN)
            if not self._owns:
                return
            if not self._detect:
                self._owns = False    # can't tell if a script painted: yield
                return
            root = self._begin("adult", 4, _GREEN)
            self._text(root, "A D U L T", _GREEN, lv.ALIGN.TOP_MID, 18)
            self._text(root, "script is running", _DIM, lv.ALIGN.TOP_MID, 42)
            for dx in (-16, 16):
                wing = self._flat(lv.obj(root), _HUSK, radius=12)
                wing.set_size(24, 66)
                wing.set_pos(_CX + dx - 12, 102)
                wing.set_style_bg_opa(70, 0)
            body = self._flat(lv.obj(root), _GREEN, radius=13)
            body.set_size(26, 62)
            body.set_pos(_CX - 13, 96)
            head = self._flat(lv.obj(root), _GREEN, radius=10)
            head.set_size(20, 20)
            head.set_pos(_CX - 10, 82)
            for dx in (-10, 10):
                eye = self._flat(lv.obj(root), _EYE, radius=3)
                eye.set_size(6, 6)
                eye.set_pos(_CX + dx - 3, 86)
            bars = [self._flat(lv.obj(root), _GREEN, radius=2)
                    for _ in range(9)]
            pat = (4, 10, 22, 34, 46, 34, 22, 10, 4, 3, 3)
            st = {"k": 0}

            def sing():
                try:
                    st["k"] += 1
                    for i, b in enumerate(bars):
                        h = pat[(st["k"] + i * 2) % len(pat)]
                        b.set_size(8, h)
                        b.set_pos(22 + i * 15, 252 - h)
                except Exception:
                    pass
            sing()
            self._ui.every(90, sing)
            self._text(root, "OK - done", _GREEN, lv.ALIGN.BOTTOM_MID, -14)
            self._present()
        except Exception:
            pass

    def rejected(self, kind):
        try:
            self._led(_ALARM)
            if not self._owns:
                return
            root = self._begin("rejected", 2, _ALARM)
            title = "R E J E C T E D" if kind == "sig" else "F A I L E D"
            sub = ("signature refused" if kind == "sig"
                   else "script raised an error")
            self._text(root, title, _ALARM, lv.ALIGN.TOP_MID, 18)
            self._text(root, sub, _DIM, lv.ALIGN.TOP_MID, 42)
            self._ground(root, 236)
            husk = self._flat(lv.obj(root), _HUSK_DK, radius=26)
            husk.set_size(64, 128)
            husk.set_pos(_CX - 32, 88)
            crack = self._flat(lv.obj(root), _ALARM, radius=3)
            crack.set_size(6, 112)
            crack.set_pos(_CX - 3, 96)
            for dx, dy, w in ((-14, 30, 18), (12, 66, 20)):
                s = self._flat(lv.obj(root), _ALARM, radius=2)
                s.set_size(w, 4)
                s.set_pos(_CX + dx - w // 2, 96 + dy)
            hint = ("not this brood" if kind == "sig"
                    else "waiting for another push")
            self._text(root, hint, _DIM, lv.ALIGN.BOTTOM_MID, -14)
            self._present()
        except Exception:
            pass
