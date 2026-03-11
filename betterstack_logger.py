import httpx
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from config import settings

logger = logging.getLogger(__name__)

class BetterStackLogger:
    """
    Utility to send logs to Better Stack asynchronously.
    """
    def __init__(self):
        self.token = settings.BETTER_STACK_TOKEN
        self.url = settings.BETTER_STACK_URL
        self.client = httpx.AsyncClient(verify=False) # --insecure as per user request

    async def send_log(self, message: str, level: str = "INFO"):
        """
        Sends a log message to Better Stack.
        """
        if not self.token:
            return

        payload = {
            "dt": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "message": f"[{level}] {message}"
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }

        try:
            response = await self.client.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
        except Exception as e:
            # We don't want to crash the app if logging fails
            logging.error(f"Failed to send log to Better Stack: {e}")

    async def close(self):
        await self.client.aclose()

# Singleton instance
betterstack_logger = BetterStackLogger()
