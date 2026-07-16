# Security policy

## Reporting a vulnerability

Please report security issues privately — email **mail@manzari.dev**, or use
GitHub's *Report a vulnerability* button under the repository's Security tab.
Do not open a public issue for an unfixed vulnerability.

This is a personal project with no SLA. Expect an acknowledgement within a week
or so.

## Scope and known limits

Read [`CLAUDE.md`](CLAUDE.md) ("Security model", "Provisioning requirements")
before reporting — several properties are **intentional** and out of scope:

- **The keys shipped in `firmware/main.py` are throwaway test values.** `PUBKEY`'s
  private half exists on the author's machine; treat it as compromised. It is not a
  vulnerability that a stock checkout trusts a known key — the loader refuses to
  boot on all-zero placeholders precisely to force rotation, and the real
  guarantee begins only after the per-unit provisioning ceremony.
- **A compromised phone is out of scope.** The phone holds the Ed25519 signing key;
  whoever holds it can push. This is the accepted trade-off (see "Signing-key
  decision").
- **An un-hardened board is out of scope for confidentiality.** Without the Secure
  Boot v2 + Flash Encryption eFuse burns, a physical attacker reads
  `DEVICE_X25519_PRIV` out of flash. This is documented, not a bug.
- **The BLE link is unencrypted at L2 by design.** Confidentiality and device
  authenticity are enforced at the application layer (encrypt-to-device-key +
  signatures), not by BLE pairing.
- **`OUT:`/`notify()` is developer-facing** and deliberately unauthenticated
  output. Never hand it key material.

## In scope — these are real bugs, please report them

- Any way to make the loader `exec` bytes that were not signed by `PUBKEY`, or that
  did not decrypt under `DEVICE_X25519_PRIV`.
- Any nonce replay, cross-unit replay, or challenge reuse.
- Any escape from the `exec` sandbox that reaches the filesystem or flash — i.e.
  lets an authenticated script rewrite the loader or `PUBKEY` and persist.
- Any byte-agreement divergence between the four implementations (firmware Python,
  vendored Monocypher C, Dart, vector generator) that changes what gets signed
  versus what gets executed.
- Any path that exfiltrates the phone's signing seed or the script DB
  (backup/extraction rules, exported components, `.cicada` export of `isSecret`
  scripts).
- Signature-verification flaws: non-canonical/malleable acceptance, the
  `crypto_eddsa_check`-vs-`crypto_ed25519_check` trap, point-validation gaps.

## Hardening checklist for a real deployment

Do not skip these; the confidentiality guarantee rests on them.

1. Rotate both keys per unit (per-owner Ed25519 signing key, per-unit X25519
   device key) — see [`CLAUDE.md`](CLAUDE.md) "Provisioning requirements".
2. Build with `firmware/sdkconfig.hardening` and burn the eFuses (Secure Boot v2 +
   Flash Encryption **release** mode, ROM download mode disabled, JTAG off). These
   burns are one-way and can brick a unit — prove the push flow on a throwaway
   board first.
3. Verify with `espefuse.py summary`, and confirm `esptool.py read_flash` yields
   ciphertext.
4. Mark secret-bearing scripts `isSecret` so their bodies are encrypted at rest and
   refused for cleartext export.
5. Keep `_DEBUG = False` in `firmware/main.py` (tracebacks otherwise go on the wire).
