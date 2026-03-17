import logging
import os
import subprocess
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from typing import List, Dict
from enum import Enum
from config import settings
from stream_manager import StreamManager

class StreamMode(str, Enum):
    video_only = "video_only"
    background_and_audio = "background_and_audio"

# Helper to get files with bandwidth info
def get_file_choices(directory: str, add_audio_bitrate: bool = False) -> Dict[str, str]:
    choices = {}
    if not os.path.exists(directory):
        return choices
    
    for f in os.listdir(directory):
        if f.endswith(('.mp4', '.mkv', '.mov')):
            # Get bitrate
            try:
                # Use shell=True for broader Windows PATH compatibility
                cmd = f'ffprobe -v quiet -show_entries format=bit_rate -of default=noprint_wrappers=1:nokey=1 "{os.path.join(directory, f)}"'
                output = subprocess.check_output(cmd, shell=True).decode().strip()
                bitrate = int(output or 0)
                
                if add_audio_bitrate:
                    bitrate += 96000 # Add audio bitrate for background videos
                
                hourly_mb = round((bitrate / (8 * 1024 * 1024)) * 3600, 1)
                kbps = round(bitrate / 1000, 0)
                label = f.split(".")[0].replace("-", "_").replace(" ", "_")
                
                # Make label very explicit
                suffix = "COMBINED" if add_audio_bitrate else "TOTAL"
                choices[f"{label}__{suffix}_{kbps}kbps_{hourly_mb}MB_hr"] = f
            except Exception as e:
                logger.debug(f"Bandwidth probe failed for {f}: {e}")
                label = f.split(".")[0].replace("-", "_").replace(" ", "_")
                choices[label] = f
    return choices

def get_bandwidth_summary_text():
    """Generates a plain text summary for the Swagger UI description."""
    try:
        report = manager.get_bandwidth_report()
        if not report: return "No video assets found."
        
        lines = ["### 📊 Bandwidth Estimation Summary", "| File | Bitrate | Hourly Usage | State |", "| :--- | :--- | :--- | :--- |"]
        for item in report:
            status = "✅ OK" if item["is_optimized"] else "⚠️ HIGH"
            lines.append(f"| {item['file_name']} | {item['bitrate_kbps']}k | {item['hourly_mb']} MB/hr | {status} |")
        return "\n".join(lines)
    except:
        return "Bandwidth estimation is loading..."

# Generate the enums with bandwidth labels
bg_choices = get_file_choices(os.path.join("assets", "background"), add_audio_bitrate=True)
vo_choices = get_file_choices(os.path.join("assets", "video_only"), add_audio_bitrate=False)

if not bg_choices: bg_choices = {"None": "none"}
if not vo_choices: vo_choices = {"None": "none"}

BackgroundFileEnum = Enum('BackgroundFileEnum', bg_choices)
VideoOnlyFileEnum = Enum('VideoOnlyFileEnum', vo_choices)

def get_subdirs(directory: str) -> list:
    if os.path.exists(directory):
        return [d for d in os.listdir(directory) if os.path.isdir(os.path.join(directory, d))]
    return []

music_categories = get_subdirs(settings.MUSIC_DIR)
# Always include 'All' and 'General' options
cat_choices = {"All_Music": "all", "General_Root": "."}
for d in music_categories:
    cat_choices[d.replace("-", "_").replace(" ", "_")] = d

MusicCategoryEnum = Enum('MusicCategoryEnum', cat_choices)
from health_monitor import HealthMonitor
from betterstack_logger import betterstack_logger
from generate_playlist import generate_playlist

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("yt-stream-loop")

# Initialize Manager and Monitor
manager = StreamManager()
monitor = HealthMonitor(manager)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Generate playlist, start health monitor and send startup log
    generate_playlist()
    await monitor.start()
    await betterstack_logger.send_log("yt-stream-loop service started.")
    yield
    # Shutdown: Stop health monitor, stream and send shutdown log
    await betterstack_logger.send_log("yt-stream-loop service shutting down.")
    await monitor.stop()
    manager.stop_stream()
    await betterstack_logger.close()

app = FastAPI(
    title="yt-stream-loop API",
    description="API to manage 24/7 YouTube Live Stream using FFmpeg",
    lifespan=lifespan
)

@app.get("/")
async def root():
    """Root endpoint to handle platform health check pings and eliminate 404 logs."""
    return {"status": "online", "message": "yt-stream-loop API is running"}

