#!/usr/bin/env python3
"""Low-level EMEET PIXY controls for Linux.

This is an independently written implementation of publicly documented and
community-reverse-engineered UVC/HID protocol facts for the EMEET PIXY
(USB 328f:00c0). See CREDITS.md for provenance.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

VENDOR_ID = "328F"
PRODUCT_ID = "00C0"
HID_ID = f"0003:0000{VENDOR_ID}:000000{PRODUCT_ID}"

PAN_MIN = -540000
PAN_MAX = 540000
TILT_MIN = -324000
TILT_MAX = 324000
ZOOM_MIN = 100
ZOOM_MAX = 150
DEGREE_UNIT = 3600
STEP_DEG = 2
STEP = STEP_DEG * DEGREE_UNIT

V4L2_CTL = shutil.which("v4l2-ctl") or "/usr/bin/v4l2-ctl"


class PixyError(RuntimeError):
    """Raised when the PIXY cannot be controlled."""


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _video_candidates() -> Iterable[Path]:
    root = Path("/sys/class/video4linux")
    if not root.exists():
        return []
    return sorted(
        root.glob("video*"),
        key=lambda p: int(p.name.removeprefix("video"))
        if p.name.removeprefix("video").isdigit()
        else 9999,
    )


def find_video_device() -> str | None:
    """Return the physical PIXY video node that exposes PTZ controls."""
    for dev_dir in _video_candidates():
        try:
            name = (dev_dir / "name").read_text().strip().upper()
        except OSError:
            continue
        if "EMEET" not in name or "PIXY" not in name or "VIRTUAL" in name:
            continue
        device = f"/dev/{dev_dir.name}"
        try:
            result = subprocess.run(
                [V4L2_CTL, "-d", device, "-l"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if "pan_absolute" in result.stdout and "tilt_absolute" in result.stdout:
            return device
    return None


def find_hidraw_device() -> str | None:
    """Return the PIXY HID node by exact USB HID identity."""
    root = Path("/sys/class/hidraw")
    if not root.exists():
        return None
    for dev_dir in sorted(root.glob("hidraw*")):
        uevent = dev_dir / "device/uevent"
        try:
            text = uevent.read_text().upper()
        except OSError:
            continue
        if HID_ID in text or (
            "HID_NAME=EMEET EMEET PIXY" in text
            and VENDOR_ID in text
            and PRODUCT_ID in text
        ):
            return f"/dev/{dev_dir.name}"
    return None


def get_control(device: str, control: str) -> int:
    result = subprocess.run(
        [V4L2_CTL, "-d", device, f"--get-ctrl={control}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PixyError(result.stderr.strip() or f"Unable to read {control}")
    if ":" not in result.stdout:
        raise PixyError(f"Unexpected v4l2-ctl output for {control}")
    return int(result.stdout.split(":", 1)[1].strip())


def set_control(device: str, control: str, value: int) -> None:
    result = subprocess.run(
        [V4L2_CTL, "-d", device, f"--set-ctrl={control}={value}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PixyError(result.stderr.strip() or f"Unable to set {control}")


def build_hid_report(payload: Iterable[int]) -> bytes:
    data = bytes(payload)
    if len(data) > 32:
        raise PixyError("HID report is longer than 32 bytes")
    return data + bytes(32 - len(data))


def send_hid_report(device: str, payload: Iterable[int]) -> None:
    report = build_hid_report(payload)
    try:
        with open(device, "wb", buffering=0) as hid:
            hid.write(report)
    except PermissionError as exc:
        raise PixyError(
            f"Permission denied writing to {device}. Install the supplied udev rule."
        ) from exc
    except OSError as exc:
        raise PixyError(f"Unable to write to {device}: {exc}") from exc


def set_tracking(device: str, mode: int) -> None:
    if mode not in (0x00, 0x01, 0x02):
        raise PixyError("Invalid tracking mode")
    send_hid_report(device, [0x09, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, mode])
    time.sleep(0.2)
    send_hid_report(device, [0x09, 0x01, 0x01, 0x01])


def set_gesture(device: str, enabled: bool) -> None:
    value = 0x01 if enabled else 0x00
    send_hid_report(
        device,
        [0x09, 0x04, 0x02, 0x00, 0x00, 0x02, 0x00, 0x02, 0x02, value],
    )
    time.sleep(0.2)
    send_hid_report(device, [0x09, 0x04, 0x02, 0x01, 0x00, 0x01, 0x00, 0x01, 0x02])


def set_audio_mode(device: str, mode: int) -> None:
    if mode not in (0x01, 0x02, 0x03):
        raise PixyError("Invalid audio mode")
    send_hid_report(device, [0x09, 0x05, 0x00, 0x03, 0x00, 0x01, 0x00, 0x01, mode])
    time.sleep(0.2)
    send_hid_report(device, [0x09, 0x05, 0x00, 0x04])


def set_auto_privacy(device: str, seconds: int) -> None:
    seconds = clamp(seconds, 0, 255)
    send_hid_report(
        device,
        [0x09, 0x02, 0x01, 0x00, 0x00, 0x04, 0x00, 0x04, seconds],
    )
    time.sleep(0.2)
    send_hid_report(device, [0x09, 0x02, 0x01, 0x01])


def status_text(video_device: str) -> str:
    pan = get_control(video_device, "pan_absolute")
    tilt = get_control(video_device, "tilt_absolute")
    zoom = get_control(video_device, "zoom_absolute")
    return (
        f"Device: {video_device}\n"
        f"pan:  {pan // DEGREE_UNIT} deg\n"
        f"tilt: {tilt // DEGREE_UNIT} deg\n"
        f"zoom: {zoom}"
    )


def execute(command: str, value: str | None = None) -> str:
    video_commands = {
        "left", "right", "up", "down", "zoom-in", "zoom-out",
        "center", "pan", "tilt", "zoom", "status", "flicker",
    }
    hid_commands = {
        "idle", "track", "privacy", "gesture-on", "gesture-off",
        "audio", "auto-privacy",
    }

    video = find_video_device() if command in video_commands else None
    hid = find_hidraw_device() if command in hid_commands else None

    if command in video_commands and not video:
        raise PixyError("EMEET PIXY video device not found")
    if command in hid_commands and not hid:
        raise PixyError("EMEET PIXY HID device not found")

    if command == "idle":
        set_tracking(hid, 0x00)
        return "Tracking OFF (idle)"
    if command == "track":
        set_tracking(hid, 0x01)
        return "Tracking ON"
    if command == "privacy":
        set_tracking(hid, 0x02)
        return "Privacy mode ON"
    if command == "gesture-on":
        set_gesture(hid, True)
        return "Gesture control ON"
    if command == "gesture-off":
        set_gesture(hid, False)
        return "Gesture control OFF"
    if command == "audio":
        if value not in {"nc", "live", "org"}:
            raise PixyError("Usage: audio nc|live|org")
        modes = {"nc": 0x01, "live": 0x02, "org": 0x03}
        set_audio_mode(hid, modes[value])
        return f"Audio: {value.upper()} mode"
    if command == "auto-privacy":
        seconds = int(value) if value is not None else 10
        set_auto_privacy(hid, seconds)
        return "Auto-privacy OFF" if seconds == 0 else f"Auto-privacy ON ({seconds}s)"
    if command == "flicker":
        if value not in {"off", "50", "60"}:
            raise PixyError("Usage: flicker off|50|60")
        values = {"off": 0, "50": 1, "60": 2}
        set_control(video, "power_line_frequency", values[value])
        return f"Anti-flicker: {value}"
    if command == "left":
        cur = get_control(video, "pan_absolute")
        set_control(video, "pan_absolute", clamp(cur - STEP, PAN_MIN, PAN_MAX))
        return ""
    if command == "right":
        cur = get_control(video, "pan_absolute")
        set_control(video, "pan_absolute", clamp(cur + STEP, PAN_MIN, PAN_MAX))
        return ""
    if command == "up":
        cur = get_control(video, "tilt_absolute")
        set_control(video, "tilt_absolute", clamp(cur + STEP, TILT_MIN, TILT_MAX))
        return ""
    if command == "down":
        cur = get_control(video, "tilt_absolute")
        set_control(video, "tilt_absolute", clamp(cur - STEP, TILT_MIN, TILT_MAX))
        return ""
    if command == "zoom-in":
        cur = get_control(video, "zoom_absolute")
        set_control(video, "zoom_absolute", clamp(cur + 10, ZOOM_MIN, ZOOM_MAX))
        return ""
    if command == "zoom-out":
        cur = get_control(video, "zoom_absolute")
        set_control(video, "zoom_absolute", clamp(cur - 10, ZOOM_MIN, ZOOM_MAX))
        return ""
    if command == "center":
        set_control(video, "pan_absolute", 0)
        set_control(video, "tilt_absolute", 0)
        set_control(video, "zoom_absolute", ZOOM_MIN)
        return "Centered"
    if command == "pan":
        degrees = int(value or 0)
        set_control(video, "pan_absolute", clamp(degrees * DEGREE_UNIT, PAN_MIN, PAN_MAX))
        return ""
    if command == "tilt":
        degrees = int(value or 0)
        set_control(video, "tilt_absolute", clamp(degrees * DEGREE_UNIT, TILT_MIN, TILT_MAX))
        return ""
    if command == "zoom":
        zoom = int(value or ZOOM_MIN)
        set_control(video, "zoom_absolute", clamp(zoom, ZOOM_MIN, ZOOM_MAX))
        return ""
    if command == "status":
        return status_text(video)

    raise PixyError(f"Unknown command: {command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EMEET PIXY Linux control backend")
    parser.add_argument(
        "command",
        choices=[
            "left", "right", "up", "down", "zoom-in", "zoom-out",
            "center", "pan", "tilt", "zoom", "status", "idle", "track",
            "privacy", "gesture-on", "gesture-off", "audio", "auto-privacy",
            "flicker",
        ],
    )
    parser.add_argument("value", nargs="?")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = execute(args.command, args.value)
    except (PixyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
