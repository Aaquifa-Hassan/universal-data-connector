from typing import List, Dict, Any

def summarize_if_large(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # If the data is still too large after limiting, we might want to 
    # summarize it further. For now, we'll just return it as is.
    # In a real implementation, this could use an LLM to summarize the content.
    return data