@app.post("/stream/check/video-only", tags=["Stream Management"])
async def check_bandwidth_video_only(
    video_file: VideoOnlyFileEnum = Query(..., description="Select file to check bandwidth")
):
    """
    Check estimated bandwidth for a video-only asset.
    (Dry-run: does NOT start the stream)
    """
    report = manager.get_bandwidth_report()
    file_stats = next((item for item in report if item["file_name"] == video_file.value), {})
    return {
        "status": "success",
        "action": "bandwidth_check",
        "mode": "video_only",
        "file": video_file.value,
        "bandwidth_info": {
            "video_bitrate_kbps": file_stats.get("video_bitrate_kbps"),
            "audio_bitrate_kbps": file_stats.get("audio_bitrate_kbps"),
            "total_bitrate_kbps": file_stats.get("total_bitrate_kbps"),
            "hourly_mb": f"{file_stats.get('hourly_mb')} MB/hr",
            "monthly_gb_estimate": f"{file_stats.get('monthly_gb')} GB/month",
            "is_within_limit": file_stats.get("is_optimized")
        }
    }

@app.post("/stream/check/background-and-audio", tags=["Stream Management"])
async def check_bandwidth_background(
    video_file: BackgroundFileEnum = Query(..., description="Select background video to check"),
    audio_category: MusicCategoryEnum = Query(..., description="Music category for estimated total")
):
    """
    Check estimated bandwidth for background + audio mode.
    (Dry-run: does NOT start the stream)
    Audio bitrate is dynamically probed from actual files in the selected category.
    """
    report = manager.get_bandwidth_report()
    file_stats = next((item for item in report if item["file_name"] == video_file.value), {})
    
    # Dynamically probe real audio bitrate for selected category
    audio_bitrate_bps = manager.get_audio_bitrate_for_category(audio_category.value)
    audio_bitrate_kbps = round(audio_bitrate_bps / 1000, 2)
    
    # Recalculate totals with real audio bitrate
    video_bitrate_kbps = file_stats.get("video_bitrate_kbps", 0)
    total_bitrate_kbps = round(video_bitrate_kbps + audio_bitrate_kbps, 2)
    hourly_mb = round((total_bitrate_kbps * 1000 * 3600) / (8 * 1024 * 1024), 2)
    daily_gb = round((hourly_mb * 24) / 1024, 2)
    monthly_gb = round(daily_gb * 30, 2)
    
    return {
        "status": "success",
        "action": "bandwidth_check",
        "mode": "background_and_audio",
        "video_file": video_file.value,
        "audio_category": audio_category.value,
        "bandwidth_info": {
            "video_bitrate_kbps": video_bitrate_kbps,
            "audio_bitrate_kbps": audio_bitrate_kbps,
            "total_bitrate_kbps": total_bitrate_kbps,
            "hourly_mb": f"{hourly_mb} MB/hr",
            "daily_gb": f"{daily_gb} GB/day",
            "monthly_gb_estimate": f"{monthly_gb} GB/month",
            "is_optimized": monthly_gb < 90
        }
    }

@app.post("/stream/start/video-only", tags=["Stream Management"])
async def start_stream_video_only(
    video_file: VideoOnlyFileEnum = Query(..., description="Select a combined video+audio file from assets/video_only")
):
    """
    Start stream using a single combined video and audio file (looping).
    
    ### 📊 Bandwidth usage for these files:
    - **ganeshmantra.mp4**: ~101 MB/hr (Optimized)
    - Others: See Bandwidth Report for details.
    """
    stream_config = {
        "mode": StreamMode.video_only.value, 
        "video_file": video_file.value, 
        "folder": "video_only"
    }
    result = manager.start_stream(stream_config)
    
    # Add bandwidth context to response
    if result["status"] == "success":
        report = manager.get_bandwidth_report()
        file_stats = next((item for item in report if item["file_name"] == video_file.value), {})
        result["bandwidth_info"] = {
            "mode": "video_only (combined file)",
            "video_bitrate_kbps": file_stats.get("video_bitrate_kbps"),
            "audio_bitrate_kbps": file_stats.get("audio_bitrate_kbps"),
            "total_bitrate_kbps": file_stats.get("total_bitrate_kbps"),
            "hourly_mb": f"{file_stats.get('hourly_mb')} MB/hr",
            "monthly_gb_estimate": f"{file_stats.get('monthly_gb')} GB/month",
            "is_within_limit": file_stats.get("is_optimized")
        }
    
    return handle_result(result)

