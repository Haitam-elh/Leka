"""The model gateway and router (LEKA-394): every LEKA feature that needs a
language model asks through here — never a vendor directly.

    contract.py   what a provider implements: Request in, Completion out
    google.py     Google Gemini — LEKA's default (Gemini 3.8 Flash)
    openai.py     the chat-completions shape: Mistral, OpenAI (or
                  compatible), a company's Azure OpenAI
    anthropic.py  Anthropic Claude
    profiles.py   the models LEKA knows: what each can do, what it costs
    routing.py    which model answers what a task needs, in what order
    service.py    the Gateway: tries, falls back, checks, keeps every call
    usage.py      what was asked, of which model, what it cost

docs/model-gateway.md says how, and why.
"""

from leka.capabilities.gateway.anthropic import Anthropic
from leka.capabilities.gateway.contract import (
    Completion,
    Endpoint,
    Message,
    Output,
    Provider,
    ProviderError,
    Request,
    Role,
    Structured,
    Tier,
    Tool,
    ToolCall,
    ToolChoice,
    Usage,
    plain_schema,
    provider,
    providers,
    register_provider,
)
from leka.capabilities.gateway.google import Google
from leka.capabilities.gateway.openai import AZURE_OPENAI, MISTRAL, OPENAI
from leka.capabilities.gateway.profiles import (
    DEFAULTS,
    Price,
    Profile,
    of_provider,
    profile,
    profiles,
    register_model,
)
from leka.capabilities.gateway.routing import Needs, Own, Passed, Prefer, Route, Routing, route
from leka.capabilities.gateway.service import (
    Attempt,
    Gateway,
    InvalidOutputError,
    NoModelError,
    Tested,
    default_ready,
    leka_default,
    leka_keys,
)
from leka.capabilities.gateway.usage import ModelUsage, model_usage
from leka.capabilities.gateway.workspace import ModelSettingError, ModelSettings

for _provider in (Google(), MISTRAL, OPENAI, AZURE_OPENAI, Anthropic()):
    register_provider(_provider)

__all__ = [
    "AZURE_OPENAI",
    "DEFAULTS",
    "MISTRAL",
    "OPENAI",
    "Anthropic",
    "Attempt",
    "Completion",
    "Endpoint",
    "Gateway",
    "Google",
    "InvalidOutputError",
    "Message",
    "ModelSettingError",
    "ModelSettings",
    "ModelUsage",
    "Needs",
    "NoModelError",
    "Output",
    "Own",
    "Passed",
    "Prefer",
    "Price",
    "Profile",
    "Provider",
    "ProviderError",
    "Request",
    "Role",
    "Route",
    "Routing",
    "Structured",
    "Tested",
    "Tier",
    "Tool",
    "ToolCall",
    "ToolChoice",
    "Usage",
    "default_ready",
    "leka_default",
    "leka_keys",
    "model_usage",
    "of_provider",
    "plain_schema",
    "profile",
    "profiles",
    "provider",
    "providers",
    "register_model",
    "register_provider",
    "route",
]
