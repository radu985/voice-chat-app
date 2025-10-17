from typing import Optional, Dict
import httpx
from app.core.config import settings


async def verify_whop_token(token: Optional[str]) -> Optional[Dict]:
    if not token:
        print("DEBUG: No token provided")
        return None
    if not settings.whop_userinfo_url:
        print("DEBUG: WHOP_USERINFO_URL not configured")
        return None
    
    print(f"DEBUG: Verifying token with URL: {settings.whop_userinfo_url}")
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                settings.whop_userinfo_url,
                headers={"Authorization": f"Bearer {token}"},
            )
        
        print(f"DEBUG: Whop API response status: {res.status_code}")
        print(f"DEBUG: Whop API response body: {res.text}")
        
        if res.status_code != 200:
            print(f"DEBUG: Token verification failed with status {res.status_code}")
            return None
            
        data = res.json()
        user_data = {
            "id": data.get("sub") or data.get("id") or data.get("user_id"),
            "name": data.get("name") or data.get("username") or data.get("email") or "Whop User",
            "raw": data,
        }
        print(f"DEBUG: Token verification successful: {user_data}")
        return user_data
        
    except httpx.TimeoutException:
        print("DEBUG: Whop API request timed out")
        return None
    except httpx.RequestError as e:
        print(f"DEBUG: Whop API request error: {e}")
        return None
    except Exception as e:
        print(f"DEBUG: Unexpected error during token verification: {e}")
        return None
