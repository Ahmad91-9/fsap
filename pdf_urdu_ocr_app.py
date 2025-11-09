"""
PDF + Image Urdu OCR Desktop App

Single-file PySide6 desktop application that:
- Loads your YOLOv8 detector (yolov8m_UrduDoc.pt) and your trained recognizer (best_norm_ED.pth)
- Uses your Model, CTCLabelConverter and text_recognizer from your repository
- Accepts images or PDFs, runs detection+recognition on a background thread
- Shows the image with bounding boxes (preview) and the recognized Urdu text (right pane)
- Provides "Save to DOCX" button

Requirements (pip):
    pip install pymupdf PySide6 pillow python-docx numpy opencv-python pytesseract ultralytics torch

Place these files in the PDFOCR folder (or they'll be auto-detected):
- UrduGlyphs.txt
- best_norm_ED.pth (recognizer)
- yolov8m_UrduDoc.pt (detector)

PORTABILITY:
This script can be placed ANYWHERE and will automatically find the PDFOCR folder!
The script searches for dependencies in the following order:
1. If script is inside the PDFOCR directory
2. If PDFOCR folder exists in the same directory as the script
3. Searches up the directory tree (up to 5 levels) for a PDFOCR folder
4. Checks for 'modules' subdirectory to confirm PDFOCR location

This means you can:
- Copy this script to your desktop and run it
- Place it in the workspace root
- Put it in any subdirectory
- And it will STILL find the PDFOCR folder and import all dependencies!

Run: python pdf_urdu_ocr_app.py
"""

import os
import sys
import traceback
import time
from typing import List, Tuple, Optional, Dict

# ============================================================================
# ROBUST CROSS-MODULE IMPORT PATTERN
# This allows the script to find dependencies in the PDFOCR folder
# regardless of where this script is placed
# ============================================================================

