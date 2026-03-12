import subprocess
import logging
import os
import signal
from typing import Optional, List
from config import settings

logger = logging.getLogger(__name__)

class FFmpegRunner:
    """
    Handles building and running the FFmpeg command for the 24/7 stream.
    """
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None

    def build_command(self) -> List[str]:
        """
        Constructs the FFmpeg command according to requirements.
        -stream_loop -1: Loop the background video infinitely
        -c:v copy: Do not re-encode video (save CPU)
        -c:a aac: Encode audio to AAC
        -b:a 128k: Audio bitrate
        -fflags +genpts: Generate PTS for smooth streaming
        """
        cmd = [
            "ffmpeg",
            "-re", 
            "-stream_loop", "-1",
            "-i", settings.BACKGROUND_VIDEO_PATH,
            "-stream_loop", "-1",
            "-f", "concat",
            "-safe", "0",
            "-i", settings.PLAYLIST_PATH,
            "-c:v", "libx264",
            "-b:v", settings.VIDEO_BITRATE,
            "-preset", "veryfast",
            "-tune", "stillimage", # Optimized for static background loop
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-map", "0:v:0", # Use video from first input
            "-map", "1:a:0", # Use audio from second input
            "-pix_fmt", "yuv420p", # Ensure compatibility
            "-bsf:a", "aac_adtstoasc",
            "-fflags", "+genpts",
            "-rtmp_live", "live",
            "-f", "flv",
            settings.full_rtmp_url
        ]
        return cmd

    def start(self) -> int:
        """
        Starts the FFmpeg process.
        Returns: PID of the started process.
        """
        if self.is_running():
            logger.warning("FFmpeg is already running.")
            return self.process.pid

        # Verify FFmpeg is installed
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            error_msg = "FFmpeg not found or not working. Please ensure it's installed and in your PATH."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        cmd = self.build_command()
        logger.info(f"Starting FFmpeg with command: {' '.join(cmd)}")
        
        try:
            # Open a file for FFmpeg output
            self.output_log = open("ffmpeg_output.log", "w", encoding="utf-8")
            
            # Start process in background
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=self.output_log,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            logger.info(f"FFmpeg started with PID: {self.process.pid}")
            return self.process.pid
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            raise

    def stop(self) -> bool:
        """
        Stops the FFmpeg process gracefully.
        """
        if not self.process:
            return True

        logger.info(f"Stopping FFmpeg process (PID: {self.process.pid})...")
        try:
            if os.name == 'nt':
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
            
            self.process.wait(timeout=10)
            logger.info("FFmpeg stopped gracefully.")
            self.process = None
            return True
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg did not stop gracefully, killing...")
            self.process.kill()
            self.process = None
            return True
        except Exception as e:
            logger.error(f"Error while stopping FFmpeg: {e}")
            self.process = None
            return False

    def is_running(self) -> bool:
        """
        Checks if the FFmpeg process is currently active.
        """
        if self.process is None:
            return False
        
        # poll() returns None if process is still running
        return self.process.poll() is None

    def get_status(self) -> dict:
        """
        Returns the current status of the FFmpeg process.
        """
        running = self.is_running()
        return {
            "is_running": running,
            "pid": self.process.pid if running else None
        }
