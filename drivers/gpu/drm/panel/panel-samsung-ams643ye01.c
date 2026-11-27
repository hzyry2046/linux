// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung AMS643YE01 PVT command-mode AMOLED panel
 *
 * Initialization and power sequencing based on the OP6893 vendor driver.
 * Copyright (c) 2015 MediaTek Inc.
 */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

#include <drm/display/drm_dsc_helper.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_probe_helper.h>

#include <video/mipi_display.h>

/* Enable for the 21651 native display bring-up image only. */
static bool test_signal_read = IS_ENABLED(CONFIG_ARM64_OP6893_21651_NATIVE_DISPLAY);
module_param(test_signal_read, bool, 0644);
MODULE_PARM_DESC(test_signal_read, "Read DCS signal mode once after display on");

struct ams643ye01 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct drm_dsc_config dsc;
	struct regulator *vci;
	struct regulator *vdd;
	struct gpio_desc *reset;
};

static const struct drm_dsc_config ams643ye01_dsc = {
	.dsc_version_major = 1,
	.dsc_version_minor = 1,
	.line_buf_depth = 9,
	.bits_per_component = 8,
	.bits_per_pixel = 8 << 4,
	.block_pred_enable = true,
	.convert_rgb = true,
	.pic_width = 1080,
	.pic_height = 2400,
	.slice_count = 2,
	.slice_width = 540,
	.slice_height = 8,
	.slice_chunk_size = 540,
	.initial_xmit_delay = 512,
	.initial_dec_delay = 526,
	.initial_scale_value = 32,
	.scale_increment_interval = 187,
	.scale_decrement_interval = 7,
	.first_line_bpg_offset = 12,
	.nfl_bpg_offset = 3511,
	.slice_bpg_offset = 3255,
	.initial_offset = 6144,
	.final_offset = 4336,
	.flatness_min_qp = 3,
	.flatness_max_qp = 12,
	.rc_model_size = 8192,
	.rc_edge_factor = 6,
	.rc_quant_incr_limit0 = 11,
	.rc_quant_incr_limit1 = 11,
	.rc_tgt_offset_high = 3,
	.rc_tgt_offset_low = 3,
	.mux_word_size = 48,
	.rc_buf_thresh = { 14, 28, 42, 56, 70, 84, 98, 105, 112, 119, 121, 123, 125, 126 },
	.rc_range_params = {
		{ 0, 4, 2 }, { 0, 4, 0 }, { 1, 5, 0 }, { 1, 6, 62 },
		{ 3, 7, 60 }, { 3, 7, 58 }, { 3, 7, 56 }, { 3, 8, 56 },
		{ 3, 9, 56 }, { 3, 10, 54 }, { 5, 11, 54 }, { 5, 12, 52 },
		{ 5, 13, 52 }, { 7, 13, 52 }, { 13, 15, 52 },
	},
};

static int ams643ye01_init(struct ams643ye01 *ctx)
{
	struct mipi_dsi_multi_context dsi = { .dsi = ctx->dsi };
	struct {
		u8 cmd;
		struct drm_dsc_picture_parameter_set pps;
	} payload = { .cmd = 0x9e };

	/* This panel loads the PPS through its DCS command 0x9e. */
	drm_dsc_pps_payload_pack(&payload.pps, &ctx->dsc);
	mipi_dsi_dcs_write_buffer_multi(&dsi, &payload, sizeof(payload));
	mipi_dsi_generic_write_seq_multi(&dsi, 0xc2, 0x14);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x9d, 0x01);

	mipi_dsi_dcs_exit_sleep_mode_multi(&dsi);
	mipi_dsi_msleep(&dsi, 120);

	/* Mask the panel clock and enable the TE output. */
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0x5a, 0x5a);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xb0, 0x2e, 0xf2);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf2, 0x55);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0xa5, 0xa5);
	mipi_dsi_dcs_set_tear_on_multi(&dsi, MIPI_DSI_DCS_TEAR_MODE_VBLANK);
	mipi_dsi_dcs_set_column_address_multi(&dsi, 0, ctx->dsc.pic_width - 1);
	mipi_dsi_dcs_set_page_address_multi(&dsi, 0, ctx->dsc.pic_height - 1);

	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0x5a, 0x5a);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xb0, 0x27, 0xf2);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf2, 0x00);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0xa5, 0xa5);

	/* Program the vendor's default color calibration. */
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0x5a, 0x5a);
	mipi_dsi_msleep(&dsi, 20);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x72, 0x2c, 0x21, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x5d, 0x46);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf8, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x62, 0x00);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xb0, 0x16, 0x62);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x62, 0xe0, 0x00, 0x00, 0x00,
				     0xff, 0x00, 0x00, 0x00, 0xff, 0x00,
				     0xff, 0xff, 0xff, 0x00, 0xff, 0xff,
				     0xff, 0x00, 0xff, 0xff, 0xff);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x72, 0x2c, 0x01, 0x00);
	mipi_dsi_msleep(&dsi, 17);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0xa5, 0xa5);

	/* Select 60 Hz, normal brightness range and no ACL. */
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0x5a, 0x5a);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x60, 0x00, 0x00);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf7, 0x0f);
	mipi_dsi_generic_write_seq_multi(&dsi, 0xf0, 0xa5, 0xa5);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x53, 0x20);
	mipi_dsi_dcs_write_seq_multi(&dsi, 0x55, 0x00);

	return dsi.accum_err;
}

