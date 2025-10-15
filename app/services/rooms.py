from __future__ import annotations

from dataclasses import dataclass
from fastapi import WebSocket
from typing import Dict, Optional, List
import uuid
import orjson


@dataclass
class Client:
    client_id: str
    name: str
    websocket: WebSocket


class Room:
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id
        self.clients: Dict[str, Client] = {}

    def add_client(self, client: Client) -> None:
        self.clients[client.client_id] = client

    def remove_client(self, client_id: str) -> None:
        if client_id in self.clients:
            del self.clients[client_id]


class RoomService:
    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}

    def get_or_create(self, room_id: str) -> Room:
        room = self.rooms.get(room_id)
        if not room:
            room = Room(room_id)
            self.rooms[room_id] = room
        return room

    def join(self, room_id: str, websocket: WebSocket, name: str) -> Client:
        room = self.get_or_create(room_id)
        client = Client(client_id=str(uuid.uuid4()), name=name, websocket=websocket)
        room.add_client(client)
        return client

    def leave(self, room_id: str, client_id: str) -> None:
        room = self.rooms.get(room_id)
        if not room:
            return
        room.remove_client(client_id)
        if not room.clients:
            del self.rooms[room_id]

    async def broadcast(self, room_id: str, message: dict, exclude_client_id: Optional[str] = None) -> None:
        room = self.rooms.get(room_id)
        if not room:
            return
        text = orjson.dumps(message).decode()
        for cid, client in list(room.clients.items()):
            if exclude_client_id and cid == exclude_client_id:
                continue
            try:
                await client.websocket.send_text(text)
            except Exception:
                self.leave(room_id, cid)

    async def send_to(self, room_id: str, client_id: str, message: dict) -> None:
        room = self.rooms.get(room_id)
        if not room:
            return
        client = room.clients.get(client_id)
        if not client:
            return
        await client.websocket.send_text(orjson.dumps(message).decode())

    def list_peers(self, room_id: str, exclude_client_id: Optional[str] = None) -> List[dict]:
        room = self.rooms.get(room_id)
        if not room:
            return []
        peers = []
        for cid, client in room.clients.items():
            if exclude_client_id and cid == exclude_client_id:
                continue
            peers.append({"clientId": cid, "name": client.name})
        return peers

    def get_name(self, room_id: str, client_id: str) -> Optional[str]:
        room = self.rooms.get(room_id)
        if not room:
            return None
        client = room.clients.get(client_id)
        return client.name if client else None
