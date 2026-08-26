from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlanTier(str, Enum):
    FREE = "FREE"
    PRO = "PRO"

class Settings(BaseSettings):
    PROJECT_NAME: str = "FlyRank Metering & Billing API"
    POSTGRES_USER: str = "Fly_admin"
    POSTGRES_PASSWORD: str = "Fly-secret_pass"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "metering_db"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    STRIPE_SECRET_KEY: str = "sk_test_mock"
    STRIPE_WEBHOOK_SECRET: str = "whsec_mock"

    # Micro-Cent Rates per Tokens ($1 USD = 100,000,000 micro-cents)
    RATE_STANDARD_INPUTS_MICROCENTS: int = 300    # $3.00 / 1M                  
    RATE_CACHED_INPUT_MICROCENTS: int = 150       # $1.50 / 1M  
    RATE_OUTPUT_MICROCENTS: int = 1500            # $15.00 / 1M
    RATE_REASONING_MICROCENTS: int = 1500         # $15.00 / 1M


    @property
    def async_database_url(self) -> str:
        return(
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

def calculate_cost_microcents(
        standard_input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
) -> int:
    """Computes exact total request cost in micro-cents using 64-bit integer arithmetic."""
    return(
        (standard_input_tokens * settings.RATE_STANDARD_INPUTS_MICROCENTS)
        +(cached_input_tokens * settings.RATE_CACHED_INPUT_MICROCENTS)
        +(output_tokens * settings.RATE_OUTPUT_MICROCENTS)
        +(reasoning_tokens * settings.RATE_REASONING_MICROCENTS)
    )
    
        