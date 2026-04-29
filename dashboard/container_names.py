# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""Container-name resolution for dashboard routers.

Compose v2 names containers as ``<project>-<service>-1`` by default, where
``<project>`` is the working-directory name unless ``COMPOSE_PROJECT_NAME``
is set. Routers that talk to sibling services via ``docker exec``/``docker
restart`` historically hardcoded ``richsinkhole-X-1`` strings, which silently
break the moment the project is renamed or relocated.

Resolution order (first hit wins):
  1. ``<NAME>_CONTAINER`` env var (e.g. ``UNBOUND_CONTAINER``) — exact override
  2. ``RS_CONTAINER_PREFIX`` env var + ``-<service>-1``
  3. ``richsinkhole-<service>-1`` (current default; matches install.sh)
"""

import os

_PREFIX = os.getenv("RS_CONTAINER_PREFIX", "richsinkhole")


def _resolve(service: str, override_var: str) -> str:
    return os.getenv(override_var, f"{_PREFIX}-{service}-1")


SINKHOLE = _resolve("sinkhole", "SINKHOLE_CONTAINER")
UNBOUND  = _resolve("unbound",  "UNBOUND_CONTAINER")
NGINX    = _resolve("nginx",    "NGINX_CONTAINER")
NTP      = _resolve("ntp",      "NTP_CONTAINER")
