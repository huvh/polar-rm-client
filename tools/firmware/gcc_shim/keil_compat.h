/* keil_compat.h - AC5/Keil 关键字到 GCC 的适配（仅用于离线语法检查，不进固件仓库） */
#ifndef KEIL_COMPAT_SHIM_H
#define KEIL_COMPAT_SHIM_H
#ifndef __packed
#define __packed __attribute__((packed))
#endif
#ifndef __align
#define __align(x) __attribute__((aligned(x)))
#endif
#ifndef __forceinline
#define __forceinline inline __attribute__((always_inline))
#endif
#endif
