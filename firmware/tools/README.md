# Desktop push client (`push_script.py`)

A `bleak` client that ENCRYPTS a script to a flashed ESP32's X25519 key, signs
the encrypted blob with an Ed25519 key, pushes the v2 frame, and prints the TX
status stream. Use it to exercise real hardware before the Android app exists.
It is the byte-for-byte reference for the wire contract in the repo's `CLAUDE.md`
(Wire protocol). It reuses `../cryptobox.py` so its crypto matches the firmware.

## Setup

`bleak` needs the host's BlueZ/D-Bus stack, so this runs on the host, not in
Docker.

```bash
python3 -m venv .venv
.venv/bin/pip install bleak cryptography
```

Or run ad-hoc without a venv: `uvx --with bleak --with cryptography python push_script.py ...`

## Keys

Two keys are involved:

- **Signing (Ed25519).** `tools/testkey.pem` holds the PRIVATE half (never commit
  it — it is gitignored). Its raw 32-byte public half is `PUBKEY` in `main.py`.
- **Device (X25519).** Per-unit; its PRIVATE half is `DEVICE_X25519_PRIV` in
  `main.py`. The client encrypts to its PUBLIC half.

```bash
.venv/bin/python push_script.py --keygen          # writes testkey.pem, prints PUBKEY hex
.venv/bin/python push_script.py --keygen-x25519   # prints a device X25519 keypair + main.py line
```

WARNING: `--keygen` OVERWRITES `testkey.pem`. If a board is already flashed with
the current key's public half, regenerating breaks the match (every push then
returns `ERR:sig`). Only regenerate when you will also reflash `main.py` with
the new `PUBKEY`.

## Push

Pass the target's X25519 key with `--device-priv <hex>` (its `DEVICE_X25519_PRIV`)
or, if you only have the public half, `--device-key <pubhex>`.

```bash
.venv/bin/python push_script.py hello.py --device-priv HEX           # OK:verified / OUT:* / OK:done
.venv/bin/python push_script.py hello.py --device-priv HEX --bad-sig # expect ERR:sig
.venv/bin/python push_script.py hello.py --device-priv HEX --replay  # OK:done, then ERR:sig on resend
```

`--address <MAC>` skips the name scan; `--timeout` / `--scan` tune the waits.
`--ack` writes frame chunks WITH response (each ATT-acked before the next)
instead of the default write-no-response — slower but useful on a lossy link.
Exit code is 0 when the observed TX outcome matches the mode's expectation.

## Notes

- The script file's exact bytes are what get encrypted and executed (UTF-8, no
  re-encoding), so it must be valid UTF-8 / valid MicroPython.
- A script reports back to this client by calling the injected `notify(...)`
  helper, which the ESP relays as `OUT:<text>` on TX.
- Only one central at a time: the ESP stops advertising while connected and
  re-advertises on disconnect, so back-to-back runs work.
- TX status strings longer than `mtu-3` bytes arrive split across notifications
  (e.g. at the default 23-byte MTU). The client rejoins them by status prefix,
  so multi-packet `OUT:`/`ERR:` lines print whole.
