"""Host-validation of the BLE script-loader (protocol v2, encrypted frames).
No hardware, no third-party deps: python3 tests/test_flow.py"""
import sys, types, os, re

FIRMWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FIRMWARE)

# ---- stubs: micropython + bluetooth + sys.print_exception -------------------
mp = types.ModuleType("micropython")
mp.const = lambda x: x
sys.modules["micropython"] = mp

if not hasattr(sys, "print_exception"):
    sys.print_exception = lambda e, f: f.write("%s: %s" % (type(e).__name__, e))

machine = types.ModuleType("machine")
machine.unique_id = lambda: bytes.fromhex("a1b2c3d4e5f6")  # fixed 6-byte test id
sys.modules["machine"] = machine

bt = types.ModuleType("bluetooth")


class UUID:
    def __init__(self, s): self.s = s
    def __bytes__(self): return bytes(16)


class BLE:
    def __init__(self):
        self.chars = {}
        self.notifies = []
        self.adv_calls = []
        self.adv_data = None
        self.resp_data = None
        self.disconnects = []
    def active(self, v): pass
    def config(self, **k): pass
    def irq(self, cb): self.cb = cb
    def gatts_register_services(self, s): return ((1, 2, 3),)  # tx, rx, nonce
    def gatts_set_buffer(self, h, n, append=False):
        self.rx_append = append
    def gap_advertise(self, interval, **k):
        self.adv_calls.append(interval)
        if interval is not None:
            self.adv_data = k.get("adv_data")
            self.resp_data = k.get("resp_data")
    def gatts_write(self, h, v): self.chars[h] = bytes(v)
    def gatts_read(self, h): return self.chars.get(h, b"")
    def gatts_notify(self, c, h, v): self.notifies.append(bytes(v))
    def gap_disconnect(self, conn):
        self.disconnects.append(conn)
        self.cb(2, (conn, 0, 0))  # mirror hardware: fire the DISCONNECT IRQ


bt.UUID = UUID
bt.BLE = BLE
sys.modules["bluetooth"] = bt

import ed25519 as E
import cryptobox as CB
assert not E.NATIVE and not CB.NATIVE_BOX, "host suite must exercise the pure-Python path"

# ---- minimal Ed25519 signer built on the module's own reference math --------
L = 2**252 + 27742317777372353535851937790883648493
_BASE9 = b"\x09" + b"\x00" * 31


def encodepoint(P):
    x, y = P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def keypair(seed):
    h = E._sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:], encodepoint(E._scalarmult(E._B, a))


def sign(seed, msg):
    a, prefix, pub = keypair(seed)
    r = int.from_bytes(E._sha512(prefix + msg), "little") % L
    R = encodepoint(E._scalarmult(E._B, r))
    h = int.from_bytes(E._sha512(R + pub + msg), "little") % L
    return R + ((r + h * a) % L).to_bytes(32, "little")


SEED = bytes(range(32))
_, _, PUB = keypair(SEED)

# Device X25519 test keypair (its private half is injected into main.py below).
DEV_PRIV = bytes([(i * 3 + 7) & 0xFF for i in range(32)])
DEV_PUB = CB.x25519(DEV_PRIV, _BASE9)

# signer sanity: roundtrip + tamper
assert E.ed25519_verify(PUB, b"hello", sign(SEED, b"hello"))
assert not E.ed25519_verify(PUB, b"hellp", sign(SEED, b"hello"))
assert not E.ed25519_verify(PUB, b"hello", bytearray(64))
print("signer sanity: OK")

# ---- load main.py with the test keys ----------------------------------------
src = open(os.path.join(FIRMWARE, "main.py")).read()
src = re.sub(r"^PUBKEY = .*$", lambda m: "PUBKEY = %r" % PUB, src, count=1, flags=re.M)
src = re.sub(r'DEVICE_X25519_PRIV = bytes\.fromhex\(\s*"[0-9a-f]*"\s*\)',
             lambda m: "DEVICE_X25519_PRIV = %r" % DEV_PRIV, src, count=1)
main = types.ModuleType("main")
main.__dict__["__name__"] = "main"
exec(compile(src, "main.py", "exec"), main.__dict__)

