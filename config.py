import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # App Settings
    STREAM_KEY: str = ""
    BACKGROUND_VIDEO_PATH: str = "assets/background/backgroundVideo.mp4"
    PLAYLIST_PATH: str = "playlist/playlist.txt"
    YOUTUBE_RTMP_URL: str = "rtmp://a.rtmp.youtube.com/live2"
    
    # Better Stack Logging Settings
    BETTER_STACK_TOKEN: str = ""
    BETTER_STACK_URL: str = "https://s2292498.eu-fsn-3.betterstackdata.com"
    
    # Utility Settings
    MUSIC_DIR: str = "assets/music"
    CHECK_INTERVAL: int = 30  # seconds
    
    # Computed property for full RTMP URL
    @property
    def full_rtmp_url(self) -> str:
        return f"{self.YOUTUBE_RTMP_URL}/{self.STREAM_KEY}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings
settings = Settings()

# Ensure necessary directories exist
Path("playlist").mkdir(exist_ok=True)
