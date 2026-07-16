# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two halves of one system: **authenticated, confidential, ephemeral code push over
BLE** (protocol v2). A phone **encrypts** a small MicroPython script to the ESP32-S3's
X25519 key and **signs** the encrypted blob with an Ed25519 key; the device runs it
**only if the signature verifies against a nonce it just issued AND the ciphertext
decrypts under its own private key**. Scripts are never persisted on the device;
every connection is a fresh challenge; a passive sniffer sees only ciphertext.

- `firmware/` — MicroPython BLE peripheral (the ESP32 stub loader). Holds the signer's
  Ed25519 **public** key and the device's own X25519 **private** decryption key.
  `main.py` (framing + nonce lifecycle + verify + decrypt + sandboxed exec), `ed25519.py`
  (native fast path + pure-Python fallback, verify-only), `cryptobox.py` (X25519 + BLAKE2b
  + XChaCha20-Poly1305, native fast path + pure-Python fallback), `ced25519/` (Monocypher
  C module: `verify`, `x25519`, `blake2b`, `aead_unlock`).
- `app/` — Flutter companion (the BLE central). Holds the Ed25519 **private** signing key
  and pins each device's X25519 **public** key. Manages a script library, encrypts, signs,
  and pushes.

The wire protocol, security model, and guardrails are specified in this file (see
**Wire protocol** and the architecture sections below — this is the authoritative
spec). Per-side build, deploy, and status details live in `firmware/README.md` and
`app/README.md`.

## Commands

**Flutter (Docker only — no host toolchain, per user policy).** `fdart.sh` runs the
pinned Flutter image and restores host file ownership afterward:

```bash
./fdart.sh flutter test                              # all Dart unit tests
./fdart.sh "flutter test test/protocol_signer_test.dart"   # a single test file
./fdart.sh flutter analyze                           # static analysis
./fdart.sh "dart run build_runner build"             # regenerate drift database.g.dart
./fdart.sh "flutter build apk --debug"               # Android build
```

iOS has no Mac — it is built in the cloud via `app/codemagic.yaml`. Develop Android-first.

**Firmware host tests** (stdlib-only CPython, no hardware, no Docker):

```bash
python3 firmware/tests/test_flow.py     # MUST stay green; stubs bluetooth/micropython
```

**Desktop push client** (`firmware/tools/push_script.py`, `bleak`) — exercises real
hardware before the app. Runs on the **host**, not Docker (needs BlueZ/D-Bus). See
`firmware/tools/README.md`. `--keygen` overwrites `testkey.pem` and will break the
match with any already-flashed board (every push → `ERR:sig`). A v2 push also needs the
target's X25519 key: pass `--device-priv <hex>` (the board's `DEVICE_X25519_PRIV`) or
`--device-key <pubhex>`; `--keygen-x25519` mints a fresh device keypair.

## Wire protocol (BLE) — exact bytes

Service = Nordic UART Service (`6E400001-…`) + one extra characteristic:

