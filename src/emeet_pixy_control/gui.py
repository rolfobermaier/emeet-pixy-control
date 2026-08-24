#!/usr/bin/env python3

import sys
import subprocess
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer, QProcess
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSlider, QVBoxLayout, QWidget,
    QScrollArea, QSplitter, QFrame
)

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND = PACKAGE_DIR / "backend.py"
ICON = PACKAGE_DIR / "assets" / "emeet-pixy-control.svg"
FFMPEG = shutil.which("ffmpeg")
V4L2_CTL = shutil.which("v4l2-ctl")


class PixyGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = QSettings("emeet-pixy", "control")
        self.camera = None
        self.capture_session = None
        self.restoring = False
        self.preview_released = False

        self.virtual_process = None
        self.virtual_active = False
        self.virtual_stopping = False
        self.preview_before_virtual = True

        # Resolution selector data:
        # { "3840x2160": QCameraFormat, ... }
        self.camera_formats = {}

        self.setWindowTitle("EMEET PIXY Control")
        if ICON.exists():
            self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1100, 700)

        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None

        saved_geometry = self.settings.value("window/geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)

        if available is not None:
            self.resize(
                min(self.width(), available.width() - 40),
                min(self.height(), available.height() - 40),
            )

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        # Header
        header = QHBoxLayout()

        title = QLabel("EMEET PIXY")
        font = title.font()
        font.setPointSize(18)
        font.setBold(True)
        title.setFont(font)

        self.device_label = QLabel("Detecting camera...")
        self.device_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.device_label)
        main.addLayout(header)

        self.message = QLabel("Ready")
        self.message.setAlignment(Qt.AlignCenter)
        main.addWidget(self.message)

        self.body_splitter = QSplitter(Qt.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)

        # Live preview
        preview_box = QGroupBox("Live Preview")
        preview_layout = QVBoxLayout(preview_box)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(320, 240)
        self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        preview_layout.addWidget(self.video_widget)

        self.released_panel = QLabel(
            "<b>CAMERA PREVIEW RELEASED</b><br><br>"
            "EMEET PIXY is available to Google Meet, OBS, Teams, "
            "and other applications.<br><br>"
            "Camera controls remain active."
        )
        self.released_panel.setAlignment(Qt.AlignCenter)
        self.released_panel.setWordWrap(True)
        self.released_panel.setMinimumSize(320, 240)
        self.released_panel.setStyleSheet(
            "QLabel {"
            "  border: 1px solid palette(mid);"
            "  padding: 40px;"
            "  font-size: 14px;"
            "}"
        )
        self.released_panel.hide()

        preview_layout.addWidget(self.released_panel)

        self.preview_status = QLabel("Starting camera...")
        self.preview_status.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_status)

        self.preview_button = QPushButton("Release Preview")
        self.preview_button.clicked.connect(self.toggle_preview)
        preview_layout.addWidget(self.preview_button)

        self.body_splitter.addWidget(preview_box)
        self.body_splitter.setStretchFactor(0, 3)

        # Controls
        controls_widget = QWidget()
        controls = QVBoxLayout(controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)

        # Pan / Tilt
        ptz_box = QGroupBox("Pan / Tilt")
        ptz = QGridLayout(ptz_box)

        up = self.make_move_button("▲", "up")
        down = self.make_move_button("▼", "down")
        left = self.make_move_button("◀", "left")
        right = self.make_move_button("▶", "right")

        center = QPushButton("● Center")
        center.setMinimumHeight(55)
        center.clicked.connect(self.center_camera)

        ptz.addWidget(up, 0, 1)
        ptz.addWidget(left, 1, 0)
        ptz.addWidget(center, 1, 1)
        ptz.addWidget(right, 1, 2)
        ptz.addWidget(down, 2, 1)

        controls.addWidget(ptz_box)

        # Resolution
        resolution_box = QGroupBox("Resolution")
        resolution_layout = QVBoxLayout(resolution_box)

        self.resolution = QComboBox()
        self.resolution.currentIndexChanged.connect(
            self.resolution_changed
        )

        self.resolution_info = QLabel("")
        self.resolution_info.setAlignment(Qt.AlignCenter)

        resolution_layout.addWidget(self.resolution)
        resolution_layout.addWidget(self.resolution_info)

        controls.addWidget(resolution_box)

        # Zoom
        zoom_box = QGroupBox("Zoom")
        zoom_layout = QVBoxLayout(zoom_box)

        self.zoom_label = QLabel("100")
        self.zoom_label.setAlignment(Qt.AlignCenter)

        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(100, 150)
        self.zoom.setValue(100)
        self.zoom.setTickInterval(5)
        self.zoom.setTickPosition(QSlider.TicksBelow)

        self.zoom.valueChanged.connect(
            lambda value: self.zoom_label.setText(str(value))
        )
        self.zoom.sliderReleased.connect(self.apply_zoom)

        zoom_layout.addWidget(self.zoom_label)
        zoom_layout.addWidget(self.zoom)
        controls.addWidget(zoom_box)

        # Tracking / Privacy
        tracking_box = QGroupBox("Tracking / Privacy")
        tracking = QGridLayout(tracking_box)

        track = QPushButton("Tracking ON")
        idle = QPushButton("Tracking OFF")
        privacy = QPushButton("Privacy")

        track.clicked.connect(lambda: self.set_tracking_mode("track"))
        idle.clicked.connect(lambda: self.set_tracking_mode("idle"))
        privacy.clicked.connect(lambda: self.set_tracking_mode("privacy"))

        tracking.addWidget(track, 0, 0)
        tracking.addWidget(idle, 0, 1)
        tracking.addWidget(privacy, 1, 0, 1, 2)

        controls.addWidget(tracking_box)

        # Gesture
        gesture_box = QGroupBox("Gesture Control")
        gesture = QHBoxLayout(gesture_box)

        gesture_on = QPushButton("ON")
        gesture_off = QPushButton("OFF")

        gesture_on.clicked.connect(lambda: self.set_gesture(True))
        gesture_off.clicked.connect(lambda: self.set_gesture(False))

        gesture.addWidget(gesture_on)
        gesture.addWidget(gesture_off)

        controls.addWidget(gesture_box)

        # Audio
        audio_box = QGroupBox("Audio Mode")
        audio_layout = QHBoxLayout(audio_box)

        self.audio = QComboBox()
        self.audio.addItem("Noise Cancel", "nc")
        self.audio.addItem("Live", "live")
        self.audio.addItem("Original", "org")

        audio_apply = QPushButton("Apply")
        audio_apply.clicked.connect(self.apply_audio)

        audio_layout.addWidget(self.audio)
        audio_layout.addWidget(audio_apply)
        controls.addWidget(audio_box)

        # Anti-flicker
        flicker_box = QGroupBox("Anti-flicker")
        flicker_layout = QHBoxLayout(flicker_box)

        self.flicker = QComboBox()
        self.flicker.addItem("60 Hz", "60")
        self.flicker.addItem("50 Hz", "50")
        self.flicker.addItem("Off", "off")

        flicker_apply = QPushButton("Apply")
        flicker_apply.clicked.connect(self.apply_flicker)

        flicker_layout.addWidget(self.flicker)
        flicker_layout.addWidget(flicker_apply)

        controls.addWidget(flicker_box)

        # Virtual Camera
        virtual_box = QGroupBox("Virtual Camera")
        virtual_layout = QGridLayout(virtual_box)

        self.virtual_device_status = QLabel("Device: checking...")
        self.virtual_device_status.setAlignment(Qt.AlignCenter)

        self.virtual_status = QLabel("Pipeline: Stopped")
        self.virtual_status.setAlignment(Qt.AlignCenter)

        self.virtual_start = QPushButton("Start")
        self.virtual_stop = QPushButton("Stop")

        self.virtual_start.clicked.connect(
            self.start_virtual_camera
        )

        self.virtual_stop.clicked.connect(
            lambda: self.stop_virtual_camera(True)
        )

        self.virtual_stop.setEnabled(False)

        virtual_layout.addWidget(
            self.virtual_device_status, 0, 0, 1, 2
        )
        virtual_layout.addWidget(
            self.virtual_status, 1, 0, 1, 2
        )
        virtual_layout.addWidget(
            self.virtual_start, 2, 0
        )
        virtual_layout.addWidget(
            self.virtual_stop, 2, 1
        )

        controls.addWidget(virtual_box)

        # Status
        status_box = QGroupBox("Camera Status")
        status_layout = QVBoxLayout(status_box)

        self.status = QLabel("Checking...")
        self.status.setAlignment(Qt.AlignCenter)

        refresh = QPushButton("Refresh Status")
        refresh.clicked.connect(self.refresh_status)

        status_layout.addWidget(self.status)
        status_layout.addWidget(refresh)

        controls.addWidget(status_box)
        controls.addStretch()

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.NoFrame)
        controls_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        controls_scroll.setWidget(controls_widget)

        self.body_splitter.addWidget(controls_scroll)
        self.body_splitter.setStretchFactor(1, 2)
        self.body_splitter.setSizes([700, 430])

        main.addWidget(self.body_splitter, 1)

        self.load_saved_ui_state()
        self.start_camera()
        self.refresh_status(save=False)

        self.refresh_virtual_device_status()

        self.virtual_device_timer = QTimer(self)
        self.virtual_device_timer.timeout.connect(
            self.refresh_virtual_device_status
        )
        self.virtual_device_timer.start(3000)

        # Allow USB/video startup to settle before restoring saved settings.
        QTimer.singleShot(800, self.restore_camera_state)

    # --------------------------------------------------
    # CAMERA PREVIEW
    # --------------------------------------------------

    def find_pixy_camera(self):
        for device in QMediaDevices.videoInputs():
            name = device.description().upper()
            if "EMEET" in name and "PIXY" in name:
                return device
        return None

    def populate_resolutions(self, device):
        """
        Populate one entry per physical resolution.

        The PIXY exposes MJPEG plus low-resolution YUYV duplicates.
        For duplicate resolutions we prefer the format with the larger
        frame-rate capability, which on this camera selects MJPEG.
        """

        formats = {}

        for fmt in device.videoFormats():
            size = fmt.resolution()
            key = f"{size.width()}x{size.height()}"

            existing = formats.get(key)

            if (
                existing is None
                or fmt.maxFrameRate() > existing.maxFrameRate()
            ):
                formats[key] = fmt

        ordered = sorted(
            formats.items(),
            key=lambda item: (
                item[1].resolution().width()
                * item[1].resolution().height()
            ),
            reverse=True,
        )

        self.camera_formats = dict(ordered)

        saved = str(
            self.settings.value(
                "camera/resolution",
                "3840x2160"
            )
        )

        self.resolution.blockSignals(True)
        self.resolution.clear()

        saved_index = 0

        for index, (key, fmt) in enumerate(ordered):
            size = fmt.resolution()

            label = (
                f"{size.width()} × {size.height()}"
            )

            self.resolution.addItem(label, key)

            if key == saved:
                saved_index = index

        self.resolution.setCurrentIndex(saved_index)
        self.resolution.blockSignals(False)

        self.update_resolution_info()

    def selected_camera_format(self):
        key = self.resolution.currentData()

        if key is None:
            return None

        return self.camera_formats.get(str(key))

    def update_resolution_info(self):
        fmt = self.selected_camera_format()

        if fmt is None:
            self.resolution_info.setText("")
            return

        minimum = round(fmt.minFrameRate())
        maximum = round(fmt.maxFrameRate())

        if minimum == maximum:
            fps_text = f"{maximum} fps"
        else:
            fps_text = f"{minimum}-{maximum} fps"

        self.resolution_info.setText(fps_text)

        key = str(self.resolution.currentData())

        # PIXY native zoom is unavailable at 4K.
        # Qt's 1080p format is 30-60 fps and Qt attempts the
        # highest supported frame rate, effectively 1080p60.
        try:
            width = int(key.split("x", 1)[0])
        except (ValueError, IndexError):
            width = 9999

        zoom_available = width < 1920

        self.zoom.setEnabled(zoom_available)

        if zoom_available:
            self.zoom.setToolTip(
                "EMEET PIXY hardware zoom"
            )
        else:
            self.zoom.setToolTip(
                "Zoom unavailable in this video mode"
            )

    def resolution_changed(self):
        if not self.camera_formats:
            return

        key = self.resolution.currentData()

        if key is None:
            return

        self.settings.setValue(
            "camera/resolution",
            str(key)
        )

        self.settings.sync()

        self.update_resolution_info()

        # Re-open the camera with the newly selected format,
        # unless another application currently owns the stream.
        if not self.preview_released:
            self.stop_camera()
            self.start_camera()

            QTimer.singleShot(
                500,
                self.restore_camera_state
            )

    def start_camera(self):
        device = self.find_pixy_camera()

        if device is None:
            self.preview_status.setText("EMEET PIXY not found")
            self.device_label.setText("Camera unavailable")
            return

        self.device_label.setText(device.description())

        if not self.camera_formats:
            self.populate_resolutions(device)

        self.capture_session = QMediaCaptureSession(self)
        self.camera = QCamera(device, self)

        selected_format = self.selected_camera_format()

        if selected_format is not None:
            self.camera.setCameraFormat(selected_format)

        self.capture_session.setCamera(self.camera)
        self.capture_session.setVideoOutput(self.video_widget)

        self.camera.errorOccurred.connect(self.camera_error)
        self.camera.activeChanged.connect(self.camera_active_changed)

        self.preview_status.setText("Starting live preview...")
        self.camera.start()

    def stop_camera(self):
        if self.camera is not None:
            self.camera.stop()
            self.camera.deleteLater()
            self.camera = None

        if self.capture_session is not None:
            self.capture_session.deleteLater()
            self.capture_session = None

    def toggle_preview(self):
        if not self.preview_released:
            # Release the physical video stream for Meet/OBS/etc.
            self.stop_camera()
            self.preview_released = True

            self.video_widget.hide()

            self.released_panel.setText(
                "<b>CAMERA PREVIEW RELEASED</b><br><br>"
                "EMEET PIXY is available to Google Meet, OBS, Teams, "
                "and other applications.<br><br>"
                "Camera controls remain active."
            )

            self.released_panel.show()

            self.preview_status.setText(
                "Controls active — video stream released"
            )

            self.preview_button.setText("Resume Preview")

            # External application now owns the video mode.
            self.resolution.setEnabled(False)
            self.zoom.setEnabled(False)

            self.resolution.setToolTip(
                "Video mode is controlled by the application using the camera"
            )

            self.zoom.setToolTip(
                "Zoom availability depends on the external application's "
                "selected video mode"
            )

            self.message.setText(
                "Camera available to other applications"
            )

        else:
            self.preview_released = False

            self.released_panel.hide()
            self.video_widget.show()

            self.preview_button.setText("Release Preview")

            self.resolution.setEnabled(True)
            self.resolution.setToolTip("")

            self.preview_status.setText(
                "Starting live preview..."
            )

            self.start_camera()
            self.update_resolution_info()

            QTimer.singleShot(
                500,
                self.restore_camera_state
            )

            self.message.setText(
                "Preview resumed"
            )

    def restart_camera(self):
        self.preview_status.setText("Restarting preview...")
        self.stop_camera()
        self.start_camera()
        QTimer.singleShot(500, self.restore_camera_state)

    def camera_active_changed(self, active):
        self.preview_status.setText(
            "Live" if active else "Preview stopped"
        )

    def camera_error(self, error, error_string):
        self.preview_status.setText(
            f"Camera error: {error_string}"
        )

    # --------------------------------------------------
    # VIRTUAL CAMERA
    # --------------------------------------------------

    def find_virtual_camera_device(self):
        """
        Locate the EMEET PIXY virtual camera by its V4L2 device name
        instead of assuming a fixed /dev/video number.
        """

        root = Path("/sys/class/video4linux")

        if not root.exists():
            return None

        devices = sorted(
            root.glob("video*"),
            key=lambda x: int(x.name.replace("video", ""))
        )

        for dev_dir in devices:
            try:
                name = (
                    dev_dir / "name"
                ).read_text().strip()
            except Exception:
                continue

            if name == "EMEET PIXY Virtual Camera":
                return f"/dev/{dev_dir.name}"

        return None


    def refresh_virtual_device_status(self):
        device = self.find_virtual_camera_device()

        if device:
            self.virtual_device_status.setText(
                f"Device: Ready — {device}"
            )
            self.virtual_start.setEnabled(
                not self.virtual_active and self.virtual_process is None
            )
        else:
            self.virtual_device_status.setText(
                "Device: Missing"
            )
            self.virtual_start.setEnabled(False)


    def find_pixy_video_device(self):
        """
        Find the PIXY capture node dynamically instead of assuming
        that it will always be /dev/video1.
        """

        root = Path("/sys/class/video4linux")

        if not root.exists():
            return None

        devices = sorted(
            root.glob("video*"),
            key=lambda x: int(x.name.replace("video", ""))
        )

        for dev_dir in devices:
            try:
                name = (
                    dev_dir / "name"
                ).read_text().strip().upper()
            except Exception:
                continue

            if "EMEET" not in name or "PIXY" not in name:
                continue

            device = f"/dev/{dev_dir.name}"

            # PIXY exposes more than one video node.
            # Select the node that actually exposes MJPEG capture.
            try:
                result = subprocess.run(
                    [
                        V4L2_CTL or "v4l2-ctl",
                        "-d",
                        device,
                        "--list-formats-ext",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )

                if "MJPG" in result.stdout:
                    return device

            except Exception:
                continue

        return None


    def start_virtual_camera(self):
        if self.virtual_active:
            return

        virtual_device = self.find_virtual_camera_device()

        if virtual_device is None:
            self.message.setText(
                "EMEET PIXY Virtual Camera is not available"
            )
            self.virtual_status.setText(
                "Pipeline: Device missing"
            )
            self.refresh_virtual_device_status()
            return

        physical_device = self.find_pixy_video_device()

        if physical_device is None:
            self.message.setText(
                "EMEET PIXY capture device not found"
            )
            self.virtual_status.setText(
                "PIXY unavailable"
            )
            return

        resolution = str(
            self.resolution.currentData()
            or "1280x720"
        )

        try:
            width, height = [
                int(x)
                for x in resolution.split("x", 1)
            ]
        except Exception:
            width, height = 1280, 720
            resolution = "1280x720"

        self.preview_before_virtual = (
            not self.preview_released
        )

        # Qt must release the physical stream before FFmpeg opens it.
        self.stop_camera()

        self.video_widget.hide()

        self.released_panel.setText(
            "<b>VIRTUAL CAMERA ACTIVE</b><br><br>"
            "The physical EMEET PIXY is feeding "
            "<b>EMEET PIXY Virtual Camera</b>.<br><br>"
            "Select EMEET PIXY Virtual Camera in "
            "Google Meet, OBS, Teams, or another application.<br><br>"
            "Pan, tilt, tracking, and other camera controls "
            "remain active."
        )

        self.released_panel.show()

        self.preview_status.setText(
            "Starting virtual camera..."
        )

        self.preview_button.setEnabled(False)
        self.resolution.setEnabled(False)

        self.virtual_start.setEnabled(False)
        self.virtual_stop.setEnabled(True)

        self.virtual_status.setText(
            f"Pipeline: Starting — {resolution} @ 30 fps"
        )

        self.message.setText(
            "Starting virtual camera"
        )

        # Give Qt a moment to fully release /dev/videoX.
        QTimer.singleShot(
            350,
            lambda: self.launch_virtual_camera(
                physical_device,
                virtual_device,
                resolution,
                width,
                height,
            )
        )


    def launch_virtual_camera(
        self,
        physical_device,
        virtual_device,
        resolution,
        width,
        height,
    ):
        if self.virtual_process is not None:
            return

        process = QProcess(self)

        if not FFMPEG:
            self.virtual_status.setText("Pipeline: FFmpeg missing")
            self.message.setText("FFmpeg is required for Virtual Camera mode")
            self.restore_after_virtual_camera()
            return

        process.setProgram(FFMPEG)

        process.setArguments(
            [
                "-hide_banner",
                "-loglevel",
                "warning",

                "-f",
                "v4l2",

                "-input_format",
                "mjpeg",

                "-video_size",
                resolution,

                "-framerate",
                "30",

                "-i",
                physical_device,

                "-vf",
                "format=yuv420p",

                "-f",
                "v4l2",

                virtual_device,
            ]
        )

        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )

        process.finished.connect(
            self.virtual_process_finished
        )

        self.virtual_process = process

        process.start()

        if not process.waitForStarted(3000):
            error = process.errorString()

            self.virtual_process = None

            self.virtual_status.setText(
                "Pipeline: Failed to start"
            )

            self.message.setText(
                f"Virtual camera error: {error}"
            )

            self.restore_after_virtual_camera()

            return

        self.virtual_active = True

        self.virtual_status.setText(
            f"Pipeline: Running — {width} × {height} @ 30 fps"
        )

        self.preview_status.setText(
            "Virtual output active"
        )

        self.message.setText(
            "EMEET PIXY Virtual Camera running"
        )

        # We know the exact resolution selected by FFmpeg,
        # so native zoom availability remains predictable.
        self.update_resolution_info()


    def stop_virtual_camera(
        self,
        restore_preview=True,
    ):
        self.virtual_stopping = True

        process = self.virtual_process

        if process is not None:
            if (
                process.state()
                != QProcess.ProcessState.NotRunning
            ):
                process.terminate()

                if not process.waitForFinished(2000):
                    process.kill()
                    process.waitForFinished(1000)

            process.deleteLater()

        self.virtual_process = None
        self.virtual_active = False
        self.virtual_stopping = False

        self.virtual_status.setText("Pipeline: Stopped")

        self.virtual_start.setEnabled(True)
        self.virtual_stop.setEnabled(False)

        if restore_preview:
            self.restore_after_virtual_camera()


    def virtual_process_finished(
        self,
        exit_code,
        exit_status,
    ):
        if self.virtual_stopping:
            return

        if not self.virtual_active:
            return

        self.virtual_process = None
        self.virtual_active = False

        self.virtual_status.setText(
            f"Pipeline: Stopped unexpectedly ({exit_code})"
        )

        self.virtual_start.setEnabled(True)
        self.virtual_stop.setEnabled(False)

        self.message.setText(
            "Virtual camera process stopped"
        )

        self.restore_after_virtual_camera()


    def restore_after_virtual_camera(self):
        self.preview_button.setEnabled(True)

        if self.preview_before_virtual:
            self.preview_released = False

            self.released_panel.hide()
            self.video_widget.show()

            self.preview_button.setText(
                "Release Preview"
            )

            self.resolution.setEnabled(True)

            self.preview_status.setText(
                "Starting live preview..."
            )

            QTimer.singleShot(
                300,
                self.start_camera
            )

            QTimer.singleShot(
                800,
                self.restore_camera_state
            )

        else:
            # Return to Direct/Release mode.
            self.preview_released = True

            self.video_widget.hide()

            self.released_panel.setText(
                "<b>CAMERA PREVIEW RELEASED</b><br><br>"
                "EMEET PIXY is available to Google Meet, OBS, "
                "Teams, and other applications.<br><br>"
                "Camera controls remain active."
            )

            self.released_panel.show()

            self.preview_button.setText(
                "Resume Preview"
            )

            self.preview_status.setText(
                "Controls active — video stream released"
            )

            self.resolution.setEnabled(False)
            self.zoom.setEnabled(False)


    # --------------------------------------------------
    # BACKEND
    # --------------------------------------------------

    def backend(self, *args):
        if not BACKEND.exists():
            self.message.setText(f"Backend missing: {BACKEND}")
            return None

        result = subprocess.run(
            [sys.executable, str(BACKEND), *map(str, args)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            self.message.setText("ERROR: " + error)
            return None

        output = result.stdout.strip()
        self.message.setText(output if output else "OK")

        return output

    # --------------------------------------------------
    # PTZ
    # --------------------------------------------------

    def make_move_button(self, text, command):
        button = QPushButton(text)
        button.setMinimumSize(80, 55)

        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(250)
        button.setAutoRepeatInterval(100)

        button.clicked.connect(
            lambda checked=False: self.backend(command)
        )

        button.released.connect(self.refresh_status)

        return button

    def center_camera(self):
        self.backend("center")
        self.zoom.setValue(100)
        self.refresh_status()

    def apply_zoom(self):
        self.backend("zoom", self.zoom.value())
        self.settings.setValue("camera/zoom", self.zoom.value())
        self.refresh_status()

    # --------------------------------------------------
    # FEATURE STATE
    # --------------------------------------------------

    def set_tracking_mode(self, mode):
        if self.backend(mode) is not None:
            self.settings.setValue("camera/tracking", mode)

    def set_gesture(self, enabled):
        command = "gesture-on" if enabled else "gesture-off"

        if self.backend(command) is not None:
            self.settings.setValue("camera/gesture", bool(enabled))

    def apply_audio(self):
        mode = self.audio.currentData()

        if self.backend("audio", mode) is not None:
            self.settings.setValue("camera/audio", mode)

    def apply_flicker(self):
        mode = self.flicker.currentData()

        if self.backend("flicker", mode) is not None:
            self.settings.setValue("camera/flicker", mode)

    # --------------------------------------------------
    # PERSISTENCE
    # --------------------------------------------------

    def bool_setting(self, key, default=False):
        value = self.settings.value(key, default)

        if isinstance(value, bool):
            return value

        return str(value).lower() in (
            "1", "true", "yes", "on"
        )

    def load_saved_ui_state(self):
        zoom = int(
            self.settings.value("camera/zoom", 100)
        )
        zoom = max(100, min(150, zoom))

        self.zoom.setValue(zoom)
        self.zoom_label.setText(str(zoom))

        audio = str(
            self.settings.value("camera/audio", "nc")
        )
        index = self.audio.findData(audio)

        if index >= 0:
            self.audio.setCurrentIndex(index)

        flicker = str(
            self.settings.value("camera/flicker", "60")
        )
        index = self.flicker.findData(flicker)

        if index >= 0:
            self.flicker.setCurrentIndex(index)

    def restore_camera_state(self):
        if self.restoring:
            return

        self.restoring = True

        try:
            pan = int(
                self.settings.value("camera/pan", 0)
            )
            tilt = int(
                self.settings.value("camera/tilt", 0)
            )
            zoom = int(
                self.settings.value("camera/zoom", 100)
            )

            tracking = str(
                self.settings.value("camera/tracking", "idle")
            )

            gesture = self.bool_setting(
                "camera/gesture", False
            )

            audio = str(
                self.settings.value("camera/audio", "nc")
            )

            flicker = str(
                self.settings.value("camera/flicker", "60")
            )

            pan = max(-150, min(150, pan))
            tilt = max(-90, min(90, tilt))
            zoom = max(100, min(150, zoom))

            self.backend("pan", pan)
            self.backend("tilt", tilt)

            if self.zoom.isEnabled():
                self.backend("zoom", zoom)

            if tracking in ("idle", "track", "privacy"):
                self.backend(tracking)

            self.backend(
                "gesture-on" if gesture else "gesture-off"
            )

            if audio in ("nc", "live", "org"):
                self.backend("audio", audio)

            if flicker in ("off", "50", "60"):
                self.backend("flicker", flicker)

            self.zoom.setValue(zoom)
            self.zoom_label.setText(str(zoom))

            self.refresh_status(save=True)

            self.message.setText(
                "Saved camera settings restored"
            )

        finally:
            self.restoring = False

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def refresh_status(self, save=True):
        output = self.backend("status")

        if not output:
            self.status.setText("Camera unavailable")
            return

        self.status.setText(output)

        parsed = {}

        for line in output.splitlines():
            line = line.strip()

            if line.startswith("pan:"):
                try:
                    parsed["pan"] = int(
                        line.split(":", 1)[1]
                        .strip()
                        .split()[0]
                    )
                except (ValueError, IndexError):
                    pass

            elif line.startswith("tilt:"):
                try:
                    parsed["tilt"] = int(
                        line.split(":", 1)[1]
                        .strip()
                        .split()[0]
                    )
                except (ValueError, IndexError):
                    pass

            elif line.startswith("zoom:"):
                try:
                    parsed["zoom"] = int(
                        line.split(":", 1)[1].strip()
                    )
                except ValueError:
                    pass

        if "zoom" in parsed:
            self.zoom.blockSignals(True)
            self.zoom.setValue(parsed["zoom"])
            self.zoom.blockSignals(False)
            self.zoom_label.setText(str(parsed["zoom"]))

        if save:
            for key in ("pan", "tilt", "zoom"):
                if key in parsed:
                    self.settings.setValue(
                        f"camera/{key}",
                        parsed[key]
                    )

    # --------------------------------------------------
    # EXIT
    # --------------------------------------------------

    def closeEvent(self, event):
        self.refresh_status(save=True)

        self.settings.setValue(
            "window/geometry",
            self.saveGeometry()
        )

        self.settings.sync()

        if self.virtual_active or self.virtual_process is not None:
            self.stop_virtual_camera(False)

        self.stop_camera()

        event.accept()


def main():
    app = QApplication(sys.argv)

    window = PixyGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
