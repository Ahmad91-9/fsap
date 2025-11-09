from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QDialog
from PySide6.QtCore import QTimer, QPropertyAnimation, QEasingCurve, Property, Qt
from PySide6.QtGui import QPainter, QPen, QColor
import math

class LoadingSpinner(QWidget):
    """Custom loading spinner widget for async operations"""
    
    def __init__(self, parent=None, size=32):
        super().__init__(parent)
        self.size = size
        self.angle = 0
        self.setFixedSize(size, size)
        
        # Animation timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.rotate)
        
    def start_animation(self):
        """Start the spinning animation"""
        try:
            # Ensure we're on the main thread
            if hasattr(self, 'timer') and self.timer:
                self.timer.start(50)  # Update every 50ms
            self.show()
        except Exception as e:
            print(f"Error starting spinner animation: {e}")
        
    def stop_animation(self):
        """Stop the spinning animation"""
        try:
            # Ensure we're on the main thread
            if hasattr(self, 'timer') and self.timer:
                self.timer.stop()
            self.hide()
        except Exception as e:
            print(f"Error stopping spinner animation: {e}")
    
    def cleanup(self):
        """Clean up the spinner and its timer"""
        try:
            if hasattr(self, 'timer') and self.timer:
                self.timer.stop()
                self.timer.deleteLater()
                self.timer = None
        except Exception as e:
            print(f"Error cleaning up spinner: {e}")
        
    def rotate(self):
        """Rotate the spinner"""
        try:
            self.angle = (self.angle + 30) % 360
            self.update()
        except Exception as e:
            print(f"Error in spinner rotation: {e}")
            # Stop the timer if there's an error
            try:
                self.timer.stop()
            except Exception:
                pass
        
    def paintEvent(self, event):
        """Paint the spinner"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Set up pen
        pen = QPen()
        pen.setWidth(3)
        pen.setCapStyle(Qt.RoundCap)
        
        # Draw spinning arcs
        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = min(center_x, center_y) - 5
        
        for i in range(8):
            alpha = int(255 * (i + 1) / 8)
            color = QColor(76, 175, 80, alpha)  # Green color with varying alpha
            pen.setColor(color)
            painter.setPen(pen)
            
            angle = self.angle + i * 45
            start_x = center_x + radius * math.cos(math.radians(angle))
            start_y = center_y + radius * math.sin(math.radians(angle))
            end_x = center_x + (radius - 8) * math.cos(math.radians(angle))
            end_y = center_y + (radius - 8) * math.sin(math.radians(angle))
            
            painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))

class LoadingOverlay(QWidget):
    """Loading overlay widget that can be placed over any widget"""
    
    def __init__(self, parent=None, message="Loading..."):
        super().__init__(parent)
        self.message = message
        self.init_ui()
        
    def init_ui(self):
        """Initialize the overlay UI"""
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 180);
                border-radius: 10px;
            }
            QLabel {
                color: white;
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(15)
        
        # Loading spinner
        self.spinner = LoadingSpinner(self, 48)
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)
        
        # Loading message
        self.message_label = QLabel(self.message)
        self.message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message_label)
        
        self.hide()
        
    def show_loading(self, message=None):
        """Show the loading overlay with optional custom message"""
        try:
            if message:
                self.message_label.setText(message)
            self.spinner.start_animation()
            self.show()
            self.raise_()
        except Exception as e:
            print(f"Error showing loading overlay: {e}")

    def update_status(self, message: str):
        """Update the overlay message text. Safe no-op if UI not fully initialized."""
        try:
            if hasattr(self, "message_label") and message is not None:
                # Ensure it runs in main thread context; PySide handles this if called from main thread.
                self.message_label.setText(str(message))
        except Exception:
            # Silently ignore to avoid logging from background threads
            pass

    def hide_loading(self):
        """Hide the loading overlay"""
        try:
            self.spinner.stop_animation()
            self.hide()
        except Exception as e:
            print(f"Error hiding loading overlay: {e}")
    
    def cleanup(self):
        """Clean up the loading overlay and its spinner"""
        try:
            if hasattr(self, 'spinner') and self.spinner:
                self.spinner.cleanup()
        except Exception as e:
            print(f"Error cleaning up loading overlay: {e}")
        
    def resizeEvent(self, event):
        """Resize overlay to match parent"""
        if self.parent():
            self.resize(self.parent().size())
        super().resizeEvent(event)

class ProgressDialog(QDialog):
    """Progress dialog for longer operations"""
    
    def __init__(self, parent=None, title="Processing..."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(300, 120)
        self.init_ui()
        
    def init_ui(self):
        """Initialize the progress dialog UI"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2D2D30;
                color: white;
                border: 2px solid #4CAF50;
                border-radius: 10px;
            }
            QLabel {
                font-size: 14px;
                background: transparent;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 5px;
                background-color: #3E3E42;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title label
        self.title_label = QLabel("Processing...")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Please wait...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
    def set_progress(self, value, maximum=100):
        """Set specific progress value"""
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)
        
    def set_indeterminate(self):
        """Set indeterminate progress"""
        self.progress_bar.setRange(0, 0)
        
    def update_status(self, message):
        """Update status message"""
        self.status_label.setText(message)
        
    def update_title(self, title):
        """Update title"""
        self.title_label.setText(title)