def setup_module_path():
    """Setup sys.path to include PDFOCR directory for imports.
    
    Search strategy:
    1. Try from current script directory (if script is inside PDFOCR)
    2. Try from parent directory (if PDFOCR folder exists there)
    3. Try to find PDFOCR folder in common locations
    """
    print("[DEBUG] Starting module path setup...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"[DEBUG] Script directory: {script_dir}")
    
    # Strategy 1: Current directory is already PDFOCR (script is inside PDFOCR)
    if os.path.basename(script_dir) == 'PDFOCR':
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
            print(f"[SUCCESS] Added PDFOCR directory to path: {script_dir}")
        return script_dir
    
    # Strategy 2: Look for PDFOCR folder in the same directory as script
    pdfocr_same_level = os.path.join(script_dir, 'PDFOCR')
    if os.path.isdir(pdfocr_same_level):
        if pdfocr_same_level not in sys.path:
            sys.path.insert(0, pdfocr_same_level)
            print(f"[SUCCESS] Added PDFOCR directory to path: {pdfocr_same_level}")
        return pdfocr_same_level
    
    # Strategy 3: Go up directory tree to find PDFOCR folder
    current = script_dir
    for _ in range(5):  # Search up to 5 levels
        parent = os.path.dirname(current)
        if parent == current:  # Reached root
            break
        pdfocr_in_parent = os.path.join(parent, 'PDFOCR')
        if os.path.isdir(pdfocr_in_parent):
            if pdfocr_in_parent not in sys.path:
                sys.path.insert(0, pdfocr_in_parent)
                print(f"[SUCCESS] Added PDFOCR directory to path: {pdfocr_in_parent}")
            return pdfocr_in_parent
        current = parent
    
    # Strategy 4: Search in sys.path entries (for when launched from main.py)
    # This is crucial when script is downloaded to temp but main.py root is in sys.path
    print("[DEBUG] Searching for PDFOCR in sys.path entries...")
    for path_entry in sys.path:
        if os.path.isdir(path_entry):
            pdfocr_in_syspath = os.path.join(path_entry, 'PDFOCR')
            if os.path.isdir(pdfocr_in_syspath):
                # Verify it's the right PDFOCR by checking for modules subdirectory
                modules_check = os.path.join(pdfocr_in_syspath, 'modules')
                if os.path.isdir(modules_check):
                    # CRITICAL: Remove it first if already in path, then insert at position 0
                    # This ensures PDFOCR is FIRST, before src/src/utils.py
                    if pdfocr_in_syspath in sys.path:
                        sys.path.remove(pdfocr_in_syspath)
                    sys.path.insert(0, pdfocr_in_syspath)
                    print(f"[SUCCESS] Found PDFOCR in sys.path entry: {pdfocr_in_syspath}")
                    print(f"[DEBUG] PDFOCR now at sys.path[0] to prioritize imports")
                    return pdfocr_in_syspath
    
    # Strategy 5: Check if modules subdirectory exists nearby
    modules_dir = os.path.join(script_dir, 'modules')
    if os.path.isdir(modules_dir):
        # Script is likely in PDFOCR already
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
            print(f"[SUCCESS] Found modules/ subdirectory, added script dir to path: {script_dir}")
        return script_dir
    
    print("[WARNING] Could not locate PDFOCR directory automatically")
    print(f"[INFO] Current sys.path: {sys.path}")
    return None

# Setup module path before imports
PDFOCR_DIR = setup_module_path()

# Debug: Show sys.path order after setup
print("[DEBUG] sys.path after setup (first 5 entries):")
for i, path in enumerate(sys.path[:5]):
    print(f"  [{i}] {path}")

# CRITICAL: Clear any cached modules that might be from wrong location
# This ensures our imports ONLY get modules from PDFOCR, not src/src
modules_to_clear = ['utils', 'read', 'model']
for module_name in modules_to_clear:
    if module_name in sys.modules:
        cached_path = sys.modules[module_name].__file__ if hasattr(sys.modules[module_name], '__file__') else 'unknown'
        print(f"[DEBUG] Found cached {module_name} module from: {cached_path}")
        # Only keep it if it's from PDFOCR directory
        if PDFOCR_DIR and cached_path and PDFOCR_DIR in cached_path:
            print(f"[DEBUG] Cached {module_name} is from PDFOCR, keeping it")
        else:
            print(f"[DEBUG] Clearing cached {module_name} module (not from PDFOCR)")
            del sys.modules[module_name]

# Model imports (from user's repo)
try:
    import torch
    print("[SUCCESS] Imported torch")
except Exception as e:
    print(f"[ERROR] Failed to import torch: {e}")
    torch = None
    TORCH_IMPORT_ERROR = e

try:
    from read import text_recognizer
    print("[SUCCESS] Imported text_recognizer from read")
    # Debug: Check where read module is from
    import read
    print(f"[DEBUG] read module location: {read.__file__}")
except Exception as e:
    print(f"[ERROR] Failed to import from read: {e}")
    text_recognizer = None
    if 'TORCH_IMPORT_ERROR' not in globals():
        TORCH_IMPORT_ERROR = e

try:
    from model import Model
    print("[SUCCESS] Imported Model from model")
    # Debug: Check where model module is from
    import model
    print(f"[DEBUG] model module location: {model.__file__}")
except Exception as e:
    print(f"[ERROR] Failed to import from model: {e}")
    Model = None
    if 'TORCH_IMPORT_ERROR' not in globals():
        TORCH_IMPORT_ERROR = e

try:
    from utils import CTCLabelConverter
    print("[SUCCESS] Imported CTCLabelConverter from utils")
    # Debug: Check where utils module is from
    import utils
    print(f"[DEBUG] utils module location: {utils.__file__}")
except Exception as e:
    print(f"[ERROR] Failed to import from utils: {e}")
    print(f"[DEBUG] Trying to find utils in sys.path...")
    import importlib.util
    for path in sys.path[:5]:
        utils_path = os.path.join(path, 'utils.py')
        if os.path.exists(utils_path):
            print(f"[DEBUG] Found utils.py at: {utils_path}")
    CTCLabelConverter = None
    if 'TORCH_IMPORT_ERROR' not in globals():
        TORCH_IMPORT_ERROR = e

# Set error flag if any imports failed
if torch is None or text_recognizer is None or Model is None or CTCLabelConverter is None:
    if 'TORCH_IMPORT_ERROR' not in globals():
        TORCH_IMPORT_ERROR = Exception("One or more required modules failed to import")
    print("[WARNING] Some imports failed. Model functionality may be limited.")
else:
    TORCH_IMPORT_ERROR = None
    print("[SUCCESS] All model imports successful!")

# YOLO
try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

# Imaging / PDF
try:
    import fitz  # PyMuPDF
    from PIL import Image, ImageDraw, ImageQt
except Exception as e:
    raise RuntimeError("Install requirements: pymupdf pillow")

# GUI
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QFileDialog, QLabel, QPushButton, QWidget,
        QVBoxLayout, QHBoxLayout, QTextEdit, QProgressBar, QLineEdit, QMessageBox, QCheckBox,
        QSpinBox, QGroupBox
    )
    from PySide6.QtCore import Qt, QThread, Signal, QSize
    from PySide6.QtGui import QPixmap
