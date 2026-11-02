# op6893 development checkpoint

This directory snapshots the board bring-up reports previously maintained at
/data/src/mainline/mt6893-direct. The source tree is experimental, not an
upstream-ready port. Validated image06374ef46937 predates this commit; changing
Git HEAD does not establish that a newly built image was tested on hardware.

See PERIPHERAL-STATUS.md for evidence and limitations, HARDWARE-PLAN.md for the
historical roadmap, and WIFI-REVERSE-ENGINEERING.md for the binary-analysis
handoff. Earlier report links may refer to large external captures/tools that
remain in mt6893-direct; boot images, rootfs, proprietary firmware and device
private data are not included here. The external build/initramfs workspace is
not a Git repository and is not made reproducible by this kernel checkpoint.

Fourteen existing host tests passed at checkpoint time; output is recorded in
evidence/attempt-50/commit-tests.log. No new hardware test occurred during
this checkpoint. Historical experiments and retained inherited-resource paths
must not be interpreted as full power management or thermal protection.

AI assistance: Codex assisted source changes, source audits, test execution
and documentation across the iterative board bring-up. Human hardware tests
are distinguished in the reports. No DCO certification is asserted.
