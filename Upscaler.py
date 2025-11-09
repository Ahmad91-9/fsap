import os
import sys
import cv2
import torch
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from basicsr.archs.srvgg_arch import SRVGGNetCompact
from realesrgan import RealESRGANer

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTextEdit,
    QComboBox, QGroupBox
)


# =============================
# Utility: Find model in sys.path
# =============================
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

    print(f"[ERROR] Model '{model_filename}' not found.")
    raise FileNotFoundError(
        f"Model file '{model_filename}' not found. "
        f"Please place it in the project root directory: {sys.path[0] if sys.path else Path.cwd()}"
    )


# =============================
# Core Upscaler
# =============================
class GeneralUpscaler:
    """General Image Upscaler with selectable target resolution."""

    SUPPORTED_FORMATS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff")
    MODEL_FILENAME = "realesr-general-x4v3.pth"

    RESOLUTIONS = {
        "1": (3840, 2160),     # 4K
        "2": (7680, 4320),     # 8K
        "3": (15360, 8640),    # 16K
        "4": (30720, 17280),   # 32K
        "5": (61440, 34560),   # 64K
    }

    def __init__(self, input_files: list[Path], output_folder: Path,
                 target_res: tuple, tile: int = 256, tile_pad: int = 10,
                 logger: Optional[Callable[[str], None]] = None):

        self.input_files = [Path(p) for p in input_files]
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.logger = logger
        self.tile = tile
        self.tile_pad = tile_pad

        # Safe CUDA check
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")
            self.log("⚠️ CUDA GPU not detected, using CPU (very slow).")

        # Ensure output directory
        self.output_folder.mkdir(parents=True, exist_ok=True)

        # Lazy model loading
        self.upsampler = None

    def log(self, message: str):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        text = f"{timestamp} {message}"
        if self.logger:
            try:
                self.logger(text)
                return
            except Exception:
                pass
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode('ascii', 'replace').decode('ascii'))

    def _load_model(self):
        if self.upsampler is not None:
            return self.upsampler

        self.log("🔄 Loading RealESRGAN model... (this may take time)")

        try:
            model_path = find_model_in_syspath(self.MODEL_FILENAME)
        except FileNotFoundError as e:
            raise FileNotFoundError(str(e))

        model = SRVGGNetCompact(
            num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32,
            upscale=4, act_type='prelu'
        )

        upsampler = RealESRGANer(
            scale=4,
            model_path=str(model_path),
            model=model,
            tile=self.tile,
            tile_pad=self.tile_pad,
            pre_pad=0,
            half=torch.cuda.is_available(),
            device=self.device,
        )

        # Hook tile logs into GUI
        def hooked_enhance(*args, **kwargs):
            self.log("🧩 Processing tiles... please wait.")
            result = upsampler._enhance(*args, **kwargs)
            self.log("✅ Tile processing complete.")
            return result

        upsampler._enhance = upsampler.enhance
        upsampler.enhance = hooked_enhance

        self.upsampler = upsampler
        self.log("✅ Model loaded successfully.")
        return self.upsampler

    def upscale_all(self):
        self._load_model()
        total = len(self.input_files)
        for i, file in enumerate(self.input_files, 1):
            self.log(f"📂 [{i}/{total}] Processing: {file.name}")
            self._upscale_file(file)
        self.log(f"🎉 Completed! {total} image(s) processed successfully.")

    def _upscale_file(self, file: Path):
        if file.suffix.lower() not in self.SUPPORTED_FORMATS:
            self.log(f"⚠️ Skipped unsupported file: {file.name}")
            return

        img = cv2.imread(str(file), cv2.IMREAD_COLOR)
        if img is None:
            self.log(f"❌ Failed to load: {file.name}")
            return

        try:
            restored, _ = self.upsampler.enhance(img, outscale=4)
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
            self.log(f"✅ Saved: {out_path}")
        except Exception as e:
            self.log(f"❌ Error processing {file.name}: {e}")


