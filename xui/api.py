from __future__ import annotations

from typing import Any

import aiohttp

from xui.config_runtime import get_xui_token, get_xui_url

_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(ssl=False)
        _session = aiohttp.ClientSession(connector=connector)
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()


def _headers() -> dict[str, str]:
    token = get_xui_token().strip()
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def xui_get(path: str) -> dict:
    xui_url = get_xui_url()
    xui_token = get_xui_token()
    if not xui_url or not xui_token:
        return {"success": False, "msg": "XUI_URL/XUI_TOKEN not configured"}
    session = await get_session()
    try:
        async with session.get(f"{xui_url}{path}", headers=_headers(), ssl=False) as resp:
            text = await resp.text()
            print(f"[XUI GET] {path} → {resp.status} {text[:200]}")
            try:
                return await resp.json(content_type=None)
            except Exception:
                return {"success": False, "msg": f"HTTP {resp.status}: {text[:100]}"}
    except Exception as e:
        return {"success": False, "msg": str(e)}


async def xui_post(path: str, data=None) -> dict:
    xui_url = get_xui_url()
    xui_token = get_xui_token()
    if not xui_url or not xui_token:
        return {"success": False, "msg": "XUI_URL/XUI_TOKEN not configured"}
    session = await get_session()
    try:
        kwargs = {
            "headers": {
                "Authorization": f"Bearer {xui_token}",
                "Content-Type": "application/json",
            },
            "ssl": False,
            "allow_redirects": True,
        }
        if data is not None:
            kwargs["json"] = data
        async with session.post(f"{xui_url}{path}", **kwargs) as resp:
            text = await resp.text()
            print(f"[XUI POST] {path} → {resp.status} {text[:200]}")
            try:
                return await resp.json(content_type=None)
            except Exception:
                return {"success": False, "msg": f"HTTP {resp.status}: {text[:100]}"}
    except Exception as e:
        return {"success": False, "msg": str(e)}


def _extract_obj(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    for key in ("obj", "data", "result"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return data


async def api_get_inbounds() -> tuple[list[dict[str, Any]], str]:
    result = await xui_get("/panel/api/inbounds/list")
    if not isinstance(result, dict):
        return [], "Пустой ответ от панели 3x-ui"
    if result.get("success"):
        obj = result.get("obj", [])
        return (obj if isinstance(obj, list) else [], "")
    # fallback for different panels
    for path in ("/panel/api/inbounds", "/api/inbounds/list", "/api/inbounds"):
        result = await xui_get(path)
        if not isinstance(result, dict):
            continue
        if result.get("success"):
            obj = result.get("obj", [])
            if isinstance(obj, list):
                return obj, ""
    return [], result.get("msg", "Неизвестная ошибка API")


async def api_get_client(email: str) -> dict | None:
    result = await xui_get(f"/panel/api/clients/get/{email}")
    if not result.get("success"):
        return None
    obj = _extract_obj(result)
    client = obj.get("client") if isinstance(obj.get("client"), dict) else obj
    return client if isinstance(client, dict) else None


async def api_add_client(ib_id: int, email: str, expiry_days: int, limit_gb: float, flow: str = "") -> tuple[dict, str]:
    import time
    import uuid as uuid_lib

    expiry_time = 2523456000000  # 12.12.2050
    if expiry_days > 0:
        expiry_time = int((time.time() + expiry_days * 86400) * 1000)
    total_bytes = 0 if limit_gb <= 0 else int(limit_gb * 1024 ** 3)
    client_uuid = str(uuid_lib.uuid4())
    client = {
        "id": client_uuid,
        "email": email,
        "flow": flow,
        "limitIp": 0,
        "totalGB": total_bytes,
        "expiryTime": expiry_time,
        "enable": True,
        "tgId": 0,
        "reset": 0,
    }
    result = await xui_post("/panel/api/clients/add", data={"client": client, "inboundIds": [ib_id]})
    return result, client_uuid


async def api_del_client_by_email(email: str) -> dict:
    return await xui_post(f"/panel/api/clients/del/{email}")


async def api_update_client(email: str, client_obj: dict) -> dict:
    allowed = {"email", "subId", "id", "flow", "totalGB", "expiryTime", "limitIp", "tgId", "comment", "enable", "reset"}
    payload = {k: v for k, v in client_obj.items() if k in allowed}
    if "id" in payload and isinstance(payload["id"], int):
        payload.pop("id", None)
    return await xui_post(f"/panel/api/clients/update/{email}", data=payload)


async def api_reset_client_traffic(email: str) -> dict:
    return await xui_post(f"/panel/api/clients/resetTraffic/{email}")
