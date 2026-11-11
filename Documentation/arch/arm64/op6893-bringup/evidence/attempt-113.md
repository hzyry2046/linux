# attempt113：FT3518 触摸屏

镜像 `3f15e3889fbd`，提交 `a6a51544b`。

- 本机（项目号 20615）触摸芯片为 Focaltech FT3518（4.19 `touch.c`、`oplus6893_common.dtsi`）：
  i2c0 `0x11015000`，地址 0x38，INT GPIO21，RST GPIO20。
- 供电不是 MT6359 VTP，而是 MT6360 LDO2（I2C5，0x64，带 CRC8），与 Mu-Silicium 一致。
  LK 交接时 LDO2 关闭（reg 0x11 = 0x80），GPIO20 为低，i2c0 上无任何应答。
- 用户态手工写 LDO2（0x15=0xAA，0x11 bit6）后芯片应答，chip id 0x54。之后改为主线
  `mt6360` MFD + `mt6360-regulator`，作为 `vcc-supply`，开机自动上电并 probe。
- 400 kHz 时约 1–2% 读取出现字节重复/错位（如 `01 a2 a2 1b 04 04`），导致 evtest
  出现越界坐标；提高引脚驱动强度无效。改为 100 kHz 后 15 秒滑动/点按共 123 帧，
  X 175–906、Y 348–2088，无越界。根因（i2c_ck 实际频率或时序）未确认。
- Mu 的触摸驱动有状态识别问题（用户提示），只参考了其上电与寄存器信息，没有参考状态处理。

工具：`mt6893-direct/tools/{mt6360-ldo.c,i2c-rd.c}`。
