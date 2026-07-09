# Security Fixes — Implementation Instructions

**Context.** A security review of the firmware + provisioning path found that the
stated guarantee — *"a script carrying valuable API keys must not be recoverable
from the ESP after a reboot, even by an attacker with physical access"* — does
**not** hold as built, and that the secrets are actually exposed on easier paths
than the physical/reboot one. This document is the fix plan. Each section is
self-contained: goal, why, exact files, steps, acceptance criteria, and the
project-specific gotchas that will bite you.

**Current state (as of this review — the app is e2e-verified but pre-hardening).**
The tree is the **v1 baseline**: plaintext `script || sig(64)` frames, verify-then-`exec`,
full-traceback error strings, cleartext script bodies in the DB and `.cicada` exports,
no peripheral authentication, no secure-boot/flash-encryption config. **None of
Fixes 1–6 below are implemented yet.** Fixes 7–12 are *new* findings from this
review, appended after the original six.

**Read first:** `CLAUDE.md` — it is the **authoritative spec** (Wire protocol,
byte-agreement contract, Security model, Firmware/App architecture, Docker-only
Flutter policy, guardrails). Note: earlier drafts of this document referenced a
`HANDOFF.md`; **no such file exists in the tree** — the spec was consolidated into
`CLAUDE.md`. Build notes for the native crypto module live in
`firmware/ced25519/BUILD.md`. Do **not** violate the standing guardrails while
fixing these:

- Native verifier stays `crypto_ed25519_check` (SHA-512), never `crypto_eddsa_check`.
- No crypto/exec/decrypt in the BLE IRQ (`_irq`, `_on_rx`) — that work belongs in
  `process()` (main loop) only.
- Sign/verify the exact bytes that get executed; no re-encode between verify and exec.
- Nonce stays single-use; preserve the placeholder-`PUBKEY` boot refusal
  (`firmware/main.py:41-42`).
- Monocypher sources are copied verbatim from the pinned upstream — never retype crypto.
- Flutter runs only via `./fdart.sh` (Docker). Firmware host tests
  (`python3 firmware/tests/test_flow.py`) MUST stay green.
- On-device MicroPython `bytearray` does not support slice-delete (`del buf[:n]`);
  the code already uses `buf = buf[n:]` — keep it that way if you touch framing.

**Repo/VCS note.** `/home/yuzer/Workspace/Combined/CicadaOS` is **not a git
repository** (no `.git` at the project root or any parent; only `app/.gitignore`
and `.idea/.gitignore` exist, no root or `firmware/` `.gitignore`). So the "commit /
`git rm`" phrasing in Fix 4 does not apply as written — adjust to plain file deletion
plus a `.gitignore` staged for whenever this *does* become a repo. If you `git init`
here later, `testkey.pem` must never be committed.

**Priority / dependency order.** Do them in this order; later confidentiality
fixes are worthless without the earlier hardware fix.

1. Fix 1 (hardware root of trust) — **prerequisite** for any on-device secret.
2. Fix 4 (kill the committed test key) — cheap, do it immediately.
3. Fix 7 (`exec` sandbox / read-only loader) — **new; do it with Fix 1.** Without
   it, one signed script rewrites `main.py`/`PUBKEY` and persists, defeating the
   whole model regardless of flash encryption.
4. Fix 2+3 (channel/script confidentiality + peripheral authentication) — one
   coherent protocol change; implement together.
5. Fix 5 (leak-back channels), Fix 6 (phone at-rest), and Fixes 8–12 (defense in depth).

---

## Fix 1 — Hardware root of trust: flash encryption + secure boot + locked download mode

**This is the decisive fix. Without it, every other confidentiality measure is
bypassable by dropping to the REPL.** It is a build + eFuse task, not Python.

**Why.** Stock MicroPython on the ESP32-C6 ships with the UART bootloader, REPL,
and JTAG live and flash unencrypted. A physical attacker never has to reboot:
Ctrl-C on the UART interrupts `run()`, drops to the REPL, and the just-executed
script's bytes are still in RAM (the `g` globals dict, the compiled code object,
freed-but-unzeroed heap — MicroPython's GC never scrubs memory). They can also
read/modify `main.py` in flash to harvest *future* pushes. "Only the public key
is on the device" defeats forgery, not confidentiality or loader tampering.

