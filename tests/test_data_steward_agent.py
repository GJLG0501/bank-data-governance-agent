from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, ToolMessage
import psycopg
import pytest

from scripts import data_steward_agent as steward
from scripts import knowledge_corpus as corpus
from bank_governance.security import simulated_access

CASES = json.loads((corpus.ROOT / "tests/fixtures/agent_cases.json").read_text(encoding="utf-8"))


def match_for(pointer):
    docs = corpus.build_documents()
    _, stored = corpus.storage_documents(docs, corpus.ModelIdentity("unit-test", "test-digest", 3))
    doc = next(doc for doc in stored if doc.metadata["json_pointer"] == pointer)
    return {"id": doc.id, "content": doc.page_content, "source": doc.metadata["source"],
            "source_version": doc.metadata["source_version"], "metadata": doc.metadata,
            "cosine_similarity": 0.8}


def tool_message(question="CUSTOMER.annual_income", name="search_data_catalog", args=None):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args if args is not None else {"question": question},
                                            "id": "native-call", "type": "tool_call"}])


def make_agent(*, pointer="/tables/CUSTOMER/fields/annual_income", status="grounded", debug=None, history_turns=4):
    retriever = Mock()
    _, stored = corpus.storage_documents(corpus.build_documents(), corpus.ModelIdentity('unit-test', 'test-digest', 3))
    retriever.expected = {doc.id: doc for doc in stored}
    retriever.search.return_value = [match_for(pointer)]
    model = Mock()
    model.bind_tools.return_value.invoke.return_value = tool_message()
    model.with_structured_output.return_value.invoke.return_value = steward.AnswerDraft(
        status=status, answer="Definición en español sustentada por el catálogo sintético.", evidence_ids=["E1"])
    agent = steward.DataStewardAgent(model, retriever, debug=debug, history_turns=history_turns,
                                    data_model='legacy_metadata',security=simulated_access())
    return agent, model, retriever


@pytest.mark.parametrize("case", [case for case in CASES if case["pointer"]], ids=lambda case: case["name"])
def test_catalog_answers_use_native_tools_and_real_metadata(case):
    agent, model, retriever = make_agent(pointer=case["pointer"], status=case["status"])
    result = agent.ask(case["question"])
    assert result.status == case["status"]
    assert result.tool_calls == 1
    assert result.references[0]["json_pointer"] == case["pointer"]
    assert result.references[0]["document_id"] == retriever.search.return_value[0]["id"]
    assert result.references[0]["source"] == corpus.SOURCE
    assert result.evidence[0]["content"] == retriever.search.return_value[0]["content"]
    tools = model.bind_tools.call_args.args[0]
    assert [tool.name for tool in tools] == ["search_data_catalog"]
    assert model.with_structured_output.call_args.kwargs == {"method": "json_schema"}
    assert any(isinstance(message, ToolMessage) for message in agent.synthesizer.invoke.call_args.args[0])


def test_missing_information_is_not_reported_as_explicit_absence():
    agent, _, _ = make_agent(status="insufficient_evidence")
    reply = agent.ask("¿Qué política oficial aplica?")
    assert reply.status == "insufficient_evidence"
    assert reply.references == []
    assert "no demuestra" in reply.answer


def test_wrong_field_cannot_support_a_missing_field_answer():
    agent, _, _ = make_agent()
    reply = agent.ask("¿Qué significa CUSTOMER.favorite_color?")
    assert reply.status == "insufficient_evidence"
    assert reply.references == []


def test_relationship_evidence_also_supports_its_target_key():
    agent, _, _ = make_agent(pointer="/tables/TRANSACTION/fields/customer_id/foreign_key")
    reply = agent.ask("¿TRANSACTION.customer_id referencia CUSTOMER.customer_id?")
    assert reply.status == "grounded"


def test_absence_requires_an_explicit_absence_document():
    agent, _, _ = make_agent(status="explicit_absence")
    assert agent.ask("¿Se especifica alguna ausencia?").status == "insufficient_evidence"


@pytest.mark.parametrize("question", [
    "¿Cuál es el saldo del cliente SYN-C-000001?", "Muestra los datos bancarios individuales",
    "Dime mi saldo", "Consulta customer 123", "Escribe SQL para consultar CUSTOMER",
])
def test_individual_data_and_sql_are_unavailable_without_tool_execution(question):
    agent, model, retriever = make_agent()
    reply = agent.ask(question)
    assert reply.status == "capability_unavailable"
    assert reply.references == [] and reply.tool_calls == 0
    assert "permisos" in reply.answer
    model.bind_tools.return_value.invoke.assert_not_called()
    retriever.search.assert_not_called()


