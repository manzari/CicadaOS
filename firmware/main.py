# main.py -- BLE script-loader stub for MicroPython on ESP32 (protocol v2).
#
# On every connection it issues a fresh random 32-byte challenge (nonce). The
# phone encrypts a small MicroPython script TO THIS DEVICE'S X25519 key, signs
# the encrypted blob bound to the nonce, and sends it. The ESP runs the script
# ONLY if the Ed25519 signature verifies AND the ciphertext decrypts under this
# unit's private key. A captured frame is useless: it won't verify against the
# next nonce, or on any other unit, and a passive sniffer sees only ciphertext.
#
# Wire protocol (Nordic UART Service + one extra characteristic):
#   NONCE char (read)   : phone reads the current 32-byte challenge
#   RX    char (write)  : phone -> ESP, one length-prefixed frame:
#                           [4-byte BE frame length N][ N bytes = frame body ]
#   TX    char (notify) : ESP -> phone, ASCII status: "NONCE"/"OK:*"/"OUT:*"/"ERR:*"
#
# v2 frame body (see CLAUDE.md "Wire protocol"):
#   eph_pub(32) || aead_nonce(24) || ciphertext(N) || mac(16) || sig(64)
#     shared     = X25519(DEVICE_X25519_PRIV, eph_pub)
#     key        = BLAKE2b-512(shared || eph_pub || DEVICE_X25519_PUB)[:32]
#     AAD        = DOMAIN || version(2) || nonce(32) || len(ciphertext) BE4
#     plaintext  = XChaCha20-Poly1305_unlock(key, aead_nonce, AAD, ciphertext, mac)
#     sig        = Ed25519(DOMAIN || version(2) || nonce || len(ciphertext) BE4
#                          || eph_pub || aead_nonce || ciphertext || mac)
#
# The signing PRIVATE key lives on the phone; the ESP holds only PUBKEY. The
# X25519 decryption key (DEVICE_X25519_PRIV) is per-unit and, on a hardened
# board, protected by flash encryption (see CLAUDE.md "Provisioning requirements").

import bluetooth
import struct
import os
import io
import sys
import time
import machine
import builtins as _builtins
from micropython import const
from ed25519 import ed25519_verify
from cryptobox import x25519, aead_unlock, kdf

# ------------------------------------------------------------------ CONFIG ---
DEVICE_NAME = "esp-script"
DOMAIN = b"espscript-v1"       # domain-separation tag; must match the signer
VERSION = const(2)             # protocol v2 (encrypted). v1 frames are rejected.
_DEBUG = False                 # True -> exec tracebacks on the wire (dev only)

# Ed25519 public key: 32 RAW bytes (the encoded point A) of the phone's signing
# key. Dumping a unit's flash reveals nothing that can forge a push.
# NOTE: the value below is a THROWAWAY TEST key -- rotate before any deployment
# (see CLAUDE.md "Provisioning requirements").
PUBKEY = bytes.fromhex("73871a59bc7d20612bd841297673847fbcc5242cbf9f1daa36bd3006064690a1")

# X25519 decryption key: 32 RAW private bytes, UNIQUE PER UNIT. Provision like
# PUBKEY (offline keygen, flash, protect with flash encryption). The public half
# is pinned by the phone so it can encrypt scripts to this device.
DEVICE_X25519_PRIV = bytes.fromhex(
    "0000000000000000000000000000000000000000000000000000000000000000")

if PUBKEY == bytes(32):        # refuse to run unconfigured (placeholder is not inert)
    raise ValueError("Set PUBKEY to your Ed25519 public key before flashing")
if DEVICE_X25519_PRIV == bytes(32):
    raise ValueError("Set DEVICE_X25519_PRIV to this unit's X25519 key before flashing")

_X25519_BASE = b"\x09" + b"\x00" * 31
DEVICE_X25519_PUB = x25519(DEVICE_X25519_PRIV, _X25519_BASE)

