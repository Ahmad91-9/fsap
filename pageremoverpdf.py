"""
pdf_editor_pro.py
A professional PySide6 PDF page editor with:
 - thumbnails (click to select)
 - click thumbnail to open page editor
 - precise rectangle eraser (blue) for single page
 - global rectangle eraser (red) that applies the same rectangle to all pages
 - erased area becomes white (preview overlay while editing; applied at save time)
 - threaded rendering and threaded saving to avoid UI lock
 - keyboard shortcuts: Ctrl+O, Ctrl+S, Delete, Esc, Ctrl+Z (undo), Ctrl+Shift+Z (redo)
Dependencies: PySide6, PyMuPDF (fitz), Pillow
"""

import sys
import io
import math
import threading
from functools import partial
from dataclasses import dataclass, field
from typing import List, Tuple, Dict

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

from PySide6.QtCore import (
    Qt, QSize, QThread, Signal, QObject, QRectF, QPoint, QRect
)
# QShortcut and QKeySequence live in QtGui
from PySide6.QtGui import QShortcut, QKeySequence

from PySide6.QtGui import (
    QPixmap, QImage, QAction, QPainter, QColor
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QFileDialog, QMessageBox, QGridLayout, QScrollArea, QFrame, QSplitter,
    QListWidget, QListWidgetItem, QSizePolicy, QToolButton
)


# -------------------------
# Constants (coordinate scales)
# -------------------------
EDIT_SCALE = 1.5   # editor render scale (coordinates of erase rects are stored at this scale)
THUMB_SCALE = 0.25  # thumbnail render scale


# -------------------------
# Utility dataclasses
# -------------------------
@dataclass
class EraseRect:
    """Rectangle stored in pixmap coordinates for a page (coordinates correspond to EDIT_SCALE)."""
    x0: int
    y0: int
    x1: int
    y1: int
    color: Tuple[int, int, int]  # always white effect but record color for UI (blue/red)
    global_rect: bool = False  # whether this rect is global (applies to all pages)


# -------------------------
# Worker to render thumbnails in background
# -------------------------
class ThumbnailRenderer(QThread):
    thumbnails_ready = Signal(int, object)  # page_index, QPixmap

    def __init__(self, pdf_doc, scale=THUMB_SCALE, parent=None):
        super().__init__(parent)
        self.pdf_doc = pdf_doc
        self.scale = scale
        self._running = True

    def run(self):
        try:
            for i, page in enumerate(self.pdf_doc):
                if not self._running:
                    break
                mat = fitz.Matrix(self.scale, self.scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                # convert to JPEG bytes to keep memory lower
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70, optimize=True)
                qt_img = QImage.fromData(buf.getvalue())
                pixmap = QPixmap.fromImage(qt_img)
                self.thumbnails_ready.emit(i, pixmap)
        except Exception as e:
            # emit nothing, main thread will handle missing thumbnails
            print("ThumbnailRenderer error:", e)

    def stop(self):
        self._running = False


# -------------------------
# Worker to save edited PDF in background
# -------------------------
class SaveWorker(QThread):
    finished_saving = Signal(bool, str)

    def __init__(self, output_path: str, original_doc: fitz.Document,
                 per_page_erases: Dict[int, List[EraseRect]], 
                 global_erases: List[EraseRect],
                 jpeg_quality: int = 80,
                 parent=None):
        """
        SaveWorker will render every page, apply erasures (global + per-page),
        and insert compressed JPEG images to the new PDF to keep file size moderate.
        """
        super().__init__(parent)
        self.output_path = output_path
        self.original_doc = original_doc
        self.per_page_erases = per_page_erases
        self.global_erases = global_erases
        self.jpeg_quality = jpeg_quality

    def run(self):
        try:
            new_doc = fitz.open()
            page_count = len(self.original_doc)
            for i in range(page_count):
                # Render original page at EDIT_SCALE for consistency with stored erase coords
                page = self.original_doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(EDIT_SCALE, EDIT_SCALE), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # Apply global and per-page erases (stored at EDIT_SCALE coordinates)
                draw = ImageDraw.Draw(img)
                for er in self.global_erases:
                    draw.rectangle([er.x0, er.y0, er.x1, er.y1], fill=(255, 255, 255))
                for er in self.per_page_erases.get(i, []):
                    draw.rectangle([er.x0, er.y0, er.x1, er.y1], fill=(255, 255, 255))

                # Convert to compressed JPEG bytes (reduces size a lot vs PNG)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self.jpeg_quality, optimize=True)
                img_bytes = buf.getvalue()

                # Insert as an image page sized to the image
                w_px, h_px = img.size
                new_page = new_doc.new_page(width=w_px, height=h_px)
                rect = fitz.Rect(0, 0, w_px, h_px)
                new_page.insert_image(rect, stream=img_bytes)

            # Save with some compression flags
            new_doc.save(self.output_path, garbage=4, deflate=True)
            new_doc.close()
            self.finished_saving.emit(True, self.output_path)
        except Exception as e:
            self.finished_saving.emit(False, str(e))


