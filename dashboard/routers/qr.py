import io
import os
import socket

import qrcode
from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()


def _host_ip() -> str:
    ip = os.getenv("HOST_IP", "")
    if ip:
        return ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "YOUR_SERVER_IP"


def _make_qr_png(data: str) -> bytes:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/qr/dns")
async def qr_dns():
    png = _make_qr_png(_host_ip())
    return Response(content=png, media_type="image/png")


@router.get("/qr/doh")
async def qr_doh():
    ip = _host_ip()
    png = _make_qr_png(f"http://{ip}/dns-query")
    return Response(content=png, media_type="image/png")