**Target:** ESP32-C6 (Secure Boot v2 + Flash Encryption both supported).

### Steps

1. **Generate a Secure Boot signing key** (separate from the Ed25519 app key):
   ```
   espsecure.py generate_signing_key --version 2 secure_boot_signing_key.pem
   ```
   Store it offline; it signs the bootloader/app images. Losing it means you can
   never update a locked board.

2. **Build MicroPython for the C6 with these sdkconfig options** (add a board
   sdkconfig fragment; do not hand-edit generated files). There is currently **no
   sdkconfig fragment, partition table, or board config anywhere in `firmware/`** —
   you are adding this from scratch:
   ```
   CONFIG_SECURE_BOOT=y
   CONFIG_SECURE_BOOT_V2_ENABLED=y
   CONFIG_SECURE_BOOT_SIGNING_KEY="secure_boot_signing_key.pem"
   CONFIG_SECURE_FLASH_ENC_ENABLED=y
   CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE=y   # NOT development mode
   CONFIG_SECURE_DISABLE_ROM_DL_MODE=y             # or SECURE_ENABLE_SECURE_ROM_DL_MODE
   CONFIG_SECURE_BOOT_ALLOW_JTAG=n
   ```
   Build alongside the `ced25519` USER_C_MODULE as today (see
   `firmware/ced25519/BUILD.md`).

3. **Provision one throwaway dev board first.** Flash encryption + secure boot
   eFuse burns are **one-way and can brick the unit**. Verify the full push flow
   on the dev board before touching production units.

4. **After first secure boot, confirm the eFuses are burned** (encryption key
   present, `DISABLE_DL_ENCRYPT`/download-mode locked, JTAG disabled) with
   `espefuse.py summary`. Confirm you can no longer `espefuse.py`-read the flash
   contents in cleartext and that the REPL over UART is gone (or password-gated).

