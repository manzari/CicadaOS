#!/usr/bin/env python3
"""Generate cross-implementation v2 (encrypted-frame) vectors for the Flutter app.

The v2 frame is deterministic once the Ed25519 seed, the device X25519 keypair,
the per-push ephemeral X25519 scalar, the AEAD nonce, the challenge nonce and the
script are all pinned. These vectors let the Dart unit tests prove byte-agreement
with the firmware (the "classic ERR:sig failure point", CLAUDE.md byte-agreement
contract) without hardware: DOMAIN bytes, the version byte, the 32-byte nonce, the
4-byte big-endian ciphertext length, the XChaCha20-Poly1305 ciphertext+mac, and
the Ed25519 signature over the whole encrypted blob.

Ed25519 signing uses the `cryptography` package (same lib the firmware host tests
trust). X25519 + BLAKE2b + XChaCha20-Poly1305 come from firmware/cryptobox.py,
whose pure-Python primitives are cross-checked against `cryptography`/`hashlib`.
The Ed25519 seed is bytes(range(32)) -- identical to firmware/tests/test_flow.py.

Run:
    python3 firmware/tools/make_vectors.py
Writes app/tools_vectors/vectors.json.
"""
import json
import os
import sys

FW = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, FW)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import cryptobox as C

DOMAIN = b"espscript-v1"
VERSION = 0x02

# Ed25519 signing key (same as firmware/tests/test_flow.py).
SEED = bytes(range(32))
# Device X25519 keypair (fixed test values; the private half never ships).
DEVICE_X25519_PRIV = bytes([(i * 3 + 7) & 0xFF for i in range(32)])
_BASE9 = b"\x09" + b"\x00" * 31
DEVICE_X25519_PUB = C.x25519(DEVICE_X25519_PRIV, _BASE9)

# (name, challenge_nonce, script). Nonces fixed so vectors are reproducible;
# scripts cover ascii, unicode, empty, and a large body.
CASES = [
    ("blink", bytes(range(32)), "notify('hi from script')"),
    ("all_ff_nonce", b"\xff" * 32, "notify('two')"),
    ("mixed_nonce", bytes([(i * 7 + 3) & 0xFF for i in range(32)]), "for i in range(3):\n    notify(i)\n"),
    ("unicode", bytes([(255 - i) & 0xFF for i in range(32)]), "notify('temp=25.1°C ✓ éè')"),
    ("empty_script", bytes(32)[:31] + b"\x01", ""),  # nonce must be non-zero
    ("large_10k", bytes([(i * 13) & 0xFF for i in range(32)]), "notify('x')\n" * 900),
]


def v2_frame(nonce: bytes, aead_nonce: bytes, eph_priv: bytes, script: bytes):
    eph_pub = C.x25519(eph_priv, _BASE9)
    shared = C.x25519(eph_priv, DEVICE_X25519_PUB)
    key = C.kdf(shared, eph_pub, DEVICE_X25519_PUB)
    vhdr = DOMAIN + bytes([VERSION]) + nonce + len(script).to_bytes(4, "big")
    mac, ct = C.aead_lock(key, aead_nonce, vhdr, script)  # AAD = vhdr
    signed = vhdr + eph_pub + aead_nonce + ct + mac
    return eph_pub, ct, mac, signed


def main() -> None:
    key = Ed25519PrivateKey.from_private_bytes(SEED)
    pub_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    vectors = []
    for name, nonce, script_str in CASES:
        assert len(nonce) == 32 and nonce != bytes(32), "never sign an all-zero nonce"
        script = script_str.encode("utf-8")
        # Deterministic per-case ephemeral scalar and AEAD nonce.
        eph_priv = C.blake2b(b"eph:" + name.encode(), 32)
        aead_nonce = C.blake2b(b"nonce:" + name.encode(), 24)
        eph_pub, ct, mac, signed = v2_frame(nonce, aead_nonce, eph_priv, script)
        sig = key.sign(signed)
        assert len(sig) == 64, "Ed25519 sig must be raw 64 bytes (R||S), never DER"
        key.public_key().verify(sig, signed)  # self-check
        # Full frame body the phone sends (before the 4-byte length prefix).
        frame_body = eph_pub + aead_nonce + ct + mac + sig
        vectors.append({
            "name": name,
            "nonce": nonce.hex(),
            "aead_nonce": aead_nonce.hex(),
            "eph_priv": eph_priv.hex(),
            "eph_pub": eph_pub.hex(),
            "script": script_str,
            "ciphertext": ct.hex(),
            "mac": mac.hex(),
            "signed": signed.hex(),
            "sig": sig.hex(),
            "frame_body": frame_body.hex(),
        })

    doc = {
        "domain": DOMAIN.decode("ascii"),
        "version": VERSION,
        "seed": SEED.hex(),
        "pubkey": pub_raw.hex(),
        "device_x25519_priv": DEVICE_X25519_PRIV.hex(),
        "device_x25519_pub": DEVICE_X25519_PUB.hex(),
        "vectors": vectors,
    }

    out_dir = os.path.normpath(os.path.join(FW, "..", "app", "tools_vectors"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "vectors.json")
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print("wrote %s (%d vectors)" % (out_path, len(vectors)))
    print("pubkey:", pub_raw.hex())
    print("device_x25519_pub:", DEVICE_X25519_PUB.hex())


if __name__ == "__main__":
    main()