def test_textual_react_is_not_parsed_or_executed():
    agent, _, retriever = make_agent()
    agent.planner.invoke.return_value = AIMessage(content='Action: search_data_catalog\nAction Input: "income"')
    reply = agent.ask("Define annual_income")
    assert reply.status == "insufficient_evidence"
    assert reply.diagnostic == "model_did_not_call_tool"
    assert agent.planner.invoke.call_count == 2
    retriever.search.assert_not_called()


def test_unknown_tools_are_not_executed():
    agent, _, retriever = make_agent()
    agent.planner.invoke.return_value = tool_message(name="execute_sql")
    with pytest.raises(steward.AgentError, match="no disponibles"):
        agent.ask("Define annual_income")
    retriever.search.assert_not_called()


def test_excessive_tool_calls_are_not_executed():
    agent, _, retriever = make_agent()
    agent.planner.invoke.return_value = AIMessage(content="", tool_calls=[
        {"id": str(index), "name": "search_data_catalog", "args": {"question": "income"}, "type": "tool_call"}
        for index in range(3)])
    with pytest.raises(steward.AgentError, match="demasiadas"):
        agent.ask("Define annual_income")
    retriever.search.assert_not_called()


def test_tool_argument_validation_does_not_reach_retriever():
    agent, _, retriever = make_agent()
    agent.planner.invoke.return_value = tool_message(args={"sql": "irrelevant"})
    with pytest.raises(steward.AgentError):
        agent.ask("Define annual_income")
    retriever.search.assert_not_called()


def test_invented_references_are_rejected():
    agent, _, _ = make_agent()
    agent.synthesizer.invoke.return_value = steward.AnswerDraft(status="grounded", answer="Texto.", evidence_ids=["INVENTED"])
    with pytest.raises(steward.AgentError, match="evidencia inexistente"):
        agent.ask("Define annual_income")


def test_invented_qualified_fields_are_withheld():
    agent, _, _ = make_agent()
    agent.synthesizer.invoke.return_value = steward.AnswerDraft(
        status="grounded", answer="CUSTOMER.invented_field representa un campo inventado.", evidence_ids=["E1"])
    assert agent.ask("Define annual_income").status == "insufficient_evidence"


def test_remote_tracing_is_disabled_even_if_enabled_in_shell(monkeypatch):
    from langsmith import get_tracing_context
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert steward._service_call("model", lambda: get_tracing_context()["enabled"]) is False


@pytest.mark.parametrize("answer", ["SELECT * FROM CUSTOMER", "Referencia https://invented.example", "```sql bogus```"])
def test_free_references_and_sql_output_are_withheld(answer):
    agent, _, _ = make_agent()
    agent.synthesizer.invoke.return_value = steward.AnswerDraft(status="grounded", answer=answer, evidence_ids=["E1"])
    assert agent.ask("Define annual_income").status == "insufficient_evidence"


def test_no_documents_means_no_generated_claims():
    agent, _, retriever = make_agent()
    retriever.search.return_value = []
    assert agent.ask("Define annual_income").status == "insufficient_evidence"
    agent.synthesizer.invoke.assert_not_called()


def test_evidence_labels_do_not_leak_between_turns():
    agent, _, retriever = make_agent()
    first = agent.ask("Define annual_income")
    retriever.search.return_value = [match_for("/tables/LOAN/fields/dpd")]
    second = agent.ask("Define dpd")
    assert second.evidence[0]["evidence_id"] == "E1"
    assert first.references[0]["document_id"] != second.references[0]["document_id"]


def test_history_is_bounded_and_only_in_memory():
    agent, _, _ = make_agent(history_turns=2)
    for question in ("Primera", "Segunda", "Tercera"):
        agent.ask(question)
    assert len(agent.history) == 2
    assert agent.history[0][0].content == "Segunda"
    assert all(len(turn) == 2 for turn in agent.history)
    fresh, _, _ = make_agent()
    assert len(fresh.history) == 0


