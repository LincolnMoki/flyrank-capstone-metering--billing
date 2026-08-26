import pytest
from app.services.pricing import calculate_usage_cost

def test_zero_tokens():
    assert calculate_usage_cost(0, 0, 0, 0) == 0

def test_standard_pricing():
    # 1,000,000 standard input = 300 microcents
    # 1,000,000 output = 1500 microcents
    cost = calculate_usage_cost(1_000_000, 0, 1_000_000, 0)
    assert cost == 300 + 1500

def test_cached_and_reasoning_pricing():
    cost = calculate_usage_cost(0, 1_000_000, 0, 1_000_000)
    assert cost == 150 + 1500

def test_extreme_volume_and_mixed():
    cost = calculate_usage_cost(500_000, 500_000, 200_000, 100_000)
    expected = (
        (500_000 * 300) +
        (500_000 * 150) +
        (200_000 * 1500) +
        (100_000 * 1500)
    )
    assert cost == expected

def test_negative_tokens_raises_error():
    with pytest.raises(ValueError):
        calculate_usage_cost(-10, 0, 0, 0)