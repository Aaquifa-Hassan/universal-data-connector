
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class AsyncBaseConnector(ABC):

    @abstractmethod
    async def execute_query(self, query: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a query and return a standardized envelope:
        { "success": bool, "data": Any, "message": str }
        """
        pass
