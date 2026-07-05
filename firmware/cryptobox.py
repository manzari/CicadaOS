# cryptobox.py -- X25519 + BLAKE2b + XChaCha20-Poly1305 for the v2 (encrypted)
# frame. Same auto-select shape as ed25519.py: if the native `ced25519` module
# exposes these primitives (Monocypher, compiled in) use them; otherwise fall
# back to the self-contained pure-Python reference below (correct but slow --
# used only by the host test suite, which forces the non-native path).
#
# Exposes:
#   x25519(scalar32, point32)                 -> 32 bytes  (RFC 7748)
#   blake2b(data, outlen=64)                  -> outlen bytes (RFC 7693)
#   aead_lock(key32, nonce24, ad, plaintext)  -> (mac16, ciphertext)
#   aead_unlock(key32, nonce24, mac16, ad, ct)-> plaintext | None
#   kdf(shared, eph_pub, dev_pub)             -> 32-byte AEAD key
#
# The XChaCha20-Poly1305 construction here is the IETF one (HChaCha20 subkey +
# 96-bit-nonce/32-bit-counter ChaCha20 + RFC-8439 Poly1305 layout). For messages
# well under 256 GB this is byte-identical to Monocypher's crypto_aead_lock and
# to libsodium's crypto_aead_xchacha20poly1305_ietf and to package:cryptography's
# Xchacha20.poly1305Aead() -- which is what makes the four implementations agree.

import struct

# ------------------------------------------------------------- X25519 (7748) ---
_P25519 = (1 << 255) - 19
_A24 = 121665


def _pytfrom(b):
    return int.from_bytes(b, "little")


def _decode_scalar(k):
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return _pytfrom(k)


def _decode_u(u):
    u = bytearray(u)
    u[31] &= 127
    return _pytfrom(u)


def _cswap(swap, a, b):
    dummy = (swap * ((a - b) % _P25519)) % _P25519
    return (a - dummy) % _P25519, (b + dummy) % _P25519


def _x25519_py(scalar, point):
    k = _decode_scalar(scalar)
    x1 = _decode_u(point)
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        x2, x3 = _cswap(swap, x2, x3)
        z2, z3 = _cswap(swap, z2, z3)
        swap = kt
        A = (x2 + z2) % _P25519
        AA = (A * A) % _P25519
        B = (x2 - z2) % _P25519
        BB = (B * B) % _P25519
        E = (AA - BB) % _P25519
        C = (x3 + z3) % _P25519
        D = (x3 - z3) % _P25519
        DA = (D * A) % _P25519
        CB = (C * B) % _P25519
        x3 = ((DA + CB) % _P25519) ** 2 % _P25519
        z3 = (x1 * (((DA - CB) % _P25519) ** 2 % _P25519)) % _P25519
        x2 = (AA * BB) % _P25519
        z2 = (E * ((AA + _A24 * E) % _P25519)) % _P25519
    x2, x3 = _cswap(swap, x2, x3)
    z2, z3 = _cswap(swap, z2, z3)
    res = (x2 * pow(z2, _P25519 - 2, _P25519)) % _P25519
    return res.to_bytes(32, "little")


# ---------------------------------------------------------- BLAKE2b (7693) -----
_BLAKE_IV = (
    0x6A09E667F3BCC908, 0xBB67AE8584CAA73B, 0x3C6EF372FE94F82B, 0xA54FF53A5F1D36F1,
    0x510E527FADE682D1, 0x9B05688C2B3E6C1F, 0x1F83D9ABFB41BD6B, 0x5BE0CD19137E2179,
)
_BLAKE_SIGMA = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    (14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3),
    (11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4),
    (7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8),
    (9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13),
    (2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9),
    (12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11),
    (13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10),
    (6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5),
    (10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0),
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    (14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3),
)
_M64 = (1 << 64) - 1


def _br(x, n):
    return ((x >> n) | (x << (64 - n))) & _M64


