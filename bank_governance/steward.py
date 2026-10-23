from bank_governance.contracts import (Evidence,AgentReply,AnswerDraft,EvidenceSelection,GroundedStatement,GroundedExplanation,SearchInput)
from bank_governance.prompts import (SELECTION_PROMPT,GROUNDED_GENERATION_PROMPT,PLANNER_PROMPT,SYNTHESIS_PROMPT,INSUFFICIENT,UNAVAILABLE)
from bank_governance.config import DEFAULT_DATA_MODEL,load_config
from bank_governance.errors import AgentError
from bank_governance.policy import unavailable_request
from bank_governance.validation import valid_calendar_statement
from bank_governance.tools import create_catalog_tool
from bank_governance.providers import create_model,ObservedModel
from bank_governance.context import TurnContext
from bank_governance.hybrid import PROMPT as HYBRID_PROMPT,ground_atomic
from bank_governance.contracts import AtomicExplanation
from bank_governance.security import anonymous_access, AuthorizationDenied
from bank_governance.secured_retrieval import SecuredRetriever

"""Agente Data Steward local: tool calling nativo y evidencia del corpus existente."""

from collections import deque
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
import json
import re

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langsmith import tracing_context
from ollama import Client, ResponseError
import psycopg
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from scripts.knowledge_corpus import RetrievalSession, model_digest


def _service_call(phase, operation):
    try:
        # Incluso si el shell tiene tracing remoto habilitado, esta etapa es local.
        with tracing_context(enabled=False):
            return operation()
    except AgentError:
        raise
    except (psycopg.Error, SQLAlchemyError):
        raise AgentError("PostgreSQL no está disponible o falló la consulta documental. Revisa Docker y .env.") from None
    except (httpx.HTTPError, ResponseError, ConnectionError):
        raise AgentError("Ollama no está disponible, el modelo falta o la llamada agotó el tiempo de espera. Revisa ollama list y el servicio local.") from None
    except (OutputParserException, ValidationError):
        raise AgentError("El modelo no devolvió una respuesta estructurada válida; no se publicaron afirmaciones sin validar.") from None
    except ValueError:
        if phase == "availability":
            raise AgentError("El modelo generativo configurado no está instalado en Ollama. Revisa OLLAMA_CHAT_MODEL y ollama list; no se cambiará automáticamente.") from None
        if phase == "retrieval":
            raise AgentError("El corpus o la configuración de recuperación no están listos o son incompatibles. Verifica knowledge_corpus; no se recreará automáticamente.") from None
        raise AgentError("La respuesta del modelo no es válida para este agente; revisa el modelo local y su compatibilidad.") from None


def reference(evidence):
    return {key: value for key, value in asdict(evidence).items() if key != "content"}