5. **Complementary RAM hygiene (in `main.py`).** After `exec`, drop references so
   GC can reclaim the script memory promptly. In `process()`
   (`firmware/main.py:252-262`), after the try/except and before the final
   `self._issue_nonce()`, explicitly clear:
   ```python
   g.clear()
   del g, script, sig, msg, blob
   ```
   This does not zero RAM (MicroPython can't guarantee that), so it is not a
   substitute for flash encryption — it only shortens the live-RAM window. Keep it
   modest; the real guarantee comes from steps 1-4. (Note: this overlaps Fix 7,
   which hardens the same `exec` — do them together.)

### Acceptance criteria
- `espefuse.py summary` on a provisioned board shows flash encryption enabled
  (release mode), Secure Boot v2 enabled, UART download mode disabled (or secure),
  JTAG disabled.
- Attempting `esptool.py read_flash` yields ciphertext, not the plaintext filesystem.
- The board still boots, advertises, and completes a valid push (regression).

### Gotchas
- Release-mode flash encryption disables re-flashing over UART. Plan OTA or accept
  that units are field-final. Document this.
- Add a **"Provisioning requirements"** subsection to `CLAUDE.md` (or a new
  `HANDOFF.md`) stating that these eFuse steps are mandatory for any board that will
  receive secret-bearing scripts — right now nothing in the repo mentions them.

---

## Fix 4 — Remove the committed test private key (do this first; it's 10 minutes)

**Why.** `firmware/tools/testkey.pem` is a real PKCS#8 Ed25519 **private** key in
the tree (119 bytes, confirmed present), and the flashed `PUBKEY` in
`firmware/main.py:39` is its public half. Anyone with the tree can sign scripts any
board still trusts. There is no `.gitignore` at the repo root or in `firmware/`
(confirmed — the only `.gitignore` files are `app/.gitignore` and `.idea/.gitignore`),
and this is not currently a git repo at all.

### Steps
1. **Delete the file:** `rm firmware/tools/testkey.pem`. (There is no git history to
   scrub — it is not a repo. But treat this key as **permanently compromised**: it
   must never be a production key regardless.)
2. Add a repo-root `.gitignore` (and/or `firmware/.gitignore`) — this protects the
   key the moment anyone runs `git init` here:
   ```
   firmware/tools/testkey.pem
   *.pem
   __pycache__/
   *.pyc
   app/tools_vectors/*.priv    # if any private material ever lands there
   ```
   (`firmware/__pycache__/` and `firmware/examples/__pycache__/` currently hold
   committed-looking `.pyc` artifacts with nothing ignoring them — same root cause;
   the `__pycache__`/`*.pyc` lines above cover them.)
3. `push_script.py --keygen` already regenerates `testkey.pem` locally on demand
   (`firmware/tools/push_script.py:39`, writes with `chmod 0o600`) — keep that;
   just never commit the output.
4. Document a **real provisioning ceremony** in `CLAUDE.md`: generate a fresh
   per-owner Ed25519 key on an offline machine, set its raw 32-byte public half as
   `PUBKEY` in `main.py`, flash, and store the private key in the phone's secure
   storage (or the owner's HSM).

   **⚠ Corrected fact:** the shipped `PUBKEY` is
   `73871a59bc7d20612bd841297673847fbcc5242cbf9f1daa36bd3006064690a1`
   (`main.py:39`) — **not** the `c3c7e6…e489` value an earlier draft of this
   document claimed. It is still the throwaway test key (its private half is
   `testkey.pem`) and **must be rotated before any real deployment.**

### Acceptance criteria
- `testkey.pem` is gone from the tree and ignored.
- `CLAUDE.md` states the shipped `PUBKEY` is a test value and must be rotated.

---

## Fix 2 + Fix 3 — Script confidentiality on the wire + peripheral authentication

Do these together: one protocol change closes both. **This is the largest change
and it modifies the byte-agreement contract**, so read `CLAUDE.md`'s
"The byte-agreement contract" section and plan to regenerate the test vectors.

**Why (Fix 2).** The frame is `script || sig(64)` over an unencrypted BLE link.
The Ed25519 signature authenticates the *pusher*; it gives **zero confidentiality**.
A passive BLE sniffer within range during a push captures the API keys in
cleartext — no physical access needed. This is the easiest attack of all and must
be closed for secret-bearing scripts. (Confirmed still v1 plaintext:
`app/lib/core/protocol.dart:52-65` builds `[len][script||sig]`;
`firmware/main.py:243` splits `blob[:-64]`, `blob[-64:]`.)

**Why (Fix 3).** The scheme authenticates phone→ESP but never ESP→phone. The
manufacturer advertisement (company `0xFFFF`, magic `0xC1 0xCA`, 6 identity bytes)
is public and spoofable — the identity is just the eFuse MAC in the clear
(`firmware/main.py` `_adv_payload`, `app/lib/core/ble/adv.dart:15-27`).
`BootWatchReceiver` fires on any advertiser replaying a known id + awaiting bit and
posts an auto-push notification (`app/android/.../BootWatchReceiver.kt:31-34,45`),
and `EspScanner.findById` connects to whatever advertises that id with **no key
pinning** (`app/lib/core/ble/scanner.dart:57-72`). Result: a rogue peripheral
harvests the owner's default script (its secrets) with no physical access.

### Recommended design: encrypt-to-device-key (closes both at once)

Give each ESP its own **X25519 static keypair**. The device holds the private
decryption key (protected by Fix 1's flash encryption); the phone pins the
device's X25519 **public** key per device. The phone encrypts the script to that
key. A rogue peripheral without the private key receives ciphertext it cannot
read (closes Fix 3), and a passive sniffer sees only ciphertext (closes Fix 2).
Device authenticity becomes implicit: only the real device can act on the script.

Monocypher (already vendored in `firmware/ced25519/`) provides everything needed:
`crypto_x25519` (key exchange, `monocypher.c:1578`),
`crypto_aead_lock`/`crypto_aead_unlock` (XChaCha20-Poly1305, `monocypher.c:2963/2974`),
and BLAKE2b for the KDF. **These primitives are compiled in but not yet surfaced to
Python** — the native module (`firmware/ced25519/moned25519.c`) currently exposes
**only** `verify(pubkey, msg, sig) -> bool`. No new crypto library on device.

**New frame layout** (keep the existing Ed25519 sig for pusher-auth + anti-replay,
wrap the *plaintext* script in an AEAD):

```
frame body = eph_pub(32) || aead_nonce(24) || ciphertext(len) || mac(16) || sig(64)
```

- `eph_pub`  : phone's ephemeral X25519 public key for this push.
- shared      = X25519(eph_priv, device_x25519_pub)   [phone] /
                X25519(device_x25519_priv, eph_pub)     [device]
- key         = BLAKE2b(shared || eph_pub || device_x25519_pub)
- ciphertext + mac = crypto_aead_lock(key, aead_nonce, AAD, script_plaintext)
- **AAD (authenticated, not encrypted)** = `DOMAIN || version(0x02) || challenge_nonce(32) || len(script) as 4-byte BE`
- `sig`(64)  : Ed25519 over `DOMAIN || version(0x02) || challenge_nonce || len(ciphertext) as 4-byte BE || (eph_pub || aead_nonce || ciphertext || mac)`

**Bump `VERSION` to `0x02`** (currently `const(1)` at `firmware/main.py:33`;
`0x01` at `app/lib/core/protocol.dart:23`) so old and new frames can't be confused,
and so the signed message is unambiguous. **The version byte is currently written
but never checked** on either side — add explicit version dispatch/rejection.

**Device `process()` order (`firmware/main.py`):**
1. Verify Ed25519 sig over the ciphertext blob bound to the challenge nonce
   (existing pusher-auth + replay protection — keep `crypto_ed25519_check`).
2. X25519 + `crypto_aead_unlock` to recover plaintext script. On MAC/decrypt
   failure → `ERR:sig` (do **not** leak which stage failed).
3. `exec` the recovered plaintext (same UTF-8 bytes that were AEAD-authenticated) —
   and do it inside the Fix 7 sandbox.

### Firmware steps
- `firmware/ced25519/moned25519.c`: expose two more Monocypher wrappers —
  `x25519(scalar, point) -> 32 bytes` and
  `aead_unlock(key, nonce, mac, ad, ciphertext) -> plaintext | None`. Copy the
  Monocypher calls verbatim; do not hand-roll. `micropython.cmake` already lists
  `monocypher.c` — no new source files needed, so leave it unless you add files.
- `firmware/main.py`: add a `DEVICE_X25519_PRIV` constant (32 raw bytes, unique
  per unit, provisioned like `PUBKEY`) — none exists today. Add the same all-zero
  placeholder boot refusal you already have for `PUBKEY` (`main.py:41-42`). Rework
  `process()` to the 3-step order above. Keep verify+decrypt+exec in the main loop,
  never the IRQ.
- Pure-Python fallback (`firmware/ed25519.py`): X25519 + XChaCha20-Poly1305 in
  pure Python is heavy. The fallback today is **verify-only and has no concept of
  frames/versions**. **Decide explicitly:** either implement decryption (slow but
  correct, for host tests) or make confidentiality require the native module and
  have the fallback refuse encrypted (v2) frames with a clear error. Document the
  choice. Host tests must still exercise *something* end-to-end.

### App steps (Flutter, via `./fdart.sh`)
- `app/lib/core/protocol.dart`: build the v2 frame — ephemeral X25519 keypair,
  ECDH to the pinned device pubkey, BLAKE2b KDF, AEAD-seal the script, assemble
  `eph_pub || aead_nonce || ct || mac || sig`, sign with the existing Ed25519 key.
  Use the `cryptography` package (already a dependency) or `libsodium` bindings —
  match Monocypher's XChaCha20-Poly1305 + X25519 exactly.
- **Pin the device X25519 public key.** Add a column to the `Devices` table in
  `app/lib/data/database.dart` (currently: `id`, `name`, `lastSeen`,
  `lastPairedAt`, `defaultScriptId` — no pinned-key column; `schemaVersion` is `1`
  with only `createAll` on create, so you must add a real migration). Then
  `./fdart.sh "dart run build_runner build"` — never edit `database.g.dart` by hand.
  Store the device pubkey at provisioning time; refuse to push to a device whose
  advertised identity has no pinned key.
- `app/lib/core/ble/push_controller.dart`: unchanged state machine (connect →
  subscribe → read nonce → sign → write → await result; it already reads NONCE and
  rejects the all-zero sentinel), but the frame it sends is now the v2 frame.
  Because the script is encrypted to the pinned key, a rogue peripheral answering
  the connection gets ciphertext it can't read.

### Boot-watch hardening (Fix 3, belt-and-suspenders)
- `BootWatchReceiver.kt` currently builds a `PendingIntent` into `MainActivity` with
  `boot_watch_auto = true` (`BootWatchReceiver.kt:45`), which
  `push_screen.dart:56` auto-runs (`if (widget.auto && _script != null) _run();`).
  For any script flagged secret-bearing (see Fix 6), gate the auto-push behind an
  explicit user confirmation in the app instead of firing automatically. The
  encryption already means a spoofed peripheral gets nothing, but don't auto-connect
  to unauthenticated advertisements for secret payloads. **See Fix 8 — the auto-push
  is also reachable from *any* app on the phone, which must be fixed regardless.**

### Regenerate the byte-vector proof (mandatory)
Per `CLAUDE.md`: any encoding change requires regenerating
`firmware/tools/make_vectors.py` → `app/tools_vectors/vectors.json`, and
`app/test/protocol_signer_test.dart` must assert the Dart output is byte-identical
to the firmware's. The vectors are currently v1 (`"version": 1`,
`"domain": "espscript-v1"`, 6 plaintext-script vectors). Update `make_vectors.py`
to emit v2 frames (fixed test keys, nonces, ephemeral scalar, and script) and update
the Dart test (which today asserts `doc['version'] == 0x01`) to match.

### Acceptance criteria
- A passive BLE capture of a real push contains no plaintext script bytes.
- Pushing to a peripheral that does not hold the device X25519 private key results
  in a decrypt/`ERR:sig` failure and no `exec` (simulate with a wrong device key).
- `python3 firmware/tests/test_flow.py` green (add a v2 encrypted-frame case; the
  suite is 14 cases, all v1 today).
- `./fdart.sh "flutter test test/protocol_signer_test.dart"` green against
  regenerated vectors.
- `./fdart.sh flutter analyze` clean.

### Lighter alternative (if the full change is out of scope now)
Enable **BLE LESC bonding** to encrypt the whole link. This closes Fix 2 (sniffing)
but **not** Fix 3 (a rogue peripheral you bond to still receives the plaintext
script), and MicroPython's NimBLE security API on the C6 is less trodden. The
encrypt-to-device-key design above is preferred because it closes both and does not
depend on link-layer pairing.

---

## Fix 5 — Close the leak-back channels (`OUT:` and tracebacks)

**Why.** `notify()` sends `OUT:<s>` over the (now-encrypted, post-Fix-2) BLE link
(`firmware/main.py:252`), and a script exception emits `ERR:<traceback>`
(`firmware/main.py:257-260`). A script that does `notify(api_key)` broadcasts it; a
traceback shows the failing source line, so a secret literal on that line leaks.
Even with the channel encrypted, this is unnecessary exposure and a footgun.

### Steps
- `firmware/main.py`: in production, make exec exceptions report a **generic**
  `ERR:exec` (or a category, not the traceback body). Keep the full traceback
  behind a build/debug flag only. This is a small change in the try/except at
  `firmware/main.py:253-260`.
- Document in `CLAUDE.md` that `notify()` output is developer-facing and must not
  be handed secrets; a secret-bearing script should not call `notify` with key
  material.

### Acceptance criteria
- A deliberately-failing secret script produces `ERR:exec` (or similar) with no
  source line / variable content on the wire.
- `python3 firmware/tests/test_flow.py` still green — update the script-exception
  case (test #12, `firmware/tests/test_flow.py:229-234`, which currently asserts
  `b"ZeroDivision" in x`) to expect the generic error instead.

---

## Fix 6 — Protect secrets at rest on the phone (largest real exposure surface)

**Why.** `CLAUDE.md` documents that script bodies live in the drift/SQLite DB and
in the `.cicada` export/share format (`app/lib/features/import_export/`). That is
where the API keys actually persist, longer and more accessibly than on the ESP.
Confirmed: the `Scripts` table stores `body` as plain `text()`
(`app/lib/data/database.dart:11-17`); the DB is an unencrypted `NativeDatabase` on
`cicadaos.sqlite` (`database.dart:63-69`); `.cicada` is plaintext JSON with the
raw body (`app/lib/features/import_export/script_format.dart:18-26`) and
`shareScript` exports any script unconditionally
(`import_export_service.dart:15-27`).

### Steps
- Add a **`isSecret` flag** to the `Scripts` table in
  `app/lib/data/database.dart` (then `./fdart.sh "dart run build_runner build"`, and
  add a real migration — schemaVersion is currently `1` with no versioned upgrades).
- Encrypt secret script bodies at rest: either adopt SQLCipher for the DB, or
  encrypt the `body` column with a key held in `flutter_secure_storage` (same
  store as the signing seed — see `app/lib/core/crypto/key_store.dart`). Do not
  put the encryption key in the DB.
- `app/lib/features/import_export/import_export_service.dart`: **exclude
  `isSecret` scripts from `.cicada` export/share by default**, or encrypt them with
  a passphrase. A shared secret script must never leave the device in cleartext.
- Ensure secret bodies never hit logs. (A repo-wide grep found no current
  body/key logging — keep it that way; audit any new `print`/logging.)

### Acceptance criteria
- A secret script's body is not readable in the on-disk SQLite file.
- Exporting/sharing a secret script either refuses or produces ciphertext.
- `./fdart.sh flutter test` and `./fdart.sh flutter analyze` clean.

---

# New findings (this review) — Fixes 7–12

These are beyond the original six. Each was verified by reading the code. Fix 7 is
serious enough to sit alongside Fix 1 in priority; the rest are defense-in-depth.

## Fix 7 — Sandbox `exec`: an authenticated script gets full builtins + a writable filesystem → persistent backdoor / PUBKEY takeover

**Severity: HIGH (medium likelihood, critical impact — it defeats the two core
guarantees).**

`firmware/main.py:252-254`:
```python
g = {"notify": lambda s: self._notify(b"OUT:" + str(s).encode()[:180])}
try:
    exec(compile(script.decode("utf-8"), "app", "exec"), g)  # trusted, authenticated
```
Passing a globals dict without a restricted `__builtins__` means MicroPython injects
the **full** builtin namespace: the script gets `open`, `__import__`, `os`,
`machine`, etc. On ESP32 MicroPython the LittleFS root (where `main.py` lives) is
writable, so a single signed script can `open("main.py", "w")` and rewrite the
loader — remove the `ed25519_verify` call, or replace the `PUBKEY` constant with an
attacker's key.

**Attack.** Whoever can get *one* script signed (a compromised/stolen phone, or a
user socially engineered into pushing a "cool demo") escalates a one-shot
authenticated run into **permanent, unauthenticated control that survives reboot**,
and can overwrite `PUBKEY` to lock the legitimate owner out even after they rotate
their key. This directly defeats "single-use nonce stops replay" and "dumping flash
reveals nothing forgeable" — and it is *not* fixed by Fix 1's flash encryption
(encryption protects confidentiality at rest, not an authenticated write from within
the running system).

**Fix.**
- Run scripts with a minimal `__builtins__` allow-list, e.g. seed `g` with
  `{"__builtins__": {...safe subset...}, "notify": ...}` exposing only what a
  dashboard/action script legitimately needs. Deny `open`, `__import__`, filesystem
  and raw-flash access by default.
- Mount the application filesystem read-only at runtime, or keep `main.py`/`PUBKEY`
  on a partition the script namespace cannot `open` — so even a bypass of the
  builtins allow-list cannot achieve persistence.
- Do this in the same `process()` change as Fix 1 step 5 (RAM hygiene) and Fix 5
  (generic errors), and add a host-test case asserting a script that tries
  `open("main.py","w")` (or `import os`) fails rather than persisting.

**Acceptance criteria**
- A pushed script attempting to write `main.py` or import a denied module fails
  (generic `ERR:exec`), and `main.py`/`PUBKEY` are unchanged afterward.
- A legitimate `notify(...)` script still runs (regression).
- `python3 firmware/tests/test_flow.py` green with the new case.

## Fix 8 — Exported `MainActivity` + `boot_watch_auto` defaulting to `true` → any co-installed app can trigger a silent auto-push

**Severity: MEDIUM.**

`MainActivity` is `android:exported="true"`
(`app/android/app/src/main/AndroidManifest.xml:20`), and `handleIntent` reads the
push extras off **any** incoming intent, defaulting `auto` to `true`
(`app/android/app/src/main/kotlin/dev/manzari/cicadaos/MainActivity.kt:46-51`):
```kotlin
val device = intent?.getStringExtra("boot_watch_push_device") ?: return
val auto = intent.getBooleanExtra("boot_watch_auto", true)
```
That forwards `{device, auto}` to Flutter (`onBootPush`), which routes to
`/push?device=…&auto=1`, and `push_screen.dart:56` auto-runs the push. Because the
activity is exported, **any other app on the phone** can
`startActivity(MainActivity with these extras)` — no permission, no user
interaction. Combined with Fix 3 (no peripheral pinning), a malicious app that
learned a device id (broadcast in the clear in BLE advertisements) can force the
phone to sign and push that device's default (secret) script while a co-located
rogue ESP spoofs the id and harvests the plaintext.

**Fix.**
- Don't trust `boot_watch_auto` on an externally-deliverable intent. Options:
  route the boot-watch launch through a component that is `exported="false"`, or
  verify the caller (`getCallingActivity`/a signature-permission), or ignore the
  `auto` extra unless the launch came from the app's own `PendingIntent` (e.g. a
  one-time nonce the receiver sets and the activity checks).
- Default `auto` to `false`, not `true`, so an unqualified external launch cannot
  auto-run.
- Pair with the Fix 3 boot-watch confirmation gate for secret scripts.

**Acceptance criteria**
- Launching `MainActivity` from another app (or `adb am start` with the extras) does
  **not** auto-run a push; at most it opens the push screen awaiting explicit tap.

## Fix 9 — iOS signing seed stored `first_unlock` (not `ThisDeviceOnly`) → seed leaves the device via backup

**Severity: MEDIUM.**

`app/lib/core/crypto/key_store.dart:19-21`:
```dart
iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
```
The Ed25519 seed is "the only secret in the whole app." `kSecAttrAccessibleAfterFirstUnlock`
(without the `ThisDeviceOnly` variant) makes the Keychain item eligible for
encrypted iTunes/Finder device backups and **restorable onto a different device**.
So the crown-jewel private key can be extracted from a host backup and reused to
forge scripts for every ESP holding the matching `PUBKEY`.

**Fix.** Use `KeychainAccessibility.first_unlock_this_device` (maps to
`…AfterFirstUnlockThisDeviceOnly`) so the seed is excluded from transferable backups.

## Fix 10 — Android `allowBackup` defaults to `true` → cleartext script DB exfiltrated off-device

**Severity: MEDIUM.**

`app/android/app/src/main/AndroidManifest.xml` has no `android:allowBackup="false"`
and no `dataExtractionRules`/`fullBackupContent` (confirmed — none exist under
`android/`). With the default `allowBackup=true` and Android Auto Backup, the app's
files — including the Drift SQLite DB holding script bodies in cleartext — are
copied to cloud backup and are extractable via `adb backup` on many devices, no root
needed. This is a *distinct* exfiltration path from Fix 6's on-device at-rest issue:
it moves the plaintext scripts entirely off the phone. (The Ed25519 seed itself
stays safe — `flutter_secure_storage` wraps it with a non-exportable AndroidKeyStore
key.)

**Fix.** Set `android:allowBackup="false"` on `<application>`, or ship
`dataExtractionRules`/`fullBackupContent` that exclude the DB. Pairs with Fix 6.

## Fix 11 — Ed25519 pure-Python fallback accepts non-canonical / malleable signatures

**Severity: LOW (not currently exploitable; standards-conformance / defense-in-depth).**

`firmware/ed25519.py:156-166`:
```python
S = int.from_bytes(sig[32:], "little")
h = _hint(sig[:32] + pubkey + msg)
return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
```
Two RFC-8032 deviations in the pure-Python path: (a) `S` is never checked to be in
`[0, L)`, so `S + L`, `S + 2L`, … also verify (classic malleability); (b)
`_decodepoint` (`ed25519.py:142-151`) masks the sign bit and validates on-curve but
never checks `y < q`, accepting non-canonical point encodings. **Neither is
practically exploitable here** because the nonce is strictly single-use and consumed
at frame-parse time, so a second valid encoding of the same signature buys nothing —
but it is worth fixing if the nonce lifecycle ever changes, and for conformance. The
native `ced25519` path (the default when compiled in) is not affected.

**Fix.** Reject `sig[32:] >= L`, and reject decoded points whose recovered `y >= q`.

## Fix 12 — Oversized-frame drain can pin the attacker's own connection (minor self-DoS)

**Severity: LOW.**

`firmware/main.py:205-206`:
```python
if self._need > _MAX_FRAME:
    self._drain = self._need   # stay in sync: swallow it, then re-arm
```
`_need` is an unbounded 32-bit value (up to ~4.29 GB). Declaring a huge length forces
the peripheral to discard that many bytes before it parses anything else on that link.
Because only one central connects at a time and advertising is disabled while
connected, this only wedges the **attacker's own** session (disconnecting frees the
device), so impact is low — but a garbage prefix silently disables the connection
until teardown.

