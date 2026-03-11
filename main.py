import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from config import settings
from stream_manager import StreamManager
from health_monitor import HealthMonitor
from betterstack_logger import betterstack_logger

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
    # Startup: Start health monitor and send startup log
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
