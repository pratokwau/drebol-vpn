from __future__ import annotations

from typing import Any

import aiohttp

from xui.config_runtime import get_xui_token, get_xui_url


def _headers() -> dict[str, str]:
    token = get_xui_token().strip()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers.update(
            {
                "Authorization": f"Bearer {token}",
                "X-API-KEY": token,
                "X-Token": token,
                "token": token,
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


def _extract_list_payload(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    candidates: list[Any] = [
        data.get("obj"),
        data.get("data"),
        data.get("result"),
        data.get("inbounds"),
    ]
    for item in candidates:
        if isinstance(item, list):
            return [x for x in item if isinstance(x, dict)]
        if isinstance(item, dict):
            nested = item.get("inbounds")
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
            for key in ("list", "items"):
                nested_list = item.get(key)
                if isinstance(nested_list, list):
                    return [x for x in nested_list if isinstance(x, dict)]
    return []


async def api_get_inbounds() -> tuple[list[dict[str, Any]], str]:
    paths = [
        "/panel/api/inbounds/list",
        "/panel/api/inbounds",
        "/api/inbounds/list",
        "/api/inbounds",
    ]
    last_err = ""
    for path in paths:
        data, err = await xui_get(path)
        if err:
            last_err = err
        payload = _extract_list_payload(data)
        if payload:
            return payload, ""
    return [], last_err or "Некорректный ответ панели"
