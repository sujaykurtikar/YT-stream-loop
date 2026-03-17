import logging
import os
import subprocess
import json
from typing import Optional, List, Dict
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
            cls._instance.stream_config = {"mode": "video_only", "video_file": "ganeshmantra.mp4", "folder": "video_only"}
        return cls._instance

    def start_stream(self, stream_config: dict = None) -> dict:
        """
        Starts the stream if it's not already running.
        """
        self.should_be_running = True
        if stream_config is not None:
            self.stream_config = stream_config
            
        if self.runner.is_running():
            return {"status": "success", "message": "Stream is already running", "pid": self.runner.process.pid}
        
        try:
            pid = self.runner.start(self.stream_config)
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

    def get_bandwidth_report(self) -> List[Dict]:
        """
        Analyzes all videos in assets/background and assets/video_only.
        Returns a list of dictionaries with metadata and hourly bandwidth estimates.
        """
        report = []
        directories = {
            "background": "assets/background",
            "video_only": "assets/video_only"
        }

        for folder_type, path in directories.items():
            if not os.path.exists(path):
                continue
            
            for file in os.listdir(path):
                if file.endswith((".mp4", ".mkv", ".mov")):
                    file_path = os.path.join(path, file)
                    metadata = self._probe_file(file_path)
                    
                    # Calculate hourly bandwidth
                    # Bitrate is in bits/sec. 
                    # Bits to Megabytes: bits / (8 * 1024 * 1024)
                    # Seconds to Hour: * 3600
                    bitrate = metadata.get("bitrate", 0)
                    
                    # If background mode, we add the 96kbps audio stream which will be mixed in
                    total_bitrate = bitrate
                    if folder_type == "background":
                        total_bitrate += 96000 # 96kbps audio
                    
                    hourly_mb = (total_bitrate / (8 * 1024 * 1024)) * 3600
                    
                    report.append({
                        "file_name": file,
                        "folder": folder_type,
                        "resolution": metadata.get("resolution", "N/A"),
                        "bitrate_kbps": round(total_bitrate / 1000, 2),
                        "hourly_mb": round(hourly_mb, 2),
                        "is_optimized": hourly_mb <= 140 # Threshold around 90GB/mo target
                    })
        return report

    def _probe_file(self, file_path: str) -> dict:
        """Uses ffprobe to get resolution and bitrate."""
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path
            ]
            result = subprocess.check_output(cmd).decode('utf-8')
            data = json.loads(result)
            
            format_info = data.get("format", {})
            bitrate = int(format_info.get("bit_rate", 0))
            
            video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
            width = video_stream.get("width")
            height = video_stream.get("height")
            resolution = f"{width}x{height}" if width and height else "N/A"
            
            return {"bitrate": bitrate, "resolution": resolution}
        except Exception as e:
            logger.error(f"Error probing {file_path}: {e}")
            return {"bitrate": 0, "resolution": "N/A"}

    def compress_asset(self, folder: str, file_name: str, target_v_bitrate: str = "200k") -> dict:
        """
        Compresses a file to target bitrate using FFmpeg.
        """
        input_path = os.path.join("assets", folder, file_name)
        if not os.path.exists(input_path):
            return {"status": "error", "message": f"File {input_path} not found"}

        # Use a temporary name for compression
        base, ext = os.path.splitext(file_name)
        output_name = f"{base}_temp{ext}"
        output_path = os.path.join("assets", folder, output_name)
        backup_path = os.path.join("assets", folder, f"{base}_original{ext}")

        # Compression Command
        # -r 15: Reduce framerate to 15fps
        # -s 1280x720: Ensure resolution is 720p
        # -c:v libx264: Use H.264
        # -c:a aac -b:a 96k: Target audio bitrate
        cmd = [
            "ffmpeg", "-i", input_path,
            "-r", "15",
            "-s", "1280x720",
            "-c:v", "libx264",
            "-b:v", target_v_bitrate,
            "-maxrate", "250k",
            "-bufsize", "500k",
            "-c:a", "aac",
            "-b:a", "96k",
            output_path, "-y"
        ]

        try:
            logger.info(f"Starting compression for {file_name}...")
            subprocess.run(cmd, check=True, capture_output=True)
            
            # If successful, backup original and swap
            if os.path.exists(backup_path):
                os.remove(backup_path) # Clean up previous backup if any
                
            os.rename(input_path, backup_path)
            os.rename(output_path, input_path)
            
            logger.info(f"Compression complete for {file_name}.")
            return {"status": "success", "message": f"Compressed {file_name}. Original backed up as {os.path.basename(backup_path)}"}
        except subprocess.CalledProcessError as e:
            error_details = e.stderr.decode()
            logger.error(f"Compression failed: {error_details}")
            return {"status": "error", "message": "Compression failed. Check logs."}
        except Exception as e:
            logger.error(f"Error during compression: {e}")
            return {"status": "error", "message": str(e)}
