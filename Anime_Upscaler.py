import cv2
import torch
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional
import contextlib
import io

# Deliberately do NOT import RRDBNet / RealESRGANer at module import time --
# they will be imported lazily inside _load_model to avoid heavy work on UI startup.

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QTextEdit,
    QComboBox,
    QMessageBox,
    QGroupBox,
)


def find_model_in_syspath(model_filename: str) -> Path:
    """Search for model file in sys.path directories."""
    print(f"[DEBUG] Searching for model: {model_filename}")

    # Strategy 1: Check current directory
    current_dir_path = Path(model_filename)
    if current_dir_path.exists():
        print(f"[SUCCESS] Found model in current directory: {current_dir_path}")
        return current_dir_path

    # Strategy 2: Search in all sys.path entries
    for path_entry in sys.path:
        if os.path.isdir(path_entry):
            model_path = Path(path_entry) / model_filename
            if model_path.exists():
                print(f"[SUCCESS] Found model in sys.path: {model_path}")
                return model_path

    # Not found anywhere
    print(f"[ERROR] Model '{model_filename}' not found in:")
    print(f"  - Current directory: {Path.cwd()}")
    for i, path in enumerate(sys.path[:5]):
        print(f"  - sys.path[{i}]: {path}")

    raise FileNotFoundError(
        f"Model file '{model_filename}' not found. "
        f"Please place it in the project root directory: {sys.path[0] if sys.path else Path.cwd()}"
    )


class StreamToLogger(io.TextIOBase):
    """File-like object that sends writes to a logger callable (line buffered)."""

    def __init__(self, logger: Callable[[str], None]):
        self.logger = logger
        self._buf = ""

    def write(self, s):
        if not s:
            return
        # Accumulate and emit on newline
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            try:
                # keep timestamping consistent with upscaler.log usage
                self.logger(line)
            except Exception:
                # swallow logger errors
                pass

    def flush(self):
        if self._buf:
            try:
                self.logger(self._buf)
            except Exception:
                pass
            self._buf = ""


