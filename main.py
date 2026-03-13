import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from config import settings
from stream_manager import StreamManager
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

@app.post("/stream/start")
async def start_stream():
    result = manager.start_stream()
    if result["status"] == "error":
        await betterstack_logger.send_log(f"Stream start failed: {result['message']}", level="ERROR")
        raise HTTPException(status_code=400, detail=result["message"])
    await betterstack_logger.send_log(f"Stream started successfully. PID: {result.get('pid')}")
    return result

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