DOMAIN, VERSION = main.DOMAIN, main.VERSION
CONNECT, DISCONNECT = main._IRQ_CENTRAL_CONNECT, main._IRQ_CENTRAL_DISCONNECT

_DEF_EPH = bytes([(i * 5 + 1) & 0xFF for i in range(32)])
_DEF_AEAD = bytes(range(24))


def frame(script, nonce, seed=SEED, sig=None, eph_priv=_DEF_EPH,
          aead_nonce=_DEF_AEAD, device_pub=DEV_PUB):
    if isinstance(script, str):
        script = script.encode("utf-8")
    eph_pub = CB.x25519(eph_priv, _BASE9)
    shared = CB.x25519(eph_priv, device_pub)
    key = CB.kdf(shared, eph_pub, device_pub)
    vhdr = DOMAIN + bytes([VERSION]) + nonce + len(script).to_bytes(4, "big")
    mac, ct = CB.aead_lock(key, aead_nonce, vhdr, script)
    signed = vhdr + eph_pub + aead_nonce + ct + mac
    body = eph_pub + aead_nonce + ct + mac + (sig if sig is not None else sign(seed, signed))
    return len(body).to_bytes(4, "big") + body


def fresh():
    ldr = main.ScriptLoader()
    ble = ldr._ble
    ble.cb(CONNECT, (7, None, None))
    ble.notifies.clear()
    return ldr, ble


def nonce_of(ble): return ble.chars[3]


# 1. connect issues a nonce; RX buffer is append-mode
ldr, ble = fresh()
assert ble.rx_append is True, "RX buffer must be append=True"
assert len(nonce_of(ble)) == 32 and nonce_of(ble) != bytes(32)
assert None in ble.adv_calls, "advertising must stop on connect"
print("connect/nonce/append/adv-stop: OK")

# 2. valid encrypted frame delivered in hostile splits (mid-prefix, tiny chunks)
f = frame("notify('hi from script')", nonce_of(ble))
for i in range(0, len(f), 3):
    ldr._on_rx(f[i:i + 3])
assert nonce_of(ble) == bytes(32), "nonce char must be blanked on consume"
ldr.process()
assert b"OK:verified" in ble.notifies and b"OK:done" in ble.notifies
assert b"OUT:hi from script" in ble.notifies
assert nonce_of(ble) != bytes(32), "fresh nonce after process"
print("split-prefix encrypted frame + OUT channel: OK")

# 3. frame + partial next-frame prefix in one write; remainder later
ldr, ble = fresh()
n2 = nonce_of(ble)
f2 = frame("notify('two')", n2)
ldr._on_rx(f2 + b"\x00\x00")  # + first 2 bytes of the next length prefix
ldr.process()
assert b"OUT:two" in ble.notifies
n3 = nonce_of(ble)
f3 = frame("notify('three')", n3)
assert f3[:2] == b"\x00\x00", "v2 body length prefix begins 0x0000.."
ldr._on_rx(f3[2:])  # remainder of prefix + body; joins the 2 buffered bytes
ldr.process()
assert b"OUT:three" in ble.notifies
print("leftover partial prefix across writes: OK")

# 4. two complete frames in one write: second gets ERR:busy, first still runs
ldr, ble = fresh()
n = nonce_of(ble)
fa = frame("notify('a')", n)
fb = frame("notify('b')", n)
ldr._on_rx(fa + fb)
assert b"ERR:busy" in ble.notifies
ldr.process()
assert b"OUT:a" in ble.notifies and b"OUT:b" not in ble.notifies
print("pipelined second frame -> ERR:busy, first unaffected: OK")

# 5. oversized frame: ERR:len once, then force-disconnect (Fix 12)
ldr, ble = fresh()
ble.notifies.clear()
big = (main._MAX_FRAME + 1).to_bytes(4, "big") + bytes(500)
ldr._on_rx(big)
assert ble.notifies.count(b"ERR:len") == 1, ble.notifies
assert ble.disconnects == [7], "oversized frame must force-disconnect, not drain"
assert ldr._conn is None and ldr._buf == bytearray(), "state reset after disconnect"
print("oversized frame -> ERR:len + force-disconnect (no 4GB drain): OK")

