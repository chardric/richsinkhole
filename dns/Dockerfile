FROM python:3.12-slim

WORKDIR /dns

# Install Python deps
RUN pip install --no-cache-dir dnslib pyyaml

COPY . /dns/

EXPOSE 53/udp
EXPOSE 53/tcp

CMD ["python", "server.py"]
