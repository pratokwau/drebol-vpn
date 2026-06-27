from __future__ import annotations

from typing import Any

import aiohttp

from xui.config_runtime import get_xui_token, get_xui_url


def _headers() -> dict[str, str]:
    token = get_xui_token().strip()
    headers = {"Accept": "application/json"}
    if token:
        headers.update(
            {
                "Authorization": f"Bearer {token}",
                "X-API-KEY": token,
                "X-Token": token,
            }
        )
    return headers


def _url(path: str) -> str:
    base = get_xui_url().rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


async def xui_request(method: str, path: str, *, json_data: Any | None = None) -> tuple[dict[str, Any] | None, str]:
    url = _url(path)
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers=_headers()) as session:
            async with session.request(method.upper(), url, json=json_data) as resp:
                text = await resp.text()
                if "application/json" in resp.headers.get("Content-Type", ""):
                    try:
                        return await resp.json(content_type=None), ""
                    except Exception:
                        return None, text
                return None, text
    except Exception as exc:
        return None, str(exc)


async def xui_get(path: str) -> tuple[dict[str, Any] | None, str]:
    return await xui_request("GET", path)


async def xui_post(path: str, json_data: Any | None = None) -> tuple[dict[str, Any] | None, str]:
    return await xui_request("POST", path, json_data=json_data)


async def api_get_inbounds() -> tuple[list[dict[str, Any]], str]:
    data, err = await xui_get("/panel/api/inbounds/list")
    if not data:
        return [], err
    obj = data.get("obj") if isinstance(data, dict) else None
    if isinstance(obj, list):
        return obj, ""
    if isinstance(obj, dict):
        return obj.get("inbounds", []) if isinstance(obj.get("inbounds", []), list) else [], ""
    return [], err or "Некорректный ответ панели"
