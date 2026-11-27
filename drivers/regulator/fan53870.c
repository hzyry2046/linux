// SPDX-License-Identifier: GPL-2.0-only
#include <linux/bits.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>

#define FAN53870_PRODUCT_ID	0x00
#define FAN53870_ENABLE		0x03
#define FAN53870_LDO3_VOUT	0x06
#define FAN53870_LDO34_SEQ	0x0c

static const struct linear_range fan53870_ldo3_ranges[] = {
	REGULATOR_LINEAR_RANGE(2800000, 0, 0, 0),
	REGULATOR_LINEAR_RANGE(1500000, 0x10, 0xff, 8000),
};

static int fan53870_ldo3_enable(struct regulator_dev *rdev)
{
	int ret;

	/* Select immediate enable for LDO3; leave LDO4's slot unchanged. */
	ret = regmap_clear_bits(rdev_get_regmap(rdev), FAN53870_LDO34_SEQ,
				GENMASK(2, 0));
	if (ret)
		return ret;

	return regulator_enable_regmap(rdev);
}

static const struct regulator_ops fan53870_ldo3_ops = {
	.list_voltage = regulator_list_voltage_linear_range,
	.map_voltage = regulator_map_voltage_linear_range,
	.set_voltage_sel = regulator_set_voltage_sel_regmap,
	.get_voltage_sel = regulator_get_voltage_sel_regmap,
	.enable = fan53870_ldo3_enable,
	.disable = regulator_disable_regmap,
	.is_enabled = regulator_is_enabled_regmap,
};

static const struct regulator_desc fan53870_ldo3_desc = {
	.name = "LDO3",
	.of_match = "LDO3",
	.regulators_node = "regulators",
	.type = REGULATOR_VOLTAGE,
	.owner = THIS_MODULE,
	.ops = &fan53870_ldo3_ops,
	.linear_ranges = fan53870_ldo3_ranges,
	.n_linear_ranges = ARRAY_SIZE(fan53870_ldo3_ranges),
	.n_voltages = 256,
	.vsel_reg = FAN53870_LDO3_VOUT,
	.vsel_mask = GENMASK(7, 0),
	.enable_reg = FAN53870_ENABLE,
	.enable_mask = BIT(2),
	.supply_name = "vin34",
};

static const struct regmap_config fan53870_regmap = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = FAN53870_LDO34_SEQ,
};

static int fan53870_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct regulator_config config = { .dev = dev };
	struct regulator_dev *rdev;
	unsigned int id;
	int ret;

	config.regmap = devm_regmap_init_i2c(client, &fan53870_regmap);
	if (IS_ERR(config.regmap))
		return PTR_ERR(config.regmap);

	ret = regmap_read(config.regmap, FAN53870_PRODUCT_ID, &id);
	if (ret)
		return dev_err_probe(dev, ret, "Failed to read product ID\n");

	if (id != 1)
		return dev_err_probe(dev, -ENODEV, "Unexpected product ID %#x\n", id);

	rdev = devm_regulator_register(dev, &fan53870_ldo3_desc, &config);
	if (IS_ERR(rdev))
		return dev_err_probe(dev, PTR_ERR(rdev), "Failed to register LDO3\n");

	return 0;
}

static const struct of_device_id fan53870_of_match[] = {
	{ .compatible = "onnn,fan53870" },
	{ }
};
MODULE_DEVICE_TABLE(of, fan53870_of_match);

static struct i2c_driver fan53870_driver = {
	.driver = {
		.name = "fan53870",
		.of_match_table = fan53870_of_match,
	},
	.probe = fan53870_probe,
};
module_i2c_driver(fan53870_driver);

MODULE_DESCRIPTION("FAN53870 LDO3 regulator");
MODULE_LICENSE("GPL");
