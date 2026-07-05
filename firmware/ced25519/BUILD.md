# Fast Ed25519 verify — build notes

Goal: replace the slow pure-Python verify with a native C module, so
`ed25519_verify()` runs in ~10–30 ms instead of tens of seconds. No change to
`main.py` — `ed25519.py` auto-detects the native module and falls back to pure
Python if it isn't compiled in.

## 1. Add the Monocypher sources (verbatim — do not retype crypto)

Use a pinned release, not master. From https://github.com/LoupVaillant/Monocypher
copy these four files into this `ced25519/` directory next to `moned25519.c`:

    src/monocypher.c
    src/monocypher.h
    src/optional/monocypher-ed25519.c   # SHA-512 Ed25519 (crypto_ed25519_check)
    src/optional/monocypher-ed25519.h

IMPORTANT: it must be the `optional/monocypher-ed25519.*` pair. Those provide
`crypto_ed25519_check()`, the standard SHA-512 / RFC 8032 verifier that matches
Android Keystore Ed25519. The core `crypto_eddsa_check()` uses BLAKE2b and will
reject every real signature.

Directory should end up as:

    ced25519/
      moned25519.c
      micropython.cmake
      monocypher.c
      monocypher.h
      monocypher-ed25519.c
      monocypher-ed25519.h

## 2. Build MicroPython for ESP32 with the module

    # one-time: fetch and export ESP-IDF for your MicroPython version
    cd micropython/ports/esp32

    make USER_C_MODULES=/ABS/PATH/TO/ced25519/micropython.cmake BOARD=ESP32_GENERIC

Equivalent idf.py form:

    idf.py -D USER_C_MODULES=/ABS/PATH/TO/ced25519/micropython.cmake build

Use the absolute path to `micropython.cmake`. Flash the resulting firmware, then
copy `ed25519.py` and `main.py` to the board as before.

## 3. Verify it took

At the REPL:

    >>> import ced25519          # imports cleanly -> native module is in
    >>> from ed25519 import ed25519_verify
    >>> import time
    >>> pk  = b"\x00"*32          # dummy; use your real values to test True
    >>> sig = b"\x00"*64
    >>> t=time.ticks_ms(); ed25519_verify(pk, b"hi", sig); time.ticks_diff(time.ticks_ms(), t)

The timing should be single/double-digit milliseconds. If `import ced25519`
raises ImportError, the module wasn't linked — `ed25519.py` will still work via
the slow pure-Python path, so check the build.

## Notes

- Adds roughly ~30–40 KB of flash. Monocypher is public-domain / CC0.
- If your MicroPython core predates the 2-arg `MP_REGISTER_MODULE`, switch to the
  3-arg form in `moned25519.c` and define `MODULE_CED25519_ENABLED` for the board.
