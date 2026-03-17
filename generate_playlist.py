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
    music_root = settings.MUSIC_DIR
    target_dir = os.path.join(music_root, category) if category and category != "all" else music_root
    
    playlist_file = settings.PLAYLIST_PATH

    if not os.path.exists(target_dir):
        logger.error(f"Music directory not found: {target_dir}")
        return

    audio_extensions = ('.mp3', '.wav', '.flac', '.m4a', '.ogg')
    files_with_paths = []

    if category == "all":
        # Recursive scan for everything
        for root, _, filenames in os.walk(music_root):
            for f in filenames:
                if f.lower().endswith(audio_extensions):
                    files_with_paths.append(os.path.join(root, f))
    else:
        # Shallow scan for specific category or root
        for f in os.listdir(target_dir):
            if f.lower().endswith(audio_extensions):
                files_with_paths.append(os.path.join(target_dir, f))
    
    if not files_with_paths:
        logger.warning(f"No audio files found in {target_dir}")
        return

    # Sort files to ensure consistent order
    files_with_paths.sort()

    logger.info(f"Generating playlist for {category or 'root'} with {len(files_with_paths)} files...")
    
    with open(playlist_file, 'w', encoding='utf-8') as f:
        playlist_dir = os.path.dirname(os.path.abspath(playlist_file))
        for abs_path in files_with_paths:
            rel_path = os.path.relpath(abs_path, playlist_dir)
            # Ensure path uses forward slashes for FFmpeg compatibility
            safe_path = rel_path.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    logger.info(f"Playlist generated at: {playlist_file}")


if __name__ == "__main__":
    generate_playlist()
