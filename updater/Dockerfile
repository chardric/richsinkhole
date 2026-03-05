FROM python:3.12-slim

WORKDIR /updater

RUN pip install --no-cache-dir httpx pyyaml schedule

COPY updater.py /updater/

CMD ["python", "updater.py"]
