
import json
import os
from typing import List, Dict, Any, Optional

class CredentialsManager:
    """Manages datalake configurations and credentials."""
    
    def __init__(self, config_path: str = "credentials.json"):
        self.config_path = config_path
        self._config: Dict[str, Any] = {"datalakes": []}
        self.load_config()

    def load_config(self):
        """Load credentials from JSON file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    self._config = json.load(f)
            except Exception as e:
                print(f"Error loading credentials from {self.config_path}: {e}")
        else:
            print(f"Credentials file {self.config_path} not found.")

    def get_datalakes(self) -> List[Dict[str, Any]]:
        """Return all configured datalakes."""
        return self._config.get("datalakes", [])

    def get_datalake_by_id(self, datalake_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific datalake configuration by its ID."""
        for dl in self.get_datalakes():
            if dl.get("id") == datalake_id:
                return dl
        return None

    def get_credentials(self, datalake_id: str) -> Optional[Dict[str, Any]]:
        """Get credentials for a specific datalake."""
        dl = self.get_datalake_by_id(datalake_id)
        return dl.get("credentials") if dl else None

# Global instance
credentials_manager = CredentialsManager()
