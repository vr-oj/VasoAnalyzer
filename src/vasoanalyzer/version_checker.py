import requests
from utils.config import APP_VERSION


def check_for_new_version(current_version=f"v{APP_VERSION}"):
    try:
        response = requests.get("https://api.github.com/repos/vr-oj/VasoAnalyzer/releases/latest")
        if response.status_code == 200:
            latest_version = response.json().get("tag_name", "")
            if latest_version and latest_version != current_version:
                return latest_version
    except Exception as e:
        print(f"Update check failed: {e}")
    return None
