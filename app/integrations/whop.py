from typing import Optional, Dict


async def verify_whop_token(token: Optional[str]) -> Optional[Dict]:
    if not token:
        return None
    # TODO: Replace with real WHOP verification via HTTP request to your WHOP server
    return {"id": "whop-user", "scopes": ["chat", "voice"]}