# ------------------------------------------------------------ exec sandbox ---
# A signed script is authenticated but NOT trusted with the loader. Run it with a
# minimal builtins allow-list and a guarded __import__: no `open`, no filesystem
# (`os`/`io`/`vfs`) and no raw-flash (`esp`/`flashbdev`) modules, so it cannot
# rewrite main.py or overwrite PUBKEY and persist. Hardware modules a dashboard
# script legitimately needs stay reachable. (MicroPython does not expose the
# CPython __subclasses__/__globals__ escape hatches, so the allow-list holds.)
_ALLOWED_IMPORTS = (
    "math", "time", "random", "struct", "gc", "micropython", "machine",
    "cicada_ui", "lvgl", "lv", "jd9853", "axs5106", "i2c", "neopixel",
    "lcd_bus", "task_handler",
)
_real_import = _builtins.__import__


def _guarded_import(name, g=None, l=None, fromlist=(), level=0):
    if name.split(".", 1)[0] not in _ALLOWED_IMPORTS:
        raise ImportError("import of '%s' is not allowed" % name)
    return _real_import(name, g, l, fromlist, level)


_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bin", "bool", "bytearray", "bytes", "callable", "chr",
    "complex", "dict", "divmod", "enumerate", "filter", "float", "frozenset",
    "hash", "hex", "id", "int", "isinstance", "issubclass", "iter", "len", "list",
    "map", "max", "min", "next", "oct", "ord", "pow", "print", "range", "repr",
    "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "type",
    "zip", "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "RuntimeError", "StopIteration", "ArithmeticError", "ZeroDivisionError",
    "OverflowError", "AttributeError", "NotImplementedError", "OSError",
    "MemoryError", "NameError", "print",
)


def _safe_builtins():
    d = {"__import__": _guarded_import}
    for n in _SAFE_BUILTIN_NAMES:
        if hasattr(_builtins, n):
            d[n] = getattr(_builtins, n)
    bc = getattr(_builtins, "__build_class__", None)  # CPython needs this for `class`
    if bc is not None:
        d["__build_class__"] = bc
    return d


# --------------------------------------------------------------- BLE consts ---
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_MTU_EXCHANGED = const(21)

_F_READ = const(0x0002)
_F_WRITE_NR = const(0x0004)
_F_WRITE = const(0x0008)
_F_NOTIFY = const(0x0010)

_UART = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), _F_NOTIFY)
_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), _F_WRITE | _F_WRITE_NR)
_NONCE = (bluetooth.UUID("6E400004-B5A3-F393-E0A9-E50E24DCCA9E"), _F_READ)
_SERVICE = (_UART, (_TX, _RX, _NONCE))

_ADV_FLAGS = const(0x01)
_ADV_NAME = const(0x09)
_ADV_UUID128 = const(0x07)
_ADV_MFR = const(0xFF)         # manufacturer-specific data AD type

# v2 frame overhead = eph_pub(32) + aead_nonce(24) + mac(16) + sig(64).
_V2_OVERHEAD = const(136)
_MAX_SCRIPT = const(16384)     # ciphertext == plaintext length for a stream cipher
_MAX_FRAME = const(16384 + 136)  # reject absurd length prefixes

# Per-device identity + boot state advertised as manufacturer data so the phone
# can recognise a specific ESP and detect a fresh boot (CLAUDE.md advertising).
_MFR_COMPANY = const(0xFFFF)
_MFR_MAGIC = b"\xc1\xca"       # payload magic: identifies a CicadaOS ESP
_MFR_AWAITING = const(0x01)    # flags bit0: no valid script has run since boot

# ------------------------------------------------- loader status display -----
# The panel narrates loader state as a cicada life cycle (lifecycle_ui.py).
# All display I/O happens in the main loop (process/_update_display) -- NEVER
# in the BLE IRQ. Terminal cards are held on screen before returning to nymph.
# Boot plays a one-shot cinematic (sky + "CicadaOS" + a cicada gliding down to
# lay the egg) that resolves into the egg card, which holds >= 5 s, then a
# one-shot hatch transition (the egg splits and a nymph crawls out and burrows)
# before the loader settles into the live nymph flow.
_HOLD_INTRO_MS = const(4500)    # boot cinematic; must outlast the animation
_HOLD_EGG_MS = const(5000)      # egg card min hold after the intro (spec: >= 5 s)
_HOLD_HATCH_MS = const(3000)    # egg->nymph hatch transition; outlast its animation
_HOLD_ERR_MS = const(2500)
_HOLD_OK_MS = const(6000)
_MIN_SHOW_MS = const(1000)      # floor: every lifecycle card stays up this long

