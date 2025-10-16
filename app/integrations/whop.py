from typing import Optional, Dict
import httpx
from app.core.config import settings


async def verify_whop_token(token: Optional[str]) -> Optional[Dict]:
    if not token:
        return None
    if not settings.whop_userinfo_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                settings.whop_userinfo_url,
                headers={"Authorization": f"Bearer {token}"},
            )
        if res.status_code != 200:
            return None
        data = res.json()
        return {
            "id": data.get("sub") or data.get("id") or data.get("user_id"),
            "name": data.get("name") or data.get("username") or data.get("email") or "Whop User",
            "raw": data,
        }
    except Exception:
        return None
