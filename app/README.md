# CicadaOS companion app (Flutter)

Phone side of the BLE Ed25519 script-loader. Manage a library of MicroPython
scripts, sign them, and push them to an ESP32 over BLE — see the repo's `../CLAUDE.md`
(wire protocol, security model, guardrails). There is no backend: all data stays on the
phone; nothing leaves it except signed frames over BLE.

## Build & test (Docker only — no host toolchain)

A wrapper runs the pinned Flutter image and restores file ownership:

```bash
../fdart.sh flutter test        # unit tests
../fdart.sh flutter analyze      # static analysis
../fdart.sh "dart run build_runner build"   # regenerate drift code (database.g.dart)
../fdart.sh "flutter build apk --debug"     # Android build
```

iOS is built in the cloud (developer has no Mac) — see `codemagic.yaml`.

## Architecture

- **State** riverpod · **Nav** go_router · **DB** drift (SQLite) · **Crypto**
  `cryptography` (Ed25519) + `flutter_secure_storage` · **BLE** flutter_blue_plus
  · **Editor** re_editor.
- `lib/core/` — the byte-exact heart, all pure-Dart and unit-tested:
  - `protocol.dart` msg/frame builders (CLAUDE.md wire protocol), `crypto/signer.dart` sign,
  - `ble/` `tx_status.dart` (status parser, kept standalone for future dashboards),
    `push_controller.dart` (the push state machine, transport-injected → testable),
    `fbp_transport.dart` (flutter_blue_plus binding), `scanner.dart`, `adv.dart`.
- `lib/data/` — drift `database.dart` + repositories + `.cicada` file format.
- `lib/features/` — scripts (library + editor), devices (+ key/provisioning),
  push (screen + device picker), import_export, boot_watch.

Push-flow guardrails: subscribe TX **before** reading NONCE (and never sign an all-zero
nonce); chunk frame writes at `min(mtu - 3, 244)` bytes, write-without-response. Verify
current plugin APIs before coding against them (flutter_blue_plus, share_handler,
drift) — do not code from memory.

### Script file format (import/export)

Extension **`.cicada`**, MIME `application/x-cicada-script`, JSON envelope:

```json
{"format": "cicada-script", "version": 1, "name": "blink", "body": "<python source>", "modifiedAt": "<iso8601>"}
```

Bare `.py` is also accepted on import (name = filename). Scripts marked `isSecret` are
refused for cleartext export.

### Byte-agreement with the firmware

`../firmware/tools/make_vectors.py` emits `tools_vectors/vectors.json` (msg + sig
for fixed keys/nonces/scripts, using the same test seed as the firmware host
tests). `test/protocol_signer_test.dart` asserts the Dart `msg` and signatures
are byte-identical. This is the proof that avoids the classic `ERR:sig` (a one-byte
`msg` mismatch) without hardware. Regenerate vectors if the protocol ever changes.

## Status

| Task | State |
|---|---|
| 1 Protocol & crypto core + vectors | Docker-tested (byte-identical to Python) |
| 2 Data layer (drift) | Docker-tested (incl. setNull cascade) |
| 3 BLE transport & push machine | logic Docker-tested · real-C6 acceptance pending |
| 4 Library + editor | built, analyzes clean · device/emulator run pending |
| 5 Import/export | format tested · device share/intent verification pending |
| 6 Devices + key provisioning | built |
| 7 Firmware identity + awaiting flag | host tests green (`../firmware`) |
| 8 Boot-watch (Android) | native scaffold in place; needs on-device verify |
| 9 iOS pipeline | `codemagic.yaml` template; needs Apple account |

"Pending" items need a flashed board / a device / an Apple account — none available
in the build environment.

Open items: Apple Developer account availability (blocks the iOS TestFlight
verification only); whether Android < 13 devices matter (affects notification
permission handling only — signing is software either way).

## Later: dashboards (design note — do NOT implement now)

Kept forward-compatible by convention, not code: scripts may emit `OUT:` lines
containing JSON (`notify('{"t":25.1}')`). A future dashboard feature attaches a widget
layout to a script, parses `OUT:` JSON into live tiles, and sends actions by pushing
small signed scripts (or a future firmware `IN:` channel — firmware scope decision for
later). Nothing in the current schema should hard-code "push is the only interaction":
the TX status stream parser is its own class (`core/ble/tx_status.dart`) for exactly this.

## Provisioning an ESP

Protocol v2 binds **two** keys per unit — do both:

1. **Signing key (phone → ESP).** Open the app → key icon → copy the 32-byte Ed25519
   hex → set `PUBKEY` in `../firmware/main.py`. One pubkey per ESP ⇒ one signing phone
   per ESP.
2. **Device key (encrypt-to-device).** Mint a per-unit X25519 keypair
   (`../firmware/tools/push_script.py --keygen-x25519`), set the private half as
   `DEVICE_X25519_PRIV` in `main.py`, and pin the public half in the app (device detail
   → pin key). Push refuses any device with no pinned key.

⚠ **The keys shipped in `main.py` are throwaway test values and must be rotated before
any real deployment, and secret-bearing units additionally require the Secure Boot +
Flash Encryption eFuse burns.** See `../firmware/README.md` ("Security notice") and
`../CLAUDE.md` ("Provisioning requirements") for the full ceremony — the app-side steps
above are not sufficient on their own.
