"""Generative configuration is independent of embedding and corpus identity."""
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field
import os

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_MODEL = 'legacy_metadata'


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    provider: Literal['ollama', 'gemini'] = 'ollama'
    model: str = Field(default='llama3.1:latest', min_length=1)
    base_url: str = 'http://127.0.0.1:11434'
    temperature: float = Field(default=0, ge=0, le=2)
    seed: int = 42
    context: int = Field(default=8192, ge=1024, le=131072)
    output_tokens: int = Field(default=384, ge=64, le=8192)
    timeout: int = Field(default=180, ge=5, le=600)
    allow_cloud: bool = False
    tools: bool = True
    structured_output: bool = True


def load_config(environ=None):
    env = {**dotenv_values(ROOT / '.env', interpolate=False),
           **(os.environ if environ is None else environ)}
    provider = env.get('BANK_LLM_PROVIDER', 'ollama')
    if provider == 'gemini' and not env.get('BANK_LLM_MODEL'):
        raise ValueError('BANK_LLM_MODEL es obligatorio para Gemini')
    return LLMConfig(provider=provider,
        model=env.get('BANK_LLM_MODEL') or env.get('OLLAMA_CHAT_MODEL', 'llama3.1:latest'),
        base_url=env.get('BANK_LLM_BASE_URL') or env.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'),
        timeout=env.get('BANK_LLM_TIMEOUT') or env.get('OLLAMA_CHAT_TIMEOUT', '180'),
        context=env.get('BANK_LLM_CONTEXT', '8192'),
        output_tokens=env.get('BANK_LLM_OUTPUT_TOKENS', '384'),
        temperature=env.get('BANK_LLM_TEMPERATURE', '0'),
        allow_cloud=env.get('BANK_ALLOW_CLOUD', 'false'),
        tools=env.get('BANK_LLM_TOOLS', 'true'),
        structured_output=env.get('BANK_LLM_STRUCTURED_OUTPUT', 'true'))