# =============================
# Worker Thread
# =============================
class UpscaleWorker(QObject):
    finished = Signal()
    errored = Signal(str)
    logged = Signal(str)

    def __init__(self, input_files, output_folder, target_res, tile, tile_pad):
        super().__init__()
        self.input_files = input_files
        self.output_folder = Path(output_folder)
        self.target_res = target_res
        self.tile = tile
        self.tile_pad = tile_pad

    @Slot()
    def run(self):
        try:
            def gui_logger(text: str):
                self.logged.emit(text)

            upscaler = GeneralUpscaler(
                input_files=self.input_files,
                output_folder=self.output_folder,
                target_res=self.target_res,
                tile=self.tile,
                tile_pad=self.tile_pad,
                logger=gui_logger,
            )
            upscaler.upscale_all()
            self.finished.emit()
        except Exception as e:
            self.errored.emit(str(e))
            self.finished.emit()


# =============================
# GUI Application
# =============================
class GeneralUpscalerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("General Image Upscaler")
        self.setFixedSize(600, 600)
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[UpscaleWorker] = None
        self._build_ui()
        self._apply_dark_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("General Image Upscaler")
        header.setObjectName("HeaderLabel")
        layout.addWidget(header)

        io_group = QGroupBox("Paths")
        io_layout = QVBoxLayout(io_group)

        # Input
        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("Input Images:"))
        self.in_edit = QLineEdit()
        self.in_edit.setPlaceholderText("Select one or more images...")
        row_in.addWidget(self.in_edit)
        self.browse_in_btn = QPushButton("Browse")
        self.browse_in_btn.clicked.connect(self._on_browse_input)
        row_in.addWidget(self.browse_in_btn)
        io_layout.addLayout(row_in)

        # Output
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
        self.label_to_res = {}
        for key, (w, h) in GeneralUpscaler.RESOLUTIONS.items():
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
        layout.addWidget(self.log_view)

    def _apply_dark_style(self):
        self.setStyleSheet("""
            QWidget { background-color: #0e0e0e; color: #e6e6e6; }
            #HeaderLabel { font-size: 18px; font-weight: bold; padding: 4px 0; }
            QGroupBox { border: 1px solid #333333; border-radius: 6px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #1a1a1a; color: #e6e6e6; border: 1px solid #3a3a3a;
                padding: 6px; border-radius: 4px;
            }
            QPushButton {
                background-color: #2b2b2b; color: #e6e6e6;
                border: 1px solid #4a4a4a; padding: 6px 12px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

    def _append_log(self, text: str):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    @Slot()
    def _on_browse_input(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select One or More Images", str(Path.cwd()),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tiff)"
        )
        if files:
            self.in_edit.setText(";".join(files))

    @Slot()
    def _on_browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

    @Slot()
    def _on_start(self):
        input_text = self.in_edit.text().strip()
        if not input_text:
            self._append_log("❌ Please select input images.")
            return

        output_folder = self.out_edit.text().strip()
        if not output_folder:
            self._append_log("❌ Please select output folder.")
            return

        input_files = [Path(p.strip()) for p in input_text.split(";") if p.strip()]
        label = self.res_combo.currentText()
        target_res = self.label_to_res.get(label, (3840, 2160))

        tile, tile_pad = 128, 8

        self.start_btn.setEnabled(False)
        self.log_view.clear()
        self._append_log("🚀 Starting upscaling thread...")

        self.worker_thread = QThread()
        self.worker = UpscaleWorker(input_files, output_folder, target_res, tile, tile_pad)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.logged.connect(self._append_log)
        self.worker.errored.connect(lambda m: self._append_log(f"❌ {m}"))
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_thread)

        self.worker_thread.start()

    @Slot()
    def _on_finished(self):
        self._append_log("✅ Done.")
        self.start_btn.setEnabled(True)

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


# =============================
# Entry Point
# =============================
if __name__ == "__main__":
    app = QApplication([])
    w = GeneralUpscalerApp()
    w.show()
    sys.exit(app.exec())