# CPython (host tests) lacks time.ticks_*; MicroPython has them and they wrap.
_ticks_ms = getattr(time, "ticks_ms", None) or (lambda: int(time.time() * 1000))
_ticks_add = getattr(time, "ticks_add", None) or (lambda a, b: a + b)
_ticks_diff = getattr(time, "ticks_diff", None) or (lambda a, b: a - b)
_sleep_ms = getattr(time, "sleep_ms", None) or (lambda ms: time.sleep(ms / 1000.0))


class NullDisplay:
    def boot(self, detail): pass
    def egg(self, detail): pass
    def hatch(self, detail): pass
    def nymph(self, connected, detail, awaiting): pass
    def molting(self, got, need): pass
    def emergence(self): pass
    def adult(self): pass
    def rejected(self, kind): pass


def _autodetect_display():
    # Never raises: a missing/broken panel must not stop the BLE loader.
    try:
        import lifecycle_ui
        d = lifecycle_ui.autodetect()
        if d is not None:
            return d
    except Exception:
        pass
    return NullDisplay()


def _device_id():
    # 6 stable bytes identifying this unit across reboots and phones (unlike the
    # iOS peripheral UUID). machine.unique_id() is the eFuse MAC on ESP32.
    try:
        uid = bytes(machine.unique_id())
    except Exception:
        uid = b""
    return (uid + b"\x00" * 6)[:6]


def _adv_payload(name):
    p = bytearray()
    p += struct.pack("BB", 2, _ADV_FLAGS) + b"\x06"
    n = name.encode()
    p += struct.pack("BB", len(n) + 1, _ADV_NAME) + n
    return bytes(p)


def _resp_payload(uuid, dev_id, awaiting):
    # Scan response: 128-bit NUS UUID (18 B) + manufacturer data (13 B) = 31 B,
    # exactly the AD budget. UUID stays advertised so iOS can filter by service.
    u = bytes(uuid)            # 16 bytes for a 128-bit UUID
    p = bytearray()
    p += struct.pack("BB", len(u) + 1, _ADV_UUID128) + u
    flags = _MFR_AWAITING if awaiting else 0x00
    body = struct.pack("<H", _MFR_COMPANY) + _MFR_MAGIC + bytes([flags]) + dev_id
    p += struct.pack("BB", len(body) + 1, _ADV_MFR) + body
    return bytes(p)


