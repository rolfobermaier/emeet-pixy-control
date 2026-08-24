# Credits and provenance

## EMEET PIXY HID protocol

The PIXY exposes standard UVC controls for PTZ/zoom and a proprietary HID interface for tracking/privacy, gesture control, and audio modes.

The HID command families used by this project were documented through community reverse engineering, including:

- rm1138 — `cam_ptz.sh`: https://gist.github.com/rm1138/ef132c3a39f3c1effabf6354e2eca965
- branzo — fork/continued notes: https://gist.github.com/branzo/de238cfe001fa4a834ca21ac43dca580
- LarsArtmann — `emeet-pixyd`: https://github.com/LarsArtmann/emeet-pixyd
- Romonaga — `PixyPilot`: https://github.com/Romonaga/PixyPilot

The backend in this repository is an independently written implementation based on those publicly documented protocol facts and local testing. It does not copy the shell implementation from the gists.

## Application icon

The application icon was derived from the **Camera** vector distributed by SVG Repo under CC0 and then modified for PTZ use.

Source: https://www.svgrepo.com/svg/450023/camera

SVG Repo lists that source vector under the CC0 License. Attribution is not required by CC0, but provenance is recorded here for clarity.

## Trademarks

EMEET and PIXY are trademarks of their respective owner. This project is unofficial and is not affiliated with or endorsed by EMEET.
