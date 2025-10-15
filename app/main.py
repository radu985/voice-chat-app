from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from typing import Optional
import os
import orjson

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