def _blake2b_compress(h, block, t, last):
    v = list(h) + list(_BLAKE_IV)
    v[12] ^= t & _M64
    v[13] ^= (t >> 64) & _M64
    if last:
        v[14] ^= _M64
    m = struct.unpack("<16Q", block)

    def g(a, b, c, d, x, y):
        v[a] = (v[a] + v[b] + x) & _M64
        v[d] = _br(v[d] ^ v[a], 32)
        v[c] = (v[c] + v[d]) & _M64
        v[b] = _br(v[b] ^ v[c], 24)
        v[a] = (v[a] + v[b] + y) & _M64
        v[d] = _br(v[d] ^ v[a], 16)
        v[c] = (v[c] + v[d]) & _M64
        v[b] = _br(v[b] ^ v[c], 63)

    for r in range(12):
        s = _BLAKE_SIGMA[r]
        g(0, 4, 8, 12, m[s[0]], m[s[1]])
        g(1, 5, 9, 13, m[s[2]], m[s[3]])
        g(2, 6, 10, 14, m[s[4]], m[s[5]])
        g(3, 7, 11, 15, m[s[6]], m[s[7]])
        g(0, 5, 10, 15, m[s[8]], m[s[9]])
        g(1, 6, 11, 12, m[s[10]], m[s[11]])
        g(2, 7, 8, 13, m[s[12]], m[s[13]])
        g(3, 4, 9, 14, m[s[14]], m[s[15]])
    for i in range(8):
        h[i] ^= v[i] ^ v[i + 8]


def _blake2b_py(data, outlen=64):
    h = list(_BLAKE_IV)
    h[0] ^= 0x01010000 ^ (outlen & 0xFF)  # no key, fanout=1, depth=1
    data = bytes(data)
    t = 0
    off = 0
    n = len(data)
    while n - off > 128:
        t += 128
        _blake2b_compress(h, data[off:off + 128], t, False)
        off += 128
    rem = data[off:]
    t += len(rem)
    block = rem + b"\x00" * (128 - len(rem))
    _blake2b_compress(h, block, t, True)
    return b"".join(x.to_bytes(8, "little") for x in h)[:outlen]


# --------------------------------------------------- ChaCha20 / Poly1305 -------
_CHACHA_CONST = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
_M32 = 0xFFFFFFFF


def _rotl32(x, n):
    return ((x << n) | (x >> (32 - n))) & _M32


def _quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & _M32
    s[d] = _rotl32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & _M32
    s[b] = _rotl32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & _M32
    s[d] = _rotl32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & _M32
    s[b] = _rotl32(s[b] ^ s[c], 7)


def _chacha_rounds(w):
    for _ in range(10):
        _quarter(w, 0, 4, 8, 12)
        _quarter(w, 1, 5, 9, 13)
        _quarter(w, 2, 6, 10, 14)
        _quarter(w, 3, 7, 11, 15)
        _quarter(w, 0, 5, 10, 15)
        _quarter(w, 1, 6, 11, 12)
        _quarter(w, 2, 7, 8, 13)
        _quarter(w, 3, 4, 9, 14)


def _hchacha20(key, nonce16):
    st = list(_CHACHA_CONST) + list(struct.unpack("<8I", key)) + list(struct.unpack("<4I", nonce16))
    w = list(st)
    _chacha_rounds(w)
    return struct.pack("<8I", w[0], w[1], w[2], w[3], w[12], w[13], w[14], w[15])


def _chacha20(key, counter, nonce12, data):
    out = bytearray(len(data))
    base = list(_CHACHA_CONST) + list(struct.unpack("<8I", key)) + [0, 0, 0, 0]
    base[13], base[14], base[15] = struct.unpack("<3I", nonce12)
    for i in range(0, len(data), 64):
        base[12] = (counter + (i >> 6)) & _M32
        w = list(base)
        _chacha_rounds(w)
        ks = struct.pack("<16I", *[(w[j] + base[j]) & _M32 for j in range(16)])
        chunk = data[i:i + 64]
        for j in range(len(chunk)):
            out[i + j] = chunk[j] ^ ks[j]
    return bytes(out)


