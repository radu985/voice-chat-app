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

    whop_client_id: str | None = os.getenv("WHOP_CLIENT_ID")
    whop_client_secret: str | None = os.getenv("WHOP_CLIENT_SECRET")
    whop_auth_url: str | None = os.getenv("WHOP_AUTH_URL")
    whop_token_url: str | None = os.getenv("WHOP_TOKEN_URL")
    whop_userinfo_url: str | None = os.getenv("WHOP_USERINFO_URL")
    oauth_redirect_url: str | None = os.getenv("OAUTH_REDIRECT_URL")
    whop_product_id: str | None = os.getenv("WHOP_PRODUCT_ID")


settings = Settings()