# 6. bad signature: ERR:sig, no exec, nonce rotated
ldr, ble = fresh()
n = nonce_of(ble)
ldr._on_rx(frame("notify('evil')", n, sig=bytes(64)))
ldr.process()
assert b"ERR:sig" in ble.notifies and b"OUT:evil" not in ble.notifies
assert nonce_of(ble) not in (bytes(32), n)
print("bad sig refused, nonce rotated: OK")

# 7. decrypt failure (script encrypted to the WRONG device key): ERR:sig, no exec
ldr, ble = fresh()
n = nonce_of(ble)
wrong_pub = CB.x25519(bytes([9] * 32), _BASE9)
ldr._on_rx(frame("notify('secret')", n, device_pub=wrong_pub))
ldr.process()
assert b"ERR:sig" in ble.notifies and b"OUT:secret" not in ble.notifies, ble.notifies
print("wrong-device-key decrypt failure -> ERR:sig (stage not leaked): OK")

# 8. stale-nonce replay: capture a valid frame, replay after rotation
ldr, ble = fresh()
n = nonce_of(ble)
captured = frame("notify('replay')", n)
ldr._on_rx(captured)
ldr.process()
assert b"OUT:replay" in ble.notifies
ble.notifies.clear()
ldr._on_rx(captured)  # same bytes, new nonce active
ldr.process()
assert b"ERR:sig" in ble.notifies and b"OUT:replay" not in ble.notifies
print("replay refused: OK")

# 9. nonce consumed, pending already cleared -> ERR:nonce
ldr, ble = fresh()
n = nonce_of(ble)
ldr._on_rx(frame("notify('x')", n))
ldr._pending = None  # as if process() just grabbed it, mid-verify
ldr._on_rx(frame("notify('y')", n))
assert b"ERR:nonce" in ble.notifies
print("ERR:nonce when challenge already consumed: OK")

# 10. disconnect with a pending frame: dropped, never executed
ldr, ble = fresh()
n = nonce_of(ble)
ldr._on_rx(frame("notify('ghost')", n))
ble.cb(DISCONNECT, (7, None, None))
assert ldr._pending is None
ldr.process()
assert b"OUT:ghost" not in ble.notifies
assert ble.adv_calls[-1] == 100_000, "re-advertising after disconnect"
print("disconnect drops pending: OK")

# 11. wrong connection handle disconnect is ignored
ldr, ble = fresh()
ble.cb(DISCONNECT, (9, None, None))
assert ldr._conn == 7
print("foreign-handle disconnect ignored: OK")

# 12. script exception -> generic ERR:exec, no traceback body (Fix 5)
ldr, ble = fresh()
ldr._on_rx(frame("1/0", nonce_of(ble)))
ldr.process()
assert b"ERR:exec" in ble.notifies, ble.notifies
assert not any(b"ZeroDivision" in x for x in ble.notifies), "traceback must not leak"
assert nonce_of(ble) != bytes(32)
print("script exception -> generic ERR:exec (no traceback leak): OK")

# 13. sandbox (Fix 7): filesystem write is denied, loader untouched
ldr, ble = fresh()
before = open(os.path.join(FIRMWARE, "main.py"), "rb").read()
ldr._on_rx(frame("open('main.py','w').write('x')", nonce_of(ble)))
ldr.process()
assert b"ERR:exec" in ble.notifies, ble.notifies
assert b"OK:done" not in ble.notifies
after = open(os.path.join(FIRMWARE, "main.py"), "rb").read()
assert before == after, "sandboxed script must not modify main.py"
print("sandbox denies open('main.py','w'): OK")

# 14. sandbox: importing a denied module fails
ldr, ble = fresh()
ldr._on_rx(frame("import os", nonce_of(ble)))
ldr.process()
assert b"ERR:exec" in ble.notifies and b"OK:done" not in ble.notifies
print("sandbox denies `import os`: OK")

# 15. sandbox: an allow-listed import + normal builtins still run (regression)
ldr, ble = fresh()
ldr._on_rx(frame("import math\nnotify(int(math.sqrt(16)))", nonce_of(ble)))
ldr.process()
assert b"OK:done" in ble.notifies and b"OUT:4" in ble.notifies, ble.notifies
print("sandbox allows math + notify (regression): OK")

