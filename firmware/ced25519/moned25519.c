// moned25519.c -- MicroPython native module: fast Ed25519 verification plus the
// v2 (encrypted-frame) primitives, all thin wrappers over vendored Monocypher.
//
// Wraps Monocypher's crypto_ed25519_check() -- the STANDARD, SHA-512, RFC 8032
// verifier from src/optional/monocypher-ed25519.c. Do NOT wire this to
// crypto_eddsa_check(): that one uses BLAKE2b and will reject standard
// (Android Keystore) Ed25519 signatures.
//
// Exposes:
//   ced25519.verify(pubkey:32, msg, sig:64)            -> bool
//   ced25519.x25519(scalar:32, point:32)               -> 32 bytes
//   ced25519.blake2b(data, outlen:int)                 -> outlen bytes
//   ced25519.aead_unlock(key:32, nonce:24, mac:16, ad, ct) -> plaintext | None
//
// The verify() argument order matches the pure-Python ed25519_verify(pubkey,
// msg, sig); the others match firmware/cryptobox.py so it can swap native for
// its pure-Python fallback with no other changes.

#include "py/runtime.h"
#include "py/obj.h"

#include "monocypher-ed25519.h"   // crypto_ed25519_check()
#include "monocypher.h"           // crypto_x25519, crypto_aead_unlock, crypto_blake2b

static mp_obj_t ced25519_verify(mp_obj_t pubkey_obj, mp_obj_t msg_obj, mp_obj_t sig_obj) {
    mp_buffer_info_t pk, msg, sig;
    mp_get_buffer_raise(pubkey_obj, &pk, MP_BUFFER_READ);
    mp_get_buffer_raise(msg_obj, &msg, MP_BUFFER_READ);
    mp_get_buffer_raise(sig_obj, &sig, MP_BUFFER_READ);

    if (pk.len != 32 || sig.len != 64) {
        return mp_const_false;
    }

    // Returns 0 iff the signature is genuine, -1 otherwise.
    int r = crypto_ed25519_check((const uint8_t *)sig.buf,
                                 (const uint8_t *)pk.buf,
                                 (const uint8_t *)msg.buf,
                                 (size_t)msg.len);

    return (r == 0) ? mp_const_true : mp_const_false;
}
static MP_DEFINE_CONST_FUN_OBJ_3(ced25519_verify_obj, ced25519_verify);

// x25519(scalar[32], point[32]) -> raw 32-byte shared secret / public key.
static mp_obj_t ced25519_x25519(mp_obj_t scalar_obj, mp_obj_t point_obj) {
    mp_buffer_info_t sc, pt;
    mp_get_buffer_raise(scalar_obj, &sc, MP_BUFFER_READ);
    mp_get_buffer_raise(point_obj, &pt, MP_BUFFER_READ);
    if (sc.len != 32 || pt.len != 32) {
        mp_raise_ValueError(MP_ERROR_TEXT("x25519 needs 32-byte scalar and point"));
    }
    uint8_t out[32];
    crypto_x25519(out, (const uint8_t *)sc.buf, (const uint8_t *)pt.buf);
    return mp_obj_new_bytes(out, 32);
}
static MP_DEFINE_CONST_FUN_OBJ_2(ced25519_x25519_obj, ced25519_x25519);

// blake2b(data, outlen) -> outlen-byte digest (1..64).
static mp_obj_t ced25519_blake2b(mp_obj_t data_obj, mp_obj_t outlen_obj) {
    mp_buffer_info_t d;
    mp_get_buffer_raise(data_obj, &d, MP_BUFFER_READ);
    mp_int_t outlen = mp_obj_get_int(outlen_obj);
    if (outlen < 1 || outlen > 64) {
        mp_raise_ValueError(MP_ERROR_TEXT("blake2b outlen must be 1..64"));
    }
    uint8_t hash[64];
    crypto_blake2b(hash, (size_t)outlen, (const uint8_t *)d.buf, d.len);
    return mp_obj_new_bytes(hash, (size_t)outlen);
}
static MP_DEFINE_CONST_FUN_OBJ_2(ced25519_blake2b_obj, ced25519_blake2b);

// aead_unlock(key[32], nonce[24], mac[16], ad, ciphertext) -> plaintext | None.
// XChaCha20-Poly1305. Returns None on MAC failure (never partial plaintext).
static mp_obj_t ced25519_aead_unlock(size_t n_args, const mp_obj_t *args) {
    (void)n_args;
    mp_buffer_info_t key, nonce, mac, ad, ct;
    mp_get_buffer_raise(args[0], &key, MP_BUFFER_READ);
    mp_get_buffer_raise(args[1], &nonce, MP_BUFFER_READ);
    mp_get_buffer_raise(args[2], &mac, MP_BUFFER_READ);
    mp_get_buffer_raise(args[3], &ad, MP_BUFFER_READ);
    mp_get_buffer_raise(args[4], &ct, MP_BUFFER_READ);
    if (key.len != 32 || nonce.len != 24 || mac.len != 16) {
        mp_raise_ValueError(MP_ERROR_TEXT("aead_unlock: key/nonce/mac sizes"));
    }
    size_t n = ct.len ? ct.len : 1;
    uint8_t *pt = m_new(uint8_t, n);
    int r = crypto_aead_unlock(pt, (const uint8_t *)mac.buf, (const uint8_t *)key.buf,
                               (const uint8_t *)nonce.buf, (const uint8_t *)ad.buf, ad.len,
                               (const uint8_t *)ct.buf, ct.len);
    mp_obj_t res = (r == 0) ? mp_obj_new_bytes(pt, ct.len) : mp_const_none;
    m_del(uint8_t, pt, n);
    return res;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ced25519_aead_unlock_obj, 5, 5, ced25519_aead_unlock);

static const mp_rom_map_elem_t ced25519_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),     MP_ROM_QSTR(MP_QSTR_ced25519) },
    { MP_ROM_QSTR(MP_QSTR_verify),       MP_ROM_PTR(&ced25519_verify_obj) },
    { MP_ROM_QSTR(MP_QSTR_x25519),       MP_ROM_PTR(&ced25519_x25519_obj) },
    { MP_ROM_QSTR(MP_QSTR_blake2b),      MP_ROM_PTR(&ced25519_blake2b_obj) },
    { MP_ROM_QSTR(MP_QSTR_aead_unlock),  MP_ROM_PTR(&ced25519_aead_unlock_obj) },
};
static MP_DEFINE_CONST_DICT(ced25519_globals, ced25519_globals_table);

const mp_obj_module_t ced25519_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&ced25519_globals,
};

// 2-argument form (MicroPython >= ~1.17). If you build against an older core,
// use the 3-arg form and add a MODULE_CED25519_ENABLED define.
MP_REGISTER_MODULE(MP_QSTR_ced25519, ced25519_user_cmodule);
