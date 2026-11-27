// SPDX-License-Identifier: GPL-2.0
/*
 * mt6893-mt6359.c -- chopin (MT6893) speaker card.
 *
 * The board has no 3.5mm jack: playback leaves the AP through AFE I2S3 into a
 * pair of CS35L41 Class-D amplifiers on i2c6 (0x40 and 0x42), one per speaker.
 * The MT6359 PMIC codec is only needed for the microphone path and is not
 * wired into the card yet.
 *
 * This is deliberately a small card: one DPCM front end (AFE DL1) and one
 * back end (I2S3 + the two amps).  It is modelled on mt8192's mt6359 card for
 * the MTK plumbing and on mt8189's cs35l41 link for the codec side.
 */

#include <linux/module.h>
#include <linux/of.h>
#include <linux/clk.h>
#include <linux/pm_runtime.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

#include <sound/pcm_params.h>
#include <sound/soc.h>

#include "../../codecs/cs35l41.h"
#include "../common/mtk-soc-card.h"
#include "../common/mtk-afe-platform-driver.h"
#include "../common/mtk-base-afe.h"
#include "../common/mtk-soundcard-driver.h"
#include "mt8192-afe-clk.h"
#include "mt8192-afe-common.h"
#include "mt8192-afe-gpio.h"

#define DRIVER_NAME		"mt6893_mt6359"
#define CARD_NAME		"mt6893_mt6359"
#define CS35L41_CODEC_DAI	"cs35l41-pcm"

/* FE */
SND_SOC_DAILINK_DEFS(playback1,
		     DAILINK_COMP_ARRAY(COMP_CPU("DL1")),
		     DAILINK_COMP_ARRAY(COMP_DUMMY()),
		     DAILINK_COMP_ARRAY(COMP_EMPTY()));

/* BE: the two amps are filled in from the sound node's speaker-codecs child */
SND_SOC_DAILINK_DEFS(i2s3,
		     DAILINK_COMP_ARRAY(COMP_CPU("I2S3")),
		     DAILINK_COMP_ARRAY(COMP_EMPTY()),
		     DAILINK_COMP_ARRAY(COMP_EMPTY()));

static struct device *mt6893_afe_dev;

static struct mtk_base_afe *mt6893_afe_from_rtd(struct snd_soc_pcm_runtime *rtd)
{
	struct snd_soc_component *cmpnt = snd_soc_rtdcom_lookup(rtd, AFE_PCM_NAME);

	return cmpnt ? snd_soc_component_get_drvdata(cmpnt) : NULL;
}

static int mt6893_cs35l41_i2s_hw_free(struct snd_pcm_substream *substream)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	struct mtk_base_afe *afe = mt6893_afe_from_rtd(rtd);

	if (afe)
		mt8192_mck_disable(afe, MT8192_I2S3_MCK);

	if (mt6893_afe_dev) {
		pm_runtime_put_autosuspend(mt6893_afe_dev);
		mt6893_afe_dev = NULL;
	}

	return 0;
}

static int mt6893_cs35l41_i2s_hw_params(struct snd_pcm_substream *substream,
					struct snd_pcm_hw_params *params)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	unsigned int rate = params_rate(params);
	unsigned int mclk_fs = rate * 128;
	struct snd_soc_dai *cpu_dai = snd_soc_rtd_to_cpu(rtd, 0);
	struct snd_soc_dai *codec_dai;
	/*
	 * Match the vendor tune: S32_LE slots, so the bit clock is 64 fs and
	 * the amplifier PLL reference is 2 * rate * 32 = 3.072 MHz at 48 kHz.
	 * That is the exact PLL_CLK_CTRL value (0x430) the stock kernel uses.
	 */
	int clk_freq = rate * 64;
	/*
	 * The amps share one I2S data line: slot 0 carries the right speaker
	 * (amp at 0x40), slot 1 the left one (amp at 0x42).
	 */
	int rx_slot[] = { 0, 1 };
	struct mtk_base_afe *afe;
	int i, ret;

	for_each_rtd_codec_dais(rtd, i, codec_dai) {
		ret = snd_soc_component_set_sysclk(codec_dai->component,
						   CS35L41_CLKID_SCLK, 0,
						   clk_freq, SND_SOC_CLOCK_IN);
		if (ret < 0 && ret != -ENOTSUPP) {
			dev_err(codec_dai->dev,
				"set component sysclk failed: %d\n", ret);
			return ret;
		}

		ret = snd_soc_dai_set_sysclk(codec_dai, CS35L41_CLKID_SCLK,
					     clk_freq, SND_SOC_CLOCK_IN);
		if (ret < 0 && ret != -ENOTSUPP) {
			dev_err(codec_dai->dev, "set sysclk failed: %d\n", ret);
			return ret;
		}

		ret = snd_soc_dai_set_channel_map(codec_dai, 0, NULL,
						  1, &rx_slot[i]);
		if (ret < 0 && ret != -ENOTSUPP) {
			dev_err(codec_dai->dev,
				"set channel map failed: %d\n", ret);
			return ret;
		}
	}

	ret = snd_soc_dai_set_sysclk(cpu_dai, 0, mclk_fs,
				     SND_SOC_CLOCK_OUT);
	if (ret)
		return ret;

	afe = mt6893_afe_from_rtd(rtd);
	if (afe) {
		mt6893_afe_dev = afe->dev;
		pm_runtime_resume_and_get(afe->dev);

		/*
		 * AUDIO_TOP_CON0 bit2 is the aud_afe power-down bit and
		 * AUDIO_TOP_CON1 bit6 the I2S3 block gate, both active low.
		 * The clock framework does not get these enabled on this
		 * board (its writes happen while the shared audsys regmap is
		 * still cache-only), so clear them explicitly.
		 */
		regmap_clear_bits(afe->regmap, 0x0, BIT(2));
		regmap_clear_bits(afe->regmap, 0x4, BIT(6));

		/* Program the I2S3 mclk divider (128 fs). */
		ret = mt8192_mck_enable(afe, MT8192_I2S3_MCK, mclk_fs);
		if (ret)
			dev_warn(rtd->card->dev,
				 "failed to enable I2S3 mclk: %d\n", ret);
	}

	return 0;
}

