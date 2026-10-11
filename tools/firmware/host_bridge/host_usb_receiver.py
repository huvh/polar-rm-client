"""Generate a bounded CDC callback queue and task-side 0x5A stream receiver.

The reference USB_Receive wrapper only rearms CDC; it never returns received bytes.
Only the real CDC callback's Buf/Len pair is ingress. No hardware binding changes.
"""
from __future__ import annotations
import re

QUEUE = r'''
/* ==== POLAR-HOST-USB: actual CDC ingress queue ==== */
#define HOST_USB_QUEUE_SIZE 512U
#define HOST_USB_PARTIAL_MS 150U
static uint8_t host_usb_queue[HOST_USB_QUEUE_SIZE];
static uint32_t host_usb_queue_time[HOST_USB_QUEUE_SIZE];
static uint16_t host_usb_head, host_usb_tail, host_usb_count;
static uint32_t host_usb_epoch;
volatile uint32_t HOST_USB_RX_OVERFLOW;
#if defined(HOST_USB_CRITICAL_ENTER) != defined(HOST_USB_CRITICAL_EXIT)
#error "Override both HOST_USB_CRITICAL_ENTER and HOST_USB_CRITICAL_EXIT"
#endif
#ifndef HOST_USB_CRITICAL_ENTER
#if defined(__arm__) || defined(__thumb__) || defined(__ARMCC_VERSION)
static uint32_t HostUsbCriticalEnter(void)
{
    uint32_t saved = __get_PRIMASK();
    __disable_irq();
    return saved;
}
#define HOST_USB_CRITICAL_ENTER() HostUsbCriticalEnter()
#define HOST_USB_CRITICAL_EXIT(saved) __set_PRIMASK(saved)
#else
#error "Define HOST_USB_CRITICAL_ENTER/EXIT for this platform"
#endif
#endif

/* Both typed schemas use packed IEEE-754 binary32 fields. Inspect bits via memcpy
 * to avoid unaligned float loads and math-library/compiler-mode differences. */
static uint8_t HostUsbFiniteFields(const uint8_t *raw, uint16_t count)
{
    uint16_t i;
    uint32_t bits;
    for (i = 0; i < count; i++) {
        memcpy(&bits, raw + 4U * i, sizeof(bits));
        if ((bits & 0x7F800000U) == 0x7F800000U) return 0;
    }
    return 1;
}

/* CDC session changes invalidate ingress without resetting the timestamp replay
 * barrier or commanding actuators. Existing control timeouts still apply. */
void HostUsbRxReset(void)
{
    uint32_t saved = HOST_USB_CRITICAL_ENTER();
    host_usb_head = host_usb_tail = host_usb_count = 0;
    host_usb_epoch++;
    HOST_USB_CRITICAL_EXIT(saved);
}

/* Only the CDC OUT callback may produce; task parsing never runs in the ISR. */
void HostUsbRxPush(const uint8_t *bytes, uint32_t len)
{
    uint32_t saved, i, received_at;
    if (bytes == 0 || len == 0U) return;
    saved = HOST_USB_CRITICAL_ENTER();
    if (len > HOST_USB_QUEUE_SIZE - host_usb_count) {
        /* Drop the entire overflowing chunk and queued prefix. The epoch also
         * invalidates any partial frame already held by the task. */
        host_usb_head = host_usb_tail = host_usb_count = 0;
        host_usb_epoch++;
        HOST_USB_RX_OVERFLOW++;
        HOST_USB_CRITICAL_EXIT(saved);
        return;
    }
    received_at = HAL_GetTick();
    for (i = 0; i < len; i++) {
        host_usb_queue[host_usb_head] = bytes[i];
        host_usb_queue_time[host_usb_head] = received_at;
        host_usb_head = (uint16_t)((host_usb_head + 1U) % HOST_USB_QUEUE_SIZE);
    }
    host_usb_count = (uint16_t)(host_usb_count + len);
    HOST_USB_CRITICAL_EXIT(saved);
}
/* ==== POLAR-HOST-USB ingress end ==== */
'''

