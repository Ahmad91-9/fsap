"""
Cleanup utilities for temporary files and system cleanup.
"""
import os
import shutil
import tempfile
import atexit
import glob
from pathlib import Path
import psutil
import sys


class CleanupManager:
    """Manages cleanup of temporary files and system resources."""
    
    def __init__(self):
        self.temp_dirs = []
        self.temp_files = []
        self.processes_to_cleanup = []
        
        # Register cleanup on exit
        atexit.register(self.cleanup_all)
    
    def add_temp_dir(self, temp_dir: str):
        """Add a temporary directory to cleanup list."""
        if temp_dir and os.path.exists(temp_dir):
            self.temp_dirs.append(temp_dir)
    
    def add_temp_file(self, temp_file: str):
        """Add a temporary file to cleanup list."""
        if temp_file and os.path.exists(temp_file):
            self.temp_files.append(temp_file)
    
    def add_process(self, process):
        """Add a process to cleanup list."""
        if process and process.is_running():
            self.processes_to_cleanup.append(process)
    
    def cleanup_temp_directories(self):
        """Clean up all temporary directories."""
        cleaned_dirs = []
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    cleaned_dirs.append(temp_dir)
                    print(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                print(f"Failed to clean temp directory {temp_dir}: {e}")
        
        # Clear the list
        self.temp_dirs.clear()
        return cleaned_dirs
    
    def cleanup_temp_files(self):
        """Clean up all temporary files."""
        cleaned_files = []
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    cleaned_files.append(temp_file)
                    print(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                print(f"Failed to clean temp file {temp_file}: {e}")
        
        # Clear the list
        self.temp_files.clear()
        return cleaned_files
    
    def cleanup_processes(self):
        """Clean up any running processes."""
        cleaned_processes = []
        for process in self.processes_to_cleanup:
            try:
                if process.is_running():
                    process.terminate()
                    process.wait(timeout=5)  # Wait up to 5 seconds
                    cleaned_processes.append(process.pid)
                    print(f"Terminated process: {process.pid}")
            except Exception as e:
                print(f"Failed to terminate process {process.pid}: {e}")
        
        # Clear the list
        self.processes_to_cleanup.clear()
        return cleaned_processes
    
    def cleanup_system_temp(self):
        """Clean up system temporary files."""
        cleaned_files = []
        
        try:
            # Get system temp directory
            temp_dir = tempfile.gettempdir()
            
            # Clean up common temp file patterns
            patterns = [
                f"{temp_dir}/*.tmp",
                f"{temp_dir}/*.temp",
                f"{temp_dir}/*.log",
                f"{temp_dir}/rbpk_*",
                f"{temp_dir}/ThreadedAdmin_*",
                f"{temp_dir}/python_*",
            ]
            
            for pattern in patterns:
                try:
                    files = glob.glob(pattern)
                    for file_path in files:
                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                cleaned_files.append(file_path)
                            elif os.path.isdir(file_path):
                                shutil.rmtree(file_path, ignore_errors=True)
                                cleaned_files.append(file_path)
                        except Exception as e:
                            print(f"Failed to clean {file_path}: {e}")
                except Exception as e:
                    print(f"Failed to process pattern {pattern}: {e}")
            
            if cleaned_files:
                print(f"Cleaned up {len(cleaned_files)} system temp files")
                
        except Exception as e:
            print(f"Failed to clean system temp files: {e}")
        
        return cleaned_files
    
    def cleanup_app_specific(self):
        """Clean up application-specific temporary files."""
        cleaned_items = []
        
        try:
            # Clean up any cached files
            cache_paths = [
                os.path.join(os.path.expanduser("~"), ".cache", "ThreadedAdmin"),
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "ThreadedAdmin"),
                os.path.join(tempfile.gettempdir(), "ThreadedAdmin"),
            ]
            
            for cache_path in cache_paths:
                if os.path.exists(cache_path):
                    try:
                        shutil.rmtree(cache_path, ignore_errors=True)
                        cleaned_items.append(cache_path)
                        print(f"Cleaned up app cache: {cache_path}")
                    except Exception as e:
                        print(f"Failed to clean cache {cache_path}: {e}")
            
            # Clean up any downloaded files in temp
            temp_dir = tempfile.gettempdir()
            app_patterns = [
                f"{temp_dir}/rbpk_*",
                f"{temp_dir}/ThreadedAdmin_*",
                f"{temp_dir}/*_script_*",
            ]
            
            for pattern in app_patterns:
                try:
                    items = glob.glob(pattern)
                    for item in items:
                        try:
                            if os.path.isfile(item):
                                os.remove(item)
                                cleaned_items.append(item)
                            elif os.path.isdir(item):
                                shutil.rmtree(item, ignore_errors=True)
                                cleaned_items.append(item)
                        except Exception as e:
                            print(f"Failed to clean {item}: {e}")
                except Exception as e:
                    print(f"Failed to process pattern {pattern}: {e}")
            
        except Exception as e:
            print(f"Failed to clean app-specific files: {e}")
        
        return cleaned_items
    
    def cleanup_all(self):
        """Perform comprehensive cleanup of all temporary resources."""
        print("Starting comprehensive cleanup...")
        
        total_cleaned = 0
        
        # Clean up tracked temp directories
        cleaned_dirs = self.cleanup_temp_directories()
        total_cleaned += len(cleaned_dirs)
        
        # Clean up tracked temp files
        cleaned_files = self.cleanup_temp_files()
        total_cleaned += len(cleaned_files)
        
        # Clean up processes
        cleaned_processes = self.cleanup_processes()
        total_cleaned += len(cleaned_processes)
        
        # Clean up system temp files
        system_cleaned = self.cleanup_system_temp()
        total_cleaned += len(system_cleaned)
        
        # Clean up app-specific files
        app_cleaned = self.cleanup_app_specific()
        total_cleaned += len(app_cleaned)
        
        print(f"Cleanup completed. Total items cleaned: {total_cleaned}")
        return total_cleaned


# Global cleanup manager instance
cleanup_manager = CleanupManager()


def register_temp_dir(temp_dir: str):
    """Register a temporary directory for cleanup."""
    cleanup_manager.add_temp_dir(temp_dir)


def register_temp_file(temp_file: str):
    """Register a temporary file for cleanup."""
    cleanup_manager.add_temp_file(temp_file)


def register_process(process):
    """Register a process for cleanup."""
    cleanup_manager.add_process(process)


def cleanup_on_exit():
    """Manually trigger cleanup."""
    return cleanup_manager.cleanup_all()
