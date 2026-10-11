#!/usr/bin/env python3
"""Guard typed referee dispatch after the KM installer has installed HostKmFeed.

Source contract: complete, CRC-validated A5 frames from referee_usart_task.c.
This helper does not replace framing, CRC validation, or board qualification.
"""
from __future__ import annotations
import re

MARK = "POLAR-REFEREE-RX"


def patch_referee_payload_dispatch(text: str, log: list[str]) -> str:
    """Return minimally patched source; reject unsupported dispatch layouts."""
    if MARK in text:
        log.append("  [skip] referee typed payload guards already installed")
        return text
    match = re.search(r"void referee_data_solve\(uint8_t \*\s*frame\)\s*\{.*?\n\}", text, re.S)
    if not match:
        raise RuntimeError("referee_data_solve layout not recognized")
    body = match.group()
    initial = re.compile(r"    if \(HAL_GetTick\(\) - referee_online_time > REFEREE_TIMEOUT\) \{\s*referee_receive_count = 0;\s*\}\s*referee_receive_count\+\+;\s*")
    body, n = initial.subn("    ", body, count=1)
    if n != 1:
        raise RuntimeError("referee counter preamble not recognized")
    header_copy = "    memcpy(&referee_receive_header, frame, sizeof(frame_header_struct_t));"
    if body.count(header_copy) != 1:
        raise RuntimeError("referee header copy not recognized")
    body = body.replace(header_copy, """    /* POLAR-REFEREE-RX: caller has validated the complete frame and CRCs.
     * Reject malformed typed payloads before touching data or freshness. */
    uint16_t payload_length;
    if (frame == 0) return;
    payload_length = (uint16_t)((uint16_t)frame[1] | ((uint16_t)frame[2] << 8));""")
    case_pattern = re.compile(r"(^        case (\w+): \{)(.*?)(^        \} break;)", re.M | re.S)
    fixed = 0
    seen = set()

    def guard(m):
        nonlocal fixed
        opening, command, content, closing = m.groups()
        seen.add(command)
        if command == "ROBOT_CUSTOM_DATA_3_CMD_ID":
            # Keep the existing canonical 26..30-byte validator as the only authority.
            content, count = re.subn(r"HostKmFeed\(frame \+ index,\s*\(uint16_t\)\(\(uint16_t\)frame\[1\] \|\s*\(\(uint16_t\)frame\[2\] << 8\)\)\);",
                                    "if (!HostKmFeed(frame + index, payload_length)) return;", content)
            if count != 1:
                raise RuntimeError("install the acceptance-returning KM HostKmFeed handoff first")
        else:
            copy = re.search(r"memcpy\(&(\w+), frame \+ index, sizeof\((\w+)\)\);", content)
            if not copy:
                raise RuntimeError(f"unrecognized typed copy: {command}")
            destination, type_name = copy.groups()
            if command == "STUDENT_INTERACTIVE_DATA_CMD_ID":
                replacement = f"""if (payload_length < sizeof({type_name}) - sizeof({destination}.user_data) ||
                payload_length > sizeof({type_name})) return;
            /* The six-byte interaction prefix is mandatory; clear unused tail. */
            memset(&{destination}, 0, sizeof({type_name}));
            memcpy(&{destination}, frame + index, payload_length);"""
            else:
                fixed += 1
                replacement = f"if (payload_length != sizeof({type_name})) return;\n            " + copy.group()
            content = content[:copy.start()] + replacement + content[copy.end():]
        content = content.replace("            referee_online_time = HAL_GetTick();\n", "")
        return opening + content + closing

    body = case_pattern.sub(guard, body)
    if not {"STUDENT_INTERACTIVE_DATA_CMD_ID", "ROBOT_CUSTOM_DATA_3_CMD_ID"} <= seen or fixed < 1:
        raise RuntimeError("required referee dispatch cases missing")
    body, n = re.subn(r"        default: \{\s*referee_receive_count--;\s*break;\s*\}",
                      "        default: {\n            return;\n        }", body)
    if n != 1:
        raise RuntimeError("referee default dispatch not recognized")
    body = body[:-2] + """
    /* Commit shared receive metadata only after a recognized payload is accepted. */
    memcpy(&referee_receive_header, frame, sizeof(frame_header_struct_t));
    if ((uint32_t)(HAL_GetTick() - referee_online_time) > REFEREE_TIMEOUT) {
        referee_receive_count = 0;
    }
    referee_receive_count++;
    referee_online_time = HAL_GetTick();
}
"""
    log.append(f"  [ok] referee typed guards: {fixed} fixed, bounded interaction, canonical KM")
    return text[:match.start()] + body + text[match.end():]
