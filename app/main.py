from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, RedirectResponse
from typing import Optional
import os
import orjson
import secrets
import urllib.parse
import httpx

from app.core.config import settings
from app.services.rooms import RoomService
from app.integrations.whop import verify_whop_token

app = FastAPI(title="WHOP Voice Chat App", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP for embedding inside whop.com
@app.middleware("http")
async def csp_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers["Content-Security-Policy"] = "frame-ancestors https://whop.com https://*.whop.com;"
    return resp

public_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
app.mount("/static", StaticFiles(directory=public_dir), name="static")

room_service = RoomService()


@app.get("/")
async def root(token: Optional[str] = None):
    # If token is provided via query (?token=..), render index and let frontend stash it
    index_path = os.path.join(public_dir, "index.html")
    return FileResponse(index_path)


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug")
async def debug():
    return {
        "client_id": settings.whop_client_id,
        "auth_url": settings.whop_auth_url,
        "redirect_url": settings.oauth_redirect_url,
        "require_auth": settings.require_auth,
        "token_url": settings.whop_token_url,
        "userinfo_url": settings.whop_userinfo_url,
        "client_secret_set": bool(settings.whop_client_secret)
    }

@app.get("/debug/token")
async def debug_token(token: str):
    """Test token verification endpoint"""
    whop_user = await verify_whop_token(token)
    return {
        "token_provided": bool(token),
        "verification_result": whop_user,
        "userinfo_url": settings.whop_userinfo_url
    }

@app.get("/auth/login")
async def auth_login():
    if not settings.whop_auth_url or not settings.whop_client_id or not settings.oauth_redirect_url:
        return Response(status_code=500, content=f"OAuth not configured: auth_url={settings.whop_auth_url}, client_id={settings.whop_client_id}, redirect_url={settings.oauth_redirect_url}")
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": settings.whop_client_id,
        "redirect_uri": settings.oauth_redirect_url,
        "scope": "openid profile",
        "state": state,
    }
    url = settings.whop_auth_url + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    print(f"DEBUG: OAuth callback received - Full URL: {request.url}")
    print(f"DEBUG: OAuth callback received - code: {bool(code)}, state: {bool(state)}")
    print(f"DEBUG: Expected redirect URI: {settings.oauth_redirect_url}")
    
    if not code:
        print("DEBUG: No authorization code received - likely redirect URI mismatch")
        print("DEBUG: Check that Whop OAuth app redirect URI exactly matches:")
        print(f"DEBUG: Expected: {settings.oauth_redirect_url}")
        return RedirectResponse("/?error=oauth_failed&reason=no_code")
        
    if not settings.whop_token_url or not settings.whop_client_id or not settings.whop_client_secret or not settings.oauth_redirect_url:
        print("DEBUG: OAuth configuration missing")
        return Response(status_code=500, content="OAuth not configured")
        
    try:
        print(f"DEBUG: Exchanging code for token at {settings.whop_token_url}")
        
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                settings.whop_token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.oauth_redirect_url,
                    "client_id": settings.whop_client_id,
                    "client_secret": settings.whop_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            
        print(f"DEBUG: Token exchange response status: {res.status_code}")
        print(f"DEBUG: Token exchange response body: {res.text}")
        
        if res.status_code != 200:
            print(f"ERROR: Token exchange failed with status {res.status_code}: {res.text}")
            return RedirectResponse(f"/?error=oauth_failed&reason=token_exchange_failed&status={res.status_code}")
            
        token_data = res.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            print("ERROR: No access_token in token exchange response")
            return RedirectResponse("/?error=oauth_failed&reason=no_access_token")
            
        print(f"DEBUG: Successfully obtained access token: {access_token[:20]}...")
        
        # Pass token to frontend via URL param; frontend will stash it to localStorage
        redirect_url = f"/?token={urllib.parse.quote(access_token)}"
        print(f"DEBUG: Redirecting to: {redirect_url}")
        return RedirectResponse(redirect_url)
        
    except httpx.HTTPStatusError as e:
        print(f"ERROR: HTTP Status Error during token exchange: {e.response.status_code} - {e.response.text}")
        return RedirectResponse(f"/?error=oauth_failed&reason=http_error&status={e.response.status_code}")
    except httpx.RequestError as e:
        print(f"ERROR: Request Error during token exchange: {e}")
        return RedirectResponse(f"/?error=oauth_failed&reason=request_error")
    except Exception as e:
        print(f"ERROR: Unexpected error during OAuth callback: {e}")
        return RedirectResponse(f"/?error=oauth_failed&reason=unexpected_error")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    client_id: Optional[str] = None
    room_id: Optional[str] = None
    user_name: Optional[str] = None

    try:
        while True:
            raw = await websocket.receive_text()
            message = orjson.loads(raw)
            msg_type = message.get("type")

            if msg_type == "join":
                room_id = message.get("roomId")
                user_name = message.get("name") or "Guest"
                token = message.get("token")

                if settings.require_auth:
                    whop_user = await verify_whop_token(token)
                    if not whop_user:
                        await websocket.send_text(orjson.dumps({"type": "error", "error": "unauthorized"}).decode())
                        await websocket.close()
                        return

                client = room_service.join(room_id=room_id, websocket=websocket, name=user_name)
                client_id = client.client_id

                await websocket.send_text(orjson.dumps({
                    "type": "joined",
                    "clientId": client_id,
                    "peers": room_service.list_peers(room_id, exclude_client_id=client_id)
                }).decode())

                await room_service.broadcast(room_id, {
                    "type": "peer-joined",
                    "clientId": client_id,
                    "name": user_name,
                }, exclude_client_id=client_id)

            elif msg_type == "chat":
                if not room_id or not client_id:
                    continue
                text = message.get("message", "")
                await room_service.broadcast(room_id, {
                    "type": "chat",
                    "fromClientId": client_id,
                    "fromName": user_name,
                    "message": text,
                })

            elif msg_type in ("offer", "answer", "ice"):
                if not room_id or not client_id:
                    continue
                target_id = message.get("to")
                payload = {"type": msg_type, "from": client_id}
                if msg_type in ("offer", "answer"):
                    payload["sdp"] = message.get("sdp")
                else:
                    payload["candidate"] = message.get("candidate")
                await room_service.send_to(room_id, target_id, payload)

            elif msg_type == "mute":
                if not room_id or not client_id:
                    continue
                await room_service.broadcast(room_id, {
                    "type": "mute",
                    "clientId": client_id,
                    "muted": bool(message.get("muted", False)),
                }, exclude_client_id=client_id)

            elif msg_type == "media-state":
                if not room_id or not client_id:
                    continue
                await room_service.broadcast(room_id, {
                    "type": "media-state",
                    "clientId": client_id,
                    "hasAudio": bool(message.get("hasAudio", False)),
                    "hasVideo": bool(message.get("hasVideo", False)),
                }, exclude_client_id=client_id)

            elif msg_type == "pitch":
                if not room_id or not client_id:
                    continue
                await room_service.broadcast(room_id, {
                    "type": "pitch",
                    "clientId": client_id,
                    "hz": message.get("hz"),
                }, exclude_client_id=client_id)

            elif msg_type == "leave":
                break

    except WebSocketDisconnect:
        pass
    finally:
        if room_id and client_id:
            name = room_service.get_name(room_id, client_id)
            room_service.leave(room_id, client_id)
            await room_service.broadcast(room_id, {"type": "peer-left", "clientId": client_id, "name": name})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
