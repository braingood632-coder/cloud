"""
خوادم وهمية لتليجرام وميسر للاختبار الشامل على Firebase Emulator.
  python tests/fake_services.py 8900
تليجرام:  /bot<TOKEN>/<method>
ميسر:     /v1/invoices , /v1/payments/<id>
تحكم:     GET /_calls  |  POST /_pay/<invoice_id>  |  POST /_reset
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BOT = {"id": 999, "is_bot": True, "first_name": "Cloud", "username": "CloudTestBot",
       "can_join_groups": True, "can_read_all_group_messages": True, "supports_inline_queries": False}
GROUP_ADMIN = 111
STATE = {"calls": [], "invoices": {}, "webhook": "", "msg_id": 1000}


def _user(uid):
    return {"id": uid, "is_bot": uid == 999, "first_name": f"u{uid}"}


def _admin(uid, creator=False):
    if creator:
        return {"status": "creator", "user": _user(uid), "is_anonymous": False}
    return {"status": "administrator", "user": _user(uid), "can_be_edited": False, "is_anonymous": False,
            "can_manage_chat": True, "can_delete_messages": True, "can_manage_video_chats": False,
            "can_restrict_members": True, "can_promote_members": False, "can_change_info": False,
            "can_invite_users": True, "can_post_stories": False, "can_edit_stories": False, "can_delete_stories": False}


def telegram(method: str, p: dict):
    STATE["calls"].append({"method": method, "params": p, "t": time.time()})
    if method == "getMe":
        return BOT
    if method == "getChatMember":
        uid = int(p["user_id"])
        if uid == 999:
            return _admin(999)
        if uid == GROUP_ADMIN:
            return _admin(uid, creator=True)
        return {"status": "member", "user": _user(uid)}
    if method in ("sendMessage", "editMessageText"):
        STATE["msg_id"] += 1
        chat_id = int(p.get("chat_id", 0))
        return {"message_id": STATE["msg_id"], "date": int(time.time()),
                "chat": {"id": chat_id, "type": "supergroup" if chat_id < 0 else "private"}, "text": p.get("text", "")}
    if method == "getChat":
        return {"id": int(p["chat_id"]), "type": "supergroup", "title": "قروب عقارات الرياض",
                "accent_color_id": 0, "max_reaction_count": 11}
    if method == "getChatMemberCount":
        return 350
    if method == "setWebhook":
        STATE["webhook"] = p.get("url", "")
        return True
    if method == "getWebhookInfo":
        return {"url": STATE["webhook"], "has_custom_certificate": False, "pending_update_count": 0}
    return True  # deleteMessage, answerCallbackQuery, ...


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _params(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(raw or b"{}")
        out = {}
        for k, v in parse_qs(raw.decode()).items():
            try:
                out[k] = json.loads(v[0])
            except ValueError:
                out[k] = v[0]
        return out

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/_calls":
            return self._send(200, STATE["calls"])
        if path.startswith("/v1/invoices/"):
            inv = STATE["invoices"].get(path.rsplit("/", 1)[1])
            return self._send(200 if inv else 404, inv or {"message": "not found"})
        if path.startswith("/v1/payments/"):
            pid = path.rsplit("/", 1)[1]
            for inv in STATE["invoices"].values():
                for pay in inv["payments"]:
                    if pay["id"] == pid:
                        return self._send(200, {**pay, "invoice_id": inv["id"]})
            return self._send(404, {})
        if path.startswith("/bot"):
            return self._dispatch(path, {})
        self._send(404, {})

    def do_POST(self):
        path = urlparse(self.path).path
        params = self._params()
        if path == "/_reset":
            STATE["calls"].clear()
            if params.get("webhook"):
                STATE["webhook"] = ""
            return self._send(200, {"ok": True})
        if path.startswith("/_pay/"):
            inv = STATE["invoices"][path.rsplit("/", 1)[1]]
            inv["status"] = "paid"
            inv["payments"] = [{"id": "pay_" + inv["id"][:8], "status": "paid", "source": {"type": "creditcard"}}]
            return self._send(200, inv)
        if path == "/v1/invoices":
            iid = str(uuid.uuid4())
            inv = {"id": iid, "status": "initiated", "amount": params["amount"], "currency": params["currency"],
                   "description": params["description"], "metadata": params.get("metadata"),
                   "url": f"https://checkout.moyasar.com/invoices/{iid}", "payments": []}
            STATE["invoices"][iid] = inv
            return self._send(201, inv)
        if path.startswith("/bot"):
            return self._dispatch(path, params)
        self._send(404, {})

    def _dispatch(self, path, params):
        method = path.rsplit("/", 1)[1]
        self._send(200, {"ok": True, "result": telegram(method, params)})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8900
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