# -------------------------
# Thumbnail widget
# -------------------------
class ThumbWidget(QFrame):
    clicked = Signal(int)
    toggled = Signal(int, bool)  # index, selected

    def __init__(self, page_index: int, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self.pixmap = pixmap
        self.selected = False
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(1)
        self.setStyleSheet("border: 2px solid lightgray; border-radius:6px;")
        self.label = QLabel()
        self.label.setPixmap(self.pixmap.scaledToWidth(140, Qt.SmoothTransformation))
        self.caption = QLabel(f"Page {page_index + 1}")
        self.caption.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.label)
        layout.addWidget(self.caption)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # toggle selection on Ctrl or click?
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ControlModifier:
                self.set_selected(not self.selected)
                self.toggled.emit(self.page_index, self.selected)
            else:
                # normal click: emit clicked (open editor)
                self.clicked.emit(self.page_index)
        super().mousePressEvent(event)

    def set_selected(self, sel: bool):
        self.selected = sel
        if sel:
            self.setStyleSheet("border: 3px solid #0078d7; border-radius:6px;")  # blue highlight
        else:
            self.setStyleSheet("border: 2px solid lightgray; border-radius:6px;")


# -------------------------
# Page editor view (shows single page, allows drawing erase rectangles)
# Preview mode: draws overlays only; actual pixels are changed at save time.
# -------------------------
class PageEditor(QWidget):
    rect_committed = Signal(EraseRect)  # emitted when an erase rectangle is finalized

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setStyleSheet("background: #f0f0f0;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.image_label)

        # state
        self.current_qpixmap = None
        self.display_scale = 1.0  # displayed image scale relative to the pixmap coordinates
        self.start_pos = None
        self.end_pos = None
        self.drawing = False
        self.preview_rects: List[Tuple[QRect, QColor, bool]] = []  # (rect, color, is_global)
        # keep last committed rect for undo/redo on current page
        self._undo_stack: List[EraseRect] = []
        self._redo_stack: List[EraseRect] = []

        # eraser mode: 'single' or 'global'. Default single.
        self.eraser_mode = 'single'
        self.eraser_color = QColor("#0078d7")  # blue default

        # enable mouse events on label area
        self.image_label.setMouseTracking(True)
        self.setMouseTracking(True)

        # store which page is currently displayed (index)
        self.current_page_index = None

    def load_pixmap(self, pixmap: QPixmap):
        self.current_qpixmap = pixmap
        self._update_display()

    def _update_display(self):
        if self.current_qpixmap is None:
            self.image_label.clear()
            return
        # scale to fit label while keeping original pixmap info for coordinate transforms
        lbl_size = self.image_label.size()
        if lbl_size.width() <= 0 or lbl_size.height() <= 0:
            self.image_label.setPixmap(self.current_qpixmap)
            self.display_scale = 1.0
            return
        scaled = self.current_qpixmap.scaled(lbl_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.display_scale = scaled.width() / self.current_qpixmap.width()
        # draw preview rectangles onto the scaled pixmap for user feedback
        composed = QPixmap(scaled)
        painter = QPainter(composed)
        painter.setRenderHint(QPainter.Antialiasing)
        for rect, color, is_global in self.preview_rects:
            pen = QColor(color)
            pen.setAlpha(200)
            painter.setPen(pen)
            brush = QColor(color)
            brush.setAlpha(60)
            painter.fillRect(rect, brush)
            painter.drawRect(rect)
        # if currently drawing, draw the active rectangle
        if self.drawing and self.start_pos and self.end_pos:
            r = QRect(self.start_pos, self.end_pos).normalized()
            pencol = QColor(self.eraser_color)
            pencol.setAlpha(220)
            painter.setPen(pencol)
            brush = QColor(self.eraser_color)
            brush.setAlpha(50)
            painter.fillRect(r, brush)
            painter.drawRect(r)
        painter.end()
        self.image_label.setPixmap(composed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def set_eraser_mode(self, mode: str):
        self.eraser_mode = mode
        self.eraser_color = QColor("#ff4d4d") if mode == 'global' else QColor("#0078d7")
        # redraw preview to update colors
        self._update_display()

    def mousePressEvent(self, event):
        if self.current_qpixmap is None:
            return
        if event.button() == Qt.LeftButton:
            # start drawing rectangle (convert event pos into label coordinates)
            pos = self.image_label.mapFrom(self, event.pos())
            # ensure pos within label content (pixmap area)
            lbl_pixmap = self.image_label.pixmap()
            if lbl_pixmap is None:
                return
            lbl_rect = self.image_label.contentsRect()
            # compute top-left of displayed pixmap within the label
            x_off = (lbl_rect.width() - lbl_pixmap.width()) // 2
            y_off = (lbl_rect.height() - lbl_pixmap.height()) // 2
            px = pos.x() - x_off
            py = pos.y() - y_off
            if px < 0 or py < 0 or px > lbl_pixmap.width() or py > lbl_pixmap.height():
                # out of pixmap area
                return
            # store positions in display pixmap coords (we'll convert to EDIT_SCALE coords on commit)
            self.drawing = True
            self.start_pos = QPoint(px, py)
            self.end_pos = QPoint(px, py)
            self._update_display()

    def mouseMoveEvent(self, event):
        if not self.drawing:
            return
        pos = self.image_label.mapFrom(self, event.pos())
        lbl_pixmap = self.image_label.pixmap()
        if lbl_pixmap is None:
            return
        lbl_rect = self.image_label.contentsRect()
        x_off = (lbl_rect.width() - lbl_pixmap.width()) // 2
        y_off = (lbl_rect.height() - lbl_pixmap.height()) // 2
        px = pos.x() - x_off
        py = pos.y() - y_off
        px = max(0, min(px, lbl_pixmap.width()))
        py = max(0, min(py, lbl_pixmap.height()))
        self.end_pos = QPoint(px, py)
        self._update_display()

    def mouseReleaseEvent(self, event):
        if not self.drawing:
            return
        self.drawing = False
        # compute rect in display pixmap coords
        if self.start_pos is None or self.end_pos is None or self.current_qpixmap is None:
            return
        r = QRect(self.start_pos, self.end_pos).normalized()
        if r.width() < 6 or r.height() < 6:
            # too small, ignore
            self.start_pos = None
            self.end_pos = None
            self._update_display()
            return
        # scale rect from display pixmap coords back to EDIT_SCALE coordinates
        # display_scale = scaled.width() / original_qpixmap.width()
        scale_back = 1.0 / self.display_scale if self.display_scale > 0 else 1.0
        x0 = int(max(0, math.floor(r.left() * scale_back)))
        y0 = int(max(0, math.floor(r.top() * scale_back)))
        x1 = int(max(0, math.ceil(r.right() * scale_back)))
        y1 = int(max(0, math.ceil(r.bottom() * scale_back)))
        # BUT those coordinates are relative to the current_qpixmap width which may correspond to a render size;
        # we assume the page was rendered into current_qpixmap at EDIT_SCALE. (Main window maintains that invariant.)
        color_rgb = (0, 122, 215) if self.eraser_mode == 'single' else (255, 77, 77)
        er = EraseRect(x0, y0, x1, y1, color_rgb, global_rect=(self.eraser_mode == 'global'))
        # push to undo stack (so user can undo before saving)
        self._undo_stack.append(er)
        self._redo_stack.clear()
        # add a preview rectangle for feedback (on display coords)
        disp_rect = QRect(int(r.left()), int(r.top()), int(r.width()), int(r.height()))
        self.preview_rects.append((disp_rect, self.eraser_color, er.global_rect))
        self._update_display()
        # emit the erase rect (main keeps lists but actual pixel edits are applied at save time)
        self.rect_committed.emit(er)
        # cleanup
        self.start_pos = None
        self.end_pos = None

    def clear_preview_rects(self):
        self.preview_rects.clear()
        self._update_display()

    def add_preview_from_erase(self, er: EraseRect):
        # convert erase rect (EDIT_SCALE coords) to display coords and store for overlay preview
        if self.current_qpixmap is None:
            return
        left = int(er.x0 * self.display_scale)
        top = int(er.y0 * self.display_scale)
        width = int((er.x1 - er.x0) * self.display_scale)
        height = int((er.y1 - er.y0) * self.display_scale)
        disp_rect = QRect(left, top, width, height)
        color = QColor("#ff4d4d") if er.global_rect else QColor("#0078d7")
        self.preview_rects.append((disp_rect, color, er.global_rect))
        self._update_display()

    def undo(self):
        if not self._undo_stack:
            return None
        last = self._undo_stack.pop()
        self._redo_stack.append(last)
        # remove last preview rect that matches last (best-effort)
        if self.preview_rects:
            self.preview_rects.pop()
            self._update_display()
        return last  # return removed rect so main controller can remove it from storage

    def redo(self):
        if not self._redo_stack:
            return None
        item = self._redo_stack.pop()
        self._undo_stack.append(item)
        # re-add preview
        self.add_preview_from_erase(item)
        return item


# -------------------------
# Main Window
# -------------------------
class PDFEditorMain(QWidget):
    def __init__(self, username: str = None):
        # Keep __init__ lightweight so the launcher can instantiate the class before QApplication exists
        super().__init__()
        self.username = username
        self._ui_initialized = False

        # Minimal window metadata (safe before QApplication)
        self.setWindowTitle("PDF Editor Pro")
        self.resize(1100, 760)

        # PDF structures (lightweight initialization)
        self.pdf_doc: fitz.Document = None
        self.pdf_path: str = None

        # store thumbnails widgets and pixmaps
        self.thumb_widgets: List[ThumbWidget] = []
        self.thumb_pixmaps: Dict[int, QPixmap] = {}

        # store erasures:
        self.per_page_erases: Dict[int, List[EraseRect]] = {}
        self.global_erases: List[EraseRect] = []

        # modified images cache
        self.modified_images_cache: Dict[int, Image.Image] = {}

        # Thread and sync primitives (do not create UI objects here)
        self.thumb_renderer: ThumbnailRenderer = None
        self._lock = threading.Lock()
        self.current_page_index: int = 0

        # Note: UI widgets (buttons, labels, etc.) are created in init_ui()
        # If a QApplication already exists, initialize UI now (standalone run)
        if QApplication.instance() is not None:
            self.init_ui()

    def init_ui(self):
        """Create all UI widgets and layout. Safe to call more than once (idempotent)."""
        if self._ui_initialized:
            return
        self._ui_initialized = True

        # UI components
        self.open_btn = QPushButton("Open PDF")
        self.save_btn = QPushButton("Save As...")
        self.delete_btn = QPushButton("Delete Selected Pages")
        self.eraser_single_btn = QToolButton()
        self.eraser_all_btn = QToolButton()
        self.status_label = QLabel("No PDF loaded.")
        self.delete_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.eraser_single_btn.setCheckable(True)
        self.eraser_all_btn.setCheckable(True)

        # thumbnails area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.thumbs_container = QWidget()
        self.grid_layout = QGridLayout(self.thumbs_container)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.scroll_area.setWidget(self.thumbs_container)

        # page editor (right side)
        self.page_editor = PageEditor()
        self.page_editor.rect_committed.connect(self.on_rect_committed)

        # layout: left thumbnails + right editor
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        top_buttons = QHBoxLayout()
        top_buttons.addWidget(self.open_btn)
        top_buttons.addWidget(self.delete_btn)
        top_buttons.addWidget(self.save_btn)
        left_layout.addLayout(top_buttons)
        left_layout.addWidget(self.scroll_area)
        left_layout.addWidget(self.status_label)

        # eraser tool buttons
        self.eraser_single_btn.setText("Single (Blue)")
        self.eraser_all_btn.setText("Global (Red)")
        self.eraser_single_btn.setStyleSheet("background: #0078d7; color: white; padding:6px;")
        self.eraser_all_btn.setStyleSheet("background: #ff4d4d; color: white; padding:6px;")
        self.eraser_single_btn.setChecked(True)  # default single
        self.eraser_all_btn.setChecked(False)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(self.eraser_single_btn)
        toolbar_layout.addWidget(self.eraser_all_btn)
        toolbar_layout.addStretch()
        left_layout.addLayout(toolbar_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(self.page_editor)
        splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)

        # connections
        self.open_btn.clicked.connect(self.open_pdf)
        self.save_btn.clicked.connect(self.save_pdf)
        self.delete_btn.clicked.connect(self.delete_selected_pages)
        self.eraser_single_btn.clicked.connect(self.set_single_eraser)
        self.eraser_all_btn.clicked.connect(self.set_global_eraser)

        # keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_pdf)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_pdf)
        QShortcut(QKeySequence("Delete"), self, activated=self.delete_selected_pages)
        QShortcut(QKeySequence("Esc"), self, activated=self.clear_all_selections)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_erase)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo_erase)
        # arrow navigation
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self.next_page)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=self.prev_page)
        QShortcut(QKeySequence(Qt.Key_PageDown), self, activated=self.next_page)
        QShortcut(QKeySequence(Qt.Key_PageUp), self, activated=self.prev_page)

    def showEvent(self, event):
        # If UI not initialized yet, do it now (this guarantees QApplication exists)
        if not getattr(self, "_ui_initialized", False):
            self.init_ui()
        super().showEvent(event)

    # -------------------------
    # UI Actions (unchanged)
    # -------------------------
    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        try:
            doc = fitz.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open PDF:\n{e}")
            return
        # stop any existing thumbnail renderer
        if self.thumb_renderer:
            self.thumb_renderer.stop()
            self.thumb_renderer.wait(200)
            self.thumb_renderer = None

        self.pdf_doc = doc
        self.pdf_path = path
        self.thumb_pixmaps.clear()
        self._clear_thumbs()
        self.per_page_erases.clear()
        self.global_erases.clear()
        self.modified_images_cache.clear()
        self.status_label.setText(f"Loaded: {path} ({len(self.pdf_doc)} pages)")
        self.delete_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        # start thumbnail renderer
        self.thumb_renderer = ThumbnailRenderer(self.pdf_doc, scale=THUMB_SCALE)
        self.thumb_renderer.thumbnails_ready.connect(self._on_thumbnail_ready)
        self.thumb_renderer.start()

    def _clear_thumbs(self):
        for w in self.thumb_widgets:
            w.setParent(None)
        self.thumb_widgets.clear()

    def _on_thumbnail_ready(self, page_index: int, pixmap: QPixmap):
        # main thread: add or update thumbnail widget
        # store pixmap
        # apply overlay of erasures (preview) onto the thumbnail pixmap for visual feedback
        base_pix = QPixmap(pixmap)  # a copy
        painter = QPainter(base_pix)
        painter.setRenderHint(QPainter.Antialiasing)
        # mapping factor from EDIT_SCALE coords to thumbnail coords:
        map_scale = THUMB_SCALE / EDIT_SCALE
        # draw global erases
        for er in self.global_erases:
            left = int(er.x0 * map_scale)
            top = int(er.y0 * map_scale)
            w = int((er.x1 - er.x0) * map_scale)
            h = int((er.y1 - er.y0) * map_scale)
            brush = QColor("#ff4d4d")
            brush.setAlpha(80)
            painter.fillRect(QRect(left, top, max(1, w), max(1, h)), brush)
            pen = QColor("#ff4d4d")
            pen.setAlpha(180)
            painter.setPen(pen)
            painter.drawRect(QRect(left, top, max(1, w), max(1, h)))
        # draw per-page erases for this page
        for er in self.per_page_erases.get(page_index, []):
            left = int(er.x0 * map_scale)
            top = int(er.y0 * map_scale)
            w = int((er.x1 - er.x0) * map_scale)
            h = int((er.y1 - er.y0) * map_scale)
            brush = QColor("#0078d7")
            brush.setAlpha(80)
            painter.fillRect(QRect(left, top, max(1, w), max(1, h)), brush)
            pen = QColor("#0078d7")
            pen.setAlpha(180)
            painter.setPen(pen)
            painter.drawRect(QRect(left, top, max(1, w), max(1, h)))
        painter.end()

        # save pixmap and create widget
        self.thumb_pixmaps[page_index] = base_pix
        tw = ThumbWidget(page_index, base_pix)
        tw.clicked.connect(self.open_page_in_editor)
        tw.toggled.connect(self.on_thumb_toggled)
        # place in grid layout
        cols = 3
        position = len(self.thumb_widgets)
        self.grid_layout.addWidget(tw, position // cols, position % cols)
        self.thumb_widgets.append(tw)

        # open first page automatically
        if page_index == 0:
            self.open_page_in_editor(0)

    def on_thumb_toggled(self, index: int, selected: bool):
        # user toggled selection with Ctrl+click on thumbnail
        # nothing else needed; selection state is inside widget
        pass

    def open_page_in_editor(self, page_index: int):
        # show page in editor as pixmap (use a medium resolution render at EDIT_SCALE)
        if self.pdf_doc is None:
            return
        # store current page
        self.current_page_index = page_index
        # update thumbnail selection visual
        for w in self.thumb_widgets:
            w.set_selected(w.page_index == page_index)

        page = self.pdf_doc[page_index]
        # render at EDIT_SCALE for good editing resolution
        mat = fitz.Matrix(EDIT_SCALE, EDIT_SCALE)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # We are using option 2 (preview overlays). Do NOT permanently modify img now.
        # Instead, draw overlays as previews in the page editor only (viewer).
        buf = io.BytesIO()
        # convert to a compressed image for preview to reduce memory
        img.save(buf, format="JPEG", quality=85, optimize=True)
        qtimg = QImage.fromData(buf.getvalue())
        pixmap = QPixmap.fromImage(qtimg)
        self.page_editor.load_pixmap(pixmap)

        # clear existing preview rects and re-add from stored erases (global + per page)
        self.page_editor.preview_rects.clear()
        for er in self.global_erases:
            self.page_editor.add_preview_from_erase(er)
        for er in self.per_page_erases.get(page_index, []):
            self.page_editor.add_preview_from_erase(er)

        # store page index in editor
        self.page_editor.current_page_index = page_index
        self.status_label.setText(f"Viewing page {page_index + 1}/{len(self.pdf_doc)}")

    def on_rect_committed(self, er: EraseRect):
        # the editor emitted a new erase rect (with coords relative to EDIT_SCALE)
        page_idx = getattr(self.page_editor, "current_page_index", None)
        if page_idx is None:
            return
        # For global rects, store in global_erases (applies to all pages)
        if er.global_rect:
            self.global_erases.append(er)
        else:
            # single page erase: append to per_page_erases for the current page
            arr = self.per_page_erases.setdefault(page_idx, [])
            arr.append(er)

        # Update thumbnail for this page (and all thumbnails for global erases)
        self._update_thumbnail_after_erase(page_idx, er)

        self.status_label.setText(f"Erased area (preview) on page {page_idx + 1} ({'global' if er.global_rect else 'single'})")

    def _update_thumbnail_after_erase(self, page_idx: int, er: EraseRect):
        # regenerate the thumbnail pixmap for the specified page (and all pages if global)
        if er.global_rect:
            # refresh all thumbnails
            for idx, pix in list(self.thumb_pixmaps.items()):
                self._apply_erase_overlay_to_thumbnail(idx)
        else:
            self._apply_erase_overlay_to_thumbnail(page_idx)

    def _apply_erase_overlay_to_thumbnail(self, page_index: int):
        # If we have the original thumbnail pix (from thumb_pixmaps) we redraw with overlays
        base = self.thumb_pixmaps.get(page_index)
        if base is None or self.pdf_doc is None:
            return
        pix_copy = QPixmap(base)  # copy
        painter = QPainter(pix_copy)
        painter.setRenderHint(QPainter.Antialiasing)
        map_scale = THUMB_SCALE / EDIT_SCALE
        # draw global erases
        for er in self.global_erases:
            left = int(er.x0 * map_scale)
            top = int(er.y0 * map_scale)
            w = int((er.x1 - er.x0) * map_scale)
            h = int((er.y1 - er.y0) * map_scale)
            brush = QColor("#ff4d4d")
            brush.setAlpha(80)
            painter.fillRect(QRect(left, top, max(1, w), max(1, h)), brush)
            pen = QColor("#ff4d4d")
            pen.setAlpha(180)
            painter.setPen(pen)
            painter.drawRect(QRect(left, top, max(1, w), max(1, h)))
        # draw per-page erases
        for er in self.per_page_erases.get(page_index, []):
            left = int(er.x0 * map_scale)
            top = int(er.y0 * map_scale)
            w = int((er.x1 - er.x0) * map_scale)
            h = int((er.y1 - er.y0) * map_scale)
            brush = QColor("#0078d7")
            brush.setAlpha(80)
            painter.fillRect(QRect(left, top, max(1, w), max(1, h)), brush)
            pen = QColor("#0078d7")
            pen.setAlpha(180)
            painter.setPen(pen)
            painter.drawRect(QRect(left, top, max(1, w), max(1, h)))
        painter.end()

        # find widget and update
        for w in self.thumb_widgets:
            if w.page_index == page_index:
                w.label.setPixmap(pix_copy.scaledToWidth(140, Qt.SmoothTransformation))
                break
        # also update stored thumb pixmap copy
        self.thumb_pixmaps[page_index] = pix_copy

    def delete_selected_pages(self):
        if self.pdf_doc is None:
            return
        # collect selected widgets
        selected_indices = [w.page_index for w in self.thumb_widgets if getattr(w, "selected", False)]
        if not selected_indices:
            QMessageBox.information(self, "No pages selected", "Select pages to delete by Ctrl+clicking thumbnails.")
            return
        confirm = QMessageBox.question(self, "Confirm Delete", f"Delete {len(selected_indices)} selected page(s)?", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        # Delete pages in reverse order from document
        for idx in sorted(selected_indices, reverse=True):
            try:
                self.pdf_doc.delete_page(idx)
            except Exception as e:
                print("Delete page error:", e)
        # After deletion, we must remap per_page_erases keys because page indexes changed.
        # Easiest approach: rebuild per_page_erases by re-indexing pages that remain.
        new_per_page = {}
        old_to_new = {}
        new_index = 0
        # determine mapping based on remaining pages count
        total = len(self.pdf_doc)
        for i in range(total):
            old_to_new[i] = i  # in PyMuPDF delete_page shifts indexes; simplest fix is to clear per_page_erases
        # clear all erases (safe approach after deletes)
        self.per_page_erases.clear()
        self.global_erases.clear()
        self.modified_images_cache.clear()
        self._clear_thumbs()
        self.thumb_pixmaps.clear()
        # restart thumbnail renderer
        if self.thumb_renderer:
            self.thumb_renderer.stop()
            self.thumb_renderer.wait(200)
        self.thumb_renderer = ThumbnailRenderer(self.pdf_doc, scale=THUMB_SCALE)
        self.thumb_renderer.thumbnails_ready.connect(self._on_thumbnail_ready)
        self.thumb_renderer.start()
        self.status_label.setText("Deleted selected pages and refreshed thumbnails.")

    def save_pdf(self):
        if self.pdf_doc is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF As", "", "PDF Files (*.pdf)")
        if not path:
            return

        # disable UI while saving
        self.status_label.setText("Saving...")
        self.save_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

        # Start save worker with current erase lists
        self.saver = SaveWorker(path, self.pdf_doc, self.per_page_erases.copy(), list(self.global_erases), jpeg_quality=80)
        self.saver.finished_saving.connect(self._on_save_finished)
        self.saver.start()

    def _on_save_finished(self, ok: bool, info: str):
        self.save_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Saved", f"PDF saved successfully:\n{info}")
            self.status_label.setText(f"Saved: {info}")
        else:
            QMessageBox.critical(self, "Save Error", f"Failed to save PDF:\n{info}")
            self.status_label.setText("Save failed.")

    def set_single_eraser(self):
        self.eraser_single_btn.setChecked(True)
        self.eraser_all_btn.setChecked(False)
        self.page_editor.set_eraser_mode('single')

    def set_global_eraser(self):
        self.eraser_all_btn.setChecked(True)
        self.eraser_single_btn.setChecked(False)
        self.page_editor.set_eraser_mode('global')

    def clear_all_selections(self):
        # clear thumbnail selection
        for w in self.thumb_widgets:
            w.set_selected(False)

    def undo_erase(self):
        # delegate to page editor undo which returns the removed erase rect; then remove from storage
        last = self.page_editor.undo()
        if last is None:
            return
        # Determine page index from editor
        page_idx = getattr(self.page_editor, "current_page_index", None)
        if last.global_rect:
            # remove last matching global erase (best-effort)
            if self.global_erases:
                self.global_erases.pop()
                # update thumbnails
                for idx in range(len(self.thumb_pixmaps)):
                    self._apply_erase_overlay_to_thumbnail(idx)
        else:
            if page_idx is not None:
                lst = self.per_page_erases.get(page_idx, [])
                if lst:
                    lst.pop()
                    # refresh the page editor previews and thumbnail
                    self.open_page_in_editor(page_idx)
                    self._apply_erase_overlay_to_thumbnail(page_idx)
        self.status_label.setText("Undo performed.")

    def redo_erase(self):
        item = self.page_editor.redo()
        if item is None:
            return
        # re-apply the redo item
        page_idx = getattr(self.page_editor, "current_page_index", None)
        if item.global_rect:
            self.global_erases.append(item)
            # apply to thumbnails
            for idx in range(len(self.thumb_pixmaps)):
                self._apply_erase_overlay_to_thumbnail(idx)
        else:
            if page_idx is not None:
                self.per_page_erases.setdefault(page_idx, []).append(item)
                self._apply_erase_overlay_to_thumbnail(page_idx)
        self.status_label.setText("Redo performed.")

    def _rebuild_modified_cache(self):
        # Not used in preview mode, but kept for completeness
        with self._lock:
            self.modified_images_cache.clear()

    # -------------------------
    # Navigation helpers
    # -------------------------
    def next_page(self):
        if self.pdf_doc is None:
            return
        if self.current_page_index < len(self.pdf_doc) - 1:
            self.open_page_in_editor(self.current_page_index + 1)

    def prev_page(self):
        if self.pdf_doc is None:
            return
        if self.current_page_index > 0:
            self.open_page_in_editor(self.current_page_index - 1)


# -------------------------
# Runner / Standalone entrypoint
# -------------------------
def run_pdf_editor_app():
    """
    Standalone runner. Returns the QApplication exec return code.
    Launcher should instantiate PDFEditorMain() directly and show it.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    win = PDFEditorMain()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_pdf_editor_app())