PARSER = r'''static void UsbReceiveData(void)
{
    /* POLAR-HOST-USB: bounded stream parser; no USB_Receive polling. */
    static uint8_t frame[261]; /* uint8 wire length + header4 + CRC16 */
    static uint16_t fill;
    static uint32_t parse_epoch, previous_byte_time, frame_started_at;
    uint32_t budget = USB_RECEIVE_LEN;
    uint32_t saved, epoch, received_at, timestamp;
    uint16_t total;
    uint8_t byte, data_id, accepted;
    uint8_t *sof_address = frame;
    while (budget-- != 0U) {
        saved = HOST_USB_CRITICAL_ENTER();
        if (host_usb_count == 0U) {
            HOST_USB_CRITICAL_EXIT(saved);
            break;
        }
        byte = host_usb_queue[host_usb_tail];
        received_at = host_usb_queue_time[host_usb_tail];
        host_usb_tail = (uint16_t)((host_usb_tail + 1U) % HOST_USB_QUEUE_SIZE);
        host_usb_count--;
        epoch = host_usb_epoch;
        HOST_USB_CRITICAL_EXIT(saved);
        if (parse_epoch != epoch || (fill != 0U &&
            (uint32_t)(received_at - previous_byte_time) > HOST_USB_PARTIAL_MS)) fill = 0;
        parse_epoch = epoch;
        previous_byte_time = received_at;
        if ((uint32_t)(HAL_GetTick() - received_at) > HOST_USB_PARTIAL_MS) {
            fill = 0;
            continue; /* Old queued bytes must not become a fresh control. */
        }
        if (fill != 0U && (uint32_t)(received_at - frame_started_at) > HOST_USB_PARTIAL_MS) fill = 0;
        if (fill == 0U) frame_started_at = received_at;
        frame[fill++] = byte;
        while (fill != 0U) {
            if (frame[0] != RECEIVE_SOF) goto host_usb_discard;
            if (fill < 4U) break;
            if (!verify_CRC8_check_sum(frame, 4U)) goto host_usb_discard;
            total = (uint16_t)((uint16_t)frame[1] + 6U);
            if (fill < total) break;
            if (!verify_CRC16_check_sum(frame, total)) goto host_usb_discard;
            data_id = frame[2];
            accepted = 0;
            /* Overflow between dequeue and dispatch invalidates the candidate.
             * Publish mailboxes and their timestamps together before unmasking. */
            saved = HOST_USB_CRITICAL_ENTER();
            timestamp = 0;
            if (total >= 10U) memcpy(&timestamp, &frame[4], sizeof(timestamp));
            /* Preserve the protocol's strict monotonic timestamp contract: replay,
             * duplicate, initial zero and rollover all fail closed. */
            if (epoch == host_usb_epoch && timestamp > LATEST_RX_TIMESTAMP &&
                (uint32_t)(HAL_GetTick() - received_at) <= HOST_USB_PARTIAL_MS &&
                (uint32_t)(HAL_GetTick() - frame_started_at) <= HOST_USB_PARTIAL_MS) {
@@DISPATCH@@
                if (accepted) {
                    LATEST_RX_TIMESTAMP = timestamp;
                    RECEIVE_TIME = received_at;
                }
            }
            HOST_USB_CRITICAL_EXIT(saved);
            fill = (uint16_t)(fill - total);
            memmove(frame, frame + total, fill);
            continue;
        host_usb_discard:
            fill--;
            memmove(frame, frame + 1, fill);
        }
    }
}
'''


