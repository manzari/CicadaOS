# Bundled example scripts

Copied verbatim from `../../../firmware/examples/0*.py`. These are the pushable
LVGL/RGB-LED demos seeded into the app's script library on first boot (and via
**Restore examples**). See `lib/data/examples_seeder.dart`.

`cicada_ui.py` is deliberately NOT bundled — it is a device-side helper that
lives on the ESP32 flash and is never signed or pushed. If you change the
firmware examples, re-copy them here.
