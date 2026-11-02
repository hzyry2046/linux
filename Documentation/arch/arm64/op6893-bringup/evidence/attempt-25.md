# Attempt25: MT6893 pinctrl registration

Kernel baseline cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a.
Boot14c7e1602c1d SHA2567634f60da980d7336f7b986d2a6d170d7ff1b398a6bc0e0acbeea41e8555b8c5.
Debian9825862f46b0 unchanged; no cache write or ACK restoration.

Fixed mainline pinctrl base-name order to base,rm,bm,lm,lb,rt,lt,tm.
Previous list required absent bl/br/tl and shifted bank indices. Binding
example EINT corrected0x1100b000->0x1000b000 and GIC specifier to3cells.
Added SoC pinctrl node with ACK register addresses/SPI212;220 physical GPIO
range. No pin states, consumers or hogs. EINT initialization does write domain
enable and mask registers; this is not a read-only hardware probe.

All220 ACK pin function/EINT descriptions match current mainline. Mainline
adds7 virtual EINT descriptions; gpiochip reports227 lines, while gpio-ranges
covers0–219 only. Six electrical field tables match exactly. All24 ACK R0/R1
entries retained among46 mainline entries each; extra entries not hardware
validated. No electrical features or IRQ consumers exercised.

Important correction to prior inventory: despite defconfig requesting PINCTRL=n,
previous generated config already enabled MediaTek pinctrl via dependencies.
This change adds the missing DT node and scopes built drivers to MT6893;
DEBUG_FS added for inspection. Config diff saved. Payload7,297,024 bytes;
free26,257,408 bytes. No compiler warnings. FDT merger tests and compiled-DTB
bank order/address/IRQ/range checks passed. Driver and binding patches separately
pass checkpatch0errors/0warnings. Maintainers identified, no messages sent.
Full dt_binding_check not completed: dtschema absent and installation stalled
on network download; cancelled installer. Do not claim schema validation.

Hardware: probe returned0 at~16ms; platform driver bound; all8 resource names
and addresses verified via /proc/iomem. All227 pin descriptors MUX/GPIO
UNCLAIMED; pinctrl map empty, physical range0–219 verified. USB native SSH,
8CPUs, pinned rootfs hash, readonly cache and1MiB random SFTP roundtrip passed.
At108s watchdog feeder alive, USB configured and heartbeat continued. No EINT
probe warning; actual interrupt delivery remains untested. Optional resource
sysfs path absent; used /proc/iomem instead. Debugfs path includes driver suffix.

Changes and analysis generated with Codex assistance. Regular hardware-resource
mapping defect; no demonstrated security-boundary violation. No commits or
Signed-off-by, preserving this session's workflow; standalone diff artifacts
saved for review. Device left running new mainline image; no reset requested.
Next: identify volume key GPIO/trigger from ACK, verify its electrical state,
then one known GPIO-key interrupt consumer; PMIC remains deferred.