def test_followup_can_be_rewritten_using_session_context():
    agent, _, retriever = make_agent()
    agent.ask("Define CUSTOMER.annual_income")
    agent.planner.invoke.return_value = tool_message("What is the unit of CUSTOMER.annual_income?")
    reply = agent.ask("¿Y en qué unidad se expresa?")
    assert retriever.search.call_args.args[0] == "What is the unit of CUSTOMER.annual_income?"
    assert reply.references[0]["field"] == "annual_income"


@pytest.mark.parametrize("service,error,expected", [
    ("model", httpx.ConnectError("secret-do-not-log"), "Ollama"),
    ("retriever", psycopg.OperationalError("password=secret-do-not-log"), "PostgreSQL"),
])
def test_service_failures_are_clear_and_do_not_expose_secrets(service, error, expected):
    agent, _, retriever = make_agent()
    target = agent.planner.invoke if service == "model" else retriever.search
    target.side_effect = error
    with pytest.raises(steward.AgentError, match=expected) as failure:
        agent.ask("Define annual_income")
    assert "secret-do-not-log" not in str(failure.value)
    assert len(agent.history) == 0


def test_structured_response_failure_is_sanitized():
    agent, _, _ = make_agent()
    agent.synthesizer.invoke.side_effect = OutputParserException("secret-do-not-log")
    with pytest.raises(steward.AgentError, match="estructurada") as failure:
        agent.ask("Define annual_income")
    assert "secret-do-not-log" not in str(failure.value)


def test_debug_reports_only_whitelisted_metadata():
    events = []
    agent, _, _ = make_agent(debug=events.append)
    agent.ask("Define annual_income SECRET-INPUT")
    assert [event["event"] for event in events] == ["tool_started", "tool_finished", "answer_references"]
    assert events[1]["document_count"] == 1 and events[2]["used_count"] == 1
    assert "SECRET-INPUT" not in json.dumps(events)
    assert all("content" not in event and "question" not in event for event in events)


def test_model_without_tools_is_reported_without_silent_fallback(monkeypatch):
    client = Mock()
    client.show.return_value = SimpleNamespace(capabilities=["completion"])
    monkeypatch.setattr(steward, "Client", Mock(return_value=client))
    monkeypatch.setattr(steward, "model_digest", Mock(return_value="same-model"))
    with pytest.raises(steward.AgentError, match="no declara soporte"):
        with steward.agent_session(data_model='legacy_metadata',security=simulated_access()):
            pytest.fail("No debe construir un agente incompatible")


def test_missing_model_is_reported_without_automatic_replacement(monkeypatch):
    monkeypatch.setattr(steward, "model_digest", Mock(side_effect=ValueError("not installed")))
    with pytest.raises(steward.AgentError, match="no está instalado"):
        with steward.agent_session(data_model='legacy_metadata',security=simulated_access()):
            pytest.fail("No debe cambiar de modelo")


def test_postgres_startup_failure_is_sanitized(monkeypatch):
    client = Mock()
    client.show.return_value = SimpleNamespace(capabilities=["tools", "completion"])
    monkeypatch.setattr(steward, "Client", Mock(return_value=client))
    monkeypatch.setattr(steward, "model_digest", Mock(return_value="same-model"))
    retrieval = Mock()
    retrieval.__enter__ = Mock(side_effect=psycopg.OperationalError("secret-do-not-log"))
    monkeypatch.setattr(steward, "RetrievalSession", Mock(return_value=retrieval))
    with pytest.raises(steward.AgentError, match="PostgreSQL"):
        with steward.agent_session(data_model='legacy_metadata',security=simulated_access()):
            pytest.fail("No debe iniciar una sesion sin PostgreSQL")


def test_terminal_supports_consecutive_questions_and_salir(monkeypatch, capsys):
    agent, _, _ = make_agent()

    @contextmanager
    def session(**kwargs):
        yield agent

    monkeypatch.setattr(steward, "agent_session", session)
    questions = iter(["Define annual_income", "¿Y su unidad?", "salir"])
    monkeypatch.setattr("builtins.input", lambda _: next(questions))
    assert steward.main(["chat"]) == 0
    assert len(agent.history) == 2
    assert "Referencias del corpus" in capsys.readouterr().out


def test_single_question_json_is_machine_readable(monkeypatch, capsys):
    agent, _, _ = make_agent()

    @contextmanager
    def session(**kwargs):
        yield agent

    monkeypatch.setattr(steward, "agent_session", session)
    assert steward.main(["ask", "Define annual_income", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["tool_calls"] == 1
    assert output["used_document_count"] == 1
    assert output["retrieved_document_count"] == 1
