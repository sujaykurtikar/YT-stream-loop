import asyncio
import logging
import os
from stream_manager import StreamManager
from config import settings
from betterstack_logger import betterstack_logger

logger = logging.getLogger(__name__)

async def health_monitor_task():
    """
    Background task to monitor FFmpeg process health.
    Restarts the stream if it crashes.
    """
    manager = StreamManager()
    logger.info(f"Health monitor started (checking every {settings.CHECK_INTERVAL}s)")
    
    # We only auto-restart if the stream was supposedly "intended" to be running.
    # We can track this with a flag in the manager if needed, but for now 
    # let's assume if it's not running, we check if it SHOULD be.
    # In a real production system, you might have a "desired_state".
    
    desired_state_running = False # Initial state

    while True:
        try:
            status = manager.get_status()
            is_running = status["is_running"]
            
            # Simple logic: If we start it once, we want it to stay up.
            # This can be refined based on API calls.
            if not is_running:
                # Check logs or status to see if it crashed
                # For now, let's just log and wait for API to start it.
                # If we want 24/7 reliability, we should auto-restart if it was running before.
                pass
            
            await asyncio.sleep(settings.CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in health monitor: {e}")
            await asyncio.sleep(settings.CHECK_INTERVAL)

class HealthMonitor:
    def __init__(self, manager: StreamManager):
        self.manager = manager
        self.is_monitoring = False
        self.task: Optional[asyncio.Task] = None

    async def start(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self.task = asyncio.create_task(self.run())
        logger.info("Health monitoring service started.")

    async def run(self):
        while self.is_monitoring:
            try:
                status = self.manager.get_status()
                # If it's NOT running but SHOULD be, it means it crashed.
                if not status["is_running"] and self.manager.should_be_running:
                    msg = "Stream crash detected! Attempting auto-restart..."
                    logger.warning(msg)
                    
                    # Try to capture last FFmpeg error efficiently
                    error_details = ""
                    try:
                        if os.path.exists("ffmpeg_output.log"):
                            with open("ffmpeg_output.log", "rb") as f:
                                # Seek to near the end of the file
                                f.seek(0, os.SEEK_END)
                                size = f.tell()
                                # Read last 2KB, which should contain enough logs
                                offset = min(size, 2048)
                                f.seek(-offset, os.SEEK_END)
                                last_logs = f.read().decode('utf-8', errors='ignore')
                                error_details = "\nLast FFmpeg logs:\n..." + last_logs[-1000:]
                    except Exception as log_err:
                        error_details = f"\nCould not read ffmpeg_output.log: {log_err}"
                    
                    await betterstack_logger.send_log(msg + error_details, level="WARNING")
                    
                    result = self.manager.start_stream()
                    if result["status"] == "success":
                        success_msg = f"Auto-restart successful. New PID: {result.get('pid')}"
                        logger.info(success_msg)
                        await betterstack_logger.send_log(success_msg)
                    else:
                        fail_msg = f"Auto-restart failed: {result.get('message')}"
                        logger.error(fail_msg)
                        await betterstack_logger.send_log(fail_msg, level="ERROR")
                
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
            
            await asyncio.sleep(settings.CHECK_INTERVAL)

    async def stop(self):
        self.is_monitoring = False
        if self.task:
            self.task.cancel()
            logger.info("Health monitoring service stopped.")
