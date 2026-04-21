from __future__ import annotations

from contextvars import ContextVar, Token

from .paths import Paths

partition_paths_ctx: ContextVar[Paths | None] = ContextVar("partition_paths_ctx", default=None)

# Holds the Token returned by set_partition_paths for the current context (async-safe).
partition_paths_reset_token_ctx: ContextVar[Token | None] = ContextVar(
    "partition_paths_reset_token_ctx",
    default=None,
)


def set_partition_paths(paths: Paths) -> Token:
    return partition_paths_ctx.set(paths)


def reset_partition_paths(token: Token) -> None:
    partition_paths_ctx.reset(token)
