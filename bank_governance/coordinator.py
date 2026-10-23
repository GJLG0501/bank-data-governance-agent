"""Minimal LangGraph routing. Only Data Steward is an implemented specialist."""
from typing import TypedDict
import re
from langgraph.graph import StateGraph,START,END
from bank_governance.contracts import SpecialistRequest,SpecialistResult
from bank_governance.errors import AgentError
from bank_governance.policy import unavailable_request
from bank_governance.context import normalize
from langsmith import tracing_context

CAPABILITIES={'data_steward':{'implemented':True,'capabilities':['catalog']},
              'data_analyst':{'implemented':False,'capabilities':['analytics']},
              'data_quality':{'implemented':False,'capabilities':['quality']},
              'data_governance':{'implemented':False,'capabilities':['governance']}}


class ConversationState(TypedDict,total=False):
    request: dict
    route: str
    result: dict


class LocalCoordinator:
    def __init__(self,compiled):
        self.compiled=compiled

    def invoke(self,state):
        with tracing_context(enabled=False):
            return self.compiled.invoke(state)

    def get_graph(self):
        return self.compiled.get_graph()


def build_graph(steward):
    def route(state):
        request=SpecialistRequest.model_validate(state['request'])
        quality_action=bool(re.search(r'\b(valida|detecta|ejecuta|comprueba)\b.{0,70}(duplicad|anomali|concili|integridad)',normalize(request.question)))
        unavailable=request.capability!='catalog' or unavailable_request(request.question) or quality_action
        return {'route':'unavailable' if unavailable else 'steward'}

    def unavailable(state):
        return {'result':SpecialistResult(specialist='coordinator',status='capability_unavailable',
            answer='La capacidad solicitada no está implementada. Solo Data Steward documental está disponible.',
            limitations=['analytics_quality_governance_not_implemented']).model_dump()}

    def ask_steward(state):
        request=SpecialistRequest.model_validate(state['request'])
        if request.model_id!=steward.data_model:
            return {'result':SpecialistResult(specialist='coordinator',status='error',
                answer='La sesión no corresponde al modelo de datos solicitado.').model_dump()}
        try:
            reply=steward.ask(request.question)
            return {'result':{**reply.to_dict(),'specialist':'data_steward'}}
        except AgentError:
            return {'result':SpecialistResult(specialist='data_steward',status='error',
                answer='Data Steward no pudo completar la consulta; no se improvisaron resultados.').model_dump()}

    graph=StateGraph(ConversationState)
    graph.add_node('route',route);graph.add_node('steward',ask_steward);graph.add_node('unavailable',unavailable)
    graph.add_edge(START,'route')
    graph.add_conditional_edges('route',lambda state:state['route'],{'steward':'steward','unavailable':'unavailable'})
    graph.add_edge('steward',END);graph.add_edge('unavailable',END)
    return LocalCoordinator(graph.compile())
