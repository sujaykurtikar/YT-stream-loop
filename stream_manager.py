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
                    
                    # Calculate bitrates (bps)
                    video_bitrate = metadata.get("bitrate", 0)
                    audio_bitrate = 96000 if folder_type == "background" else 0 # 96kbps estimate
                    total_bitrate = video_bitrate + audio_bitrate
                    
                    # Bandwidth calculations
                    hourly_mb = (total_bitrate / (8 * 1024 * 1024)) * 3600
                    daily_gb = (hourly_mb * 24) / 1024
                    monthly_gb = daily_gb * 30
                    
                    report.append({
                        "file_name": file,
                        "folder": folder_type,
                        "resolution": metadata.get("resolution", "N/A"),
                        "video_bitrate_kbps": round(video_bitrate / 1000, 2),
                        "audio_bitrate_kbps": round(audio_bitrate / 1000, 2),
                        "total_bitrate_kbps": round(total_bitrate / 1000, 2),
                        "hourly_mb": round(hourly_mb, 2),
                        "daily_gb": round(daily_gb, 2),
                        "monthly_gb": round(monthly_gb, 2),
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

    def get_audio_bitrate_for_category(self, category: str = None) -> int:
        """
        Dynamically probes audio files in the selected music category.
        Returns the average bitrate in bps.
        Falls back to 128000 bps (128kbps) if no files found.
        """
        if category and category != ".":
            folder_path = os.path.join("assets", "music", category)
        else:
            folder_path = os.path.join("assets", "music")
        
        if not os.path.exists(folder_path):
            logger.warning(f"Music folder not found: {folder_path}, using 128kbps fallback")
            return 128000

        audio_extensions = (".mp3", ".aac", ".wav", ".flac", ".ogg", ".m4a")
        bitrates = []
        
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(audio_extensions):
                    file_path = os.path.join(root, file)
                    try:
                        cmd = [
                            "ffprobe", "-v", "error", "-show_entries",
                            "format=bit_rate", "-of", "default=noprint_wrappers=1:nokey=1",
                            file_path
                        ]
                        result = subprocess.check_output(cmd, shell=True).decode().strip()
                        if result and result.isdigit():
                            bitrates.append(int(result))
                    except Exception as e:
                        logger.warning(f"Could not probe {file}: {e}")
            break  # Don't recurse unless category is None or "all"

        if not bitrates:
            logger.warning(f"No audio bitrates found in {folder_path}, using 128kbps fallback")
            return 128000

        avg_bitrate = int(sum(bitrates) / len(bitrates))
        logger.info(f"Probed {len(bitrates)} audio files in '{folder_path}': avg {avg_bitrate//1000}kbps")
        return avg_bitrate

    def compress_asset(self, folder: str, file_name: str, target_v_bitrate: str = "200k") -> dict:
        """
        Compresses a file to target bitrate using FFmpeg.
        Forces a fixed GOP to satisfy YouTube keyframe requirements.
        """
        base, ext = os.path.splitext(file_name)
        input_path = os.path.join("assets", folder, file_name)
        backup_path = os.path.join("assets", folder, f"{base}_original{ext}")
        
        # If an original backup already exists, use it as the source for better quality
        source_path = backup_path if os.path.exists(backup_path) else input_path
        
        if not os.path.exists(source_path):
            return {"status": "error", "message": f"Source file {source_path} not found"}

        output_name = f"{base}_temp{ext}"
        output_path = os.path.join("assets", folder, output_name)

        # Compression Command
        # -r 15: 15fps
        # -g 30: Keyframe every 2 seconds
        # -sc_threshold 0: Disable scene change detection to keep GOP fixed
        cmd = [
            "ffmpeg", "-i", source_path,
            "-r", "15",
            "-s", "1280x720",
            "-c:v", "libx264",
            "-b:v", target_v_bitrate,
            "-g", "30",
            "-keyint_min", "30",
            "-sc_threshold", "0",
            "-maxrate", "350k",
            "-bufsize", "700k",
            "-c:a", "aac",
            "-b:a", "96k",
            output_path, "-y"
        ]

        try:
            logger.info(f"Starting compression for {file_name} using source {source_path}...")
            subprocess.run(cmd, check=True, capture_output=True)
            
            # If we used the original input_path as source, create the backup now
            if source_path == input_path:
                os.rename(input_path, backup_path)
            
            # Replace the target file with the new compressed version
            if os.path.exists(input_path):
                os.remove(input_path)
            os.rename(output_path, input_path)
            
            logger.info(f"Compression complete for {file_name}.")
            return {"status": "success", "message": f"Compressed {file_name} with 2s keyframe interval. Source used: {os.path.basename(source_path)}"}
        except subprocess.CalledProcessError as e:
            error_details = e.stderr.decode()
            logger.error(f"Compression failed: {error_details}")
            if os.path.exists(output_path): os.remove(output_path)
            return {"status": "error", "message": "Compression failed. Check logs."}
        except Exception as e:
            logger.error(f"Error during compression: {e}")
            if os.path.exists(output_path): os.remove(output_path)
            return {"status": "error", "message": str(e)}

    def trim_asset(self, folder: str, file_name: str, duration: float = 4.0) -> dict:
        """
        Trims a video to a specific duration (to fix loop keyframes).
        This is perfect for short loops to keep bandwidth extremely low.
        """
        base, ext = os.path.splitext(file_name)
        input_path = os.path.join("assets", folder, file_name)
        backup_path = os.path.join("assets", folder, f"{base}_original{ext}")
        
        source_path = backup_path if os.path.exists(backup_path) else input_path
        if not os.path.exists(source_path):
            return {"status": "error", "message": f"Source file {source_path} not found"}

        output_name = f"{base}_temp{ext}"
        output_path = os.path.join("assets", folder, output_name)

        # Trimming Command
        # This re-encodes but ONLY the short duration, so the final file is tiny!
        cmd = [
            "ffmpeg", "-i", source_path,
            "-t", str(duration),
            "-r", "15",
            "-s", "1280x720",
            "-c:v", "libx264",
            "-crf", "28",           # High compression for static loops
            "-g", "999",            # Only one keyframe at the very start
            "-c:a", "aac",
            "-b:a", "96k",
            output_path, "-y"
        ]

        try:
            logger.info(f"Trimming {file_name} to {duration}s...")
            subprocess.run(cmd, check=True, capture_output=True)
            
            if source_path == input_path:
                os.rename(input_path, backup_path)
            
            if os.path.exists(input_path):
                os.remove(input_path)
            os.rename(output_path, input_path)
            
            return {"status": "success", "message": f"Trimmed to {duration}s. This loop now fulfills YouTube keyframe requirement via the loop point."}
        except Exception as e:
            logger.error(f"Trimming failed: {e}")
            return {"status": "error", "message": str(e)}
