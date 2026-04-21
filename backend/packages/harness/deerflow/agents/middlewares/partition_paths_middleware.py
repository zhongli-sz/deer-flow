"""Per-run filesystem partition from LangGraph configurable ``im_partition_key``."""

from __future__ import annotations

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.config import path_context
from deerflow.config.im_partition import im_user_root
from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


class PartitionPathsMiddlewareState(AgentState):
    """State schema placeholder (no extra keys)."""

    pass


class PartitionPathsMiddleware(AgentMiddleware[PartitionPathsMiddlewareState]):
    """Point ``get_paths()`` at ``im_users/<key>/`` when ``im_partition_key`` is set on the run."""

    state_schema = PartitionPathsMiddlewareState

    @override
    def before_agent(self, state: PartitionPathsMiddlewareState, runtime: Runtime) -> dict | None:
        cfg = get_config() or {}
        key = cfg.get("configurable", {}).get("im_partition_key")
        if not key:
            return None

        global_base = get_paths().base_dir
        part = Paths(base_dir=im_user_root(global_base, key))
        token = path_context.set_partition_paths(part)
        path_context.partition_paths_reset_token_ctx.set(token)
        logger.debug("Partitioned agent paths under %s", part.base_dir)
        return None

    @override
    def after_agent(self, state: PartitionPathsMiddlewareState, runtime: Runtime) -> dict | None:
        token = path_context.partition_paths_reset_token_ctx.get()
        if token is not None:
            path_context.reset_partition_paths(token)
            path_context.partition_paths_reset_token_ctx.set(None)
        return None
