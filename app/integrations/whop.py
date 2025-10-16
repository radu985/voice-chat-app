from typing import Optional, Dict
import os
import httpx

USERINFO_URL = os.getenv("WHOP_USERINFO_URL")


async def verify_whop_token(token: Optional[str]) -> Optional[Dict]:
    if not token or not USERINFO_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return None
        data = r.json()
        # Normalize minimal fields expected by the app
        return {
            "id": data.get("sub") or data.get("id") or data.get("uid"),
            "name": data.get("name") or data.get("username") or data.get("email") or "Whop User",
            "raw": data,
        }
    except Exception:
        return None
