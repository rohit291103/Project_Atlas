import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    github_token: str
    supabase_db_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            github_token=os.environ["GITHUB_TOKEN"],
            supabase_db_url=os.environ["SUPABASE_DB_URL"],
        )
