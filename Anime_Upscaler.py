import cv2
import torch
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional
import contextlib
import io
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QComboBox, QMessageBox, QGroupBox,
)


def find_model_in_syspath(model_filename: str) -> Path:
    print(f"[DEBUG] Searching for model: {model_filename}")
    current_dir_path = Path(model_filename)
    if current_dir_path.exists():
        print(f"[SUCCESS] Found model in current directory: {current_dir_path}")
        return current_dir_path
    for path_entry in sys.path:
        if os.path.isdir(path_entry):
            model_path = Path(path_entry) / model_filename
            if model_path.exists():
                print(f"[SUCCESS] Found model in sys.path: {model_path}")
                return model_path
    raise FileNotFoundError(
        f"Model file '{model_filename}' not found. Place it in project root or sys.path."
    )


class StreamToLogger(io.TextIOBase):
    def __init__(self, logger: Callable[[str], None]):
        self.logger = logger
        self._buf = ""

    def write(self, s):
        if not s:
            return
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            try:
                self.logger(line)
            except Exception:
                pass

    def flush(self):
        if self._buf:
            try:
                self.logger(self._buf)
            except Exception:
                pass
            self._buf = ""


class AnimeUpscaler:
    SUPPORTED_IMAGE_FORMATS = (".png", ".jpg", ".jpeg", ".bmp")
    SUPPORTED_VIDEO_FORMATS = (".mp4", ".avi", ".mkv", ".mov")
    SUPPORTED_FORMATS = SUPPORTED_IMAGE_FORMATS + SUPPORTED_VIDEO_FORMATS
    MODEL_FILENAME = "RealESRGAN_x4plus_anime_6B.pth"
    RESOLUTIONS = {
        "1": (3840, 2160),
        "2": (7680, 4320),
        "3": (15360, 8640),
        "4": (30720, 17280),
        "5": (61440, 34560),
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
        self.input_path = Path(input_path)
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.logger = logger
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if self.device.type == "cuda":
            self._log_to_console("[INFO] CUDA GPU detected.")
        else:
            self._log_to_console("[WARNING] CUDA GPU not detected, using CPU.")

        self.tile = tile
        self.tile_pad = tile_pad
        self.upsampler = None
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input path not found: {self.input_path}")
        self.output_folder.mkdir(parents=True, exist_ok=True)

    def _log_to_console(self, message: str):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        print(f"{timestamp} {message}")

    def _load_model(self):
        model_path = find_model_in_syspath(self.MODEL_FILENAME)
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer

        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
        self.upsampler = RealESRGANer(
            scale=4,
            model_path=str(model_path),
            model=model,
            tile=self.tile,
            tile_pad=self.tile_pad,
            pre_pad=0,
            half=(self.device.type == "cuda"),
            device=self.device,
        )
        return self.upsampler

    def log(self, message: str):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        text = f"{timestamp} {message}"
        if self.logger:
            try:
                self.logger(text)
                return
            except Exception:
                pass
        print(text)

    def _calculate_output_size(self, source_w: int, source_h: int) -> tuple[int, int]:
        target_w, target_h = self.target_res
        scale = min(target_w / source_w, target_h / source_h)
        out_w = max(1, int(source_w * scale) // 2 * 2)
        out_h = max(1, int(source_h * scale) // 2 * 2)
        return (out_w, out_h)

    def _upscale_file(self, file: Path):
        img = cv2.imread(str(file), cv2.IMREAD_COLOR)
        if img is None:
            self.log(f"[ERROR] Failed to load: {file.name}")
            return
        if self.upsampler is None:
            self.log("[INFO] Loading model...")
            self._load_model()
            self.log("[INFO] Model loaded.")
        img_height, img_width = img.shape[:2]
        self.log(f"[INFO] Upscaling image {file.name} ({img_width}x{img_height})")
        stream = StreamToLogger(self.log)
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            restored, _ = self.upsampler.enhance(img, outscale=4)
        out_w, out_h = self._calculate_output_size(*restored.shape[1::-1])
        final = cv2.resize(restored, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        out_path = self.output_folder / f"upscaled_{file.stem}_{out_w}x{out_h}{file.suffix}"
        cv2.imwrite(str(out_path), final)
        self.log(f"[SUCCESS] Saved: {out_path}")

    def _process_frame(self, frame_idx: int, frame):
        # Per-frame processing for parallel execution
        restored, _ = self.upsampler.enhance(frame, outscale=4)
        out_w, out_h = self._calculate_output_size(*restored.shape[1::-1])
        final = cv2.resize(restored, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        return frame_idx, final

    def _upscale_video(self, video_path: Path):
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            self.log(f"[ERROR] Failed to open video: {video_path.name}")
            return
        if self.upsampler is None:
            self.log("[INFO] Loading model...")
            self._load_model()
            self.log("[INFO] Model loaded.")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.log(f"[INFO] Input Video: {video_path.name} ({frame_width}x{frame_height}, {fps:.2f} FPS, {frame_count} frames)")

        src_w, src_h = frame_width * 4, frame_height * 4
        out_w, out_h = self._calculate_output_size(src_w, src_h)
        out_path = self.output_folder / f"upscaled_{video_path.stem}_{out_w}x{out_h}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(out_path), fourcc, fps, (out_w, out_h))
        if not writer.isOpened():
            self.log("[WARNING] mp4v failed, trying XVID...")
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            writer = cv2.VideoWriter(str(out_path), fourcc, fps, (out_w, out_h))
            if not writer.isOpened():
                self.log(f"[ERROR] VideoWriter failed: {out_path}")
                cap.release()
                return

        frames = []
        idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frames.append((idx, frame))
            idx += 1
        cap.release()
        self.log(f"[INFO] Total frames loaded: {len(frames)}")

        max_workers = min(int(fps), len(frames))
        self.log(f"[INFO] Processing frames in parallel: {max_workers} workers")

        processed_frames = [None] * len(frames)
        stream = StreamToLogger(self.log)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._process_frame, idx, frame): idx for idx, frame in frames}
            for future in as_completed(futures):
                try:
                    idx, result = future.result()
                    processed_frames[idx] = result
                    if idx % 50 == 0 or idx == len(frames) - 1:
                        self.log(f"[PROGRESS] Processed frame {idx+1}/{len(frames)}")
                except Exception as e:
                    self.log(f"[ERROR] Frame processing error: {e}")

        for f in processed_frames:
            writer.write(f)
        writer.release()
        self.log(f"[SUCCESS] Video saved: {out_path} ({len(processed_frames)} frames)")


class UpscaleWorker(QObject):
    finished = Signal()
    errored = Signal(str)
    logged = Signal(str)

    def __init__(self, input_files: list[Path], output_folder: Path, target_res: tuple, tile: int, tile_pad: int):
        super().__init__()
        self.input_files = [Path(f) for f in input_files]
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.tile = tile
        self.tile_pad = tile_pad

    @Slot()
    def run(self):
        def gui_logger(text: str):
            self.logged.emit(text)
        total = len(self.input_files)
        if total == 0:
            self.logged.emit("[ERROR] No input files provided.")
            self.finished.emit()
            return
        for idx, input_file in enumerate(self.input_files, start=1):
            self.logged.emit(f"[FILE] Processing {idx}/{total}: {input_file.name}")
            try:
                upscaler = AnimeUpscaler(input_path=input_file, output_folder=self.output_folder,
                                         target_res=self.target_res, tile=self.tile, tile_pad=self.tile_pad,
                                         logger=gui_logger)
                if input_file.suffix.lower() in AnimeUpscaler.SUPPORTED_IMAGE_FORMATS:
                    upscaler._upscale_file(input_file)
                elif input_file.suffix.lower() in AnimeUpscaler.SUPPORTED_VIDEO_FORMATS:
                    upscaler._upscale_video(input_file)
                self.logged.emit(f"[FILE] Completed {idx}/{total}: {input_file.name}")
            except Exception as e:
                self.errored.emit(f"{type(e).__name__}: {e}")
                self.logged.emit(f"[ERROR] Failed {input_file.name}, continuing.")
        self.logged.emit(f"[SUCCESS] Batch finished: {total} files attempted.")
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
        header = QLabel("Anime Media Upscaler (Image & Video)")
        header.setObjectName("HeaderLabel")
        layout.addWidget(header)

        io_group = QGroupBox("Paths")
        io_layout = QVBoxLayout(io_group)

        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("Input Media:"))
        self.in_edit = QLineEdit()
        row_in.addWidget(self.in_edit)
        self.browse_in_btn = QPushButton("Browse")
        self.browse_in_btn.clicked.connect(self._on_browse_input)
        row_in.addWidget(self.browse_in_btn)
        io_layout.addLayout(row_in)

        row_out = QHBoxLayout()
        row_out.addWidget(QLabel("Output Folder:"))
        self.out_edit = QLineEdit()
        row_out.addWidget(self.out_edit)
        self.browse_out_btn = QPushButton("Browse")
        self.browse_out_btn.clicked.connect(self._on_browse_output)
        row_out.addWidget(self.browse_out_btn)
        io_layout.addLayout(row_out)
        layout.addWidget(io_group)

        settings_group = QGroupBox("Settings")
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.addWidget(QLabel("Max Resolution:"))
        self.res_combo = QComboBox()
        self.label_to_res = {}
        for key, (w, h) in AnimeUpscaler.RESOLUTIONS.items():
            label = f"{key}. {w}x{h}"
            self.res_combo.addItem(label)
            self.label_to_res[label] = (w, h)
        settings_layout.addWidget(self.res_combo)
        note = QLabel("Note: Video processing is parallelized per FPS.")
        note.setStyleSheet("color: orange;")
        settings_layout.addWidget(note)
        layout.addWidget(settings_group)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start Upscaling")
        self.start_btn.clicked.connect(self._on_start)
        controls.addWidget(self.start_btn)
        layout.addLayout(controls)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

    def _apply_dark_style(self):
        self.setStyleSheet(
            """
            QWidget { background-color: #0e0e0e; color: #e6e6e6; }
            #HeaderLabel { font-size: 18px; font-weight: bold; padding: 4px 0; }
            QLineEdit, QComboBox, QTextEdit, QPushButton { background-color: #1a1a1a; color: #e6e6e6; border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px; }
            QPushButton:hover { background-color: #3a3a3a; }
            """
        )

    def _show_startup_warning(self):
        QMessageBox.warning(
            self,
            "Important Notice: Video Support",
            (
                "This tool supports image & video upscaling.\n"
                "Video frames are now processed in parallel (based on FPS).\n"
                "High resolutions may use significant memory."
            ),
        )

    def _append_log(self, text: str):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    @Slot()
    def _on_browse_input(self):
        filter_str = "Media Files (*.png *.jpg *.jpeg *.bmp; *.mp4 *.avi *.mkv *.mov)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Input Media", str(Path.cwd()), filter_str)
        if files:
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
        if not input_path or not output_folder:
            self._append_log("[ERROR] Input files and output folder required.")
            return
        label = self.res_combo.currentText()
        target_res = self.label_to_res.get(label, (3840, 2160))
        input_files = [p.strip() for p in input_path.split(";") if p.strip()]
        self.start_btn.setEnabled(False)
        self.browse_in_btn.setEnabled(False)
        self.browse_out_btn.setEnabled(False)
        self.res_combo.setEnabled(False)
        self.log_view.clear()
        self._append_log("Starting media upscaling batch...")

        self.worker_thread = QThread()
        self.worker = UpscaleWorker(input_files, Path(output_folder), target_res, tile=128, tile_pad=8)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.logged.connect(self._append_log)
        self.worker.errored.connect(lambda m: self._append_log(f"[ERROR] {m}"))
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_thread)
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
        if self.worker:
            self.worker.deleteLater()
        if self.worker_thread:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    w = AnimeUpscalerApp()
    w.show()
    sys.exit(app.exec())