except Exception:
    raise RuntimeError("PySide6 required. pip install PySide6")

# DOCX
try:
    from docx import Document
except Exception:
    Document = None

# Helpers

def pil_from_pixmap(pix: fitz.Pixmap) -> Image.Image:
    mode = "RGBA" if pix.alpha else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    if mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img


def pil_to_qpixmap(img: Image.Image, max_size: Optional[Tuple[int,int]] = None) -> QPixmap:
    if max_size:
        img = img.copy()
        img.thumbnail(max_size, Image.LANCZOS)
    qimg = ImageQt.ImageQt(img)
    pix = QPixmap.fromImage(qimg)
    return pix

# Worker thread for processing
class OCRWorker(QThread):
    progress = Signal(int)
    finished = Signal(str, object)  # recognized_text, preview PIL.Image
    page_processed = Signal(int, object, str)  # page_num, preview_image, page_text
    file_progress = Signal(int, int, str, int, int)  # file_index, total_files, filename, current_page, total_pages_in_file
    error = Signal(str)

    def __init__(self, paths: List[str], yolo_path: Optional[str], recog_path: Optional[str], glyphs_path: Optional[str], device:str='cuda' if torch and torch.cuda.is_available() else 'cpu'):
        super().__init__()
        self.paths = paths
        self.yolo_path = yolo_path
        self.recog_path = recog_path
        self.glyphs_path = glyphs_path
        self.device = device
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            # Validate imports
            if 'TORCH_IMPORT_ERROR' in globals() and TORCH_IMPORT_ERROR is not None:
                raise RuntimeError(f"Recognizer imports failed: {TORCH_IMPORT_ERROR}")

            # load vocab
            if not self.glyphs_path or not os.path.exists(self.glyphs_path):
                raise RuntimeError("UrduGlyphs.txt not found. Please provide path in UI.")
            with open(self.glyphs_path, 'r', encoding='utf-8') as f:
                content = f.readlines()
            content = ''.join([str(elem).strip('\n') for elem in content])
            content = content + ' '
            converter = CTCLabelConverter(content)

            # load recognition model
            if not self.recog_path or not os.path.exists(self.recog_path):
                raise RuntimeError("Recognition model (.pth) not found. Select best_norm_ED.pth in UI.")
            device = torch.device(self.device)
            recog_model = Model(num_class=len(converter.character), device=device)
            recog_model = recog_model.to(device)
            state = torch.load(self.recog_path, map_location=device)
            recog_model.load_state_dict(state)
            recog_model.eval()

            # load detection model (YOLO)
            detector = None
            if self.yolo_path:
                if YOLO is None:
                    raise RuntimeError("ultralytics YOLO not installed. pip install ultralytics")
                if not os.path.exists(self.yolo_path):
                    raise RuntimeError("YOLO model path invalid.")
                detector = YOLO(self.yolo_path)

            collected_text_lines: List[str] = []
            preview_img: Optional[Image.Image] = None
            total_files = len(self.paths)
            processed = 0
            page_count = 0

            for file_index, path in enumerate(self.paths):
                if self._is_cancelled:
                    break
                basename = os.path.basename(path)
                
                # handle PDF
                if path.lower().endswith('.pdf'):
                    doc = fitz.open(path)
                    total_pages_in_file = len(doc)
                    
                    for pno in range(total_pages_in_file):
                        if self._is_cancelled: break
                        page = doc[pno]
                        mat = fitz.Matrix(300/72.0, 300/72.0)  # 300 dpi
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        pil_img = pil_from_pixmap(pix)
                        page_text, page_preview_img = self._process_image(pil_img, detector, recog_model, converter, device)
                        
                        # Emit file progress
                        self.file_progress.emit(file_index + 1, total_files, basename, pno + 1, total_pages_in_file)
                        
                        # Emit page data for navigation
                        page_count += 1
                        page_text_str = "\n".join(page_text) if page_text else ""
                        self.page_processed.emit(page_count, page_preview_img, page_text_str)
                        
                        if page_text:
                            collected_text_lines.append(f"--- Page {pno+1} ({basename}) ---")
                            collected_text_lines.extend(page_text)
                        preview_img = page_preview_img  # Keep last page as final preview
                        processed += 1
                        self.progress.emit(int((processed/total_files)*100))
                    doc.close()
                else:
                    # Single image file
                    self.file_progress.emit(file_index + 1, total_files, basename, 1, 1)
                    
                    pil_img = Image.open(path).convert('RGB')
                    page_text, page_preview_img = self._process_image(pil_img, detector, recog_model, converter, device)
                    
                    # Emit page data for navigation
                    page_count += 1
                    page_text_str = "\n".join(page_text) if page_text else ""
                    self.page_processed.emit(page_count, page_preview_img, page_text_str)
                    
                    if page_text:
                        collected_text_lines.append(f"--- {basename} ---")
                        collected_text_lines.extend(page_text)
                    preview_img = page_preview_img  # Keep as final preview
                    processed += 1
                    self.progress.emit(int((processed/total_files)*100))

            final_text = "\n".join(collected_text_lines)
            self.finished.emit(final_text, preview_img)
        except Exception as e:
            tb = traceback.format_exc()
            self.error.emit(f"OCRWorker error: {e}\n{tb}")

    def _process_image(self, pil_img: Image.Image, detector, recog_model, converter, device) -> Tuple[List[str], Image.Image]:
        """Run detection (if available) + recognition on an image. Returns list of recognized lines and preview image with boxes."""
        draw = ImageDraw.Draw(pil_img)
        texts: List[str] = []

        if detector is not None:
            # run detector on PIL image, use same options as your gradio snippet
            results = detector.predict(source=pil_img, conf=0.2, imgsz=1280, save=False, nms=True, device=device)
            boxes = []
            if results and len(results) > 0:
                r = results[0]
                if hasattr(r, 'boxes') and r.boxes is not None:
                    for b in r.boxes:
                        try:
                            xy = b.xyxy.cpu().numpy().ravel() if hasattr(b.xyxy, 'cpu') else b.xyxy
                        except Exception:
                            xy = b.xyxy
                        boxes.append([float(xy[0]), float(xy[1]), float(xy[2]), float(xy[3])])
            # sort top->bottom
            boxes.sort(key=lambda x: x[1])

            # draw boxes and recognize
            for box in boxes:
                if self._is_cancelled: break
                # crop box
                x0,y0,x1,y1 = [int(v) for v in box]
                # pad slightly
                pad_x = max(4, int(0.02*(x1-x0)))
                pad_y = max(4, int(0.02*(y1-y0)))
                rx0 = max(0, x0-pad_x); ry0 = max(0, y0-pad_y)
                rx1 = min(pil_img.width, x1+pad_x); ry1 = min(pil_img.height, y1+pad_y)
                crop = pil_img.crop((rx0,ry0,rx1,ry1))
                # recognize
                try:
                    txt = text_recognizer(crop, recog_model, converter, device)
                except Exception as e:
                    txt = ""
                texts.append(txt.strip())
                # draw rectangle
                draw.rectangle([x0,y0,x1,y1], outline=(255,0,0), width=3)
        else:
            # fallback: use tesseract via pytesseract if available (not ideal but better than nothing)
            try:
                import pytesseract
                pp = pil_img.convert('L')
                pp = pp.resize((int(pp.width*1.0), int(pp.height*1.0)), Image.LANCZOS)
                ocr_text = pytesseract.image_to_string(pp, lang='urd') if pytesseract else ''
                texts = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
            except Exception:
                texts = []

        return texts, pil_img

