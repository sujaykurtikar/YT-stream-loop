import os
import logging
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("generate_playlist")

def generate_playlist():
    """
    Scans the music directory and generates a playlist.txt in FFmpeg concat format.
    """
    music_dir = settings.MUSIC_DIR
    playlist_file = settings.PLAYLIST_PATH

    if not os.path.exists(music_dir):
        logger.error(f"Music directory not found: {music_dir}")
        return

    audio_extensions = ('.mp3', '.wav', '.flac', '.m4a', '.ogg')
    files = [f for f in os.listdir(music_dir) if f.lower().endswith(audio_extensions)]
    
    if not files:
        logger.warning(f"No audio files found in {music_dir}")
        return

    # Sort files to ensure consistent order
    files.sort()

    logger.info(f"Generating playlist with {len(files)} files...")
    
    with open(playlist_file, 'w', encoding='utf-8') as f:
        for file in files:
            # FFmpeg concat format requires: file 'path/to/file'
            # We use absolute paths or paths relative to the working directory
            full_path = os.path.abspath(os.path.join(music_dir, file))
            # Escape single quotes in filenames for FFmpeg
            safe_path = full_path.replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    logger.info(f"Playlist generated at: {playlist_file}")

if __name__ == "__main__":
    generate_playlist()
