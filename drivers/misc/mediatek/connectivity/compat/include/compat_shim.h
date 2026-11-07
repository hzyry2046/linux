/* SPDX-License-Identifier: GPL-2.0 */
/*
 * 7.3 API drift shims for the vendor connectivity stack.
 * Semantics notes: strncpy->strscpy (terminates, no NUL padding),
 * get_random_int->get_random_u32, alarm_start_relative->
 * alarm_start_timer(relative=true) introduced in 6.19.
 */
#ifndef _CONNPORT_COMPAT_SHIM_H_
#define _CONNPORT_COMPAT_SHIM_H_

#include <linux/string.h>
#include <linux/random.h>
#include <linux/alarmtimer.h>
#include <linux/rtc.h>

static inline char *compat_strncpy(char *d, const char *s, unsigned long n)
{
	strscpy(d, s, n);
	return d;
}
#define strncpy compat_strncpy
static inline void compat_rtc_time64_to_tm(time64_t time, struct rtc_time *tm)
{
	/* RTC_LIB is a promptless bool in 7.3; log timestamps only. */
	u64 days = div_u64(time, 86400);
	unsigned int secs = div_u64_rem(time, 86400, NULL);

	memset(tm, 0, sizeof(*tm));
	tm->tm_sec = secs % 60; secs /= 60;
	tm->tm_min = secs % 60; tm->tm_hour = secs / 60;
	tm->tm_mday = 1;
	tm->tm_year = 70;
	tm->tm_wday = (days + 4) % 7;
	tm->tm_yday = days % 365;
}
#define rtc_time64_to_tm compat_rtc_time64_to_tm
#define get_random_int() get_random_u32()
#define alarm_start_relative(a, kt) alarm_start_timer(a, kt, true)

#endif /* _CONNPORT_COMPAT_SHIM_H_ */
