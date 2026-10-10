/* portmacro.h - FreeRTOS RVDS/ARM_CM4F 的 GCC 可解析替身（离线语法检查用） */
#ifndef INC_PORTMACRO_H
#define INC_PORTMACRO_H
#include "projdefs.h"
#define portCHAR char
#define portFLOAT float
#define portDOUBLE double
#define portLONG long
#define portSHORT short
#define portSTACK_TYPE uint32_t
#define portBASE_TYPE long
typedef portSTACK_TYPE StackType_t;
typedef long BaseType_t;
typedef unsigned long UBaseType_t;
typedef uint32_t TickType_t;
#define portMAX_DELAY ( TickType_t ) 0xffffffffUL
#define portTICK_TYPE_IS_ATOMIC 1
#define portSTACK_GROWTH ( -1 )
#define portTICK_PERIOD_MS ( ( TickType_t ) 1000 / configTICK_RATE_HZ )
#define portBYTE_ALIGNMENT 8
#define portSY_FULL_READ_WRITE ( 15 )
#define portNVIC_INT_CTRL_REG ( * ( ( volatile uint32_t * ) 0xe000ed04 ) )
#define portNVIC_PENDSVSET 0x10000000
#define portEND_SWITCHING_ISR( x ) if( x ) portYIELD()
#define portYIELD() portYIELD_INTERNAL()
#define portYIELD_FROM_ISR( x ) if( x ) portYIELD()
#define portYIELD_INTERNAL() __asm__ __volatile__ ( "" )
#define portENABLE_INTERRUPTS() __asm__ __volatile__ ( "" )
#define portDISABLE_INTERRUPTS() __asm__ __volatile__ ( "" )
extern void vPortEnterCritical( void );
extern void vPortExitCritical( void );
#define portENTER_CRITICAL() vPortEnterCritical()
#define portEXIT_CRITICAL() vPortExitCritical()
#define portSET_INTERRUPT_MASK_FROM_ISR() ( portDISABLE_INTERRUPTS(), 0U )
#define portCLEAR_INTERRUPT_MASK_FROM_ISR( x ) portENABLE_INTERRUPTS()
#define portTASK_FUNCTION( vFunction, pvParameters ) void vFunction( void * pvParameters )
#define portTASK_FUNCTION_PROTO( vFunction, pvParameters ) void vFunction( void * pvParameters )
#define portFORCE_INLINE inline __attribute__( ( always_inline ) )
#define portINLINE inline
#define portNOP() __asm__ __volatile__ ( "" )
#define portMemoryBarriers() __asm__ __volatile__ ( "" )
#define portYIELD_WITHIN_API() portYIELD()
#define portUSING_MPU_WRAPPERS 0
#define portTASK_USES_FLOATING_POINT()
#define portCONFIGURE_TIMER_FOR_RUNNER()
#define portGET_RUN_TIME_COUNTER_VALUE() 0
#endif
