import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")
MOCK_DIR = os.path.join(DATA_DIR, "mock")

def get_game_upload_dir(game_id: str) -> str:
    path = os.path.join(UPLOADS_DIR, game_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_game_output_dir(game_id: str) -> str:
    path = os.path.join(OUTPUTS_DIR, game_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_clips_dir(game_id: str, player_name: str) -> str:
    safe_name = sanitize_player_name(player_name)
    path = os.path.join(get_game_output_dir(game_id), "clips", safe_name)
    os.makedirs(path, exist_ok=True)
    return path

def get_rendered_dir(game_id: str) -> str:
    path = os.path.join(get_game_output_dir(game_id), "rendered")
    os.makedirs(path, exist_ok=True)
    return path

def get_approved_dir(game_id: str) -> str:
    path = os.path.join(get_game_output_dir(game_id), "approved")
    os.makedirs(path, exist_ok=True)
    return path


def get_scan_dir(game_id: str) -> str:
    path = os.path.join(get_game_output_dir(game_id), "scan")
    os.makedirs(path, exist_ok=True)
    return path


def get_digit_templates_dir(game_id: str, profile_name: str) -> str:
    path = os.path.join(get_scan_dir(game_id), "digit_templates", profile_name)
    os.makedirs(path, exist_ok=True)
    return path


def sanitize_player_name(name: str) -> str:
    """Convert player name to safe folder/filename format."""
    import re
    safe = re.sub(r"[^\w\s-]", "", name)
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe
