"""Explicit LangChain provider factory; no remote fallback or remote probes."""
from dataclasses import dataclass
import os
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler
from langchain_ollama import ChatOllama
from ollama import Client

from bank_governance.config import LLMConfig
from bank_governance.errors import ProviderError


@dataclass(frozen=True)
class ModelHandle:
    model: object
    identity: dict
    config: LLMConfig


def create_model(config, *, client_cls=Client, digest_fn=None, ollama_cls=ChatOllama,
                 remote_cls=None, environ=None):
    if not config.tools or not config.structured_output:
        raise ProviderError('El Steward requiere tool calling y salida estructurada declarados.')
    if config.provider == 'ollama':
        from scripts.knowledge_corpus import model_digest
        client = client_cls(host=config.base_url, timeout=config.timeout)
        try:
            digest = (digest_fn or model_digest)(client, config.model)
        except ValueError:
            raise ProviderError('El modelo generativo no está instalado; no se cambiará automáticamente.') from None
        info = client.show(config.model)
        if 'tools' not in (info.capabilities or []):
            raise ProviderError('El modelo no declara soporte de tool calling; no hay fallback.')
        model = ollama_cls(model=config.model, base_url=config.base_url,
            temperature=config.temperature, seed=config.seed, num_ctx=config.context,
            num_predict=config.output_tokens, client_kwargs={'timeout':config.timeout})
        return ModelHandle(model, {'provider':'ollama','name':config.model,'digest':digest}, config)
    if not config.allow_cloud:
        raise ProviderError('Cloud requiere BANK_ALLOW_CLOUD=true y selección explícita del proveedor.')
    env = os.environ if environ is None else environ
    api_key = env.get('GOOGLE_API_KEY') or env.get('GEMINI_API_KEY')
    if not api_key:
        raise ProviderError('Falta la credencial de Gemini en el entorno.')
    if remote_cls is None:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            remote_cls = ChatGoogleGenerativeAI
        except ImportError:
            raise ProviderError('Instala la dependencia opcional cloud para Gemini.') from None
    # No constructor probe/invoke. Explicit Developer API, never Vertex auto-detection.
    try:
        model = remote_cls(model=config.model, api_key=api_key, vertexai=False,
            temperature=config.temperature, timeout=config.timeout,
            max_output_tokens=config.output_tokens, max_retries=0)
    except Exception:
        raise ProviderError('No se pudo configurar Gemini; revisa dependencia y parámetros.') from None
    return ModelHandle(model, {'provider':'gemini','name':config.model,'digest':None,
        'identity_note':'remote model name; immutable revision not supplied by API'}, config)


class Usage(BaseCallbackHandler):
    def __init__(self):
        self.input_tokens = self.output_tokens = None
        self.length_stop = False

    def on_llm_end(self, response, **_kwargs):
        for batch in response.generations:
            for generation in batch:
                message = getattr(generation, 'message', None)
                usage = getattr(message, 'usage_metadata', None) or {}
                meta = getattr(message, 'response_metadata', None) or {}
                self.input_tokens = usage.get('input_tokens', meta.get('prompt_eval_count'))
                self.output_tokens = usage.get('output_tokens', meta.get('eval_count'))
                self.length_stop = meta.get('done_reason', meta.get('finish_reason')) in ('length','MAX_TOKENS')


class ObservedRunnable:
    def __init__(self, runnable, handle, emit, phase):
        self.runnable, self.handle, self.emit, self.phase = runnable, handle, emit, phase

    def invoke(self, messages):
        usage = Usage(); start = perf_counter()
        try:
            return self.runnable.invoke(messages, config={'callbacks':[usage]})
        except ProviderError:
            raise
        except Exception:
            # Structured parsing exceptions must retain their category for abstention.
            from langchain_core.exceptions import OutputParserException
            from pydantic import ValidationError
            import sys
            if isinstance(sys.exc_info()[1], (OutputParserException, ValidationError)):
                raise
            raise ProviderError('Fallo del proveedor generativo o de sus capacidades; no hay fallback.') from None
        finally:
            self.emit({'event':'model_call','phase':self.phase,
                'provider':self.handle.identity['provider'], 'model':self.handle.identity['name'],
                'configured_context':self.handle.config.context,
                'input_chars':sum(len(str(m.content)) for m in messages),
                'input_tokens':usage.input_tokens,'output_tokens':usage.output_tokens,
                'possible_truncation':usage.length_stop or (
                    usage.input_tokens is not None and usage.input_tokens >= self.handle.config.context),
                'duration_seconds':round(perf_counter()-start,3)})


class ObservedModel:
    def __init__(self, handle, emit):
        self.handle, self.emit = handle, emit

    def bind_tools(self, tools):
        try:
            return ObservedRunnable(self.handle.model.bind_tools(tools),self.handle,self.emit,'planner')
        except Exception:
            raise ProviderError('El proveedor no admite las herramientas requeridas.') from None

    def with_structured_output(self, schema, **kwargs):
        try:
            return ObservedRunnable(self.handle.model.with_structured_output(schema,**kwargs),
                                    self.handle,self.emit,'synthesis')
        except Exception:
            raise ProviderError('El proveedor no admite el contrato de salida estructurada.') from None
