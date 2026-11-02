# Attempt27: identify volume-up on current ACK

Device was already running ACK6.6.30-4k-gf3ddcd7f927a-dirty on entry,
uptime~2469s, rather than previous mainline. No reboot/flash performed.
Do not infer why or when user switched systems from these observations.

getevent -lp event1 reports mtk-pmic-keys with KEY_VOLUMEUP and KEY_POWER.
Live getevent captured six complete KEY_VOLUMEUP press/release pairs.
ACK IRQ counters HOMEKEY49 and HOMEKEY_R51 each reached6. Driver log says
legacy PMIC homekey reports keycode115. This is direct evidence volume-up
is wired to PMIC HOMEKEY, not SoC GPIO20/59 or the keypad matrix. ACK keypad
source comment saying matrix is superseded by this live evidence and by
its PMIC driver legacy mapping from kpd-sw-rstkey=115. GPIO20 is touch reset;
leave both stale volume-up pinctrl/GPIO properties unused in mainline.

Next implementation dependency: pwrap transport + MT6359-family MFD and
PMIC interrupt route, then standard mtk-pmic-keys with homekey code115.
Mainline already has MT6359 key data. Mainline pwrap has MT6873 support but
no MT6885 match; register/protocol/clock equivalence must be demonstrated
before using any fallback. ACK pwrap uses GIC SPI220 (displayed hwirq252).
No new hardware code or mainline image in this investigation. Device kept
in its observed ACK state. Captures under attempt-27/.
