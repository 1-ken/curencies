"""Application configuration loader."""
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


class Config:
    """Application configuration."""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
        
        self.config_path = config_path
        self.data: Dict[str, Any] = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return data
        except FileNotFoundError:
            logger.error(f"Config file not found: {self.config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.data.get(key, default)
    
    @property
    def url(self) -> str:
        return self.get("url", "https://finance.yahoo.com/markets/currencies/")
    
    @property
    def wait_selector(self) -> str:
        return self.get("waitSelector", "body")
    
    @property
    def table_selector(self) -> str:
        return self.get("tableSelector", "table")
    
    @property
    def pair_cell_selector(self) -> str:
        return self.get("pairCellSelector", "tbody tr td:nth-child(2)")
    
    @property
    def stream_interval_seconds(self) -> float:
        return float(self.get("streamIntervalSeconds", 1))
    
    @property
    def majors(self) -> list:
        return self.get("majors", ["USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"])
    
    @property
    def inject_mutation_observer(self) -> bool:
        return bool(self.get("injectMutationObserver", True))


# Global config instance
config: Config = None


def get_config() -> Config:
    """Get global config instance."""
    global config
    if config is None:
        config = Config()
    return config
