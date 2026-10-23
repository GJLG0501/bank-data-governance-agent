class AgentError(RuntimeError):
    """Public error; never includes credentials or provider payloads."""


class ProviderError(AgentError):
    """Provider configuration, compatibility or invocation failure."""
