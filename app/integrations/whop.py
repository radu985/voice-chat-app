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

async def check_product_access(token: Optional[str], product_id: Optional[str] = None) -> bool:
    """
    Check if user has access to the voice chat product.
    If product_id is provided, check specific product access.
    If not provided, assume any valid Whop user has access.
    """
    # If no Whop configuration is available, allow access (development mode)
    if not settings.whop_userinfo_url or not settings.whop_client_id:
        print("DEBUG: Whop configuration missing, allowing access (development mode)")
        return True
    
    if not token:
        print("DEBUG: No token provided for product access check")
        # If no specific product_id required, allow access even without token
        if not product_id:
            print("DEBUG: No product_id required, allowing access without token")
            return True
        return False
        
    # First verify the token is valid
    user_data = await verify_whop_token(token)
    if not user_data:
        print("DEBUG: Token verification failed, denying access")
        return False
    
    # If no specific product_id required, any valid user has access
    if not product_id:
        print(f"DEBUG: No product_id required, allowing access for user {user_data.get('id')}")
        return True
    
    # TODO: Implement product-specific access check
    # This would require calling Whop's products/entitlements API
    # For now, return True if user is authenticated
    print(f"DEBUG: Product access check for product_id={product_id}, user={user_data.get('id')}")
    return True
