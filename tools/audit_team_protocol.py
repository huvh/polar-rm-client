"""Read-only source audit: MCU 0x5A IDs vs ROS2 0x5A IDs are NOT interchangeable.

Does not patch/build/flash firmware, connect serial, or generate field evidence.
Usage: python tools/audit_team_protocol.py --firmware <clone> --ros-driver <clone>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rm_client.backend import polar_link

# The source symbol names, rather than one shared numeric segment namespace,
# identify semantics. Patch-added capabilities are checked separately below.
MCU_SYMBOLS = {
    "IMU_DATA_SEND_ID": "SEG_IMU",
    "ROBOT_STATE_INFO_DATA_SEND_ID": "SEG_ROBOT_STATE_INFO",
    "GAME_STATUS_SEND_ID": "SEG_GAME_STATUS",
    "ALL_ROBOT_HP_SEND_ID": "SEG_ALL_ROBOT_HP",
    "EVENT_DATA_SEND_ID": "SEG_EVENT",
    "REFEREE_WARNING_SEND_ID": "SEG_REFEREE_WARNING",
    "ROBOT_STATUS_SEND_ID": "SEG_ROBOT_STATUS",
    "BUFF_SEND_ID": "SEG_BUFF",
    "SHOOT_DATA_SEND_ID": "SEG_SHOOT_DATA",
    "RFID_STATUS_SEND_ID": "SEG_RFID_STATUS",
    "GROUND_ROBOT_POSITION_SEND_ID": "SEG_GROUND_ROBOT_POSITION",
    "JOINT_STATE_SEND_ID": "SEG_JOINT_STATE",
    "ROBOT_MOTION_DATA_SEND_ID": "SEG_ROBOT_MOTION",
    "ROBOT_CMD_DATA_RECEIVE_ID": "CMD_ROBOT",
    "VIRTUAL_RC_DATA_RECEIVE_ID": "CMD_VIRTUAL_RC",
}
ROS_SEMANTICS = {
    "ID_IMU": "SEG_IMU", "ID_ROBOT_STATE_INFO": "SEG_ROBOT_STATE_INFO",
    "ID_GAME_STATUS": "SEG_GAME_STATUS", "ID_ALL_ROBOT_HP": "SEG_ALL_ROBOT_HP",
    "ID_EVENT_DATA": "SEG_EVENT", "ID_ROBOT_STATUS": "SEG_ROBOT_STATUS",
    "ID_BUFF": "SEG_BUFF", "ID_RFID_STATUS": "SEG_RFID_STATUS",
    "ID_GROUND_ROBOT_POSITION": "SEG_GROUND_ROBOT_POSITION",
    "ID_JOINT_STATE": "SEG_JOINT_STATE", "ID_ROBOT_MOTION": "SEG_ROBOT_MOTION",
}


def commit(repo: Path) -> str:
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"


def inspect_header(repo: Path, relative: str, symbols: dict) -> dict:
    path = repo / relative
    text = path.read_text(encoding="utf-8-sig")
    # Only declarations, never commented-out old IDs.
    clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    checks = []
    for source_symbol, client_symbol in symbols.items():
        match = re.search(r"\b" + re.escape(source_symbol) + r"\b[^\n;]*?\b(0x[0-9a-fA-F]+|\d+)\s*[);]", clean)
        actual = int(match.group(1), 0) if match else None
        expected = getattr(polar_link, client_symbol)
        checks.append({"source_symbol": source_symbol, "client_symbol": client_symbol,
                       "source_id": actual, "client_id": expected, "matches": actual == expected})
    return {"git_commit": commit(repo), "header": relative,
            "header_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "checks": checks, "all_ids_match": all(row["matches"] for row in checks)}


def audit(firmware: Path, ros_driver: Path | None = None) -> dict:
    firmware = Path(firmware).resolve()
    result = {
        "verdict": "NOT READY FOR REAL MATCH",
        "scope": "READ-ONLY source/ID provenance; not layout, flash or field qualification",
        "firmware": inspect_header(firmware, "application/typedef/usb_typdef.h", MCU_SYMBOLS),
        "capabilities": {
            "explicit_spin_and_gimbal_host": (firmware / "application/typedef/host_chassis_bridge.h").is_file(),
            "prm1_customcontrol_km": (firmware / "application/typedef/host_km_link.h").is_file(),
        },
        "required_field_checks": ["flashed firmware hash", "physical RC arbitration",
                                  "command/feedback loop", "loss-of-link zero", "physical E-stop"],
    }
    if ros_driver is not None:
        result["ros_driver"] = inspect_header(Path(ros_driver).resolve(),
            "include/standard_robot_pp_ros2/packet_typedef.hpp", ROS_SEMANTICS)
        result["ros_driver"]["warning"] = (
            "Do not substitute this ID table for the MCU protocol; same SOF does not imply same schema"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--ros-driver", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.firmware, args.ros_driver)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["firmware"]["all_ids_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