class AnimeUpscaler:
    """Anime Image Upscaler with selectable target resolution (4K / 8K / 16K / 32K / 64K )."""

    SUPPORTED_FORMATS = (".png", ".jpg", ".jpeg", ".bmp")
    MODEL_FILENAME = "RealESRGAN_x4plus_anime_6B.pth"  # Just the filename, path will be auto-detected

    # Predefined resolutions
    RESOLUTIONS = {
        "1": (3840, 2160),     # 4K
        "2": (7680, 4320),     # 8K
        "3": (15360, 8640),    # 16K
        "4": (30720, 17280),   # 32K
        "5": (61440, 34560),   # 64K
    }

    def __init__(
        self,
        input_path: Path,
        output_folder: Path,
        target_res: tuple,
        tile: int = 200,
        tile_pad: int = 10,
        logger: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            input_path (Path): Path to input file or folder
            output_folder (Path): Path to save results
            target_res (tuple): (width, height) final resolution
            tile (int): Tile size (smaller = less VRAM, safer on T4; try 200–300)
            tile_pad (int): Padding between tiles to avoid seams
        """
        self.input_path = Path(input_path)
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.logger = logger

        # CUDA check (but allow CPU fallback)
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self._log_to_console("[WARNING] CUDA GPU not detected, using CPU (very slow).")
            self.device = torch.device("cpu")

        self.tile = tile
        self.tile_pad = tile_pad

        # Do NOT load model here if you want very fast UI startup in main thread.
        # Instead, we'll load it lazily when needed via _load_model which will be called
        # from the worker thread.
        self.upsampler = None

        if not self.input_path.exists():
            raise FileNotFoundError(f"[ERROR] Input path not found: {self.input_path}")

        self.output_folder.mkdir(parents=True, exist_ok=True)

    def _log_to_console(self, message: str):
        # fallback used during initialization warnings
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        try:
            print(f"{timestamp} {message}")
        except Exception:
            pass

    def _load_model(self):
        """Load the RealESRGAN model with tiling (lazy, safe import)."""
        # Auto-detect model path from sys.path directories
        try:
            model_path = find_model_in_syspath(self.MODEL_FILENAME)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"[ERROR] {e}")

        # Lazy imports (so module import does not trigger heavy loads on UI startup)
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
        except Exception as e:
            raise RuntimeError(f"Failed to import model libraries: {e}")

        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=6,  # Anime model uses 6 blocks
            num_grow_ch=32,
            scale=4,
        )

        upsampler = RealESRGANer(
            scale=4,
            model_path=str(model_path),
            model=model,
            tile=self.tile,
            tile_pad=self.tile_pad,
            pre_pad=0,
            half=(torch.cuda.is_available()),   # FP16 only if GPU and supported
            device=self.device,
        )

        self.upsampler = upsampler
        return upsampler

    def log(self, message: str):
        """Log with timestamps, to GUI if available, otherwise stdout."""
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        text = f"{timestamp} {message}"
        if self.logger is not None:
            try:
                self.logger(text)
                return
            except Exception:
                # Fallback to print if logger fails
                pass
        # Handle encoding issues on Windows by encoding to utf-8
        try:
            print(text)
        except UnicodeEncodeError:
            ascii_text = text.encode("ascii", "replace").decode("ascii")
            print(ascii_text)

    def _calculate_tile_count(self, img_height: int, img_width: int) -> int:
        """Calculate the number of tiles needed for an image."""
        num_tiles_x = (img_width + self.tile - 1) // self.tile
        num_tiles_y = (img_height + self.tile - 1) // self.tile
        return num_tiles_x * num_tiles_y

    def upscale(self):
        """Process file or folder."""
        if self.input_path.is_file():
            self._upscale_file(self.input_path)
        elif self.input_path.is_dir():
            self._upscale_folder(self.input_path)
        else:
            raise ValueError("[ERROR] Input path must be a file or a folder.")

    def _upscale_file(self, file: Path):
        """Upscale a single image file to target resolution."""
        if file.suffix.lower() not in self.SUPPORTED_FORMATS:
            self.log(f"[WARNING] Skipped unsupported file: {file.name}")
            return

        img = cv2.imread(str(file), cv2.IMREAD_COLOR)
        if img is None:
            self.log(f"[ERROR] Failed to load: {file.name}")
            return

        try:
            # Ensure model loaded in the same thread as this call
            if self.upsampler is None:
                self.log("[INFO] Loading model (this may take a while)...")
                self._load_model()
                self.log("[INFO] Model loaded.")

            # Calculate total number of tiles for progress display (based on input image)
            img_height, img_width = img.shape[:2]
            total_tiles = self._calculate_tile_count(img_height, img_width)

            self.log(f"[INFO] Image size: {img_width}x{img_height}")
            self.log(f"[INFO] Tile size: {self.tile}")
            self.log(f"[INFO] Total tiles to process: {total_tiles}")

            # Many libraries print progress to stdout. We'll redirect stdout/stderr
            # to our GUI logger for the duration of enhance so those messages show up.
            stream = StreamToLogger(self.log)
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                # Call RealESRGAN enhancement (this will run inside the worker thread)
                restored, _ = self.upsampler.enhance(img, outscale=4)

            # After enhance, re-log simulated tile completion (if desired)
            # Note: If the library emitted per-tile messages we already captured them.
            # Keep a completion loop so the GUI has clear progress lines.
            for i in range(1, total_tiles + 1):
                self.log(f"[PROGRESS] Tile {i}/{total_tiles}")

            # Step 2: Resize to fit within chosen target resolution while preserving aspect ratio
            target_w, target_h = self.target_res
            src_h, src_w = restored.shape[:2]
            scale = min(target_w / src_w, target_h / src_h)
            out_w = max(1, int(src_w * scale))
            out_h = max(1, int(src_h * scale))
            if out_w != src_w or out_h != src_h:
                final = cv2.resize(restored, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            else:
                final = restored

            out_path = self.output_folder / f"upscaled_{file.stem}_{out_w}x{out_h}{file.suffix}"
            cv2.imwrite(str(out_path), final)

            self.log(f"[SUCCESS] Saved: {out_path} ({out_w}x{out_h})")

        except Exception as e:
            # Include type + message for easier debugging
            self.log(f"[ERROR] Error processing {file.name}: {type(e).__name__}: {e}")

    def _upscale_folder(self, folder: Path):
        """Upscale all supported images in a folder."""
        processed = 0
        for file in folder.iterdir():
            if file.suffix.lower() in self.SUPPORTED_FORMATS:
                self._upscale_file(file)
                processed += 1
        self.log(f"[SUCCESS] Completed! {processed} image(s) processed.")


class UpscaleWorker(QObject):
    """Background worker to run upscale without blocking UI."""
    finished = Signal()
    errored = Signal(str)
    logged = Signal(str)

    def __init__(self, input_files: list[Path], output_folder: Path, target_res: tuple, tile: int, tile_pad: int):
        super().__init__()
        # Normalize input paths into Path objects
        self.input_files = [Path(f) for f in input_files]
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.tile = tile
        self.tile_pad = tile_pad
        self._should_stop = False

    @Slot()
    def run(self):
        try:
            # gui_logger will run in the worker thread but emits Qt signals which are thread-safe
            def gui_logger(text: str):
                # keep messages short and consistent
                self.logged.emit(text)

            total = len(self.input_files)
            if total == 0:
                self.logged.emit("[ERROR] No input files provided to worker.")
                self.finished.emit()
                return

            for idx, input_file in enumerate(self.input_files, start=1):
                # Header for each image
                self.logged.emit(f"[IMAGE] Processing {idx}/{total}: {input_file.name}")

                if not input_file.exists():
                    self.logged.emit(f"[ERROR] File not found: {input_file}")
                    continue
                if input_file.suffix.lower() not in AnimeUpscaler.SUPPORTED_FORMATS:
                    self.logged.emit(f"[WARNING] Unsupported format, skipping: {input_file.name}")
                    continue

                try:
                    upscaler = AnimeUpscaler(
                        input_path=input_file,
                        output_folder=self.output_folder,
                        target_res=self.target_res,
                        tile=self.tile,
                        tile_pad=self.tile_pad,
                        logger=gui_logger,
                    )

                    # Process this single file (will log its own details)
                    upscaler._upscale_file(input_file)
                    self.logged.emit(f"[IMAGE] Completed {idx}/{total}: {input_file.name}")

                except Exception as e:
                    # Per-image error should not stop the rest of the batch
                    self.errored.emit(f"{type(e).__name__}: {e}")
                    self.logged.emit(f"[ERROR] Failed to process {input_file.name}, continuing with next.")

            # Batch completed
            self.logged.emit(f"[SUCCESS] Batch finished: {total} file(s) attempted.")
            self.finished.emit()
        except Exception as e:
            # Emit a clear, typed error message for unexpected exceptions
            self.errored.emit(f"{type(e).__name__}: {e}")
            self.finished.emit()


class AnimeUpscalerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anime Image Upscaler")
        self.setFixedSize(600, 600)
        self.worker_thread: QThread | None = None
        self.worker: UpscaleWorker | None = None
        self._build_ui()
        self._apply_dark_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header
        header = QLabel("Anime Image Upscaler")
        header.setObjectName("HeaderLabel")
        layout.addWidget(header)

        io_group = QGroupBox("Paths")
        io_layout = QVBoxLayout(io_group)

        # Input file
        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("Input Image(s):"))
        self.in_edit = QLineEdit()
        self.in_edit.setPlaceholderText("Select one or more image files (separated internally)")
        row_in.addWidget(self.in_edit)
        self.browse_in_btn = QPushButton("Browse")
        self.browse_in_btn.clicked.connect(self._on_browse_input)
        row_in.addWidget(self.browse_in_btn)
        io_layout.addLayout(row_in)

        # Output folder
        row_out = QHBoxLayout()
        row_out.addWidget(QLabel("Output Folder:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Select destination folder")
        row_out.addWidget(self.out_edit)
        self.browse_out_btn = QPushButton("Browse")
        self.browse_out_btn.clicked.connect(self._on_browse_output)
        row_out.addWidget(self.browse_out_btn)
        io_layout.addLayout(row_out)

        layout.addWidget(io_group)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_layout = QHBoxLayout(settings_group)

        settings_layout.addWidget(QLabel("Resolution:"))
        self.res_combo = QComboBox()
        # Map label to resolution tuple
        self.label_to_res = {}
        for key, (w, h) in AnimeUpscaler.RESOLUTIONS.items():
            label = f"{key}. {w}x{h}"
            self.res_combo.addItem(label)
            self.label_to_res[label] = (w, h)
        settings_layout.addWidget(self.res_combo)

        layout.addWidget(settings_group)

        # Controls
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        controls.addWidget(self.start_btn)
        layout.addLayout(controls)

        # Logs
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Logs will appear here...")
        layout.addWidget(self.log_view)

    def _apply_dark_style(self):
        self.setStyleSheet(
            """
            QWidget { background-color: #0e0e0e; color: #e6e6e6; }
            #HeaderLabel { font-size: 18px; font-weight: bold; padding: 4px 0; }
            QGroupBox { border: 1px solid #333333; border-radius: 6px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QLineEdit { background-color: #1a1a1a; color: #e6e6e6; border: 1px solid #3a3a3a; padding: 6px; border-radius: 4px; }
            QPushButton { background-color: #2b2b2b; color: #e6e6e6; border: 1px solid #4a4a4a; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:disabled { color: #888888; border-color: #3a3a3a; }
            QTextEdit { background-color: #0e0e0e; color: #e6e6e6; border: 1px solid #333333; font-family: Consolas, Monaco, monospace; font-size: 11px; }
            QComboBox { background-color: #1a1a1a; color: #e6e6e6; border: 1px solid #3a3a3a; padding: 4px; border-radius: 4px; }
            QComboBox QAbstractItemView { background-color: #1a1a1a; color: #e6e6e6; selection-background-color: #333333; }
            QLabel { color: #e6e6e6; }
            """
        )

    def _show_startup_warning(self):
        QMessageBox.warning(
            self,
            "Important Notice",
            (
                "This tool works best for anime-style images.\n\n"
                "Selecting extremely high resolutions (e.g., 16K/32K/64K) may cause crashes\n"
                "due to high memory usage, especially without a powerful GPU."
            ),
        )

    def _append_log(self, text: str):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    @Slot()
    def _on_browse_input(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select One or More Input Images",
            str(Path.cwd()),
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if files:
            # Store multiple file paths separated by ;
            self.in_edit.setText(";".join(files))

    @Slot()
    def _on_browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

    @Slot()
    def _on_start(self):
        input_path = self.in_edit.text().strip()
        output_folder = self.out_edit.text().strip()
        if not input_path:
            self._append_log("[ERROR] Please select at least one input image.")
            return
        if not output_folder:
            self._append_log("[ERROR] Please select an output folder.")
            return

        label = self.res_combo.currentText()
        target_res = self.label_to_res.get(label, (3840, 2160))

        # Lower tile size to reduce CPU/memory usage
        tile = 128
        tile_pad = 8

        # Parse multiple files (semicolon-separated)
        input_files = [p.strip() for p in input_path.split(";") if p.strip()]
        if not input_files:
            self._append_log("[ERROR] No valid image files found in the input field.")
            return

        # Disable UI while running
        self.start_btn.setEnabled(False)
        self.browse_in_btn.setEnabled(False)
        self.browse_out_btn.setEnabled(False)
        self.res_combo.setEnabled(False)
        self.log_view.clear()
        self._append_log("Starting upscaling...")

        # Create worker + thread and move worker to that thread
        self.worker_thread = QThread()
        self.worker = UpscaleWorker(
            input_files=input_files,
            output_folder=Path(output_folder),
            target_res=target_res,
            tile=tile,
            tile_pad=tile_pad,
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.run)
        self.worker.logged.connect(self._append_log)
        self.worker.errored.connect(lambda m: self._append_log(f"[ERROR] {m}"))
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        # Ensure thread cleanup
        self.worker_thread.finished.connect(self._cleanup_thread)

        # Start
        self.worker_thread.start()

    @Slot()
    def _on_finished(self):
        self._append_log("[SUCCESS] Done.")
        self.start_btn.setEnabled(True)
        self.browse_in_btn.setEnabled(True)
        self.browse_out_btn.setEnabled(True)
        self.res_combo.setEnabled(True)

    @Slot()
    def _cleanup_thread(self):
        try:
            if self.worker:
                self.worker.deleteLater()
            if self.worker_thread:
                self.worker_thread.deleteLater()
        finally:
            self.worker = None
            self.worker_thread = None


if __name__ == "__main__":
    app = QApplication([])
    w = AnimeUpscalerApp()
    w.show()
    app.exec()
