WHOP Voice Chat App (FastAPI + WebRTC)

A modern web-based chat and voice app where users join channels, chat, and talk freely (everyone can speak and unmute themselves). Built with Python FastAPI, WebSockets for signaling, and WebRTC for media.

Project Structure
- app/
  - core/config.py          # settings and CORS
  - integrations/whop.py    # WHOP token verification stub
  - services/rooms.py       # in-memory rooms and signaling helpers
  - main.py                 # FastAPI app and WebSocket endpoint
- public/
  - index.html              # UI
  - styles.css              # modern styling
  - app.js                  # WebRTC + chat client logic
- requirements.txt
- README.md

Prerequisites
- Python 3.10+

Quick Start
1) Install dependencies
   pip install -r requirements.txt

2) (Optional) Configure environment via .env
   Copy .env.example to .env and adjust values.

3) Run the server (dev)
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

4) Open the app
   http://localhost:8000

Notes for WebRTC
- Browsers typically require HTTPS for getUserMedia/WebRTC except on localhost.
- For LAN/production, serve behind HTTPS (e.g., Caddy, Nginx, Cloudflare Tunnel).

Everyone-can-speak Policy
- All participants publish audio/video by default. The Mute button locally disables audio tracks; unmute re-enables them. There is no server-side mute gatekeeping.

WHOP Integration Stub
- Frontend sends a token with the join message (localStorage key: whop_token).
- If REQUIRE_AUTH=true, the server calls app.integrations.whop.verify_whop_token(). Replace this stub with real verification against your WHOP server.

Environment Variables (.env)
- APP_HOST=0.0.0.0
- APP_PORT=8000
- REQUIRE_AUTH=false
- CORS_ALLOW_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

Security & Production
- Replace WHOP verification with a secure implementation.
- Configure proper CORS.
- Use HTTPS and a TURN server for NAT traversal if needed.

License
- MIT
