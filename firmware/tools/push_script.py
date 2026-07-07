#!/usr/bin/env python3
# push_script.py -- bleak desktop client for the BLE script-loader stub (v2).
#
# Exercises a flashed ESP32 end-to-end without the Android app: connect, read
# the challenge nonce, ENCRYPT the script to the device's X25519 key, sign the
# encrypted blob bound to the nonce, push the v2 frame, and print the TX status
# stream. It is the reference for the byte-for-byte contract the Android signer
# must also satisfy (CLAUDE.md wire protocol).
#
#   python push_script.py --keygen                    # make tools/testkey.pem, print PUBKEY hex
#   python push_script.py --keygen-x25519             # make a device X25519 keypair, print both halves
#   python push_script.py hello.py --device-priv HEX  # encrypt+sign+push, expect OK:done
#   python push_script.py hello.py --device-key  HEX  # ...if you only have the device's public half
#   python push_script.py hello.py --device-priv HEX --bad-sig  # corrupt one sig byte, expect ERR:sig
#   python push_script.py hello.py --device-priv HEX --replay   # push twice, expect OK:done then ERR:sig
#
# The signing PRIVATE key lives in tools/testkey.pem (never commit it); its raw
# 32-byte public half is PUBKEY in main.py. The device X25519 private key is
# DEVICE_X25519_PRIV in main.py (per-unit) -- pass it here so the tool can derive
# the public half it encrypts to.

import argparse
import asyncio
import os
import sys

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cryptobox as C  # X25519 + BLAKE2b + XChaCha20-Poly1305 (byte-matches firmware)

DEVICE_NAME = "esp-script"
RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"     # write:  phone -> ESP (frame)
TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"     # notify: ESP -> phone (status)
NONCE = "6e400004-b5a3-f393-e0a9-e50e24dcca9e"  # read:   current challenge

DOMAIN = b"espscript-v1"
VERSION = 0x02
_BASE9 = b"\x09" + b"\x00" * 31

HERE = os.path.dirname(os.path.abspath(__file__))
KEYPATH = os.path.join(HERE, "testkey.pem")


# ------------------------------------------------------------------ keys -----
def keygen():
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())
    with open(KEYPATH, "wb") as f:
        f.write(pem)
    os.chmod(KEYPATH, 0o600)
    raw = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
    print("wrote", KEYPATH)
    print("PUBKEY hex:", raw.hex())
    print('main.py:  PUBKEY = bytes.fromhex("%s")' % raw.hex())


def keygen_x25519():
    priv = os.urandom(32)
    pub = C.x25519(priv, _BASE9)
    print("device X25519 private (flash into main.py, keep secret):", priv.hex())
    print("device X25519 public  (encrypt to this):", pub.hex())
    print('main.py:  DEVICE_X25519_PRIV = bytes.fromhex("%s")' % priv.hex())


def load_key():
    if not os.path.exists(KEYPATH):
        sys.exit("no key at %s -- run --keygen first (or restore the PEM)" % KEYPATH)
    return ser.load_pem_private_key(open(KEYPATH, "rb").read(), None)


def build_frame(key, nonce, script, device_pub, bad_sig=False):
    # v2: encrypt the script to the device's X25519 key, then sign the blob.
    eph_priv = os.urandom(32)
    eph_pub = C.x25519(eph_priv, _BASE9)
    shared = C.x25519(eph_priv, device_pub)
    aead_key = C.kdf(shared, eph_pub, device_pub)
    aead_nonce = os.urandom(24)
    vhdr = DOMAIN + bytes([VERSION]) + nonce + len(script).to_bytes(4, "big")
    mac, ct = C.aead_lock(aead_key, aead_nonce, vhdr, script)  # AAD = vhdr
    signed = vhdr + eph_pub + aead_nonce + ct + mac
    sig = key.sign(signed)                   # raw 64-byte R||S (not DER)
    if bad_sig:
        b = bytearray(sig)
        b[0] ^= 0x01
        sig = bytes(b)
    body = eph_pub + aead_nonce + ct + mac + sig
    return len(body).to_bytes(4, "big") + body


def resolve_device_pub(args):
    if args.device_priv:
        return C.x25519(bytes.fromhex(args.device_priv), _BASE9)
    if args.device_key:
        pub = bytes.fromhex(args.device_key)
        if len(pub) != 32:
            sys.exit("--device-key must be 32 bytes (64 hex)")
        return pub
    sys.exit("push needs the device X25519 key: pass --device-priv or --device-key "
             "(see --keygen-x25519)")


# --------------------------------------------------------------- TX plumbing -
class TxReassembler:
    # The ESP splits one logical status message across notifications at mtu-3
    # with no delimiter. Rejoin: a chunk starting with a known status prefix
    # begins a new message; anything else continues the current one. An idle
    # timer flushes the final message (e.g. OK:done with nothing after it).
    PREFIXES = (b"NONCE", b"OK:", b"OUT:", b"ERR:")

    def __init__(self, q, loop, idle=0.2):
        self.q, self.loop, self.idle = q, loop, idle
        self.buf = b""
        self.timer = None

    def _flush(self):
        if self.buf:
            self.q.put_nowait(self.buf)
            self.buf = b""
        self.timer = None

    def feed(self, data):
        data = bytes(data)
        if self.buf and data.startswith(self.PREFIXES):
            self.q.put_nowait(self.buf)
            self.buf = b""
        self.buf += data
        if self.timer:
            self.timer.cancel()
        self.timer = self.loop.call_later(self.idle, self._flush)