def balanced(text: str, start: int) -> int:
    """Find the matching C brace in these known generated/reference functions."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0: return i + 1
    raise RuntimeError('Unbalanced receiver function')


def patch_usb_task(text: str) -> str:
    # Preserve the installed switch, including the team's per-kind timestamp hooks.
    m = re.search(r'static void UsbReceiveData\(void\)\s*\n\{', text)
    if not m: raise RuntimeError('UsbReceiveData definition not found')
    end = balanced(text, text.index('{', m.start()))
    body = text[m.start():end]
    switch = re.search(r'switch\s*\(data_id\)\s*\{', body)
    if not switch: raise RuntimeError('USB dispatch switch not found')
    dispatch = body[switch.start():balanced(body, body.index('{', switch.start()))]
    sizes = {'ROBOT_CMD_DATA_RECEIVE_ID': 'ReceiveDataRobotCmd_s',
             'PID_DEBUG_DATA_RECEIVE_ID': 'ReceiveDataPidDebug_s',
             'VIRTUAL_RC_DATA_RECEIVE_ID': 'ReceiveDataVirtualRc_s',
             'CHASSIS_CMD_DATA_RECEIVE_ID': 'ReceiveDataChassisCmd_s'}
    for ident, typ in sizes.items():
        anchor = re.search(r'case\s+' + ident + r'\s*:\s*\{[^\n]*\n', dispatch)
        if not anchor: raise RuntimeError(f'USB dispatch missing {ident}')
        guard = f'                        if (total != sizeof({typ})) break; /* POLAR-HOST-USB typed size */\n'
        if guard.strip() not in dispatch:
            dispatch = dispatch[:anchor.end()] + guard + dispatch[anchor.end():]
        finite_count = {'ROBOT_CMD_DATA_RECEIVE_ID': 9, 'PID_DEBUG_DATA_RECEIVE_ID': 5}.get(ident)
        if finite_count:
            finite = f'                        if (!HostUsbFiniteFields(sof_address + 8U, {finite_count}U)) break; /* POLAR-HOST-USB finite */\n'
            if finite.strip() not in dispatch:
                dispatch = dispatch.replace(guard, guard + finite, 1)
        # Mark acceptance only after the copy and all semantic checks. Never mark
        # it at case entry, where an internal break may reject reserved bits.
        anchor = re.search(r'case\s+' + ident + r'\s*:\s*\{', dispatch)
        close = balanced(dispatch, dispatch.index('{', anchor.start())) - 1
        if 'accepted = 1;' not in dispatch[anchor.start():close]:
            dispatch = dispatch[:close] + '    accepted = 1;\n                    ' + dispatch[close:]
    dispatch = dispatch.replace('= HAL_GetTick();', '= received_at;')
    text = text[:m.start()] + PARSER.replace('@@DISPATCH@@', dispatch).rstrip() + text[end:]
    text = re.sub(r'\n?/\* ==== POLAR-HOST-USB: actual CDC ingress queue ====[\s\S]*?'
                  r'/\* ==== POLAR-HOST-USB ingress end ==== \*/\n\n?', '', text)
    # Before the function, after all type definitions and mailbox declarations.
    pos = text.index('static void UsbReceiveData(void)\n{')
    text = text[:pos] + QUEUE + '\n' + text[pos:]
    # The obsolete polling buffer must not consume memory or warn as unused.
    text = re.sub(r'^static uint8_t USB_RX_BUF\[USB_RX_DATA_SIZE\];\n', '', text, flags=re.M)
    return text


def patch_cdc(text: str) -> str:
    declaration = ('/* POLAR-HOST-USB: task-owned bounded ingress, called only on delivered OUT bytes. */\n'
                   'extern void HostUsbRxPush(const uint8_t *bytes, uint32_t len);\n')
    if declaration not in text:
        anchor = '/* USER CODE BEGIN INCLUDE */\n'
        if anchor not in text: raise RuntimeError('CDC include anchor not found')
        text = text.replace(anchor, anchor + declaration, 1)
    reset_decl = 'extern void HostUsbRxReset(void);\n'
    if reset_decl not in text:
        text = text.replace(declaration, declaration + reset_decl, 1)
    for block in (3, 4):
        anchor = f'  /* USER CODE BEGIN {block} */\n'
        reset = anchor + '  HostUsbRxReset(); /* POLAR-HOST-USB: invalidate previous session ingress */\n'
        if reset not in text:
            if anchor not in text: raise RuntimeError('CDC session reset anchor not found')
            text = text.replace(anchor, reset, 1)
    m = re.search(r'static int8_t CDC_Receive_FS\(uint8_t\* Buf, uint32_t \*Len\)\s*\n\{', text)
    if not m: raise RuntimeError('Actual CDC receive callback not found')
    end = balanced(text, text.index('{', m.start()))
    body = text[m.start():end]
    if 'HostUsbRxPush(Buf, *Len);' not in body:
        anchor = '  /* USER CODE BEGIN 6 */\n'
        if anchor not in body: raise RuntimeError('CDC callback ingress anchor not found')
        body = body.replace(anchor, anchor + '  if (Len != 0) HostUsbRxPush(Buf, *Len); /* POLAR-HOST-USB */\n', 1)
        text = text[:m.start()] + body + text[end:]
    return text