@app.post("/stream/start/background-and-audio", tags=["Stream Management"])
async def start_stream_with_audio(
    video_file: BackgroundFileEnum = Query(..., description="Select a background video from assets/background"),
    audio_category: MusicCategoryEnum = Query(..., description="Select the music category (playlist) to use")
):
    """
    Start stream using a background video + the separate audio playlist.
    
    ### ⚠️ Bandwidth Warning (incl. 96kbps audio):
    - **backgroundVideo.mp4**: ~150 MB/hr
    - **backgroundVideo_old.mp4**: ~3,000 MB/hr (HIGH USAGE!)
    """
    # Re-generate the playlist based on chosen category
    generate_playlist(audio_category.value if audio_category.value != "." else None)
    
    stream_config = {
        "mode": StreamMode.background_and_audio.value, 
        "video_file": video_file.value, 
        "folder": "background"
    }
    result = manager.start_stream(stream_config)
    
    # Add bandwidth context to response
    if result["status"] == "success":
        report = manager.get_bandwidth_report()
        file_stats = next((item for item in report if item["file_name"] == video_file.value), {})
        result["bandwidth_info"] = {
            "mode": "background_and_audio (combined estimate)",
            "video_bitrate_kbps": file_stats.get("video_bitrate_kbps"),
            "audio_bitrate_kbps": file_stats.get("audio_bitrate_kbps"),
            "total_bitrate_kbps": file_stats.get("total_bitrate_kbps"),
            "hourly_mb": f"{file_stats.get('hourly_mb')} MB/hr",
            "monthly_gb_estimate": f"{file_stats.get('monthly_gb')} GB/month",
            "is_within_limit": file_stats.get("is_optimized")
        }
    
    return handle_result(result)

def handle_result(result: dict):
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

# Remove the old consolidated endpoint
# @app.post("/stream/start")
# ...

@app.get("/assets/bandwidth-report", tags=["Asset Management"])
async def bandwidth_report():
    """Returns a report on all video assets and their estimated bandwidth consumption."""
    return manager.get_bandwidth_report()

@app.post("/assets/compress/background", tags=["Asset Management"])
async def compress_background(
    video_file: BackgroundFileEnum = Query(..., description="Select the background video to compress"),
    target_v_bitrate: str = Query("200k", description="Target video bitrate (e.g., 200k, 500k)")
):
    """
    Compresses a background video. 
    Backs up original and optimizes for bandwidth.
    """
    result = manager.compress_asset("background", video_file.value, target_v_bitrate)
    return handle_result(result)

@app.post("/assets/compress/video-only", tags=["Asset Management"])
async def compress_video_only(
    video_file: VideoOnlyFileEnum = Query(..., description="Select the video-only file to compress"),
    target_v_bitrate: str = Query("200k", description="Target video bitrate (e.g., 200k, 500k)")
):
    """
    Compresses a video-only asset.
    Backs up original and optimizes for bandwidth.
    """
    result = manager.compress_asset("video_only", video_file.value, target_v_bitrate)
    return handle_result(result)


@app.post("/assets/trim/video-only", tags=["Asset Management"])
async def trim_video_only(
    video_file: VideoOnlyFileEnum = Query(..., description="Select the video-only file to trim"),
    duration: float = Query(4.0, description="Target duration in seconds (4.0 is recommended for YouTube loops)")
):
    """
    Trims a video loop to a shorter duration. 
    This fix is perfect for short loops to satisfy YouTube's 4s keyframe limit 
    at the loop point with ZERO extra bandwidth.
    """
    result = manager.trim_asset("video_only", video_file.value, duration)
    return handle_result(result)

@app.post("/assets/trim/background", tags=["Asset Management"])
async def trim_background(
    video_file: BackgroundFileEnum = Query(..., description="Select the background video to trim"),
    duration: float = Query(4.0, description="Target duration in seconds (4.0 is recommended for YouTube loops)")
):
    """
    Trims a background video loop to a shorter duration.
    """
    result = manager.trim_asset("background", video_file.value, duration)
    return handle_result(result)

@app.post("/stream/stop")
async def stop_stream():
    result = manager.stop_stream()
    if result["status"] == "error":
        await betterstack_logger.send_log(f"Stream stop failed: {result['message']}", level="ERROR")
        raise HTTPException(status_code=400, detail=result["message"])
    await betterstack_logger.send_log("Stream stopped successfully.")
    return result

@app.post("/stream/restart")
async def restart_stream():
    return manager.restart_stream()

@app.get("/stream/status")
async def get_status():
    return manager.get_status()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "ffmpeg": manager.get_status()}

@app.head("/health-check")
async def health_check_simple():
    """Simple health check returning JSON for platform monitoring."""
    return {"status": "ok"}

def find_available_port(start_port: int, max_attempts: int = 10) -> int:
    """Finds an available port starting from start_port."""
    import socket
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except socket.error:
                continue
    return start_port # Fallback to start_port

if __name__ == "__main__":
    import uvicorn
    # Use PORT from env, or default to 8080
    requested_port = int(os.getenv("PORT", 8080))
    port = find_available_port(requested_port)
    
    if port != requested_port:
        logger.info(f"Port {requested_port} was busy. Automatically switched to {port}")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
