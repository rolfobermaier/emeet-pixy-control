# Pre-publish test checklist

Run this on the same Linux machine where the PIXY is already working.

## 1. Keep your current install intact

Do **not** delete `~/emeet-pixy-control` yet. The GitHub package installs into `~/.local/share/emeet-pixy-control`, so it can be tested separately.

## 2. Smoke-test the GitHub code without installing it

Your existing CachyOS setup already has the needed runtime dependencies. From the extracted repository folder:

```bash
PYTHONPATH=src python -m emeet_pixy_control
```

This runs the GitHub version directly and does not replace your current launcher, service, udev rule, or `~/emeet-pixy-control` folder.

Verify the GUI behaves normally, then close it.

## 3. Install prerequisites (for a clean machine)

On CachyOS/Arch:

```bash
sudo pacman -S --needed python python-pip v4l-utils ffmpeg v4l2loopback-utils
```

## 4. Test the installer

Only after the source smoke test passes:

```bash
./install.sh
```

Then launch **EMEET PIXY Control** from the application menu.

Verify:

- live preview appears;
- arrows move the camera;
- Center works;
- resolution menu populates;
- tracking on/off works;
- privacy works;
- gesture on/off works;
- audio mode applies;
- anti-flicker applies;
- settings survive closing/reopening.

## 5. Test Release Preview

1. Click **Release Preview**.
2. Open Google Meet or OBS.
3. Select the physical **EMEET PIXY**.
4. Verify video works.
5. Verify PTZ arrows still work from EMEET PIXY Control.
6. Close Meet/OBS.
7. Click **Resume Preview**.

## 6. Test persistent virtual camera

```bash
systemctl status emeet-pixy-virtual-camera.service --no-pager
v4l2-ctl --list-devices
```

Verify a device named **EMEET PIXY Virtual Camera** exists.

## 7. Test Virtual Camera mode

1. In EMEET PIXY Control, choose a known-good resolution such as `1280x720`.
2. Click **Virtual Camera → Start**.
3. Open Google Meet or OBS.
4. Select **EMEET PIXY Virtual Camera**.
5. Verify video and PTZ controls.
6. Stop the virtual camera in the GUI.
7. Verify the normal preview returns.

## 8. Reboot test

Reboot once, then run:

```bash
systemctl status emeet-pixy-virtual-camera.service --no-pager
v4l2-ctl --list-devices
```

Verify the virtual camera device was recreated automatically.

## 9. Uninstall test (optional, after everything else passes)

```bash
./uninstall.sh
```

Reinstall with `./install.sh` afterward if desired.