# ---- per-device identity + "awaiting script" flag ---------------------------
def parse_ads(payload):
    ads, i, payload = {}, 0, bytes(payload)
    while i < len(payload):
        ln = payload[i]
        if ln == 0:
            break
        ads[payload[i + 1]] = payload[i + 2:i + 1 + ln]
        i += 1 + ln
    return ads


def mfr_fields(resp):
    mfr = parse_ads(resp)[0xFF]
    return int.from_bytes(mfr[:2], "little"), mfr[2:4], mfr[4], mfr[5:11]


# 16. mfr identity in scan response, AD budget within 31 bytes, awaiting at boot
ldr, ble = fresh()
assert len(ble.adv_data) <= 31 and len(ble.resp_data) <= 31, (len(ble.adv_data), len(ble.resp_data))
company, magic, flags, dev_id = mfr_fields(ble.resp_data)
assert company == 0xFFFF and magic == b"\xc1\xca"
assert dev_id == bytes.fromhex("a1b2c3d4e5f6"), dev_id
assert flags & 0x01, "awaiting bit must be set at boot"
print("mfr identity present, AD budget<=31, awaiting set at boot: OK")

# 17. bad sig keeps awaiting; first OK:done clears it; re-advertise reflects it
ble.notifies.clear()
ldr._on_rx(frame("notify('evil')", nonce_of(ble), sig=bytes(64)))
ldr.process()
assert ldr._awaiting is True, "bad sig must not clear awaiting"
ldr._on_rx(frame("notify('ok')", nonce_of(ble)))
ldr.process()
assert b"OK:done" in ble.notifies and ldr._awaiting is False, "OK:done clears awaiting"
ble.cb(DISCONNECT, (7, None, None))  # re-advertise with the current flag value
assert not (mfr_fields(ble.resp_data)[2] & 0x01), "awaiting cleared after successful exec"
print("awaiting lifecycle (bad-sig keeps, OK:done clears, re-adv reflects): OK")

# 18. empty script is a valid v2 frame (min body = 136 bytes)
ldr, ble = fresh()
ldr._on_rx(frame("", nonce_of(ble)))
ldr.process()
assert b"OK:done" in ble.notifies
print("empty script accepted: OK")

# ---- loader status display (cicada lifecycle facade) ------------------------
class FakeDisplay:
    def __init__(self): self.calls = []
    def egg(self, detail): self.calls.append(("egg", detail))
    def nymph(self, connected, detail, awaiting):
        self.calls.append(("nymph", connected, detail, awaiting))
    def molting(self, got, need): self.calls.append(("molting", got, need))
    def emergence(self): self.calls.append(("emergence",))
    def adult(self): self.calls.append(("adult",))
    def rejected(self, kind): self.calls.append(("rejected", kind))
    def stages(self): return [c[0] for c in self.calls]


_clk = {"t": 0}
main._ticks_ms = lambda: _clk["t"]
main._ticks_add = lambda a, b: a + b
main._ticks_diff = lambda a, b: a - b

# 19. boot shows the egg; the BLE IRQ never draws; boot card holds ~2 s
disp = FakeDisplay()
ldr = main.ScriptLoader(display=disp)
ble = ldr._ble
assert disp.calls == [("egg", "a1b2c3d4e5f6")], disp.calls
before = len(disp.calls)
ble.cb(CONNECT, (7, None, None))
assert len(disp.calls) == before, "no display I/O inside the BLE IRQ"
ldr._update_display()
assert disp.stages() == ["egg"], "boot card must hold before nymph"
_clk["t"] = 2001
ldr._update_display()
assert disp.calls[-1] == ("nymph", True, nonce_of(ble)[:4].hex(), True), disp.calls[-1]
print("display: egg at boot, IRQ draws nothing, boot hold then nymph: OK")

