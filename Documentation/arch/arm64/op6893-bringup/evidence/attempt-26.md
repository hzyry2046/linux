# Attempt26: volume-down GPIO/EINT input

Boot42b2ff5658c2, SHA256620c13c3307ffd2e2953aca5b146e8ebd68fe2ea669ab34d2187c2bdfac34dbe.
Debian9825862f46b0 unchanged. GPIO155 confirmed by ACK live DT pinmux0x9b00,
keypad GPIO property and EINT155. ACK driver reports !gpio_value as pressed.
Volume-up deferred: GPIO property20 conflicts with pinmux59.

Added standard gpio-keys, KEY_VOLUMEDOWN, GPIO_ACTIVE_LOW,32ms debounce.
Default pin state selects GPIO155/input-enable; inherited bias retained.
Enabled INPUT/EVDEV/KEYBOARD_GPIO. No power-key, wakeup or suspend behavior
added. First build failed on missing closing DTS brace; corrected before
successful build. Final build has no compiler warnings; FDT tests and image
roundtrip passed. Incremental DTS/config checkpatch0errors/0warnings.

Hardware: gpio-keys bound, event0 registered, EINT155 mapped to IRQ170.
Initial IRQ count0. Captured KEY_VOLUMEDOWN code114 press/release pairs
from real user key presses; at least three complete alternating pairs.
Additional key events arrived during observation; exact-three assertion was
too strict and failed, not evidence of driver failure. User confirmed pressing
completed. Count later held60 across15s; final idle check saved separately.
Read helper was stopped while latest captured event was pressed, so its final
release is not in that capture; physical idle pin state was checked afterward.
8CPUs, USB SSH and pinned backing rootfs hash pass. Debugfs confirms GPIO155
owned by gpio-keys; inherited bias bits remain (0 1). No other key added.
This verifies physical GPIO-to-EINT-to-evdev delivery, not suspend wakeup,
all GPIO electrical controls or long-duration debounce stress.

Device left running mainline; no reset scheduled. Artifacts in attempt-26/.
No commits or Signed-off-by. DTS/config and test helper generated with Codex
assistance. Next step investigate volume-up wiring against live ACK behavior
or proceed to PMIC transport resource audit; do not guess volume-up GPIO.
