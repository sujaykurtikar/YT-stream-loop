import logging
from typing import Optional
from ffmpeg_runner import FFmpegRunner

logger = logging.getLogger(__name__)

class StreamManager:
    """
    Service layer class to manage the FFmpeg stream instance.
    Ensures that only one stream runs at a time.
    """
    _instance: Optional['StreamManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StreamManager, cls).__new__(cls)
            cls._instance.runner = FFmpegRunner()
            cls._instance.should_be_running = False
        return cls._instance

    def start_stream(self) -> dict:
        """
        Starts the stream if it's not already running.
        """
        self.should_be_running = True
        if self.runner.is_running():
            return {"status": "success", "message": "Stream is already running", "pid": self.runner.process.pid}
        
        try:
            pid = self.runner.start()
            return {"status": "success", "message": "Stream started", "pid": pid}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop_stream(self) -> dict:
        """
        Stops the stream if it's running.
        """
        self.should_be_running = False
        if not self.runner.is_running():
            return {"status": "error", "message": "Stream is not running"}
        
        success = self.runner.stop()
        if success:
            return {"status": "success", "message": "Stream stopped"}
        else:
            return {"status": "error", "message": "Failed to stop stream gracefully"}

    def restart_stream(self) -> dict:
        """
        Restarts the stream.
        """
        self.stop_stream()
        return self.start_stream()

    def get_status(self) -> dict:
        """
        Returns the current status of the stream.
        """
        return self.runner.get_status()
