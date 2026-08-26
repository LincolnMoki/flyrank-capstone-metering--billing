from app.core.config import settings

def calculate_usage_cost(
    standard_input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
) -> int:
    """Computes exact total cost in microcents using integer arithmetic."""
    if any(t < 0 for t in [standard_input_tokens, cached_input_tokens, output_tokens, reasoning_tokens]):
        raise ValueError("Token counts cannot be negative.")
        
    return (
        (standard_input_tokens * settings.RATE_STANDARD_INPUTS_MICROCENTS)
        + (cached_input_tokens * settings.RATE_CACHED_INPUT_MICROCENTS)
        + (output_tokens * settings.RATE_OUTPUT_MICROCENTS)
        + (reasoning_tokens * settings.RATE_REASONING_MICROCENTS)
    )