**Fix.** On a length exceeding `_MAX_FRAME`, drop the frame and force-disconnect (or
cap `_drain` to a small bound) instead of draining up to 4 GB.

---

## Areas checked and found clean (no action needed)

- **Nonce generation / lifecycle** (`firmware/main.py`): `os.urandom(32)` (ESP
  hardware TRNG); nonce consumed and the readable char blanked the instant a frame
  is captured; every failed path rotates to a fresh nonce; disconnect clears state.
  No reuse window or predictable re-issue found.
- **Frame length / integer handling**: unsigned BE parse, `N ≤ 16384` enforced,
  `< 65` rejected, buffer stays bounded even under write floods; `ERR:busy`/
  `ERR:nonce` drop frames without touching the nonce.
- **App signer / keygen** (`crypto/signer.dart`): `Ed25519().newKeyPair()` (CSPRNG),
  seed never logged/exported, raw 64-byte R||S matches the wire contract.
- **Android secure storage backing**: the seed is wrapped by a non-exportable
  AndroidKeyStore key (safe even under Fix 10).
- **`.cicada` import path**: plain JSON envelope (no zip → no zip-slip), export
  filename sanitised and written only under `getTemporaryDirectory()`, import
  creates a collision-free name — no silent overwrite, no path traversal.
- **Deep-link / import intent filters**: the `VIEW`/`BROWSABLE`/`SEND` filters only
  add a script to the library and open the editor — they never push (the auto-push
  route is the exported-activity extras path, Fix 8). `BootWatchReceiver` is
  `exported="false"`.
