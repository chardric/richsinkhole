FROM python:3.12-slim

WORKDIR /dashboard

RUN pip install --no-cache-dir fastapi uvicorn[standard] aiosqlite httpx jinja2 python-multipart pyyaml "qrcode[pil]" dnslib

COPY . /dashboard/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