class ScriptLoader:
    def __init__(self, name=DEVICE_NAME, display=None):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.config(gap_name=name)
        try:
            self._ble.config(mtu=256)
        except Exception:
            pass
        self._ble.irq(self._irq)
        ((self._tx, self._rx, self._nh),) = self._ble.gatts_register_services((_SERVICE,))
        self._ble.gatts_set_buffer(self._rx, 1024, True)  # append: queued WNR chunks must not overwrite

        self._conn = None
        self._mtu = 23
        self._nonce = None
        self._buf = bytearray()
        self._need = None         # parsed frame length, or None until prefix seen
        self._pending = None      # (nonce, blob) ready for the main loop

        self._dev_id = _device_id()
        self._awaiting = True     # boot state: no valid script has run yet
        self._adv = _adv_payload(name)
        self._advertise()

        self._display = display or NullDisplay()
        self._shown = None        # last state key drawn (dedupe for the loop)
        self._hold_until = None   # keep the current card up until this tick
        self._stage = None        # last lifecycle method drawn (min-show floor)
        self._stage_at = _ticks_ms()
        self._boot_seq = True      # play intro -> egg -> nymph before normal flow
        self._show("boot", self._dev_id.hex())
        self._hold(_HOLD_INTRO_MS)

    # -- BLE plumbing ---------------------------------------------------------
    def _advertise(self):
        # Rebuild the scan response each time so the awaiting flag reflects the
        # current state on every (re)advertise after a disconnect.
        resp = _resp_payload(_UART, self._dev_id, self._awaiting)
        self._ble.gap_advertise(100_000, adv_data=self._adv, resp_data=resp)

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn, _, _ = data
            self._conn = conn
            self._mtu = 23
            self._pending = None
            self._reset_rx()
            self._ble.gap_advertise(None)     # exclusive: one central at a time
            self._issue_nonce()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn, _, _ = data
            if conn != self._conn:
                return
            self._conn = None
            self._nonce = None
            self._pending = None              # never run a script for a central that left
            self._reset_rx()
            self._advertise()
        elif event == _IRQ_MTU_EXCHANGED:
            conn, mtu = data
            if conn == self._conn:
                self._mtu = mtu
        elif event == _IRQ_GATTS_WRITE:
            conn, attr = data
            if attr == self._rx:
                self._on_rx(self._ble.gatts_read(self._rx))

    def _reset_rx(self):
        self._buf = bytearray()
        self._need = None

    def _disconnect(self):
        if self._conn is not None:
            try:
                self._ble.gap_disconnect(self._conn)
            except Exception:
                pass

    def _notify(self, msg):
        if self._conn is None:
            return
        step = max(self._mtu - 3, 20)
        for i in range(0, len(msg), step):
            try:
                self._ble.gatts_notify(self._conn, self._tx, msg[i:i + step])
            except Exception:
                break

    # -- display (main loop only; the BLE IRQ never touches these) -------------
    def _show(self, method, *a):
        # Hold the previous card on screen for _MIN_SHOW_MS before the next paints
        # over it -- native verify can flip emergence->adult in a few ms, so this
        # is what guarantees each lifecycle stage is actually seen (~1 s floor).
        # Same-method redraws (molting progress, nymph challenge) are not padded.
        if self._stage is not None and method != self._stage:
            rem = _MIN_SHOW_MS - _ticks_diff(_ticks_ms(), self._stage_at)
            if rem > 0:
                _sleep_ms(rem)
        try:
            getattr(self._display, method)(*a)
        except Exception:
            self._display = NullDisplay()   # one glitch disables the panel, not BLE
        self._stage = method
        self._stage_at = _ticks_ms()

    def _hold(self, ms):
        self._hold_until = _ticks_add(_ticks_ms(), ms)

    def _held(self):
        return (self._hold_until is not None
                and _ticks_diff(self._hold_until, _ticks_ms()) > 0)

    def _update_display(self):
        # Poll IRQ-written state and narrate it. process() covers the pending
        # frame itself (emergence/adult/rejected), so skip while one is queued.
        if self._pending is not None:
            return
        if self._boot_seq:
            # Linear boot prelude: hold the intro cinematic, then the egg card
            # (>= _HOLD_EGG_MS), then the egg->nymph hatch transition, then fall
            # through to the live nymph/molting flow. A push mid-prelude (stage
            # becomes emergence/adult/rejected) ends it.
            if self._stage not in ("boot", "egg", "hatch"):
                self._boot_seq = False
            elif self._held():
                return
            elif self._stage == "boot":
                self._shown = None
                self._show("egg", self._dev_id.hex())
                self._hold(_HOLD_EGG_MS)
                return
            elif self._stage == "egg":            # egg hold elapsed -> hatch
                self._shown = None
                self._show("hatch", self._dev_id.hex())
                self._hold(_HOLD_HATCH_MS)
                return
            else:                                 # hatch done -> go live
                self._boot_seq = False
                self._shown = None
        if self._conn is None:
            st = ("nymph", False, self._dev_id.hex(), self._awaiting)
        elif self._need is not None or self._buf:
            st = ("molting", len(self._buf), self._need or 0)
        else:
            n = self._nonce
            st = ("nymph", True, n[:4].hex() if n else "", self._awaiting)
        if st == self._shown:
            return
        if st[0] == "nymph" and self._held():
            return                          # keep the boot/terminal card up
        self._hold_until = None
        self._shown = st
        self._show(st[0], *st[1:])

    def _issue_nonce(self):
        # Fresh single-use challenge, published on the readable NONCE char.
        self._nonce = os.urandom(32)          # ESP32 hardware RNG (radio active)
        self._ble.gatts_write(self._nh, self._nonce)
        self._notify(b"NONCE")                # tell the phone to (re)read it

    # -- framing (runs in IRQ context: keep it cheap, no crypto here) ----------
    def _on_rx(self, chunk):
        if not chunk:
            return
        self._buf.extend(chunk)
        while True:
            if self._need is None:
                if len(self._buf) < 4:
                    return
                self._need = int.from_bytes(self._buf[:4], "big")
                self._buf = self._buf[4:]
                if self._need > _MAX_FRAME:
                    # Never drain up to 4 GB to resync -- a garbage length
                    # would wedge the link. Drop everything and force a reconnect.
                    self._need = None
                    self._notify(b"ERR:len")
                    self._reset_rx()
                    self._disconnect()
                    return
            if len(self._buf) < self._need:
                return
            take = self._need
            self._need = None
            if self._pending is not None:
                self._buf = self._buf[take:]
                self._notify(b"ERR:busy")
                continue
            if self._nonce is None:
                self._buf = self._buf[take:]
                self._notify(b"ERR:nonce")
                continue
            blob = bytes(self._buf[:take])
            self._buf = self._buf[take:]
            self._pending = (self._nonce, blob)
            self._nonce = None                # consume: next frame needs a new one
            self._ble.gatts_write(self._nh, bytes(32))  # blank the stale challenge

    # -- verify + decrypt + run (main loop, off the BLE stack) ----------------
    def _recover(self, nonce, blob):
        # Return the plaintext script, or None if auth/decryption fails. A single
        # ERR:sig covers a bad signature AND a decryption/MAC failure so the wire
        # never reveals which stage rejected the frame.
        if len(blob) < _V2_OVERHEAD:
            return None
        eph_pub = blob[0:32]
        aead_nonce = blob[32:56]
        ct = blob[56:-80]
        mac = blob[-80:-64]
        sig = blob[-64:]

        vhdr = DOMAIN + bytes([VERSION]) + nonce + len(ct).to_bytes(4, "big")
        signed = vhdr + eph_pub + aead_nonce + ct + mac
        if not ed25519_verify(PUBKEY, signed, sig):
            return None
        try:
            shared = x25519(DEVICE_X25519_PRIV, eph_pub)
            key = kdf(shared, eph_pub, DEVICE_X25519_PUB)
            return aead_unlock(key, aead_nonce, mac, vhdr, ct)  # AAD = vhdr
        except Exception:
            return None

    def process(self):
        if self._pending is None:
            return
        nonce, blob = self._pending
        self._pending = None

        if self._conn is None:                # central left mid-flight: drop, don't run
            return

        self._shown = None                    # this frame owns the screen now
        self._show("emergence")               # drawn BEFORE the (maybe slow) verify
        script = self._recover(nonce, blob)
        if script is None:
            self._notify(b"ERR:sig")
            self._show("rejected", "sig")
            self._hold(_HOLD_ERR_MS)
            self._issue_nonce()               # rotate; force a fresh challenge
            return

        self._notify(b"OK:verified")
        g = {"__builtins__": _safe_builtins(),
             "notify": lambda s: self._notify(b"OUT:" + str(s).encode()[:180])}
        try:
            exec(compile(script.decode("utf-8"), "app", "exec"), g)  # authenticated, sandboxed
            self._awaiting = False        # first success clears the boot flag
            self._notify(b"OK:done")
            self._show("adult")           # no-op if the script painted its own UI
            self._hold(_HOLD_OK_MS)
        except Exception as e:
            if _DEBUG:
                tb = io.StringIO()
                sys.print_exception(e, tb)
                self._notify(b"ERR:" + tb.getvalue().encode()[:180])
            else:
                self._notify(b"ERR:exec")     # no source line / secret leak
            self._show("rejected", "exec")
            self._hold(_HOLD_ERR_MS)
        finally:
            # Drop references so GC can reclaim the script memory promptly.
            # Not a zeroise (MicroPython can't guarantee that) -- it just shortens
            # the live-RAM window; flash encryption is the real guarantee.
            g.clear()
            del g, script, blob

        self._issue_nonce()                   # ready for the next script this session

    def run(self):
        while True:
            self.process()
            self._update_display()
            time.sleep_ms(50)


if __name__ == "__main__":
    ScriptLoader(display=_autodetect_display()).run()