class DataStewardAgent:
    """Un modelo, una herramienta y dos fases acotadas; sin grafo ni ReAct textual."""

    def __init__(self, model, retriever, *, history_turns=4, debug=None, data_model='legacy_metadata',
                 response_mode='extractive', conceptual_context=None, security=None):
        if data_model not in ('legacy_metadata','new_bank_2026'):
            raise ValueError('Modelo de datos desconocido')
        if response_mode not in ('extractive','grounded_generation_experimental','hybrid_experimental'):
            raise ValueError('Modo de respuesta desconocido')
        if response_mode!='extractive' and data_model!='new_bank_2026':
            raise ValueError('El modo experimental requiere new_bank_2026')
        if conceptual_context is not None and response_mode!='grounded_generation_experimental':
            raise ValueError('El contexto conceptual requiere el modo experimental')
        self._data_model=data_model
        self.response_mode=response_mode
        self.conceptual_context=conceptual_context
        if not 0 <= history_turns <= 8:
            raise ValueError("history_turns debe estar entre 0 y 8.")
        self.history = deque(maxlen=history_turns)
        self.debug = debug or (lambda event: None)
        self.security = security or anonymous_access()
        self.retriever = SecuredRetriever(retriever, data_model, self.security)
        self._evidence = {}
        self.context=TurnContext(data_model,getattr(retriever,'corpus_id',None))

        self.tool = create_catalog_tool(self, _service_call)
        # Ollama ignora tool_choice; no se depende de ese parametro para forzar evidencia.
        self.planner = model.bind_tools([self.tool])
        schema=(AtomicExplanation if response_mode=='hybrid_experimental' else
                GroundedExplanation if response_mode=='grounded_generation_experimental' else
                EvidenceSelection if data_model=='new_bank_2026' else AnswerDraft)
        self.synthesizer = model.with_structured_output(schema, method="json_schema")

    def ask(self, question):
        question = question.strip()
        if not question or len(question) > 2000:
            raise AgentError("Escribe una pregunta de entre 1 y 2,000 caracteres.")
        self._evidence = {}
        self.security.begin_request()
        try:
            self.security.run('catalog.'+self.data_model, 'read', tool='agent_entry')
        except AuthorizationDenied as error:
            self.history.clear()
            self.context = TurnContext(self.data_model)
            return AgentReply('access_denied', str(error), diagnostic=error.decision.policy_id)
        self.context.begin(question)
        if unavailable_request(question):
            reply = AgentReply("capability_unavailable", UNAVAILABLE)
            self._remember(question, reply)
            return reply
        history = [message for turn in self.history for message in turn]
        messages = [SystemMessage(content=PLANNER_PROMPT), *history, HumanMessage(content=question)]
        planned = _service_call("model", lambda: self.planner.invoke(messages))
        if planned.invalid_tool_calls:
            raise AgentError("El modelo emitió llamadas de herramienta inválidas; no se ejecutaron.")
        if not planned.tool_calls:
            # Un unico reintento nativo. No se interpreta texto como una llamada.
            messages.extend([planned, SystemMessage(content="Aun no hay evidencia de este turno. Llama ahora search_data_catalog; no respondas de memoria.")])
            planned = _service_call("model", lambda: self.planner.invoke(messages))
        if planned.invalid_tool_calls:
            raise AgentError("El modelo emitió llamadas de herramienta inválidas; no se ejecutaron.")
        if not planned.tool_calls:
            reply = AgentReply("insufficient_evidence", INSUFFICIENT, diagnostic="model_did_not_call_tool")
            self._remember(question, reply)
            return reply
        if len(planned.tool_calls) > 2 or any(call["name"] != self.tool.name for call in planned.tool_calls):
            raise AgentError("El modelo solicitó herramientas no disponibles o demasiadas llamadas; no se ejecutaron.")
        tool_results = []
        for call in planned.tool_calls:
            message = _service_call("model", lambda call=call: self.tool.invoke(call))
            tool_results.append(message)
        if not self._evidence:
            reply = AgentReply("insufficient_evidence", INSUFFICIENT, tool_calls=len(planned.tool_calls))
        else:
            synthesis_messages=[
                SystemMessage(content=SYNTHESIS_PROMPT), *history, HumanMessage(content=question),
                planned, *tool_results]
            if self.data_model=='new_bank_2026':
                synthesis_messages=[SystemMessage(content=GROUNDED_GENERATION_PROMPT if
                    self.response_mode=='grounded_generation_experimental' else SELECTION_PROMPT),
                    *history,HumanMessage(content=
                    json.dumps({'untrusted_evidence':[{'evidence_id':e.evidence_id,'content':e.content}
                        for e in self._evidence.values()],
                        **({'experimental_conceptual_context':self.conceptual_context} if self.conceptual_context else {})},
                        ensure_ascii=False)+'\nPregunta actual: '+question)]
                if self.response_mode=='hybrid_experimental':
                    synthesis_messages[0]=SystemMessage(content=HYBRID_PROMPT)
            try:
                draft = _service_call("model", lambda: self.synthesizer.invoke(synthesis_messages))
            except AgentError as error:
                if self.data_model!='new_bank_2026' or 'estructurada' not in str(error):
                    raise
                reply=AgentReply('insufficient_evidence',INSUFFICIENT,tool_calls=len(planned.tool_calls),diagnostic='invalid_selection')
            else:
                if self.response_mode=='hybrid_experimental':
                    reply=_service_call('model',lambda:ground_atomic(self,question,draft,len(planned.tool_calls)))
                elif self.response_mode=='grounded_generation_experimental':
                    reply=_service_call('model',lambda:self._ground_explanation(question,draft,len(planned.tool_calls)))
                else:
                    reply = _service_call("model", lambda: self._ground(question, draft, len(planned.tool_calls)))
        self.debug({"event": "answer_references", "retrieved_count": len(self._evidence),
                    "used_count": len(reply.references),
                    "document_ids": [ref["document_id"] for ref in reply.references]})
        self._remember(question, reply)
        return reply

    def _ground(self, question, draft, calls):
        draft = (EvidenceSelection if self.data_model=='new_bank_2026' else AnswerDraft).model_validate(draft)
        evidence = list(self._evidence.values())
        by_label = {e.evidence_id: e for e in evidence}
        labels = list(dict.fromkeys(draft.evidence_ids))
        if any(label not in by_label for label in labels):
            raise AgentError("El modelo citó evidencia inexistente; la respuesta se descartó.")
        selected = [by_label[label] for label in labels]
        if self.data_model=='new_bank_2026':
            return self._ground_new(question,draft,calls,evidence,selected)
        insufficient = draft.status == "insufficient_evidence" or not selected or not draft.answer.strip()
        # No se permite fundamentar un campo solicitado con un fragmento de otro campo.
        requested = re.findall(r"\b(CUSTOMER|TRANSACTION|LOAN)\.([a-z_]+)\b", question, re.IGNORECASE)
        if requested and any(not any(self._supports_field(e, table.upper(), name.lower()) for e in selected)
                             for table, name in requested):
            insufficient = True
        claimed = re.findall(r"\b(CUSTOMER|TRANSACTION|LOAN)\.([a-z_]+)\b", draft.answer, re.IGNORECASE)
        if any(not any(self._supports_field(e, table.upper(), name.lower()) for e in selected)
               for table, name in claimed):
            insufficient = True
        if draft.status == "explicit_absence" and not any(e.kind == "explicit_absence" for e in selected):
            insufficient = True
        # El texto visible no puede introducir referencias libres ni codigo SQL.
        if re.search(r"https?://|```|\b(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE|DROP)\b", draft.answer, re.IGNORECASE):
            insufficient = True
        if insufficient:
            return AgentReply("insufficient_evidence", INSUFFICIENT,
                              evidence=[asdict(e) for e in evidence], tool_calls=calls)
        return AgentReply(draft.status, draft.answer.strip(), [reference(e) for e in selected],
                          [asdict(e) for e in evidence], calls)

    @staticmethod
    def _supports_field(evidence, table, name):
        if evidence.table == table and evidence.field == name:
            return True
        payload = json.loads(evidence.content)
        target = payload.get("foreign_key") or payload.get("definition", {}).get("foreign_key")
        return target == f"{table}.{name}"

    @property
    def data_model(self):
        return self._data_model

    def _ground_new(self,question,draft,calls,evidence,selected):
        # References and their per-claim source ranges originate in validated
        # document metadata, never in generated answer text.
        text='\n'.join(e.content for e in selected)
        qualified=lambda s:re.findall(r'\b(?:dim|cfg)\.[a-z_]+(?:\.[a-z_]+)?\b',s.lower())
        unsupported=any(name not in text.lower() for name in qualified(question))
        if not selected or unsupported:
            return AgentReply('insufficient_evidence',INSUFFICIENT,evidence=[asdict(e) for e in evidence],tool_calls=calls)
        # Generic extractive rendering: claims are never supplied by the LLM.
        # Scope and claim text were compared to the immutable catalog at retrieval.
        claims={claim['id']:claim for e in selected for claim in e.claims}
        if not claims:
            return AgentReply('insufficient_evidence',INSUFFICIENT,tool_calls=calls)
        answer='\n'.join('['+c['classification']+'] '+c['text'] for c in claims.values())
        status='explicit_absence' if all('/absence.' in e.json_pointer for e in selected) else 'grounded'
        return AgentReply(status,answer,[reference(e) for e in selected],
                          [asdict(e) for e in evidence],calls)

    def _ground_explanation(self,question,draft,calls):
        """Validate labels and objective literals; semantic fidelity still needs review."""
        draft=GroundedExplanation.model_validate(draft)
        evidence=list(self._evidence.values())
        by_label={e.evidence_id:e for e in evidence}
        if draft.status=='insufficient_evidence':
            return AgentReply('insufficient_evidence',INSUFFICIENT,
                              evidence=[asdict(e) for e in evidence],tool_calls=calls)
        if not draft.statements:
            return AgentReply('insufficient_evidence',INSUFFICIENT,
                              evidence=[asdict(e) for e in evidence],tool_calls=calls)
        used=[]; lines=[]; rejected=0
        qualified=lambda s:set(re.findall(r'\b(?:dim|cfg)\.[a-z_]+(?:\.[a-z_]+)?\b',s.lower()))
        requested=qualified(question)
        for statement in draft.statements:
            # The model may repeat labels in prose, but only code may render
            # citations. Remove a redundant parenthetical list; reject any
            # other free label or source string.
            claim_text=re.sub(r'\s*\(E\d+(?:\s*,\s*E\d+)*\)', '',statement.text,flags=re.I)
            labels=list(dict.fromkeys(statement.evidence_ids))
            if any(label not in by_label for label in labels):
                raise AgentError('El modelo citó evidencia inexistente; la respuesta se descartó.')
            refs=[by_label[label] for label in labels]
            support='\n'.join(e.content for e in refs).lower()
            if (not valid_calendar_statement(claim_text) or
                any(name not in support for name in qualified(claim_text)) or
                re.search(r'https?://|```|\b(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE|DROP)\b|\bE\d+\b|\[\d+\]|data/source/|sha-256',claim_text,re.I)):
                rejected+=1
                continue
            # Numeric values must be in cited material. A percentage can be
            # expressed as its decimal multiplier (5% = 0.05), not as a new rate.
            source_numbers={Decimal(x.replace(',','.')) for x in
                re.findall(r'\b\d+(?:[.,]\d+)?\b',support)}
            unsupported=[]
            for match in re.finditer(r'\b(\d+(?:[.,]\d+)?)\b',claim_text):
                number=Decimal(match.group(1).replace(',','.'))
                is_percent=bool(re.match(r'\s*%',claim_text[match.end():]))
                if number not in source_numbers and not (is_percent and number/100 in source_numbers):
                    unsupported.append(number)
            if unsupported:
                rejected+=1
                continue
            for e in refs:
                if e.evidence_id not in used: used.append(e.evidence_id)
            lines.append(claim_text.strip()+' '+''.join('['+label+']' for label in labels))
        if not lines:
            return AgentReply('insufficient_evidence',INSUFFICIENT,
                              evidence=[asdict(e) for e in evidence],tool_calls=calls,
                              diagnostic='all_statements_rejected')
        selected=[by_label[label] for label in used]
        if any(name not in '\n'.join(e.content for e in selected).lower() for name in requested):
            return AgentReply('insufficient_evidence',INSUFFICIENT,
                              evidence=[asdict(e) for e in evidence],tool_calls=calls,
                              diagnostic='unsupported_requested_field')
        if draft.status=='explicit_absence' and not any('/absence.' in e.json_pointer for e in selected):
            return AgentReply('insufficient_evidence',INSUFFICIENT,
                              evidence=[asdict(e) for e in evidence],tool_calls=calls,
                              diagnostic='absence_without_source')
        return AgentReply(draft.status,'\n'.join(lines),[reference(e) for e in selected],
                          [asdict(e) for e in evidence],calls,
                          diagnostic=f'filtered_unsupported_statements:{rejected}' if rejected else None)

    def _remember(self, question, reply):
        self.context.accept(reply)
        # Pares completos, sin persistencia ni mensajes tool huérfanos al recortar.
        if self.data_model=='new_bank_2026':
            topics=', '.join(ref['json_pointer'] for ref in reply.references)
            self.history.append((HumanMessage(content=question),AIMessage(content=
                'Temas del turno anterior en '+self.data_model+': '+topics+
                '. Recupera nuevamente las fichas para responder cualquier seguimiento.')))
            return
        context = reply.answer + "\nReferencias del turno: " + ", ".join(
            f"{ref['table']}.{ref['field']} ({ref['kind']})" for ref in reply.references)
        self.history.append((HumanMessage(content=question), AIMessage(content=context)))


