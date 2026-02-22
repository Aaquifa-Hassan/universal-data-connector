
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseConnector(ABC):

    @abstractmethod
    def fetch(self, **kwargs) -> List[Dict[str, Any]]:
        pass
