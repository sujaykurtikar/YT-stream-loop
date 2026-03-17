import os
import logging
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("generate_playlist")

def generate_playlist(category: str = None):
    """
    Scans the music directory (or a specific category subdirectory) 
    and generates a playlist.txt in FFmpeg concat format.
    """
    music_dir = settings.MUSIC_DIR
    if category:
        music_dir = os.path.join(music_dir, category)
        
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

    logger.info(f"Generating playlist for {category or 'root'} with {len(files)} files...")
    
    with open(playlist_file, 'w', encoding='utf-8') as f:
        for file in files:
            # FFmpeg concat format requires: file 'path/to/file'
            # Paths should be relative to the playlist file itself
            abs_audio_path = os.path.abspath(os.path.join(music_dir, file))
            playlist_dir = os.path.dirname(os.path.abspath(playlist_file))
            rel_path = os.path.relpath(abs_audio_path, playlist_dir)
            
            # Ensure path uses forward slashes for FFmpeg compatibility
            safe_path = rel_path.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    logger.info(f"Playlist generated at: {playlist_file}")


if __name__ == "__main__":
    generate_playlist()