def _poly1305(msg, key):
    r = _pytfrom(key[:16]) & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = _pytfrom(key[16:32])
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(msg), 16):
        block = msg[i:i + 16]
        n = _pytfrom(block) | (1 << (8 * len(block)))
        acc = ((acc + n) * r) % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(n):
    return b"\x00" * ((16 - (n % 16)) % 16)


def _aead_common(key, nonce24):
    subkey = _hchacha20(key, nonce24[:16])
    inonce = b"\x00\x00\x00\x00" + bytes(nonce24[16:24])
    polykey = _chacha20(subkey, 0, inonce, b"\x00" * 32)
    return subkey, inonce, polykey


def _mac_data(ad, ciphertext):
    return (bytes(ad) + _pad16(len(ad)) + bytes(ciphertext) + _pad16(len(ciphertext))
            + struct.pack("<Q", len(ad)) + struct.pack("<Q", len(ciphertext)))


def _aead_lock_py(key, nonce24, ad, plaintext):
    subkey, inonce, polykey = _aead_common(key, nonce24)
    ciphertext = _chacha20(subkey, 1, inonce, plaintext)
    mac = _poly1305(_mac_data(ad, ciphertext), polykey)
    return mac, ciphertext


def _ct_eq(a, b):
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(bytes(a), bytes(b)):
        r |= x ^ y
    return r == 0


def _aead_unlock_py(key, nonce24, mac, ad, ciphertext):
    subkey, inonce, polykey = _aead_common(key, nonce24)
    if not _ct_eq(_poly1305(_mac_data(ad, ciphertext), polykey), mac):
        return None
    return _chacha20(subkey, 1, inonce, ciphertext)


# ---------------------------------------------- native fast path selection -----
# On-device, `ced25519` (Monocypher) exposes these. On the host it resolves to an
# empty namespace package (the ced25519/ source dir), so use getattr throughout
# and fall back to the pure-Python reference for anything missing.
try:
    import ced25519 as _n
except ImportError:
    _n = None

x25519 = getattr(_n, "x25519", None) or _x25519_py
blake2b = getattr(_n, "blake2b", None) or _blake2b_py
aead_unlock = getattr(_n, "aead_unlock", None) or _aead_unlock_py
aead_lock = _aead_lock_py  # phone/host side only; device never encrypts
NATIVE_BOX = getattr(_n, "x25519", None) is not None


def kdf(shared, eph_pub, dev_pub):
    # AEAD key = BLAKE2b-512(shared || eph_pub || dev_pub) truncated to 32 bytes.
    return blake2b(bytes(shared) + bytes(eph_pub) + bytes(dev_pub), 64)[:32]


# ------------------------------------------------------ import-time self-test --
# Roundtrip + a couple of published vectors guard against transcription errors,
# mirroring ed25519.py's SHA-512 self-test.
if __name__ != "__main__":
    # RFC 7748 X25519 vector.
    _sc = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
    _pt = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
    if _x25519_py(_sc, _pt).hex() != "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552":
        raise ValueError("X25519 self-test failed")
    # RFC 7693 BLAKE2b-512("abc").
    if _blake2b_py(b"abc").hex() != (
        "ba80a53f981c4d0d6a2797b69f12f6e94c212f14685ac4b74b12bb6fdbffa2d1"
        "7d87c5392aab792dc252d5de4533cc9518d38aa8dbf1925ab92386edd4009923"):
        raise ValueError("BLAKE2b self-test failed")
    # AEAD roundtrip (self-consistency of chacha/poly/pad layout).
    _k = bytes(range(32))
    _nz = bytes(range(24))
    _m, _c = _aead_lock_py(_k, _nz, b"header", b"secret script")
    if _aead_unlock_py(_k, _nz, _m, b"header", _c) != b"secret script":
        raise ValueError("AEAD roundtrip self-test failed")
