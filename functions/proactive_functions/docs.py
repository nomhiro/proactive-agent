"""Cosmos から読んだ文書を1件ずつ検証する。壊れた文書はログに残して飛ばす。

手で書き換えた文書が1件壊れていても、残りの処理（振り分け、tick）が止まらないようにする。
"""

import logging
from collections.abc import Iterable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)


def parse_each(docs: Iterable[dict], model: type[M], *, skip_seed: bool = False) -> list[tuple[dict, M]]:
    out = []
    for d in docs:
        if skip_seed and d.get("origin") == "seed":
            continue
        try:
            out.append((d, model.model_validate(d)))
        except ValidationError as e:
            log.warning("skip invalid %s doc id=%s errors=%d", model.__name__, d.get("id"), e.error_count())
    return out


def models(docs: Iterable[dict], model: type[M], *, skip_seed: bool = False) -> list[M]:
    return [m for _, m in parse_each(docs, model, skip_seed=skip_seed)]
