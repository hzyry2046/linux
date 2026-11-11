# Attempt52: MT6359P connectivity supply ownership

Baseline remains06374ef46937. Added pmic-conn-snapshot.py: exact release/board
check, fixed seeked regmap reads (no complete PMIC dump), returned-address
validation and MT6359P revision check. No PMIC writes, regulator registration,
firmware activity, power transitions, build or flash.

## Measured register state

Two captures of18 registers are saved in attempt-52/. HWCID=0x5930 selects
the mainline MT6359P descriptors. VCN13, VCN18, VCN33_1 and VCN33_2 control
and enabled-status bits all zero. VCN33 Wi-Fi enable registers also zero.
VCN13 voltage selector4 nominally denotes1.3V, but the rail is off; a selector
is not a measurement. VCN33 selectors15 denote3.5V, also with both rails off.

VS2 is on. Software VOSEL0x30 denotes1.4V; DA_VOSEL low7bits0x2c denotes1.35V.
Do not interpret the difference as a fault or write the status to match the
request: voter/sleep selection must be reviewed. These are nominal selector
conversions, not multimeter measurements. Vendor code uses additional voter,
sleep and VCN13 VOCAL fields beyond regulator_set_voltage semantics.

## Probe side effects and representation

Mainline drivers/regulator/mt6359-regulator.c:mt6359_sync_vcn33_setting reads
both Wi-Fi enable bits. When set, it enables the corresponding BT bit then
clears Wi-Fi's bit before registering regulators. With this snapshot both
iterations skip writes, but that prediction excludes framework constraints
and depends on the live state at probe time. regulator_ignore_unused does
not suppress probe-side synchronization or voltage constraints.

The real shared rails are VCN33_1 and VCN33_2. *_BT/*_WIFI descriptors are
NOOP compatibility wrappers whose supplies are rewritten to the real rail's
registered name; they are not four independent hardware supplies.

Proposed mainline consumer mapping (not yet enabled):

| conninfra supply | Physical regulator | Mainline DT match |
|---|---|---|
|vcn13|VCN13, upstream vs2-ldo2|ldo_vcn13|
|vcn18|VCN18, upstream vs1-ldo2|ldo_vcn18|
|vcn33_1_bt and vcn33_1_wifi|same VCN33_1|ldo_vcn33_1|
|vcn33_2_wifi|VCN33_2|ldo_vcn33_2|

Use explicit supply phandles on the consumer, with actual upstream supply
mapping audited. Do not rely on vendor regulator-name lookup. Current driver
parses a `regulators` child at the PMIC, whereas the ACK DT has
`mt6359regulator`; copying that container verbatim is not a valid adaptation.

The regulator probe loops over all descriptors, even when only a few DT rail
nodes are supplied. Before enabling REGULATOR_MT6359, review unmentioned rails'
constraints and provider registration, keep unused suppression, and capture
state before/after. Do not add always-on or fixed voltage constraints merely
to make probe pass. Do not import conninfra's probe-time VS2 write blindly.

## Power-domain sequence audit refinement

Existing generic BUS_PROT_WR polls for clear acknowledgement. ACK releases
protection without checking clear ACK. Combined with the bank/mask/order
mismatch in attempt51, this adds another reason a table-only transplant is
not yet justified. BUS_PROT_WR_IGN provides a per-entry clear-ACK exception,
but choosing it requires resolving this device's sequence, not guessing.

Next implementation gates: confirm SPM register-write unlock handling;
resolve exact set/clear ordering and bounded failure cleanup; establish a
CONN-only consumer and explicit MT6359P supply graph. Continue these independently
of the NVRAM binary analysis. No successful wireless power-on is claimed.
