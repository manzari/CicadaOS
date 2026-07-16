# Firmware — BLE stub loader (MicroPython, ESP32-S3)

Device half of the system: receives an encrypted+signed MicroPython script over BLE,
verifies, decrypts, and runs it sandboxed. The wire protocol, security model, and hard
guardrails live in the repo's `../CLAUDE.md` — read that first; it is the authoritative
spec. Build the one-image loader (LVGL + BLE + native `ced25519`) per `BUILD_LVGL.md`;
push from the desktop with `tools/push_script.py` (see `tools/README.md`); pushable
example scripts live in `examples/`.

## ⚠ Security notice — read before deploying

The confidentiality guarantee holds **only after** the per-unit provisioning ceremony in
`../CLAUDE.md` ("Provisioning requirements"). Two things are mandatory and cannot be
verified by the host test suite:

1. **Rotate the shipped keys — they are throwaway test values.** The `PUBKEY` in
   `main.py` corresponds to a signing key whose private half was previously in-tree;
   treat it as **publicly compromised**. `DEVICE_X25519_PRIV` ships as an all-zero
   placeholder (the loader refuses to boot until it is set). Before a unit carries any
   real secret, generate a fresh per-owner Ed25519 signing key and a per-unit X25519
   keypair offline, set `PUBKEY`/`DEVICE_X25519_PRIV` in `main.py`, and pin the X25519
   public half in the app. The boot guards force *some* rotation but cannot tell a real
   key from another test key.

2. **Burn the hardware root of trust (ESP32-S3).** Build with `sdkconfig.hardening`
   (Secure Boot v2 + Flash Encryption **release** mode + ROM download mode disabled +
   JTAG off). Without these one-way eFuse burns, a physical attacker drops to the REPL
   and reads `DEVICE_X25519_PRIV` straight out of flash — defeating confidentiality
   regardless of the protocol. The burns can **brick a unit** and disable UART
   re-flashing: prove the full push flow on a throwaway dev board first, then confirm
   with `espefuse.py summary` and that `esptool.py read_flash` yields ciphertext.

Until both are done, the loader is safe to demo but must not receive secret-bearing
scripts.

## Testing

```bash
python3 tests/test_flow.py   # stdlib-only CPython, no hardware — MUST stay green
```

After ANY change to `main.py`, `ed25519.py`, or `cryptobox.py`: run it and extend it to
cover the new behavior.

## Loader status display (`lifecycle_ui.py`, optional)

Narrates loader state on the 172×320 panel as a cicada life cycle. All stages, in
order, with the exact on-screen text (each card shows a title, a top subtitle, and a
bottom caption):

| Loader state              | Stage       | Title        | Subtitle (top)      | Caption (bottom)          | Screen                                            |
|---------------------------|-------------|--------------|---------------------|---------------------------|---------------------------------------------------|
| power-on                  | `boot`      | `CicadaOS`   | "loader"            | *(none)*                  | one-shot cinematic: dusk sky → cicada glides down, title dissolves, camera pans to the horizon, egg is laid; resolves into the `egg` card |
| boot (settled)            | `egg`       | `E G G`      | "waking"            | "unit `<id>`"             | egg on a twig, breathing glow                     |
| advertising (idle)        | `nymph`     | `N Y M P H`  | "listening for a push" | "unit `<id>`"          | nymph deep underground, expanding cyan call-ring  |
| central connected         | `nymph`     | `N Y M P H`  | "challenge `<hex>`" | "conditions met"            | nymph surfaced; shows `challenge nonce[:4].hex()` |
| frame reception (RX)      | `molting`   | `M O L T I N G` | "receiving …%"   | "shell splitting"         | husk at the surface, dorsal-crack progress bar    |
| verify+decrypt            | `emergence` | `E M E R G E N C E` | "verifying signature" | *(none)*          | teneral cicada, wings unfurling (drawn *before* the slow verify) |
| script ran (`OK:done`)    | `adult`     | `A D U L T`  | "script is running" | "OK - done"               | green cicada + chirping song bars                 |
| `ERR:sig`                 | `rejected`  | `R E J E C T E D` | "signature refused" | "not this brood"     | cracked husk, red                                 |
| `ERR:exec`                | `rejected`  | `F A I L E D` | "script raised an error" | "waiting for another push" | cracked husk, red                          |

At idle with no phone connected you only ever see `boot` → `egg` → `nymph` (advertising);
the `nymph`(connected) → `molting` → `emergence` → `adult`/`rejected` stages are
push-driven. The `boot` cinematic plays once at power-on and dissolves seamlessly into the
`egg` card (its final frame is drawn to match).

Invariants (also in `../CLAUDE.md` — do not silently revert): display I/O only from the
main loop, never the BLE IRQ (the loop polls IRQ-written state); `autodetect()` never
raises and any display fault degrades to `NullDisplay` (panel dies, BLE lives); terminal
cards hold (`_HOLD_*_MS`: intro cinematic 4.5 s → egg 5 s, error 2.5 s, success 6 s) before returning to nymph,
and new RX activity breaks the hold immediately; **every stage is held at least
`_MIN_SHOW_MS` (1 s) before the next paints over it** (so a fast native verify can't flash
`emergence` past in a few ms); once a pushed script paints its own UI (loader root's DELETE
event), the loader goes screen-silent until reboot, LED cues only.

Deploy (it's an optional flash file):

```bash
mpremote fs cp lifecycle_ui.py :lifecycle_ui.py
mpremote fs cp examples/cicada_ui.py :cicada_ui.py   # panel bring-up helper it depends on
```

`tests/test_flow.py` has a recording `FakeDisplay` (stage sequences, IRQ purity, holds,
faulting-panel fallback) — keep it green.

## Remaining work

- `tools/provision.py`: helper that patches a given pubkey hex into `main.py` and prints
  the mpremote copy commands. (Today this is done by hand — see **Provisioning
  requirements** in `../CLAUDE.md`.)