- **SQL layer** (`scripts_repository.dart`): all Drift-parameterised; no
  string-concatenated SQL.
- **`push_script.py`**: key written `chmod 0o600`, no temp files — the only issue is
  the committed `testkey.pem` (Fix 4).

---

## Global acceptance gate (run before declaring done)

- `python3 firmware/tests/test_flow.py` — green (updated for v2 frames, generic
  errors, and the Fix 7 sandbox case).
- `./fdart.sh flutter test` — green.
- `./fdart.sh flutter analyze` — clean.
- Vectors regenerated: `firmware/tools/make_vectors.py` re-run, `vectors.json`
  updated to v2, `app/test/protocol_signer_test.dart` asserts byte-identity.
- `CLAUDE.md` updated: v2 frame layout, mandatory eFuse provisioning + device X25519
  key + at-rest/export policy, and the `VERSION` bump to `0x02`.
- One physical dev board provisioned per Fix 1 and a real push verified end-to-end.

## What each fix actually buys you (map back to the guarantee)

| Fix | Threat closed |
|-----|---------------|
| 1   | Physical attacker can't drop to REPL, dump live RAM, read flash, or plant a capturing loader. **Prerequisite for the stated goal.** |
| 4   | No one can sign scripts with a key that's in the tree. |
| 2   | Passive BLE sniffer during a push can't read the secrets. |
| 3   | A spoofed/rogue peripheral can't harvest the owner's secret script. |
| 5   | Secrets don't leak back over the status channel or in tracebacks. |
| 6   | Secrets aren't sitting in cleartext in the phone DB / exports (their real long-term home). |
| 7   | An authenticated script can't rewrite the loader / `PUBKEY` and persist. **Also a prerequisite — flash encryption alone doesn't stop it.** |
| 8   | A co-installed app can't drive a silent auto-push via the exported activity. |
| 9   | The signing seed can't be lifted from an iOS device backup. |
| 10  | The cleartext script DB can't be exfiltrated via Android cloud/adb backup. |
| 11  | Signature-malleability / non-canonical encodings rejected (conformance). |
| 12  | A garbage length prefix can't wedge the BLE session. |