| Char  | UUID (128-bit)                         | Props       | Direction / use |
|-------|----------------------------------------|-------------|-----------------|
| RX    | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` | Write / WNR | phone → ESP: the frame |
| TX    | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | Notify      | ESP → phone: ASCII status |
| NONCE | `6E400004-B5A3-F393-E0A9-E50E24DCCA9E` | Read        | phone reads the 32-byte challenge |

**Frame (RX), v2:** `[4-byte BE length N][ N bytes = frame body ]`, script ≤ 16384 bytes
(so N ≤ 16384 + 136). The body is:

```
eph_pub(32) || aead_nonce(24) || ciphertext(len) || mac(16) || sig(64)
```

A central chunks the frame at `min(mtu - 3, 244)` bytes, write-without-response, and
subscribes TX **before** reading NONCE. `sig` is raw 64-byte Ed25519 R||S — never DER. Both the signed message and the AEAD's
additional data are reconstructed on the ESP from its *own* nonce + ciphertext length (see
**The byte-agreement contract** below). There is no transmitted version byte; the version
is bound cryptographically (in the sig message and AAD), so a v1 frame simply fails
verification. `VERSION` is `0x02` on both sides.

**TX status strings:** `NONCE` (fresh challenge — re-read it), `OK:verified`, `OK:done`,
`OUT:<text>` (from a script's injected `notify()`), `ERR:sig` (bad signature **or**
decryption/MAC failure — the stage is deliberately not distinguished), `ERR:frame`,
`ERR:len` (oversized — the device drops the frame and force-disconnects; reconnect and
resend), `ERR:busy` (prior frame still processing), `ERR:nonce` (challenge already
consumed — wait for `NONCE`, re-read), `ERR:exec` (a pushed script raised — generic by
default; full traceback only when `_DEBUG=True` in `main.py`). NONCE reads 32 zero bytes
when no challenge is active — never sign an all-zero nonce.

**Security model.** Protects against unsigned pushes, replay (single-use nonce), cross-unit
replay (per-device nonce), **passive sniffing (the script is encrypted to the device's
X25519 key)**, **rogue/spoofed peripherals (only the real device can decrypt)**, and — on a
hardened board — flash extraction. `notify()`/`ERR:` no longer echo secrets by default
(`OUT:` is developer-facing; `ERR:exec` hides the traceback). Does NOT protect against a
compromised phone holding the signing key. The BLE **link** is still unencrypted at L2, but
confidentiality and device authenticity are enforced at the application layer (encrypt-to-
device-key + signatures). See **Provisioning requirements** for the hardware root of trust
that the confidentiality guarantee ultimately rests on.

## The byte-agreement contract (the thing most likely to break)

Both sides independently reconstruct the signed message and must produce **identical
bytes**. A single-byte mismatch is the classic "valid key, valid sig, still fails"
bug (`ERR:sig`).

```
header = DOMAIN("espscript-v1") || version(0x02) || nonce(32) || len(ciphertext) as 4-byte BE
AEAD additional data (AAD) = header
AEAD key   = BLAKE2b-512(X25519(eph, device_pub) || eph_pub || device_pub)[:32]
ciphertext,mac = XChaCha20-Poly1305(key, aead_nonce, AAD=header, plaintext=script)
signed msg = header || eph_pub || aead_nonce || ciphertext || mac    # what Ed25519 signs
```

- Four implementations must agree byte-for-byte: firmware `main.py`/`cryptobox.py`, vendored
  Monocypher (C), the app's `lib/core/protocol.dart` + `lib/core/crypto/box.dart`, and the
  vector generator. The primitives are the standard IETF XChaCha20-Poly1305 / X25519 /
  BLAKE2b — for scripts well under 256 GB Monocypher's `crypto_aead_lock` == libsodium's
  `xchacha20poly1305_ietf` == package:cryptography's `Xchacha20.poly1305Aead()`, which is why
  they line up. `firmware/cryptobox.py`'s pure-Python primitives are cross-checked against
  reference libs.
- **The proof without hardware:** `firmware/tools/make_vectors.py` emits
  `app/tools_vectors/vectors.json` (fixed device/ephemeral keys, aead nonce, challenge nonce,
  script → full frame body + sig). `app/test/protocol_signer_test.dart` asserts the Dart
  frame is byte-identical; `firmware/tests/test_flow.py` both builds the same frame and
  *decrypts* the vector with the device key. **If you change the encoding on either side,
  regenerate the vectors** (`python3 firmware/tools/make_vectors.py`).
- The decrypted `script` bytes and the bytes passed to `exec()` are the same UTF-8 — never
  re-encode/normalize between decrypt and exec.

## Firmware architecture (do not silently revert)

- **Two strictly-separated execution contexts.** BLE IRQ (`_irq`, `_on_rx`) does cheap
  framing only — **no crypto, no exec, no decrypt, no display I/O**. The main loop
  (`process()` → `_recover()`) does the slow/dangerous work. This is why a multi-second
  pure-Python verify/decrypt can't watchdog-reset the BLE stack.
- **`process()` order:** verify Ed25519 over the encrypted blob (keeps pusher-auth + replay
  protection) → X25519 + `aead_unlock` to recover the plaintext → sandboxed `exec`. A bad
  sig **and** a decrypt/MAC failure both surface as `ERR:sig` (stage not leaked).
- **Asymmetric (Ed25519) auth + encrypt-to-device-key (X25519).** The device holds the
  signer's public key (can't forge pushes) and its own X25519 private key (only it can
  decrypt). On a hardened board the X25519 key is protected by flash encryption.
- **Single-use nonce challenge–response**, re-issued after every processed frame (accepted
  or rejected). Never cache/reuse a nonce across frames. NONCE char reads 32 zero bytes
  while none is active — a signer must never sign an all-zero nonce.
- **Native verifier is `crypto_ed25519_check` (SHA-512), NEVER `crypto_eddsa_check`**
  (BLAKE2b — rejects standard Android/Dart Ed25519 sigs). Single most likely way to break
  everything.
- `ed25519.py` (verify) and `cryptobox.py` (x25519/blake2b/aead_unlock) each auto-select the
  native `ced25519` module if compiled in, else a self-contained pure-Python fallback
  (correct but slow; the host test suite forces the pure-Python path). Both bundle their own
  hashes since stock ESP32 hashlib lacks sha512/blake2b.
- The pure-Python verifier enforces RFC 8032 canonicality — it rejects `S >= L` (signature
  malleability) and decoded points with `y >= q`. Keep both checks. They are not currently
  exploitable (the nonce is single-use and consumed at frame-parse time, so a second valid
  encoding of the same signature buys nothing), but that safety net disappears the moment the
  nonce lifecycle changes. The native path is unaffected.
- **`exec` is sandboxed** (`_safe_builtins` + a guarded `__import__` allow-list): no `open`,
  no `os`/`io`/`vfs`/`esp`/`flashbdev`, so an authenticated script can't rewrite `main.py`
  or `PUBKEY` and persist. Hardware modules a dashboard script needs (`machine`, `gc`,
  `math`, `time`, `lvgl`, …) stay reachable — extend `_ALLOWED_IMPORTS` if a new one is
  needed, never re-add filesystem/flash modules. The host test asserts `open('main.py','w')`
  and `import os` fail; keep it green.
- `main.py` refuses to boot with the all-zero placeholder `PUBKEY` **or** all-zero
  `DEVICE_X25519_PRIV` — preserve both guards. The shipped `PUBKEY` and `DEVICE_X25519_PRIV`
  are **throwaway test values** and MUST be rotated before any real deployment (see
  **Provisioning requirements**).
- **`ERR:len` force-disconnects** (never drains up to 4 GB to resync); **RAM hygiene** clears
  the script/blob/globals after exec. Both are intentional — don't revert.
- Monocypher sources in `ced25519/` are copied verbatim from a pinned upstream release —
  never retype crypto from memory. `moned25519.c` only *wraps* Monocypher calls (`verify`,
  `x25519`, `blake2b`, `aead_unlock`). Build notes in `ced25519/BUILD.md`.
- **Loader status display** (`lifecycle_ui.py`, optional flash file): narrates loader
  state as a cicada life cycle (boot=intro cinematic, egg=waking, hatch=egg→nymph transition,
  nymph=advertising/linked, molting=RX progress, emergence=verify, adult=script ran,
  rejected=errors). At power-on the
  `boot` stage plays a one-shot cinematic (dusk sky titled "CicadaOS", a cicada glides down
  as the title dissolves and the camera pans until the horizon sits mid-screen, then it lays
  the egg on the grassline) whose final frame is built to match the `egg` card, so the
  hand-off is seamless; boot then holds the egg card ≥5 s, then plays the one-shot `hatch`
  transition (the egg wobbles, cracks, its shell splits into two halves that part and fall,
  and a nymph crawls out and burrows down) before going live. `hatch`'s first frame matches
  the `egg` card and its last frame matches `nymph`, so both hand-offs are seamless. Display
  I/O happens **only in the
  main loop** (`process()`/`_update_display()`), never the BLE IRQ; `autodetect()` never
  raises and any display fault degrades to `NullDisplay`. Once a pushed script paints its
  own UI (root DELETE event), the loader goes screen-silent until reboot (LED cues only).
- **Advertising** emits a manufacturer AD
  (company `0xFFFF`, magic `0xC1 0xCA`, a flags byte with an "awaiting script" bit, and 6
  identity bytes). The awaiting bit is set at boot and cleared on the first `OK:done`. The
  host test suite asserts this lifecycle — keep it green.

## App architecture (Flutter)

Stack: **riverpod** (state) · **go_router** (nav) · **drift/SQLite** (`lib/data/`, script
bodies live in the DB, ≤16 KB by protocol; secret bodies encrypted at rest) · **cryptography**
Ed25519 + X25519 + XChaCha20-Poly1305 + BLAKE2b + AES-GCM, **flutter_secure_storage** for the
signing seed and the DB body key · **flutter_blue_plus** (BLE) · **re_editor**.

- `lib/core/` — the byte-exact, pure-Dart, unit-tested heart: `protocol.dart` (v2 frame/header
  builders), `crypto/signer.dart` + `crypto/key_store.dart`, `crypto/box.dart` (the
  `ScriptSealer`: X25519 ECDH → BLAKE2b KDF → XChaCha20-Poly1305 seal → Ed25519 sign),
  `ble/tx_status.dart` (status parser), `ble/push_controller.dart` (the push state machine —
  **transport-injected + device-pubkey-injected so it's testable without hardware**),
  `ble/fbp_transport.dart`, `scanner.dart`, `adv.dart`.
- `lib/data/` — `database.dart` (drift; `Devices.x25519PubKey` pins each device's key,
  `Scripts.isSecret` marks secrets), `scripts_repository.dart` (transparently
  encrypts/decrypts secret bodies via `script_body_cipher.dart`), `devices_repository.dart`
  (`pinKey`).
- `lib/features/` — `scripts` (library + editor), `devices` (+ key provisioning: pin the
  device X25519 key), `push` (refuses to push to a device with no pinned key),
  `import_export` (`.cicada` — refuses to export `isSecret` scripts in cleartext),
  `boot_watch` (auto-push is gated behind a one-time token from our own PendingIntent).
- **`MainActivity` is `exported="true"`** (Flutter needs it), so any co-installed app can
  launch it with arbitrary extras. Auto-push therefore runs **only** when the launch carries
  the one-time token `BootWatchReceiver` minted for its own `PendingIntent`; the `auto` extra
  defaults to **false**. Never trust `boot_watch_*` extras off a bare intent — without the
  token gate, any app that learned a device id (BLE advertisements broadcast it in the clear)
  could force the phone to sign and push that device's default secret script.
- **Backups are off:** `allowBackup="false"` + `fullBackupContent="false"` +
  `dataExtractionRules`. Otherwise Android Auto Backup / `adb backup` lifts the whole script
  DB off the phone. Keep all three; they are the only thing stopping that path.
- **Signing-key decision:** a software Ed25519 key generated in-app and stored in secure
  storage (`ThisDeviceOnly` on iOS so it can't be lifted from a device backup) — NOT
  hardware-bound. Accepted cross-platform trade-off. A signed script runs sandboxed on the
  device, but the signing key is still the crown jewel — protect it.

`database.g.dart` is generated — edit the drift table definitions in `database.dart` and
rerun `build_runner`, never edit the `.g.dart` by hand. **Schema changes need a migration**
(`schemaVersion` + `onUpgrade`); the v1→v2 migration adds `x25519PubKey`/`isSecret`.

## Provisioning requirements (mandatory for secret-bearing units)

The confidentiality guarantee rests on a hardware root of trust; the shipped keys are
throwaway test values. Before a board receives real secret-bearing scripts:

1. **Rotate the keys.** Generate a per-owner Ed25519 signing key (offline) → set its raw
   32-byte public half as `PUBKEY` in `main.py`; keep the private half in the phone's secure
   storage. Generate a per-unit X25519 keypair (`push_script.py --keygen-x25519`) → set the
   private half as `DEVICE_X25519_PRIV` in `main.py`, and pin the public half in the app
   (`DevicesRepository.pinKey`). The all-zero placeholders refuse to boot.
2. **Burn the eFuses** (ESP32-S3): build MicroPython with `firmware/sdkconfig.hardening`
   (Secure Boot v2 + Flash Encryption **release** mode + ROM download mode disabled + JTAG
   off). These burns are **one-way and can brick a unit** — prove the full push flow on a
   throwaway dev board first, then confirm with `espefuse.py summary` and that
   `esptool.py read_flash` yields ciphertext. Store the secure-boot signing key offline;
   losing it means you can never update a locked board. Release-mode flash encryption
   disables UART re-flashing — plan OTA or accept field-final units.
3. **Keep secrets off the leak-back channels.** `OUT:`/`notify()` is developer-facing; never
   hand it key material. Mark secret scripts `isSecret` so their bodies are encrypted at rest
   and excluded from `.cicada` export.
