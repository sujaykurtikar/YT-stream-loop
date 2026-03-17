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

    def build_command(self, stream_config: dict) -> List[str]:
        """
        Constructs the FFmpeg command according to requirements based on stream_config.
        """
        folder = stream_config.get("folder", "background")
        video_file = stream_config.get("video_file", "ganeshmantra.mp4")
        video_path = os.path.join("assets", folder, video_file)
        mode = stream_config.get("mode", "video_only")
        
        if mode == "video_only":
            cmd = [
                "ffmpeg",
                "-re",
                "-fflags", "+genpts+igndts+flush_packets",
                "-avoid_negative_ts", "make_zero",
                "-thread_queue_size", "512",
                "-stream_loop", "-1",
                "-i", video_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "96k",
                "-ar", "44100",
                "-pix_fmt", "yuv420p",
                "-bsf:a", "aac_adtstoasc",
                "-flvflags", "+no_duration_filesize",
                "-rtmp_live", "live",
                "-f", "flv",
                settings.full_rtmp_url
            ]
        else:
            # background_and_audio mode
            cmd = [
                "ffmpeg",
                "-re",
                "-fflags", "+genpts+igndts+flush_packets",
                "-avoid_negative_ts", "make_zero",
                "-thread_queue_size", "512",
                "-stream_loop", "-1",
                "-i", video_path,
                "-thread_queue_size", "512",
                "-stream_loop", "-1",
                "-f", "concat",
                "-safe", "0",
                "-i", settings.PLAYLIST_PATH,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "96k",
                "-ar", "44100",
                "-map", "0:v:0", # Use video from first input
                "-map", "1:a:0", # Use audio from second input
                "-pix_fmt", "yuv420p",
                "-bsf:a", "aac_adtstoasc",
                "-flvflags", "+no_duration_filesize",
                "-rtmp_live", "live",
                "-f", "flv",
                settings.full_rtmp_url
            ]
        return cmd

    def start(self, stream_config: dict = None) -> int:
        """
        Starts the FFmpeg process.
        Returns: PID of the started process.
        """
        if stream_config is None:
            stream_config = {"mode": "video_only", "video_file": "ganeshmantra.mp4", "folder": "video_only"}

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

        cmd = self.build_command(stream_config)
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
