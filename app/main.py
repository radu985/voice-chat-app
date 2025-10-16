from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, RedirectResponse, HTMLResponse
from typing import Optional
import os
import orjson
import secrets
import httpx
from urllib.parse import urlencode

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

@app.middleware("http")
async def csp_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers["Content-Security-Policy"] = "frame-ancestors https://whop.com https://*.whop.com;"
    return resp

public_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
app.mount("/static", StaticFiles(directory=public_dir), name="static")

room_service = RoomService()


@app.get("/")
async def root():
    index_path = os.path.join(public_dir, "index.html")
    return FileResponse(index_path)


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/auth/login")
async def auth_login():
    if not all([settings.whop_auth_url, settings.whop_client_id, settings.oauth_redirect_url]):
        return HTMLResponse("OAuth not configured", status_code=500)
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.whop_client_id,
        "response_type": "code",
        "redirect_uri": settings.oauth_redirect_url,
        "scope": "openid profile email",
        "state": state,
    }
    url = f"{settings.whop_auth_url}?{urlencode(params)}"
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        return HTMLResponse("Missing code", status_code=400)
    if not all([settings.whop_token_url, settings.whop_client_id, settings.whop_client_secret, settings.oauth_redirect_url]):
        return HTMLResponse("OAuth not configured", status_code=500)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
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
        if token_resp.status_code != 200:
            return HTMLResponse("Token exchange failed", status_code=401)
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return HTMLResponse("No access token", status_code=401)
        # Simple page to stash token to localStorage then redirect home
        html = f"""
<!doctype html><html><body>
<script>
localStorage.setItem('whop_token', '{access_token}');
window.location.href = '/';
</script>
</body></html>
"""
        return HTMLResponse(html)
    except Exception:
        return HTMLResponse("OAuth error", status_code=500)


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
