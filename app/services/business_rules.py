from typing import List, Dict, Any

def apply_voice_limits(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # For voice interfaces, we want to limit the amount of data returned
    # to avoid overwhelming the user with TTS output.
    # We'll limit to the top 3 items.
    return data[:3]