# Main UI
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PDF Urdu OCR — Desktop')
        self.resize(1100,700)
        # Maximize the window on startup
        self.showMaximized()

        # UI elements
        central = QWidget(); mainlay = QHBoxLayout(central)

        left = QVBoxLayout()
        btn_open = QPushButton('Open Files (PDF / Images)')
        btn_open.clicked.connect(self.open_files)
        left.addWidget(btn_open)

        self.lst_files = QLineEdit(); self.lst_files.setReadOnly(True)
        left.addWidget(self.lst_files)

        # model selection - auto-detect files in same directory
        self.input_glyphs = QLineEdit(); self.input_glyphs.setPlaceholderText('Auto-detected UrduGlyphs.txt')
        self.input_glyphs.setReadOnly(True)
        left.addWidget(self.input_glyphs)

        self.input_recog = QLineEdit(); self.input_recog.setPlaceholderText('Auto-detected best_norm_ED.pth')
        self.input_recog.setReadOnly(True)
        left.addWidget(self.input_recog)

        self.chk_yolo = QCheckBox('Use YOLO detector (recommended)')
        self.chk_yolo.setChecked(True)
        self.input_yolo = QLineEdit(); self.input_yolo.setPlaceholderText('Auto-detected yolov8m_UrduDoc.pt')
        self.input_yolo.setReadOnly(True)
        left.addWidget(self.chk_yolo); left.addWidget(self.input_yolo)

        # device option
        self.input_device = QLineEdit(); self.input_device.setPlaceholderText("Device (cpu or cuda)")
        left.addWidget(self.input_device)

        self.btn_start = QPushButton('Start OCR')
        self.btn_start.clicked.connect(self.start_ocr)
        left.addWidget(self.btn_start)

        self.progress = QProgressBar(); left.addWidget(self.progress)
        
        # Real-time processing status
        self.status_group = QGroupBox("Processing Status")
        status_layout = QVBoxLayout(self.status_group)
        
        self.current_file_label = QLabel("Current File: None")
        self.current_file_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        status_layout.addWidget(self.current_file_label)
        
        self.current_page_label = QLabel("Current Page: None")
        self.current_page_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        status_layout.addWidget(self.current_page_label)
        
        self.progress_details = QLabel("Progress: 0% (0/0 files)")
        self.progress_details.setStyleSheet("color: #FF9800;")
        status_layout.addWidget(self.progress_details)
        
        self.remaining_time_label = QLabel("Estimated Time Remaining: Calculating...")
        self.remaining_time_label.setStyleSheet("color: #9C27B0;")
        status_layout.addWidget(self.remaining_time_label)
        
        left.addWidget(self.status_group)

        # right side: preview image + text in horizontal layout
        right = QHBoxLayout()
        
        # Left side: Preview section
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        # Navigation controls
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton('◀ Previous')
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self.prev_page)
        nav_layout.addWidget(self.btn_prev)
        
        self.page_info = QLabel('Page 0 of 0')
        self.page_info.setAlignment(Qt.AlignCenter)
        nav_layout.addWidget(self.page_info)
        
        self.btn_next = QPushButton('Next ▶')
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self.next_page)
        nav_layout.addWidget(self.btn_next)
        
        preview_layout.addLayout(nav_layout)
        
        self.lbl_preview = QLabel('Preview will appear here')
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setFixedSize(QSize(400, 400))  # Reduced size for better balance
        self.lbl_preview.setStyleSheet("""
            QLabel {
                border: 2px solid #3E3E42;
                border-radius: 8px;
                background-color: #2D2D30;
                padding: 10px;
            }
        """)
        preview_layout.addWidget(self.lbl_preview)
        
        right.addWidget(preview_group)

        # Right side: Text section
        text_group = QGroupBox("Recognized Text")
        text_layout = QVBoxLayout(text_group)
        
        # Text output with better styling
        self.txt_output = QTextEdit()
        self.txt_output.setStyleSheet("""
            QTextEdit {
                border: 2px solid #3E3E42;
                border-radius: 8px;
                background-color: #2D2D30;
                color: white;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                padding: 10px;
                line-height: 1.4;
            }
            QTextEdit:focus {
                border-color: #2196F3;
            }
        """)
        text_layout.addWidget(self.txt_output)

        # Save button with better styling
        btn_save = QPushButton('Save to DOCX')
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
        btn_save.clicked.connect(self.save_docx)
        text_layout.addWidget(btn_save)
        
        right.addWidget(text_group)

        mainlay.addLayout(left, 1)
        mainlay.addLayout(right, 2)
        self.setCentralWidget(central)

        # state
        self.file_paths: List[str] = []
        self.worker: Optional[OCRWorker] = None
        self.page_data: List[Tuple[Image.Image, str]] = []  # (image, text) for each page
        self.current_page: int = 0
        self.total_pages: int = 0
        
        # Processing status tracking
        self.start_time = None
        self.processed_files = 0
        self.total_files = 0
        self.current_file_index = 0
        self.current_page_in_file = 0
        self.total_pages_in_current_file = 0
        
        # Flag to track if files were provided via command line
        self.files_provided_via_args = False
        
        # Store actual file paths for OCR processing
        self.actual_glyphs_path = None
        self.actual_recog_path = None
        self.actual_yolo_path = None
        
        # Check for command-line arguments first, then auto-detect
        self.handle_command_line_args()
        if not self.files_provided_via_args:
            self.auto_detect_model_files()

    def handle_command_line_args(self):
        """Handle command-line arguments for file paths"""
        import argparse
        
        parser = argparse.ArgumentParser(description='PDF Urdu OCR App')
        parser.add_argument('--urduglyphs', help='Path to UrduGlyphs.txt')
        parser.add_argument('--bestnorm', help='Path to best_norm_ED.pth')
        parser.add_argument('--yolo', help='Path to yolov8m_UrduDoc.pt')
        
        args, unknown = parser.parse_known_args()
        
        
        # Check if any file paths were provided
        if args.urduglyphs or args.bestnorm or args.yolo:
            self.files_provided_via_args = True
            
            # Set the file paths in the UI and store actual paths
            if args.urduglyphs and os.path.exists(args.urduglyphs):
                self.input_glyphs.setText("✓ File loaded")
                self.input_glyphs.setStyleSheet("color: green; font-weight: bold;")
                self.actual_glyphs_path = args.urduglyphs
            else:
                self.input_glyphs.setText("✗ Not found")
                self.input_glyphs.setStyleSheet("color: red; font-weight: bold;")
            
            if args.bestnorm and os.path.exists(args.bestnorm):
                self.input_recog.setText("✓ File loaded")
                self.input_recog.setStyleSheet("color: green; font-weight: bold;")
                self.actual_recog_path = args.bestnorm
            else:
                self.input_recog.setText("✗ Not found")
                self.input_recog.setStyleSheet("color: red; font-weight: bold;")
            
            if args.yolo and os.path.exists(args.yolo):
                self.input_yolo.setText("✓ File loaded")
                self.input_yolo.setStyleSheet("color: green; font-weight: bold;")
                self.actual_yolo_path = args.yolo
            else:
                self.input_yolo.setText("✗ Not found")
                self.input_yolo.setStyleSheet("color: red; font-weight: bold;")

    def auto_detect_model_files(self):
        """Auto-detect model files in the PDFOCR directory"""
        # Always try to use PDFOCR_DIR first (set during import)
        model_dir = None
        
        if PDFOCR_DIR and os.path.isdir(PDFOCR_DIR):
            model_dir = PDFOCR_DIR
            print(f"[DEBUG] Using PDFOCR_DIR for model files: {model_dir}")
        else:
            # Fallback: Try to find PDFOCR directory from current location
            current_script = os.path.abspath(__file__)
            current_dir = os.path.dirname(current_script)
            
            # Strategy 1: Check if we're in PDFOCR
            if os.path.basename(current_dir) == 'PDFOCR':
                model_dir = current_dir
                print(f"[DEBUG] Script is in PDFOCR directory: {model_dir}")
            else:
                # Strategy 2: Look for PDFOCR in same directory
                pdfocr_sibling = os.path.join(current_dir, 'PDFOCR')
                if os.path.isdir(pdfocr_sibling):
                    model_dir = pdfocr_sibling
                    print(f"[DEBUG] Found PDFOCR as sibling: {model_dir}")
                else:
                    # Strategy 3: Search up the tree
                    search_dir = current_dir
                    for _ in range(5):
                        parent = os.path.dirname(search_dir)
                        if parent == search_dir:  # Reached root
                            break
                        pdfocr_path = os.path.join(parent, 'PDFOCR')
                        if os.path.isdir(pdfocr_path):
                            model_dir = pdfocr_path
                            print(f"[DEBUG] Found PDFOCR in parent tree: {model_dir}")
                            break
                        search_dir = parent
                    
                    # Strategy 4: Search in sys.path (same as import strategy)
                    if not model_dir:
                        print(f"[DEBUG] Searching for PDFOCR in sys.path for model files...")
                        for path_entry in sys.path:
                            if os.path.isdir(path_entry):
                                pdfocr_in_syspath = os.path.join(path_entry, 'PDFOCR')
                                if os.path.isdir(pdfocr_in_syspath):
                                    # Verify with modules check
                                    modules_check = os.path.join(pdfocr_in_syspath, 'modules')
                                    if os.path.isdir(modules_check):
                                        model_dir = pdfocr_in_syspath
                                        print(f"[DEBUG] Found PDFOCR in sys.path entry: {model_dir}")
                                        break
        
        # Final fallback: use script directory
        if not model_dir:
            model_dir = os.path.dirname(os.path.abspath(__file__))
            print(f"[WARNING] PDFOCR not found, using script directory: {model_dir}")
        
        script_dir = model_dir
        
        # Look for UrduGlyphs.txt
        glyphs_path = os.path.join(script_dir, 'UrduGlyphs.txt')
        if os.path.exists(glyphs_path):
            self.input_glyphs.setText("✓ File loaded")
            self.input_glyphs.setStyleSheet("color: green; font-weight: bold;")
            self.actual_glyphs_path = glyphs_path
        else:
            self.input_glyphs.setText("✗ Not found")
            self.input_glyphs.setStyleSheet("color: red; font-weight: bold;")
        
        # Look for best_norm_ED.pth
        recog_path = os.path.join(script_dir, 'best_norm_ED.pth')
        if os.path.exists(recog_path):
            self.input_recog.setText("✓ File loaded")
            self.input_recog.setStyleSheet("color: green; font-weight: bold;")
            self.actual_recog_path = recog_path
        else:
            self.input_recog.setText("✗ Not found")
            self.input_recog.setStyleSheet("color: red; font-weight: bold;")
        
        # Look for yolov8m_UrduDoc.pt
        yolo_path = os.path.join(script_dir, 'yolov8m_UrduDoc.pt')
        if os.path.exists(yolo_path):
            self.input_yolo.setText("✓ File loaded")
            self.input_yolo.setStyleSheet("color: green; font-weight: bold;")
            self.actual_yolo_path = yolo_path
        else:
            self.input_yolo.setText("✗ Not found")
            self.input_yolo.setStyleSheet("color: red; font-weight: bold;")

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Select files', '', 'PDF Files (*.pdf);;Images (*.png *.jpg *.jpeg *.tiff);;All files (*)')
        if not paths: return
        self.file_paths = paths
        self.lst_files.setText('; '.join([os.path.basename(p) for p in paths]))


    def start_ocr(self):
        if not self.file_paths:
            QMessageBox.warning(self, 'No files', 'Select at least one PDF or image file to process.')
            return
        
        # Use the actual stored file paths instead of UI text
        glyphs = self.actual_glyphs_path
        recog = self.actual_recog_path
        yolo = self.actual_yolo_path if self.chk_yolo.isChecked() else None
        device = self.input_device.text().strip() or ('cuda' if torch and torch.cuda.is_available() else 'cpu')

        # disable UI
        self.btn_start.setEnabled(False)
        self.page_data.clear()
        self.current_page = 0
        self.total_pages = 0
        self.update_navigation()
        
        # Initialize timing and status
        self.start_time = time.time()
        self.processed_files = 0
        self.total_files = len(self.file_paths)
        self.current_file_index = 0
        self.current_page_in_file = 0
        self.total_pages_in_current_file = 0
        self.update_status_display()
        
        self.worker = OCRWorker(self.file_paths, yolo, recog, glyphs, device=device)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.file_progress.connect(self.on_file_progress)
        self.worker.page_processed.connect(self.on_page_processed)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_file_progress(self, file_index: int, total_files: int, filename: str, current_page: int, total_pages_in_file: int):
        """Handle file processing progress updates"""
        self.current_file_index = file_index
        self.current_page_in_file = current_page
        self.total_pages_in_current_file = total_pages_in_file
        self.update_status_display()

    def on_page_processed(self, page_num: int, preview_img: Image.Image, page_text: str):
        """Handle each page as it's processed"""
        self.page_data.append((preview_img, page_text))
        self.total_pages = len(self.page_data)
        self.current_page = self.total_pages - 1  # Show the latest page
        self.update_navigation()
        self.show_current_page()

    def update_status_display(self):
        """Update the real-time status display"""
        if self.total_files > 0:
            # Update current file info
            if self.current_file_index <= len(self.file_paths):
                current_filename = os.path.basename(self.file_paths[self.current_file_index - 1]) if self.current_file_index > 0 else "None"
                self.current_file_label.setText(f"Current File: {current_filename}")
            else:
                self.current_file_label.setText("Current File: None")
            
            # Update current page info
            if self.total_pages_in_current_file > 0:
                self.current_page_label.setText(f"Current Page: {self.current_page_in_file}/{self.total_pages_in_current_file}")
            else:
                self.current_page_label.setText("Current Page: None")
            
            # Update progress details
            progress_percent = int((self.current_file_index / self.total_files) * 100)
            self.progress_details.setText(f"Progress: {progress_percent}% ({self.current_file_index}/{self.total_files} files)")
            
            # Calculate estimated time remaining
            if self.start_time and self.current_file_index > 0:
                elapsed_time = time.time() - self.start_time
                if self.current_file_index > 0:
                    avg_time_per_file = elapsed_time / self.current_file_index
                    remaining_files = self.total_files - self.current_file_index
                    estimated_remaining = avg_time_per_file * remaining_files
                    
                    if estimated_remaining < 60:
                        time_str = f"{int(estimated_remaining)} seconds"
                    elif estimated_remaining < 3600:
                        time_str = f"{int(estimated_remaining/60)} minutes"
                    else:
                        time_str = f"{int(estimated_remaining/3600)} hours {int((estimated_remaining%3600)/60)} minutes"
                    
                    self.remaining_time_label.setText(f"Estimated Time Remaining: {time_str}")
                else:
                    self.remaining_time_label.setText("Estimated Time Remaining: Calculating...")
            else:
                self.remaining_time_label.setText("Estimated Time Remaining: Calculating...")

    def on_finished(self, text: str, preview_img: Image.Image):
        self.btn_start.setEnabled(True)
        self.progress.setValue(100)
        self.txt_output.setPlainText(text)
        if preview_img is not None:
            pix = pil_to_qpixmap(preview_img, max_size=(400,400))  # Updated to match new size
            self.lbl_preview.setPixmap(pix)
        
        # Update final status
        if self.start_time:
            total_time = time.time() - self.start_time
            if total_time < 60:
                time_str = f"{int(total_time)} seconds"
            elif total_time < 3600:
                time_str = f"{int(total_time/60)} minutes {int(total_time%60)} seconds"
            else:
                time_str = f"{int(total_time/3600)} hours {int((total_time%3600)/60)} minutes"
            
            self.remaining_time_label.setText(f"Total Processing Time: {time_str}")
        
        QMessageBox.information(self, 'Done', 'OCR Finished')

    def prev_page(self):
        """Go to previous page"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_navigation()
            self.show_current_page()

    def next_page(self):
        """Go to next page"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_navigation()
            self.show_current_page()

    def update_navigation(self):
        """Update navigation button states and page info"""
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled(self.current_page < self.total_pages - 1)
        self.page_info.setText(f'Page {self.current_page + 1} of {self.total_pages}')

    def show_current_page(self):
        """Display the current page"""
        if 0 <= self.current_page < len(self.page_data):
            preview_img, page_text = self.page_data[self.current_page]
            if preview_img is not None:
                pix = pil_to_qpixmap(preview_img, max_size=(400,400))  # Updated to match new size
                self.lbl_preview.setPixmap(pix)
            # Update text output to show current page text
            if page_text.strip():
                self.txt_output.setPlainText(page_text)
            else:
                self.txt_output.setPlainText("No text recognized on this page.")

    def on_error(self, msg: str):
        self.btn_start.setEnabled(True)
        QMessageBox.critical(self, 'Error', msg)

    def save_docx(self):
        txt = self.txt_output.toPlainText().strip()
        if not txt:
            QMessageBox.warning(self, 'Empty', 'No text to save.')
            return
        if Document is None:
            QMessageBox.critical(self, 'Missing dependency', 'python-docx not installed. pip install python-docx')
            return
        out_suggest = os.path.splitext(self.file_paths[0] if self.file_paths else 'extracted')[0] + '_extracted.docx'
        out_path, _ = QFileDialog.getSaveFileName(self, 'Save DOCX', out_suggest, 'Word Documents (*.docx)')
        if not out_path: return
        try:
            doc = Document()
            for line in txt.splitlines():
                doc.add_paragraph(line)
            doc.save(out_path)
            QMessageBox.information(self, 'Saved', f'Saved extracted text to:\n{out_path}')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to save DOCX: {e}')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
