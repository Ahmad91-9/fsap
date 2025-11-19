import cv2
import torch
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional
import contextlib
import io
import numpy as np

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
    """Anime Image/Video Upscaler with selectable target resolution."""

    # Supported formats
    SUPPORTED_IMAGE_FORMATS = (".png", ".jpg", ".jpeg", ".bmp")
    # Note: MP4 output requires a compatible codec (e.g., 'mp4v' or 'XVID' for VideoWriter)
    SUPPORTED_VIDEO_FORMATS = (".mp4", ".avi", ".mkv", ".mov")
    # FIX: Corrected typo from SUPPORTed_IMAGE_FORMATS to SUPPORTED_IMAGE_FORMATS
    SUPPORTED_FORMATS = SUPPORTED_IMAGE_FORMATS + SUPPORTED_VIDEO_FORMATS

    MODEL_FILENAME = "RealESRGAN_x4plus_anime_6B.pth"  # Just the filename, path will be auto-detected
    
    # Safe maximum batch size for video processing (30 is a good compromise for VRAM and speed)
    VIDEO_BATCH_SIZE = 30 

    # Predefined resolutions (The output will be constrained by these max dimensions)
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
            target_res (tuple): (width, height) final max resolution
            tile (int): Tile size (smaller = less VRAM, safer on T4; try 200–300)
            tile_pad (int): Padding between tiles to avoid seams
        """
        self.input_path = Path(input_path)
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.logger = logger

        # CUDA check (but allow CPU fallback)
        if torch.cuda.is_available():
            self._log_to_console("[INFO] CUDA GPU detected, using GPU acceleration.")
            self.device = torch.device("cuda")
        else:
            self._log_to_console("[WARNING] CUDA GPU not detected, using CPU (very slow).")
            self.device = torch.device("cpu")

        self.tile = tile
        self.tile_pad = tile_pad
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
            raise RuntimeError(f"Failed to import model libraries: {e}. Check if basicsr and realesrgan are installed.")

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

    def _calculate_output_size(self, source_w: int, source_h: int) -> tuple[int, int]:
        """Calculates the final output size based on the 4x upscaled content (source_w, source_h)
        to fit within the user-defined target resolution (self.target_res) while preserving aspect ratio.
        """
        target_w, target_h = self.target_res
        
        # Calculate the size to fit the 4x upscaled image (source) within the target size.
        # This prevents the final image from exceeding the user's resolution cap.
        scale = min(target_w / source_w, target_h / source_h)
        out_w = max(1, int(source_w * scale))
        out_h = max(1, int(source_h * scale))

        # Ensure width and height are even numbers, which is critical for video codecs and best practice for images
        out_w = out_w // 2 * 2
        out_h = out_h // 2 * 2
        
        if out_w == 0 or out_h == 0:
            self.log(f"[WARNING] Calculated output size is zero, falling back to 4x size ({source_w}x{source_h}).")
            return source_w, source_h

        return out_w, out_h

    def _calculate_tile_count(self, img_height: int, img_width: int) -> int:
        """Calculate the number of tiles needed for an image."""
        num_tiles_x = (img_width + self.tile - 1) // self.tile
        num_tiles_y = (img_height + self.tile - 1) // self.tile
        return num_tiles_x * num_tiles_y

    def upscale(self):
        """Process file or folder."""
        if self.input_path.is_file():
            suffix = self.input_path.suffix.lower()
            if suffix in self.SUPPORTED_IMAGE_FORMATS:
                self._upscale_file(self.input_path)
            elif suffix in self.SUPPORTED_VIDEO_FORMATS:
                self._upscale_video(self.input_path)
            else:
                self.log(f"[ERROR] Unsupported file format: {self.input_path.name}")
        elif self.input_path.is_dir():
            self._upscale_folder(self.input_path)
        else:
            raise ValueError("[ERROR] Input path must be a file or a folder.")

    def _process_frame_batch(self, batch_frames: list, out_w: int, out_h: int) -> list[np.ndarray]:
        """
        Process a batch of frames on the GPU in a single forward pass (manual batching).
        NOTE: This bypasses RealESRGANer's tiling logic, meaning all 4x upscaled frames
              in the batch must fit into VRAM. Use small batch sizes for large frames.
        """
        if not batch_frames:
            return []

        # Lazy imports for required utilities (assuming basicsr is installed)
        try:
            from basicsr.utils import img2tensor, tensor2img
        except Exception:
            self.log("[ERROR] Cannot import basic utility functions (img2tensor/tensor2img). Video batch processing failed.")
            raise

        # 1. Convert frames to PyTorch tensor format (B, C, H, W) and move to device
        tensor_list = []
        for frame in batch_frames:
            # img2tensor handles conversion and normalization (BGR->RGB, HWC->CHW, unit8->float)
            tensor_list.append(img2tensor(frame / 255.0, bgr2rgb=True, float32=True).to(self.device))
        
        # Stack into batch tensor: (B, C, H, W)
        batch_tensor = torch.stack(tensor_list, dim=0)

        output_frames = []
        # Run model inference in non-gradient mode
        with torch.no_grad():
            # Use the underlying RRDBNet model directly for batch inference
            output_tensor = self.upsampler.model(batch_tensor)

        # 2. Post-process: Convert back to NumPy images (B, H, W, C), denormalize/clip, and resize
        for single_output_tensor in output_tensor:
            # Convert back: (C, H, W) -> (H, W, C), RGB -> BGR, float->uint8, clip
            restored_img = tensor2img(single_output_tensor, rgb2bgr=True)
            
            # 3. Resize to target resolution (out_w, out_h)
            final_img = cv2.resize(restored_img, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            output_frames.append(final_img)

        return output_frames

    def _upscale_file(self, file: Path):
        """Upscale a single image file to target resolution (using tiling for safety)."""
        if file.suffix.lower() not in self.SUPPORTED_IMAGE_FORMATS:
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

            img_height, img_width = img.shape[:2]
            
            # 1. Upscale 4x with RealESRGAN (uses tiling internally)
            self.log(f"[INFO] Image size: {img_width}x{img_height}")
            self.log(f"[INFO] Tile size: {self.tile}")
            
            total_tiles = self._calculate_tile_count(img_height, img_width)
            self.log(f"[INFO] Total tiles to process: {total_tiles}")

            # Redirect stdout/stderr to the GUI logger during enhancement
            stream = StreamToLogger(self.log)
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                restored, _ = self.upsampler.enhance(img, outscale=4)

            self.log("[INFO] 4x Upscaling complete. Beginning final resize.")

            # 2. Resize to fit within chosen target resolution while preserving aspect ratio
            src_h, src_w = restored.shape[:2]
            out_w, out_h = self._calculate_output_size(src_w, src_h)

            if out_w != src_w or out_h != src_h:
                final = cv2.resize(restored, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            else:
                final = restored

            # 3. Save the final image
            out_path = self.output_folder / f"upscaled_{file.stem}_{out_w}x{out_h}{file.suffix}"
            cv2.imwrite(str(out_path), final)

            self.log(f"[SUCCESS] Saved: {out_path} ({out_w}x{out_h})")

        except Exception as e:
            # Include type + message for easier debugging
            self.log(f"[ERROR] Error processing {file.name}: {type(e).__name__}: {e}")

    def _upscale_video(self, video_path: Path):
        """Upscale a single video file to target resolution using frame batching."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            self.log(f"[ERROR] Failed to open video: {video_path.name}")
            return

        writer = None
        try:
            # Ensure model loaded in the same thread as this call
            if self.upsampler is None:
                self.log("[INFO] Loading model (this may take a while)...")
                self._load_model()
                self.log("[INFO] Model loaded.")

            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Determine batch size: min(FPS, 30) frames for parallel GPU processing
            # 30 is a safe max to prevent VRAM overflow.
            batch_size = min(int(fps), self.VIDEO_BATCH_SIZE)
            if batch_size == 0: # Ensure batch size is at least 1
                batch_size = 1

            self.log(f"[INFO] Input Video: {video_path.name} ({frame_width}x{frame_height}, {fps:.2f} FPS, {frame_count} frames)")
            self.log(f"[INFO] Upscaling {batch_size} frames in parallel batches for speed.")
            self.log("[WARNING] Frame batching bypasses tiling and requires enough VRAM.")

            # Calculate the constant output resolution based on the 4x size and target size
            src_w, src_h = frame_width * 4, frame_height * 4 
            out_w, out_h = self._calculate_output_size(src_w, src_h)

            # Output path and setup (always save as MP4 for compatibility)
            out_name = f"upscaled_{video_path.stem}_{out_w}x{out_h}.mp4"
            out_path = self.output_folder / out_name
            
            # Codec setup (MP4V for MP4 container - widely supported by OpenCV installations)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
            
            writer = cv2.VideoWriter(str(out_path), fourcc, fps, (out_w, out_h))
            if not writer.isOpened():
                self.log("[WARNING] Failed to open video writer with 'mp4v'. Trying 'XVID' fallback...")
                fourcc_fallback = cv2.VideoWriter_fourcc(*'XVID')
                writer = cv2.VideoWriter(str(out_path), fourcc_fallback, fps, (out_w, out_h))
                
                if not writer.isOpened():
                    self.log(f"[ERROR] Failed to open video writer for: {out_path} using 'mp4v' or 'XVID'. Check OpenCV/FFMPEG installation.")
                    cap.release()
                    return

            self.log(f"[INFO] Output Video: {out_path} ({out_w}x{out_h}, {fps:.2f} FPS). Starting frame processing...")

            processed_frames = 0
            current_batch = []
            
            # Redirect stdout/stderr to the GUI logger during enhancement
            stream = StreamToLogger(self.log)

            while cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    current_batch.append(frame)
                
                # Check if batch is full or if we reached the end of the video stream (and have remaining frames)
                if len(current_batch) == batch_size or (not ret and current_batch):
                    
                    self.log(f"[INFO] Processing batch of {len(current_batch)} frames...")
                    
                    # Process the batch
                    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                        final_frames = self._process_frame_batch(current_batch, out_w, out_h)
                    
                    # Write the frames
                    for final_frame in final_frames:
                        writer.write(final_frame)
                        processed_frames += 1
                        
                    # Log progress based on frames written
                    log_interval = max(1, frame_count // 20) # Log every 5% of frames
                    if processed_frames % log_interval == 0 or processed_frames == frame_count:
                        self.log(f"[PROGRESS] Processed {processed_frames}/{frame_count} frames ({processed_frames * 100 / frame_count:.1f}%)")

                    # Reset batch
                    current_batch = []
                    
                if not ret:
                    break # End of video stream

            self.log(f"[SUCCESS] Video processing complete. Total frames written: {processed_frames}")
            self.log(f"[SUCCESS] Saved: {out_path}")

        except Exception as e:
            self.log(f"[ERROR] Error processing video {video_path.name}: {type(e).__name__}: {e}")
        finally:
            # Always release resources
            if cap and cap.isOpened():
                cap.release()
            if writer and writer.isOpened():
                writer.release()


    def _upscale_folder(self, folder: Path):
        """Upscale all supported images and videos in a folder."""
        processed = 0
        for file in folder.iterdir():
            suffix = file.suffix.lower()
            if suffix in self.SUPPORTED_FORMATS:
                # Use the unified upscale method which handles file type internally
                try:
                    # Note: We create a new AnimeUpscaler instance per file in the worker,
                    # so calling upscale() directly here might double process. 
                    # Re-implementing the per-file logic here for correctness.
                    if suffix in self.SUPPORTED_IMAGE_FORMATS:
                        self._upscale_file(file)
                    elif suffix in self.SUPPORTED_VIDEO_FORMATS:
                        self._upscale_video(file)

                    processed += 1
                except Exception as e:
                    self.log(f"[ERROR] Failed to process {file.name} in folder: {e}")
            else:
                self.log(f"[WARNING] Skipped unsupported file in folder: {file.name}")
                
        self.log(f"[SUCCESS] Completed! {processed} file(s) processed from folder.")


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
                self.logged.emit(text)

            total = len(self.input_files)
            if total == 0:
                self.logged.emit("[ERROR] No input files provided to worker.")
                self.finished.emit()
                return

            for idx, input_file in enumerate(self.input_files, start=1):
                # Header for each file
                self.logged.emit(f"[FILE] Processing {idx}/{total}: {input_file.name}")

                if not input_file.exists():
                    self.logged.emit(f"[ERROR] File not found: {input_file}")
                    continue
                
                suffix = input_file.suffix.lower()
                if suffix not in AnimeUpscaler.SUPPORTED_FORMATS:
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
                    
                    # Call the appropriate method based on file type
                    if suffix in AnimeUpscaler.SUPPORTED_IMAGE_FORMATS:
                        upscaler._upscale_file(input_file)
                    elif suffix in AnimeUpscaler.SUPPORTED_VIDEO_FORMATS:
                        upscaler._upscale_video(input_file)
                    
                    self.logged.emit(f"[FILE] Completed {idx}/{total}: {input_file.name}")

                except Exception as e:
                    # Per-file error should not stop the rest of the batch
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
        self.setWindowTitle("Anime Media Upscaler (Image & Video)")
        self.setFixedSize(600, 600)
        self.worker_thread: QThread | None = None
        self.worker: UpscaleWorker | None = None
        self._build_ui()
        self._apply_dark_style()
        self._show_startup_warning()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header
        header = QLabel("Anime Media Upscaler (Image & Video)")
        header.setObjectName("HeaderLabel")
        layout.addWidget(header)

        io_group = QGroupBox("Paths")
        io_layout = QVBoxLayout(io_group)

        # Input file
        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("Input Media:"))
        self.in_edit = QLineEdit()
        self.in_edit.setPlaceholderText("Select one or more image/video files (separated internally)")
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

        settings_layout.addWidget(QLabel("Max Resolution:"))
        self.res_combo = QComboBox()
        # Map label to resolution tuple
        self.label_to_res = {}
        for key, (w, h) in AnimeUpscaler.RESOLUTIONS.items():
            label = f"{key}. {w}x{h}"
            self.res_combo.addItem(label)
            self.label_to_res[label] = (w, h)
        settings_layout.addWidget(self.res_combo)
        
        # Add warning for video processing time
        note = QLabel("Note: Video processing is significantly slower.")
        note.setStyleSheet("color: orange;")
        settings_layout.addWidget(note)

        layout.addWidget(settings_group)

        # Controls
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start Upscaling")
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
            "Important Notice: Video Batch Processing",
            (
                "Video upscaling is now significantly faster using **GPU batch processing** (up to 30 frames at a time).\n\n"
                "**WARNING:** This speedup comes at the cost of higher **VRAM usage**. If your video frames are very large or you select a high batch size, you may experience crashes on GPUs with limited memory."
            ),
        )

    def _append_log(self, text: str):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    @Slot()
    def _on_browse_input(self):
        # Update the filter string to include video formats
        filter_str = "Media Files (*.png *.jpg *.jpeg *.bmp; *.mp4 *.avi *.mkv *.mov)"
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select One or More Input Images or Videos",
            str(Path.cwd()),
            filter_str,
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
            self._append_log("[ERROR] Please select at least one input file (image or video).")
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
            self._append_log("[ERROR] No valid image or video files found in the input field.")
            return

        # Disable UI while running
        self.start_btn.setEnabled(False)
        self.browse_in_btn.setEnabled(False)
        self.browse_out_btn.setEnabled(False)
        self.res_combo.setEnabled(False)
        self.log_view.clear()
        self._append_log("Starting media upscaling batch...")

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
    # Ensure a QApplication instance is available for PySide6
    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()
        
    w = AnimeUpscalerApp()
    w.show()
    sys.exit(app.exec())
