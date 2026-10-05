from newsbot.ai.base import AIClient, AIError, Analysis, ArticleInput


def build_ai_client(settings) -> AIClient:
    if settings.ai_provider == "fake":
        from newsbot.ai.fake import FakeAIClient

        return FakeAIClient()
    if settings.ai_provider == "anthropic":
        from newsbot.ai.anthropic_client import AnthropicAIClient

        return AnthropicAIClient(settings)
    raise ValueError(f"unknown AI_PROVIDER: {settings.ai_provider}")


__all__ = ["AIClient", "AIError", "Analysis", "ArticleInput", "build_ai_client"]
