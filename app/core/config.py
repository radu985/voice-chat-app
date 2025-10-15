from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", "8000"))
    require_auth: bool = os.getenv("REQUIRE_AUTH", "false").lower() == "true"
    cors_allow_origins: list[str] = (
        os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173").split(",")
        if os.getenv("CORS_ALLOW_ORIGINS")
        else ["*"]
    )


settings = Settings()
