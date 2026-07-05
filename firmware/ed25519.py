# ed25519.py -- Ed25519 verification with an automatic fast path.
#
# If the native module `ced25519` (Monocypher's crypto_ed25519_check, compiled
# into the firmware) is present, use it: ~10-30 ms per verify on ESP32.
# Otherwise fall back to the self-contained pure-Python reference below:
# correct but slow (several seconds to tens of seconds). Either way this exposes
#
#     ed25519_verify(pubkey, msg, sig) -> bool
#
# so main.py never needs to know which path is active.
#
# NOTE: the fallback bundles its OWN SHA-512, because stock ESP32 MicroPython
# hashlib does not provide sha512. An import-time self-test (SHA-512("abc"))
# guards against a transcription error in the constants below.

try:
    from ced25519 import verify as ed25519_verify   # native fast path
    NATIVE = True
except ImportError:
    NATIVE = False


if not NATIVE:
    import struct
    import binascii

    # ---- self-contained SHA-512 (FIPS 180-4) --------------------------------
    _MASK64 = (1 << 64) - 1

    _H512 = (
        0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b,
        0xa54ff53a5f1d36f1, 0x510e527fade682d1, 0x9b05688c2b3e6c1f,
        0x1f83d9abfb41bd6b, 0x5be0cd19137e2179,
    )
    _K512 = (
        0x428a2f98d728ae22, 0x7137449123ef65cd, 0xb5c0fbcfec4d3b2f, 0xe9b5dba58189dbbc,
        0x3956c25bf348b538, 0x59f111f1b605d019, 0x923f82a4af194f9b, 0xab1c5ed5da6d8118,
        0xd807aa98a3030242, 0x12835b0145706fbe, 0x243185be4ee4b28c, 0x550c7dc3d5ffb4e2,
        0x72be5d74f27b896f, 0x80deb1fe3b1696b1, 0x9bdc06a725c71235, 0xc19bf174cf692694,
        0xe49b69c19ef14ad2, 0xefbe4786384f25e3, 0x0fc19dc68b8cd5b5, 0x240ca1cc77ac9c65,
        0x2de92c6f592b0275, 0x4a7484aa6ea6e483, 0x5cb0a9dcbd41fbd4, 0x76f988da831153b5,
        0x983e5152ee66dfab, 0xa831c66d2db43210, 0xb00327c898fb213f, 0xbf597fc7beef0ee4,
        0xc6e00bf33da88fc2, 0xd5a79147930aa725, 0x06ca6351e003826f, 0x142929670a0e6e70,
        0x27b70a8546d22ffc, 0x2e1b21385c26c926, 0x4d2c6dfc5ac42aed, 0x53380d139d95b3df,
        0x650a73548baf63de, 0x766a0abb3c77b2a8, 0x81c2c92e47edaee6, 0x92722c851482353b,
        0xa2bfe8a14cf10364, 0xa81a664bbc423001, 0xc24b8b70d0f89791, 0xc76c51a30654be30,
        0xd192e819d6ef5218, 0xd69906245565a910, 0xf40e35855771202a, 0x106aa07032bbd1b8,
        0x19a4c116b8d2d0c8, 0x1e376c085141ab53, 0x2748774cdf8eeb99, 0x34b0bcb5e19b48a8,
        0x391c0cb3c5c95a63, 0x4ed8aa4ae3418acb, 0x5b9cca4f7763e373, 0x682e6ff3d6b2b8a3,
        0x748f82ee5defb2fc, 0x78a5636f43172f60, 0x84c87814a1f0ab72, 0x8cc702081a6439ec,
        0x90befffa23631e28, 0xa4506cebde82bde9, 0xbef9a3f7b2c67915, 0xc67178f2e372532b,
        0xca273eceea26619c, 0xd186b8c721c0c207, 0xeada7dd6cde0eb1e, 0xf57d4f7fee6ed178,
        0x06f067aa72176fba, 0x0a637dc5a2c898a6, 0x113f9804bef90dae, 0x1b710b35131c471b,
        0x28db77f523047d84, 0x32caab7b40c72493, 0x3c9ebe0a15c9bebc, 0x431d67c49c100d4c,
        0x4cc5d4becb3e42b6, 0x597f299cfc657e2a, 0x5fcb6fab3ad6faec, 0x6c44198c4a475817,
    )

    def _rotr(x, n):
        return ((x >> n) | (x << (64 - n))) & _MASK64

    def _sha512(msg):
        ml = len(msg) * 8
        msg = bytes(msg) + b"\x80"
        while len(msg) % 128 != 112:
            msg += b"\x00"
        msg += ml.to_bytes(16, "big")
        h = list(_H512)
        for off in range(0, len(msg), 128):
            w = list(struct.unpack(">16Q", msg[off:off + 128]))
            for t in range(16, 80):
                x15 = w[t - 15]
                x2 = w[t - 2]
                s0 = _rotr(x15, 1) ^ _rotr(x15, 8) ^ (x15 >> 7)
                s1 = _rotr(x2, 19) ^ _rotr(x2, 61) ^ (x2 >> 6)
                w.append((w[t - 16] + s0 + w[t - 7] + s1) & _MASK64)
            a, b, c, d, e, f, g, hh = h
            for t in range(80):
                S1 = _rotr(e, 14) ^ _rotr(e, 18) ^ _rotr(e, 41)
                ch = (e & f) ^ ((e ^ _MASK64) & g)
                t1 = (hh + S1 + ch + _K512[t] + w[t]) & _MASK64
                S0 = _rotr(a, 28) ^ _rotr(a, 34) ^ _rotr(a, 39)
                maj = (a & b) ^ (a & c) ^ (b & c)
                t2 = (S0 + maj) & _MASK64
                hh, g, f = g, f, e
                e = (d + t1) & _MASK64
                d, c, b = c, b, a
                a = (t1 + t2) & _MASK64
            for i, v in enumerate((a, b, c, d, e, f, g, hh)):
                h[i] = (h[i] + v) & _MASK64
        return b"".join(x.to_bytes(8, "big") for x in h)

    # fail loudly at import if the constants above are wrong
    if _sha512(b"abc") != binascii.unhexlify(
        b"ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        b"2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
    ):
        raise ValueError("SHA-512 self-test failed")

    # ---- Ed25519 verify (RFC 8032 reference, verify-only) -------------------
    _b = 256
    _q = (1 << 255) - 19
    _L = (1 << 252) + 27742317777372353535851937790883648493  # group order
    _d = (-121665 * pow(121666, _q - 2, _q)) % _q          # -121665/121666
    _I = pow(2, (_q - 1) // 4, _q)                          # sqrt(-1) mod q

    def _inv(x):
        return pow(x % _q, _q - 2, _q)

    def _xrecover(y):
        xx = (y * y - 1) * _inv(_d * y * y + 1)
        x = pow(xx % _q, (_q + 3) // 8, _q)
        if (x * x - xx) % _q != 0:
            x = (x * _I) % _q
        if x % 2 != 0:
            x = _q - x
        return x

    _By = (4 * _inv(5)) % _q
    _Bx = _xrecover(_By)
    _B = (_Bx % _q, _By % _q)

    def _edwards(P, Q):
        x1, y1 = P
        x2, y2 = Q
        dm = _d * x1 * x2 * y1 * y2
        x3 = (x1 * y2 + x2 * y1) * _inv(1 + dm)
        y3 = (y1 * y2 + x1 * x2) * _inv(1 - dm)
        return (x3 % _q, y3 % _q)

    def _scalarmult(P, e):
        Q = (0, 1)
        while e > 0:
            if e & 1:
                Q = _edwards(Q, P)
            P = _edwards(P, P)
            e >>= 1
        return Q

    def _isoncurve(P):
        x, y = P
        return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0

    def _decodepoint(s):
        y = int.from_bytes(s, "little") & ((1 << (_b - 1)) - 1)
        if y >= _q:                               # reject non-canonical y (>= q)
            raise ValueError("non-canonical point")
        x = _xrecover(y)
        sign = (s[(_b - 1) // 8] >> ((_b - 1) % 8)) & 1
        if (x & 1) != sign:
            x = _q - x
        P = (x, y)
        if not _isoncurve(P):
            raise ValueError("point not on curve")
        return P

    def _hint(m):
        return int.from_bytes(_sha512(m), "little")

    def ed25519_verify(pubkey, msg, sig):
        try:
            if len(sig) != 64 or len(pubkey) != 32:
                return False
            R = _decodepoint(sig[:32])
            A = _decodepoint(pubkey)
            S = int.from_bytes(sig[32:], "little")
            if S >= _L:                           # reject malleable S (>= group order)
                return False
            h = _hint(sig[:32] + pubkey + msg)
            return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
        except Exception:
            return False