static int ams643ye01_prepare(struct drm_panel *panel)
{
	struct ams643ye01 *ctx = container_of(panel, struct ams643ye01, panel);
	int ret;

	ret = regulator_set_voltage(ctx->vci, 3000000, 3000000);
	if (ret)
		return ret;

	ret = regulator_enable(ctx->vci);
	if (ret)
		return ret;

	ret = regulator_enable(ctx->vdd);
	if (ret)
		goto disable_vci;

	ret = gpiod_direction_output(ctx->reset, 0);
	if (ret)
		goto disable_vdd;

	usleep_range(10000, 12000);
	gpiod_set_value_cansleep(ctx->reset, 1);
	usleep_range(1000, 2000);
	gpiod_set_value_cansleep(ctx->reset, 0);
	usleep_range(10000, 12000);

	ret = ams643ye01_init(ctx);
	if (!ret)
		return 0;

	gpiod_set_value_cansleep(ctx->reset, 1);
	usleep_range(10000, 12000);
disable_vdd:
	regulator_disable(ctx->vdd);
	usleep_range(7000, 8000);
disable_vci:
	regulator_disable(ctx->vci);
	msleep(110);

	return ret;
}

static int ams643ye01_enable(struct drm_panel *panel)
{
	struct ams643ye01 *ctx = container_of(panel, struct ams643ye01, panel);
	u8 mode = 0;
	int ret;

	ret = mipi_dsi_dcs_set_display_on(ctx->dsi);
	if (ret || !READ_ONCE(test_signal_read))
		return ret;

	ret = mipi_dsi_set_maximum_return_packet_size(ctx->dsi, 1);
	if (!ret)
		ret = mipi_dsi_dcs_read(ctx->dsi, MIPI_DCS_GET_SIGNAL_MODE, &mode,
				       sizeof(mode));
	if (ret != sizeof(mode))
		dev_warn(panel->dev, "Failed to read signal mode after display on: %d\n",
			 ret);
	else
		dev_info(panel->dev, "test signal mode after display on: %02x (%d)\n",
			 mode, ret);

	return 0;
}

static int ams643ye01_disable(struct drm_panel *panel)
{
	struct ams643ye01 *ctx = container_of(panel, struct ams643ye01, panel);
	int ret;

	ret = mipi_dsi_dcs_set_display_off(ctx->dsi);
	usleep_range(10000, 12000);

	if (ret)
		dev_warn(panel->dev, "Failed to turn off display: %d\n", ret);

	return 0;
}

static int ams643ye01_unprepare(struct drm_panel *panel)
{
	struct ams643ye01 *ctx = container_of(panel, struct ams643ye01, panel);
	int ret;

	ret = mipi_dsi_dcs_enter_sleep_mode(ctx->dsi);
	msleep(120);
	gpiod_set_value_cansleep(ctx->reset, 1);
	usleep_range(10000, 12000);
	regulator_disable(ctx->vdd);
	usleep_range(7000, 8000);
	regulator_disable(ctx->vci);
	msleep(110);

	if (ret)
		dev_warn(panel->dev, "Failed to enter sleep mode: %d\n", ret);

	return 0;
}