# 20. molting progress from the main loop, then emergence -> adult, hold, nymph
f = frame("notify('ui')", nonce_of(ble))
before = len(disp.calls)
ldr._on_rx(f[:10])
assert len(disp.calls) == before, "RX IRQ path must not draw"
ldr._update_display()
assert disp.calls[-1] == ("molting", 6, len(f) - 4), disp.calls[-1]
ldr._on_rx(f[10:])
ldr._update_display()  # frame pending: process() narrates from here
assert disp.calls[-1][0] == "molting"
ldr.process()
assert disp.stages()[-2:] == ["emergence", "adult"], disp.stages()
ldr._update_display()
assert disp.stages()[-1] == "adult", "success card must hold"
_clk["t"] += 6001
ldr._update_display()
assert disp.calls[-1] == ("nymph", True, nonce_of(ble)[:4].hex(), False), disp.calls[-1]
ble.cb(DISCONNECT, (7, None, None))
ldr._update_display()
assert disp.calls[-1] == ("nymph", False, "a1b2c3d4e5f6", False), disp.calls[-1]
print("display: molting progress, emergence->adult, hold, nymph again: OK")

# 21. bad signature: emergence then rejected('sig')
disp = FakeDisplay()
ldr = main.ScriptLoader(display=disp)
ble = ldr._ble
ble.cb(CONNECT, (7, None, None))
ldr._on_rx(frame("notify('evil')", nonce_of(ble), sig=bytes(64)))
ldr.process()
assert disp.stages()[-2:] == ["emergence", "rejected"], disp.stages()
assert disp.calls[-1] == ("rejected", "sig")
print("display: bad sig -> emergence, rejected('sig'): OK")

# 22. script exception: rejected('exec')
disp = FakeDisplay()
ldr = main.ScriptLoader(display=disp)
ble = ldr._ble
ble.cb(CONNECT, (7, None, None))
ldr._on_rx(frame("1/0", nonce_of(ble)))
ldr.process()
assert disp.calls[-1] == ("rejected", "exec"), disp.calls[-1]
print("display: script exception -> rejected('exec'): OK")

# 23. a raising display is disabled on first fault; BLE flow is unharmed
class BoomDisplay(FakeDisplay):
    def emergence(self): raise RuntimeError("panel dead")


ldr = main.ScriptLoader(display=BoomDisplay())
ble = ldr._ble
ble.cb(CONNECT, (7, None, None))
ldr._on_rx(frame("notify('ok')", nonce_of(ble)))
ldr.process()
assert b"OK:done" in ble.notifies, "a dead panel must not break the push"
assert isinstance(ldr._display, main.NullDisplay), "faulting display gets nulled"
print("display: faulting panel disabled, loader unharmed: OK")

# 24. cross-check against the shared app vectors (byte-agreement with Dart)
import json
vpath = os.path.join(FIRMWARE, "..", "app", "tools_vectors", "vectors.json")
with open(vpath) as fh:
    doc = json.load(fh)
assert doc["version"] == 0x02 and doc["pubkey"] == PUB.hex()
vdev_priv = bytes.fromhex(doc["device_x25519_priv"])
vdev_pub = bytes.fromhex(doc["device_x25519_pub"])
for v in doc["vectors"]:
    nonce = bytes.fromhex(v["nonce"])
    eph_priv = bytes.fromhex(v["eph_priv"])
    aead_nonce = bytes.fromhex(v["aead_nonce"])
    built = frame(v["script"], nonce, eph_priv=eph_priv, aead_nonce=aead_nonce,
                  device_pub=vdev_pub)
    body = built[4:]
    assert body.hex() == v["frame_body"], "frame_body mismatch for %s" % v["name"]
    # and the device recovers the plaintext with the vector's device key
    vhdr = DOMAIN + bytes([VERSION]) + nonce + len(v["script"].encode()).to_bytes(4, "big")
    eph_pub = bytes.fromhex(v["eph_pub"])
    shared = CB.x25519(vdev_priv, eph_pub)
    key = CB.kdf(shared, eph_pub, vdev_pub)
    pt = CB.aead_unlock(key, aead_nonce, bytes.fromhex(v["mac"]), vhdr, bytes.fromhex(v["ciphertext"]))
    assert pt == v["script"].encode("utf-8"), "decrypt mismatch for %s" % v["name"]
print("vectors byte-agreement + device decrypt (%d cases): OK" % len(doc["vectors"]))

print("\nALL TESTS PASSED")