static const struct snd_soc_ops mt6893_cs35l41_i2s_ops = {
	.hw_params = mt6893_cs35l41_i2s_hw_params,
	.hw_free = mt6893_cs35l41_i2s_hw_free,
};

/*
 * Pin the back end to 16-bit samples: the codec SCLK above is 32 fs, which is
 * exactly two 16-bit slots per frame.  A wider format would make the I2S port
 * run 48/64 fs while the amplifier still expected 32 fs, so normalise the
 * stream here instead of relying on user space.
 */
static int mt6893_i2s_hw_params_fixup(struct snd_soc_pcm_runtime *rtd,
				      struct snd_pcm_hw_params *params)
{
	snd_mask_reset_range(hw_param_mask(params, SNDRV_PCM_HW_PARAM_FORMAT),
			     0, (__force unsigned int)SNDRV_PCM_FORMAT_LAST);
	params_set_format(params, SNDRV_PCM_FORMAT_S32_LE);

	return 0;
}

static struct snd_soc_dai_link mt6893_mt6359_dai_links[] = {
	/* Front end */
	{
		.name = "Playback_1",
		.stream_name = "Playback_1",
		.trigger = { SND_SOC_DPCM_TRIGGER_PRE,
			     SND_SOC_DPCM_TRIGGER_PRE },
		.dynamic = 1,
		.playback_only = 1,
		.ops = &mtk_soundcard_common_playback_ops,
		SND_SOC_DAILINK_REG(playback1),
	},
	/* Back end: AFE I2S3 -> CS35L41 pair */
	{
		.name = "I2S3",
		.dai_fmt = SND_SOC_DAIFMT_I2S | SND_SOC_DAIFMT_CBC_CFC,
		.ops = &mt6893_cs35l41_i2s_ops,
		.be_hw_params_fixup = mt6893_i2s_hw_params_fixup,
		.no_pcm = 1,
		.playback_only = 1,
		.ignore_suspend = 1,
		SND_SOC_DAILINK_REG(i2s3),
	},
};

/*
 * The AFE connection matrix is a DAPM mixer: playback only reaches I2S3 when
 * the "DL1 -> I2S3_CHx" switches are on, and DPCM refuses to open the front
 * end when no backend DAI is reachable ("no backend DAIs enabled").  Android
 * sets these from its audio HAL/UCM profile; there is no UCM here, so do it
 * once when the card is instantiated.
 */
static const char * const mt6893_afe_matrix_switches[] = {
	"I2S3_CH1 DL1_CH1",
	"I2S3_CH2 DL1_CH2",
};

/*
 * The AFE connection-matrix switches are DAPM mixer controls, and those
 * only exist after snd_soc_dapm_new_widgets(), which runs *after* the
 * card's late_probe.  Flip them from a delayed work once the card is
 * registered, otherwise DL1 has no consumer and its memif never starts.
 */
static void mt6893_afe_route_work(struct work_struct *work);
static DECLARE_DELAYED_WORK(mt6893_afe_route_dw, mt6893_afe_route_work);
static struct snd_soc_card *mt6893_afe_route_card;

static void mt6893_afe_route_work(struct work_struct *work)
{
	struct snd_ctl_elem_value ucontrol = {};
	struct snd_kcontrol *kctl;
	int i, ret;

	if (!mt6893_afe_route_card)
		return;

	for (i = 0; i < ARRAY_SIZE(mt6893_afe_matrix_switches); i++) {
		const char *name = mt6893_afe_matrix_switches[i];

		kctl = snd_soc_card_get_kcontrol(mt6893_afe_route_card, name);
		if (!kctl) {
			dev_warn(mt6893_afe_route_card->dev,
				 "AFE route %s not found\n", name);
			continue;
		}

		memset(&ucontrol, 0, sizeof(ucontrol));
		ucontrol.value.integer.value[0] = 1;
		ret = kctl->put(kctl, &ucontrol);
		if (ret < 0)
			dev_err(mt6893_afe_route_card->dev,
				"could not enable AFE route %s: %d\n",
				name, ret);
	}
}