def _fmt(msg):
    try:
        return msg.decode("utf-8", "replace")
    except Exception:
        return repr(msg)


async def drain_until(q, predicate, timeout, echo=True):
    """Consume TX messages (printing them) until predicate(msg) is true."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        msg = await asyncio.wait_for(q.get(), remaining)
        if echo:
            print("  TX <-", _fmt(msg))
        if predicate(msg):
            return msg


def _is_terminal(m):
    return m.startswith(b"OK:done") or m.startswith(b"ERR:")


async def get_nonce(client, q, timeout=5.0):
    # On connect the ESP issues a fresh challenge; a 32-zero read means it is
    # consumed-but-not-yet-reissued -- wait for a NONCE notify and re-read.
    for _ in range(6):
        n = bytes(await client.read_gatt_char(NONCE))
        if len(n) == 32 and any(n):
            return n
        print("  nonce not active yet; waiting for NONCE...")
        try:
            await drain_until(q, lambda m: m.startswith(b"NONCE"), timeout)
        except asyncio.TimeoutError:
            pass
    raise SystemExit("no active nonce after several tries")


async def push_frame(client, q, frame, timeout, ack=False):
    mtu = getattr(client, "mtu_size", 23) or 23
    chunk = max(min(mtu - 3, 244), 20)
    for i in range(0, len(frame), chunk):
        await client.write_gatt_char(RX, frame[i:i + chunk], response=ack)
        if not ack:
            await asyncio.sleep(0.01)        # gentle pacing for write-no-response
    print("  pushed %d-byte frame in %d-byte chunks (mtu=%d, ack=%s)"
          % (len(frame), chunk, mtu, ack))
    return await drain_until(q, _is_terminal, timeout)


# ---------------------------------------------------------------- main flow --
async def run(args):
    key = load_key()
    device_pub = resolve_device_pub(args)
    script = open(args.script, "rb").read()
    print("script: %s (%d bytes)" % (args.script, len(script)))
    print("device X25519 pub:", device_pub.hex())

    if args.address:
        target = args.address
    else:
        print("scanning for %r ..." % DEVICE_NAME)
        dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=args.scan)
        if dev is None:
            sys.exit("device %r not found (is it advertising?)" % DEVICE_NAME)
        target = dev
        print("found", dev.address)

    async with BleakClient(target) as client:
        print("connected; mtu=%s" % getattr(client, "mtu_size", "?"))
        q = asyncio.Queue()
        reasm = TxReassembler(q, asyncio.get_event_loop())
        await client.start_notify(TX, lambda _, d: reasm.feed(d))

        nonce = await get_nonce(client, q)
        print("nonce:", nonce.hex())

        frame = build_frame(key, nonce, script, device_pub, bad_sig=args.bad_sig)
        print("-- push --")
        term = await push_frame(client, q, frame, args.timeout, ack=args.ack)

        expected_ok = not args.bad_sig
        outcome_ok = term.startswith(b"OK:done") if expected_ok else term.startswith(b"ERR:sig")

        if args.replay and term.startswith(b"OK:done"):
            # wait for the re-armed challenge, then resend the SAME (old-nonce) frame
            await drain_until(q, lambda m: m.startswith(b"NONCE"), args.timeout)
            print("-- replay (identical frame, stale nonce) --")
            term2 = await push_frame(client, q, frame, args.timeout, ack=args.ack)
            outcome_ok = term2.startswith(b"ERR:sig")
            print("replay result:", _fmt(term2), "(want ERR:sig)")

        print("\nRESULT:", "PASS" if outcome_ok else "FAIL", "->", _fmt(term))
        return 0 if outcome_ok else 1


def main():
    p = argparse.ArgumentParser(description="BLE script-loader push client")
    p.add_argument("script", nargs="?", help="python script file to sign + push")
    p.add_argument("--keygen", action="store_true", help="generate tools/testkey.pem and print PUBKEY")
    p.add_argument("--keygen-x25519", action="store_true", help="generate a device X25519 keypair and print both halves")
    p.add_argument("--device-priv", help="device X25519 private key hex (derives the pubkey to encrypt to)")
    p.add_argument("--device-key", help="device X25519 public key hex (if you don't have the private half)")
    p.add_argument("--bad-sig", action="store_true", help="corrupt one sig byte; expect ERR:sig")
    p.add_argument("--replay", action="store_true", help="push twice; expect OK:done then ERR:sig")
    p.add_argument("--address", help="BLE address; skip the name scan")
    p.add_argument("--ack", action="store_true", help="write frame chunks WITH response (reliable; default is write-no-response)")
    p.add_argument("--scan", type=float, default=10.0, help="scan timeout seconds")
    p.add_argument("--timeout", type=float, default=30.0, help="per-push TX wait seconds")
    args = p.parse_args()

    if args.keygen:
        keygen()
        return
    if args.keygen_x25519:
        keygen_x25519()
        return
    if not args.script:
        p.error("a script file is required (or use --keygen)")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
