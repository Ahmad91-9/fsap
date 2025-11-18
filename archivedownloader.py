import os
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
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
    QProgressBar,
    QGroupBox,
    QMessageBox,
)


class DownloadWorker(QObject):
    finished = Signal()
    errored = Signal(str)
    logged = Signal(str)
    progress = Signal(int)

    def __init__(self, item_id: str, dest_dir: str, max_workers: int = 5):
        super().__init__()
        self.item_id = item_id.strip()
        self.dest_dir = dest_dir.strip() if dest_dir.strip() else self.item_id
        self.max_workers = max_workers
        self.cancelled = False

    @Slot()
    def cancel(self):
        self.cancelled = True

    def _meta_url(self) -> str:
        return f"https://archive.org/metadata/{self.item_id}"

    def _base_url(self) -> str:
        return f"https://archive.org/download/{self.item_id}/"

    def _fetch_file_list(self) -> List[str]:
        self.logged.emit("Fetching metadata...")
        resp = requests.get(self._meta_url(), timeout=30)
        resp.raise_for_status()
        metadata = resp.json()
        files = metadata.get('files', [])
        names = [f['name'] for f in files if isinstance(f, dict) and 'name' in f]
        return names

    def _download_one(self, filename: str):
        if self.cancelled:
            return "cancelled"
        url = self._base_url() + filename
        local_folder = os.path.join(self.dest_dir, os.path.dirname(filename))
        os.makedirs(local_folder, exist_ok=True)
        local_path = os.path.join(self.dest_dir, filename)

        # Skip existing non-empty files
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            self.logged.emit(f"Skipping exists: {filename}")
            return "skipped"

        self.logged.emit(f"Downloading: {filename}")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if self.cancelled:
                        return "cancelled"
                    if chunk:
                        f.write(chunk)
        return "downloaded"

    @Slot()
    def run(self):
        try:
            files = self._fetch_file_list()
            total = len(files)
            if total == 0:
                self.logged.emit("No files found in metadata.")
                self.finished.emit()
                return

            self.logged.emit(f"Found {total} files. Starting downloads...")
            completed = 0

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self._download_one, fn): fn for fn in files}
                for future in as_completed(futures):
                    fn = futures[future]
                    try:
                        status = future.result()
                        if status == "downloaded":
                            self.logged.emit(f"Done: {fn}")
                        elif status == "skipped":
                            pass
                        elif status == "cancelled":
                            self.logged.emit("Cancellation requested. Stopping remaining downloads...")
                            break
                    except Exception as exc:
                        self.logged.emit(f"Error downloading {fn}: {exc}")
                    finally:
                        completed += 1
                        pct = int((completed / total) * 100)
                        self.progress.emit(pct)

            self.finished.emit()
        except Exception as exc:
            self.errored.emit(str(exc))
            self.finished.emit()


class ArchiveDownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Archive.org Downloader")
        self.setMinimumSize(800, 500)

        self.worker_thread: QThread | None = None
        self.worker: DownloadWorker | None = None

        self._build_ui()
        self._apply_dark_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Item section
        item_group = QGroupBox("Item Settings")
        item_layout = QVBoxLayout(item_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Item ID:"))
        self.item_edit = QLineEdit()
        self.item_edit.setPlaceholderText("e.g. course-for-free.-com-..._202010")
        row1.addWidget(self.item_edit)
        item_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Destination:"))
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Select destination folder (defaults to Item ID)")
        row2.addWidget(self.dest_edit)
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._on_browse)
        row2.addWidget(self.browse_btn)
        item_layout.addLayout(row2)

        layout.addWidget(item_group)

        # Controls and progress
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        controls.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        controls.addWidget(self.cancel_btn)
        self.help_btn = QPushButton("How to Use")
        self.help_btn.clicked.connect(self._on_help)
        controls.addWidget(self.help_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # Log area
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Logs will appear here...")
        layout.addWidget(self.log_view)

    def _apply_dark_style(self):
        self.setStyleSheet(
            """
            QWidget { background-color: #000000; color: #ffffff; }
            QGroupBox { border: 1px solid #333333; border-radius: 6px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QLineEdit { background-color: #111111; color: #ffffff; border: 1px solid #333333; padding: 6px; }
            QPushButton { background-color: #333333; color: #ffffff; border: 1px solid #555555; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #444444; }
            QTextEdit { background-color: #000000; color: #ffffff; border: 1px solid #333333; font-family: Consolas, Monaco, monospace; font-size: 11px; }
            QProgressBar { border: 1px solid #333333; border-radius: 4px; text-align: center; background-color: #111111; color: #ffffff; }
            QProgressBar::chunk { background-color: #4CAF50; }
            QLabel { color: #ffffff; }
            """
        )

    @Slot()
    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.dest_edit.setText(folder)

    def _append_log(self, text: str):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    @Slot()
    def _on_start(self):
        item_id = self.item_edit.text().strip()
        if not item_id:
            self._append_log("Please enter a valid Item ID.")
            return

        dest_dir = self.dest_edit.text().strip() or item_id

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_view.clear()
        self._append_log(f"Starting downloads for: {item_id}")

        self.worker_thread = QThread()
        self.worker = DownloadWorker(item_id=item_id, dest_dir=dest_dir)
        self.worker.moveToThread(self.worker_thread)

        # Wire signals
        self.worker_thread.started.connect(self.worker.run)
        self.worker.logged.connect(self._append_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.errored.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_thread)

        self.worker_thread.start()

    @Slot()
    def _on_cancel(self):
        if self.worker:
            self._append_log("Cancellation requested...")
            self.worker.cancel()
        self.cancel_btn.setEnabled(False)

    @Slot()
    def _on_help(self):
        QMessageBox.information(
            self,
            "How to Use",
            (
                "1) Enter the Archive.org Item ID.\n\n"
                "What is an Item ID?\n"
                "- It's the unique identifier at the end of an item's URL on archive.org.\n"
                "- Example URL: https://archive.org/details/course-for-free.-com-..._202010\n"
                "- Item ID here is: course-for-free.-com-..._202010\n\n"
                "2) (Optional) Choose a destination folder. If left empty, a folder named\n"
                "   after the Item ID will be created in the app's working directory.\n\n"
                "3) Click Start to fetch the file list and download all files.\n"
                "4) Use Cancel to stop ongoing downloads.\n"
            ),
        )

    @Slot(int)
    def _on_progress(self, pct: int):
        self.progress_bar.setValue(pct)

    @Slot(str)
    def _on_error(self, msg: str):
        self._append_log(f"Error: {msg}")

    @Slot()
    def _on_finished(self):
        self._append_log("Done.")
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

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


def main():
    app = QApplication(sys.argv)
    w = ArchiveDownloaderApp()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
 