static int mt6893_mt6359_late_probe(struct snd_soc_card *card)
{
	struct snd_ctl_elem_value ucontrol = {};
	struct snd_kcontrol *kctl;


	mt6893_afe_route_card = card;
	schedule_delayed_work(&mt6893_afe_route_dw, msecs_to_jiffies(1000));

	/*
	 * The vendor audio HAL also sets I2S3_HD_Mux to Low_Jitter (HD mode),
	 * which makes the I2S3_HD_EN supply set AFE_I2S_CON3 bit12 for the
	 * 32-bit slot format used above.
	 */
	kctl = snd_soc_card_get_kcontrol(card, "I2S3_HD_Mux");
	if (kctl) {
		memset(&ucontrol, 0, sizeof(ucontrol));
		ucontrol.value.enumerated.item[0] = 1;
		kctl->put(kctl, &ucontrol);
	}

	return 0;
}

static struct snd_soc_card mt6893_mt6359_card = {
	.name = CARD_NAME,
	.owner = THIS_MODULE,
	.dai_link = mt6893_mt6359_dai_links,
	.num_links = ARRAY_SIZE(mt6893_mt6359_dai_links),
	.late_probe = mt6893_mt6359_late_probe,
};

static int mt6893_mt6359_soc_card_probe(struct mtk_soc_card_data *soc_card_data,
					bool legacy)
{
	struct snd_soc_card *card = soc_card_data->card_data->card;
	struct device *dev = card->dev;
	struct device_node *speaker_codec;
	struct snd_soc_dai_link *dai_link;
	int i, ret = 0;

	/*
	 * The legacy path is the normal one here: without "audio-routing"
	 * the common probe does not parse per-link "codec" children, so the
	 * amps are attached through the sound node's speaker-codecs phandles.
	 */
	if (!legacy)
		return 0;

	speaker_codec = of_get_child_by_name(dev->of_node, "speaker-codecs");
	if (!speaker_codec)
		return dev_err_probe(dev, -EINVAL,
				     "speaker-codecs node missing or invalid\n");

	for_each_card_prelinks(card, i, dai_link) {
		if (strcmp(dai_link->name, "I2S3"))
			continue;

		ret = snd_soc_of_get_dai_link_codecs(dev, speaker_codec,
						     dai_link);
		if (ret < 0)
			dev_err_probe(dev, ret, "get speaker codecs failed\n");
		break;
	}

	of_node_put(speaker_codec);

	if (ret)
		return ret;

	/*
	 * Prepare the named audio pin states on the card device so the I2S3_EN
	 * DAPM supply can mux BCLK/LRCK/DATA at every stream start (and undo
	 * it afterwards) instead of relying on the one-shot "default" state.
	 */
	return mt8192_afe_gpio_init(card->dev);
}

static const unsigned int mt6893_pcm_playback_channels[] = { 1, 2 };
static const unsigned int mt6893_pcm_playback_rates[] = { 44100, 48000 };

static const struct mtk_pcm_constraints_data mt6893_pcm_constraints[] = {
	[MTK_CONSTRAINT_PLAYBACK] = {
		.channels = &(const struct snd_pcm_hw_constraint_list) {
			.list = mt6893_pcm_playback_channels,
			.count = ARRAY_SIZE(mt6893_pcm_playback_channels),
		},
		.rates = &(const struct snd_pcm_hw_constraint_list) {
			.list = mt6893_pcm_playback_rates,
			.count = ARRAY_SIZE(mt6893_pcm_playback_rates),
		},
	},
};

static const struct mtk_soundcard_pdata mt6893_mt6359_pdata = {
	.card_name = CARD_NAME,
	.card_data = &(struct mtk_platform_card_data) {
		.card = &mt6893_mt6359_card,
		.num_jacks = 0,
		.pcm_constraints = mt6893_pcm_constraints,
		.num_pcm_constraints = ARRAY_SIZE(mt6893_pcm_constraints),
	},
	.soc_probe = mt6893_mt6359_soc_card_probe,
};

static const struct of_device_id mt6893_mt6359_dt_match[] = {
	{ .compatible = "mediatek,mt6893-mt6359", .data = &mt6893_mt6359_pdata },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, mt6893_mt6359_dt_match);

static struct platform_driver mt6893_mt6359_driver = {
	.probe = mtk_soundcard_common_probe,
	.driver = {
		.name = DRIVER_NAME,
		.of_match_table = mt6893_mt6359_dt_match,
	},
};
module_platform_driver(mt6893_mt6359_driver);

MODULE_DESCRIPTION("MT6893-MT6359/CS35L41 ALSA SoC machine driver");
MODULE_LICENSE("GPL v2");
