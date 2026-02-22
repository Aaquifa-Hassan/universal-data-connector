import pytest
from app.services.business_rules import apply_voice_limits

def test_apply_voice_limits():
    data = [{"id": i} for i in range(10)]
    result = apply_voice_limits(data)
    assert len(result) == 3
    assert result == [{"id": 0}, {"id": 1}, {"id": 2}]
