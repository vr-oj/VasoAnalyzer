# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import requests
from requests.exceptions import Timeout
from utils.config import APP_VERSION


def check_for_new_version(current_version=f"v{APP_VERSION}"):
    try:
        response = requests.get(
            "https://api.github.com/repos/vr-oj/VasoAnalyzer/releases/latest",
            timeout=5,
        )
        if response.status_code == 200:
            latest_version = response.json().get("tag_name", "")
            if latest_version and latest_version != current_version:
                return latest_version
    except Timeout:
        print("Update check timed out")
    except Exception as e:
        print(f"Update check failed: {e}")
    return None
