# Sample pushed script. Runs on the ESP with full builtins plus notify().
# notify(s) sends OUT:<s> back over BLE TX to the push client.
import machine
notify("hello from esp-script")
notify("freq=%d MHz" % (machine.freq() // 1_000_000))