static const struct drm_display_mode ams643ye01_mode = {
	.clock = 167670,
	.hdisplay = 1080,
	.hsync_start = 1120,
	.hsync_end = 1130,
	.htotal = 1150,
	.vdisplay = 2400,
	.vsync_start = 2420,
	.vsync_end = 2422,
	.vtotal = 2430,
	.width_mm = 67,
	.height_mm = 149,
};

static int ams643ye01_get_modes(struct drm_panel *panel,
			       struct drm_connector *connector)
{
	return drm_connector_helper_get_modes_fixed(connector, &ams643ye01_mode);
}

static const struct drm_panel_funcs ams643ye01_funcs = {
	.prepare = ams643ye01_prepare,
	.enable = ams643ye01_enable,
	.disable = ams643ye01_disable,
	.unprepare = ams643ye01_unprepare,
	.get_modes = ams643ye01_get_modes,
};

static int ams643ye01_bl_update(struct backlight_device *backlight)
{
	struct ams643ye01 *ctx = bl_get_data(backlight);

	if (!ctx->panel.prepared)
		return 0;

	return mipi_dsi_dcs_set_display_brightness_large(ctx->dsi,
							backlight_get_brightness(backlight));
}

static const struct backlight_ops ams643ye01_bl_ops = {
	.update_status = ams643ye01_bl_update,
};

static int ams643ye01_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	const struct backlight_properties props = {
		.type = BACKLIGHT_RAW,
		.brightness = 600,
		.max_brightness = 2047,
	};
	struct ams643ye01 *ctx;
	int ret;

	ctx = devm_drm_panel_alloc(dev, struct ams643ye01, panel,
				   &ams643ye01_funcs, DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);

	ctx->vci = devm_regulator_get_optional(dev, "vci");
	if (IS_ERR(ctx->vci))
		return dev_err_probe(dev, PTR_ERR(ctx->vci), "Failed to get VCI supply\n");

	ctx->vdd = devm_regulator_get_optional(dev, "vdd");
	if (IS_ERR(ctx->vdd))
		return dev_err_probe(dev, PTR_ERR(ctx->vdd), "Failed to get VDD supply\n");

	ctx->reset = devm_gpiod_get(dev, "reset", GPIOD_ASIS);
	if (IS_ERR(ctx->reset))
		return dev_err_probe(dev, PTR_ERR(ctx->reset), "Failed to get reset GPIO\n");

	ctx->dsi = dsi;
	ctx->dsc = ams643ye01_dsc;
	dsi->dsc = &ctx->dsc;
	dsi->lanes = 4;
	dsi->hs_rate = 520000000;
	dsi->format = MIPI_DSI_FMT_RGB888;
	/* Match the vendor's command-mode link configuration. */
	dsi->mode_flags = MIPI_DSI_MODE_LPM | MIPI_DSI_MODE_NO_EOT_PACKET |
			  MIPI_DSI_CLOCK_NON_CONTINUOUS;
	ctx->panel.prepare_prev_first = true;

	ctx->panel.backlight = devm_backlight_device_register(dev, dev_name(dev),
							     dev, ctx, &ams643ye01_bl_ops,
							     &props);
	if (IS_ERR(ctx->panel.backlight))
		return dev_err_probe(dev, PTR_ERR(ctx->panel.backlight),
				     "Failed to register backlight\n");

	ret = devm_drm_panel_add(dev, &ctx->panel);
	if (ret)
		return ret;

	return devm_mipi_dsi_attach(dev, dsi);
}

static const struct of_device_id ams643ye01_of_match[] = {
	{ .compatible = "samsung,ams643ye01-pvt" },
	{ }
};
MODULE_DEVICE_TABLE(of, ams643ye01_of_match);

static struct mipi_dsi_driver ams643ye01_driver = {
	.probe = ams643ye01_probe,
	.driver = {
		.name = "panel-samsung-ams643ye01",
		.of_match_table = ams643ye01_of_match,
	},
};
module_mipi_dsi_driver(ams643ye01_driver);

MODULE_DESCRIPTION("Samsung AMS643YE01 PVT AMOLED panel driver");
MODULE_LICENSE("GPL");
