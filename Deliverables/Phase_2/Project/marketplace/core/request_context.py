from contextvars import ContextVar


client_ip_context: ContextVar[str | None] = ContextVar(
    "client_ip",
    default=None
)


def get_client_ip() -> str | None:
    return client_ip_context.get()