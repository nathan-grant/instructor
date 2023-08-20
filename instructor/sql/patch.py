"""
TODO: add the created_at, id and called it completion vs response
"""

try:
    from sqlalchemy.orm import Session
except ImportError:
    import warnings

    warnings.warn("SQLAlchemy is not installed. Please install it to use this feature.")

import openai
import inspect
import json
from typing import Callable
from functools import wraps

from sa import ChatCompletionSQL, MessageSQL


def message_sql(index, message, is_response=False):
    return MessageSQL(
        index=index,
        content=message.get("content", None),
        role=message["role"],
        arguments=message.get("function_call", {}).get("arguments", None),
        name=message.get("function_call", {}).get("name", None),
        is_function_call="function_call" in message,
        is_response=is_response,
    )


# Synchronous function to insert chat completion
def sync_insert_chat_completion(
    engine,
    messages: list[dict],
    responses: list[dict] = [],
    **kwargs,
):
    with Session(engine) as session:  # type: ignore
        chat = ChatCompletionSQL(
            id=kwargs.pop("id", None),
            created_at=kwargs.pop("created", None),
            functions=json.dumps(kwargs.pop("functions", None)),
            function_call=json.dumps(kwargs.pop("function_call", None)),
            messages=[
                message_sql(index=ii, message=message)
                for (ii, message) in enumerate(messages)
            ],
            responses=[
                message_sql(index=resp["index"], message=resp.message, is_response=True)  # type: ignore
                for resp in responses
            ],
            **kwargs,
        )
        session.add(chat)
        session.commit()


def patch_with_engine(engine):
    def add_sql_alchemy(func: Callable) -> Callable:
        is_async = inspect.iscoroutinefunction(func)
        if is_async:

            @wraps(func)
            async def new_chatcompletion(*args, **kwargs):  # type: ignore
                response = await func(*args, **kwargs)
                sync_insert_chat_completion(
                    engine,
                    messages=kwargs.pop("messages", []),
                    responses=response.choices,
                    id=response["id"],
                    **response["usage"],
                    **kwargs,
                )
                return response

        else:

            @wraps(func)
            def new_chatcompletion(*args, **kwargs):
                response = func(*args, **kwargs)

                sync_insert_chat_completion(
                    engine,
                    messages=kwargs.pop("messages", []),
                    responses=response.choices,
                    id=response["id"],
                    **response["usage"],
                    **kwargs,
                )
                response._completion_id = response["id"]
                return response

        return new_chatcompletion

    return add_sql_alchemy


def instrument_with_sqlalchemy(engine):
    patcher = patch_with_engine(engine)
    original_chatcompletion = openai.ChatCompletion.create
    original_chatcompletion_async = openai.ChatCompletion.acreate
    openai.ChatCompletion.create = patcher(original_chatcompletion)
    openai.ChatCompletion.acreate = patcher(original_chatcompletion_async)