def chat_config():
    try:
        config=load_config()
    except ValueError:
        raise AgentError('Configuracion generativa invalida; revisa proveedor, modelo y limites.') from None
    return config.model,config.timeout


@contextmanager
def agent_session(*, debug=None, data_model=None, response_mode='extractive', conceptual_context=None,
                  retrieval_mode='semantic', llm_config=None, security=None):
    data_model=data_model or DEFAULT_DATA_MODEL
    security=security or anonymous_access()
    security.run('catalog.'+data_model, 'read', tool='agent_entry')
    try:
        config=llm_config or load_config()
    except ValueError:
        raise AgentError('Configuracion generativa invalida; revisa proveedor, modelo y limites.') from None
    if retrieval_mode not in ('semantic','hybrid'):
        raise AgentError('Modo de recuperacion desconocido.')
    if retrieval_mode=='hybrid' and data_model!='new_bank_2026':
        raise AgentError('La recuperacion hibrida requiere new_bank_2026.')
    handle=_service_call('availability',lambda:create_model(config,client_cls=Client,
        digest_fn=model_digest,ollama_cls=ChatOllama))
    model=ObservedModel(handle,debug or (lambda event:None))
    if data_model=='legacy_metadata':
        retrieval=RetrievalSession()
    else:
        from bank_governance.retrieval import catalog_session
        retrieval=catalog_session(data_model, security=security)
    session=_service_call('retrieval',retrieval.__enter__)
    try:
        if retrieval_mode=='hybrid':
            from bank_governance.retrieval import HybridRetriever
            session=HybridRetriever(session, security=security)
        agent=DataStewardAgent(model,session,debug=debug,data_model=data_model,
            response_mode=response_mode,conceptual_context=conceptual_context,security=security)
        if retrieval_mode=='hybrid':session.context=agent.context
        agent.model_identity=handle.identity
        yield agent
    finally:
        _service_call('retrieval',lambda:retrieval.__exit__(None,None,None))


def main(argv=None):
    from bank_governance.cli import main as cli_main
    return cli_main(argv,session_factory=agent_session)

from bank_governance.cli import print_reply
