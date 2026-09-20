"""Theme, uploads and plugins: the ``themeModule``/``pluginsModule`` ports.

Plugin payloads are the same "one big text blob injected into the frontend" model
as on Android, stored in ``plugins.json`` instead of a SharedPreferences file,
with the same 5 MiB ceiling so a runaway paste cannot fill the root filesystem.
Uploads live under ``<data_dir>/uploads`` -- the Linux analogue of
``filesDir/uploads`` -- and are served with the same traversal protection.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Dict, List, Optional, Tuple

from ..httpd import ApiError, Response, guess_content_type, json_response
from ..store import MAX_PLUGIN_BYTES, MAX_UPLOAD_BYTES, new_upload_name

_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_DISPOSITION_RE = re.compile(r'name="([^"]*)"(?:;\s*filename="([^"]*)")?', re.IGNORECASE)


def parse_multipart(body: bytes, content_type: str) -> List[Tuple[str, Optional[str], bytes]]:
    """Minimal multipart/form-data parser (fields and file parts).

    Only the first ``filename`` part matters for this API, but parsing all of it
    keeps the helper honest and testable.
    """
    match = _BOUNDARY_RE.search(content_type or "")
    if not match:
        raise ApiError("缺少 multipart boundary", 400)
    boundary = ("--" + match.group(1)).encode("utf-8")

    parts: List[Tuple[str, Optional[str], bytes]] = []
    for chunk in body.split(boundary):
        if not chunk.strip() or chunk.strip() == b"--":
            continue
        head, _, payload = chunk.partition(b"\r\n\r\n")
        if not _:
            continue
        payload = payload.rstrip(b"\r\n")
        if payload.endswith(b"--"):
            payload = payload[:-2]
        header_text = head.decode("utf-8", "replace")
        disposition = _DISPOSITION_RE.search(header_text)
        if not disposition:
            continue
        parts.append((disposition.group(1) or "", disposition.group(2), payload))
    return parts


def _uploads_dir(app) -> str:
    path = app.config.uploads_dir
    os.makedirs(path, exist_ok=True)
    return path


def register(router, app) -> None:
    config = app.config

    # -- uploaded files ----------------------------------------------------
    def serve_upload(request):
        relative = request.params.get("tail", "") if hasattr(request, "params") else ""
        relative = relative.lstrip("/")
        if not relative or relative.startswith("/") or "\x00" in relative:
            return Response(403, b"403 Forbidden", "text/plain; charset=utf-8")
        root = os.path.realpath(_uploads_dir(app))
        target = os.path.realpath(os.path.join(root, relative))
        if target != root and not target.startswith(root + os.sep):
            return Response(403, b"403 Forbidden", "text/plain; charset=utf-8")
        if not os.path.isfile(target):
            return Response(404, b"404 Not Found", "text/plain; charset=utf-8")
        with open(target, "rb") as handle:
            payload = handle.read()
        return Response(200, payload, guess_content_type(target))

    router.add("GET", "/api/uploads/{...}", serve_upload)

    def upload_img(request):
        content_type = request.header("Content-Type", "multipart/form-data")
        parts = parse_multipart(request.body, content_type)
        file_part = next((part for part in parts if part[1]), None)
        if file_part is None:
            raise ApiError("未找到上传文件")
        _, original, payload = file_part
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ApiError("文件过大（上限 %dMB）" % (MAX_UPLOAD_BYTES // 1024 // 1024))
        name = new_upload_name(original or "file")
        target = os.path.join(_uploads_dir(app), name)
        with open(target, "wb") as handle:
            handle.write(payload)
        return json_response({"url": "/uploads/%s" % name})

    router.add("POST", "/api/upload_img", upload_img)

    def delete_img(request):
        file_name = str(request.json_body().get("file_name") or "").strip()
        if ".." in file_name or file_name.startswith("/"):
            raise ApiError("文件名非法")
        target = os.path.join(_uploads_dir(app), file_name)
        try:
            os.remove(target)
        except FileNotFoundError:
            pass  # Android also reports success for a missing file
        except OSError as exc:
            raise ApiError("删除失败: %s" % exc)
        return json_response({"result": "success"})

    router.add("POST", "/api/delete_img", delete_img)

    def delete_all_uploads(request):
        root = _uploads_dir(app)
        deleted: Dict[str, bool] = {}
        for name in os.listdir(root):
            target = os.path.join(root, name)
            if not os.path.isfile(target):
                continue
            try:
                os.remove(target)
                deleted[name] = True
            except OSError:
                deleted[name] = False
        return json_response({"result": "success", "deleted_list": deleted})

    router.add("POST", "/api/delete_all_uploads_data", delete_all_uploads)

    # -- theme -------------------------------------------------------------
    router.add("GET", "/api/get_theme", lambda request: json_response(app.theme.merged()))

    def set_theme(request):
        app.theme.update(request.json_body())
        return json_response({"result": "success"})

    router.add("POST", "/api/set_theme", set_theme)

    # -- plugins -----------------------------------------------------------
    router.add("GET", "/api/get_custom_head", lambda request: json_response({"text": app.plugins.text}))

    def set_custom_head(request):
        raw = request.body
        if len(raw) > MAX_PLUGIN_BYTES:
            raise ApiError("配置出错: 插件总容量超出限制: %dKB/%dKB" % (
                len(raw) // 1024, MAX_PLUGIN_BYTES // 1024))
        text = str(request.json_body().get("text") or "").strip()
        app.plugins.set_text(text)
        return json_response({"result": "success"})

    router.add("POST", "/api/set_custom_head", set_custom_head)

    def plugins_store(request):
        base = str(config.get("GLOBAL_SERVER_URL") or "").rstrip("/")
        download_url = "%s/d/UFI-TOOLS-UPDATE/plugins/ufi-tools-plugins" % base
        payload = json.dumps({
            "path": "/UFI-TOOLS-UPDATE/plugins/ufi-tools-plugins",
            "password": "",
            "page": 1,
            "per_page": 0,
            "refresh": False,
        }).encode("utf-8")
        upstream = urllib.request.Request(
            "%s/api/fs/list" % base,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(upstream, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            raise ApiError("请求出错: %s" % exc)
        return json_response({"download_url": download_url, "res": body})

    router.add("GET", "/api/plugins_store", plugins_store)
