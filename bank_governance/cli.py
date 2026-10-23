"""Terminal presentation and argument parsing only."""
import argparse
import json
import sys
from bank_governance.config import DEFAULT_DATA_MODEL
from bank_governance.errors import AgentError

def print_reply(reply):
    if reply.status == "explicit_absence":
        print("Ausencia explícitamente documentada en el catálogo sintético:")
    print(reply.answer)
    if reply.diagnostic == "model_did_not_call_tool":
        print("El modelo no invocó la herramienta tras el reintento. Puedes probar knowledge_corpus search mientras revisas su tool calling.")
    if reply.references:
        print("\nReferencias del corpus:")
        for index, ref in enumerate(reply.references, 1):
            similarity = "" if ref["similarity"] is None else f" · similitud={ref['similarity']:.3f}"
            print(f"[{index}] {ref['source']}#{ref['json_pointer']} · v{ref['source_version']} · doc={ref['document_id']}{similarity}")
            if ref.get('claims'):
                print(f"    modelo={ref['model_id']} · corpus={ref['corpus_id']}")
                for claim in ref['claims']:
                    for origin in claim['source_refs']:
                        print(f"    {claim['classification']}: {origin['path']}:{origin['line_start']}-{origin['line_end']} · SHA-256={origin['sha256']}")

def main(argv=None, *, session_factory=None):
    if session_factory is None:
        from bank_governance.steward import agent_session
        session_factory=agent_session
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    chat = commands.add_parser("chat", help="Conversacion en memoria; escribe salir para terminar.")
    ask = commands.add_parser("ask", help="Una pregunta, sin historial previo.")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="Salida estructurada para pruebas y revision de evidencia.")
    for child in (chat, ask):
        child.add_argument('--data-model',choices=('new_bank_2026','legacy_metadata'),default=DEFAULT_DATA_MODEL)
        child.add_argument('--response-mode',choices=('extractive','grounded_generation_experimental','hybrid_experimental'),
                           default='extractive')
        child.add_argument('--retrieval-mode',choices=('semantic','hybrid'),default='semantic')
        child.add_argument('--coordinator',action='store_true',help='Grafo mínimo; solo Steward implementado.')
        child.add_argument('--capability',choices=('catalog','analytics','quality','governance'),default='catalog')
        child.add_argument('--simulated-user', choices=('steward_demo','analyst_demo','support_demo'),
                           help='Identidad sintética explícita; no autentica usuarios reales.')
        child.add_argument('--conceptual-context-experiment',action='store_true')
        child.add_argument("--debug", action="store_true", help="Eventos breves por stderr, sin preguntas ni secretos.")
    args = parser.parse_args(argv)

    def debug(event):
        print(json.dumps(event, ensure_ascii=False), file=sys.stderr)

    try:
        context=None
        if args.response_mode!='extractive' and args.data_model!='new_bank_2026':
            raise AgentError('El modo experimental requiere el catálogo new_bank_2026.')
        if args.conceptual_context_experiment:
            if args.response_mode!='grounded_generation_experimental' or args.data_model!='new_bank_2026':
                raise AgentError('El contexto conceptual requiere el modelo nuevo y el modo experimental.')
            from scripts.steward_reasoning_context import build_context
            context=build_context()
        from bank_governance.security import simulated_access, anonymous_access
        security=simulated_access(args.simulated_user) if args.simulated_user else anonymous_access()
        with session_factory(debug=debug if args.debug else None,data_model=args.data_model,
                           response_mode=args.response_mode,conceptual_context=context,
                           retrieval_mode=args.retrieval_mode,security=security) as agent:
            graph=None
            if args.coordinator:
                from bank_governance.coordinator import build_graph
                graph=build_graph(agent)
            def respond(question):
                if graph is None:
                    if args.capability!='catalog':
                        raise AgentError('Las capacidades analytics y quality requieren coordinación y no están implementadas.')
                    return agent.ask(question)
                from bank_governance.contracts import AgentReply,SpecialistRequest
                data=graph.invoke({'request':SpecialistRequest(question=question,
                    model_id=args.data_model,capability=args.capability).model_dump()})['result']
                return AgentReply(**{k:v for k,v in data.items() if k in AgentReply.__dataclass_fields__})
            if args.command == "ask":
                reply = respond(args.question)
                if args.json:
                    print(json.dumps(reply.to_dict(), ensure_ascii=False, indent=2))
                else:
                    print_reply(reply)
            else:
                print("Data Steward educativo. Solo catálogo sintético. Escribe salir para terminar.")
                while True:
                    try:
                        question = input("Tú: ")
                    except EOFError:
                        break
                    if question.strip().casefold() == "salir":
                        break
                    if not question.strip():
                        continue
                    try:
                        print_reply(respond(question))
                    except AgentError as error:
                        print(f"Error: {error}", file=sys.stderr)
        return 0
    except AgentError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
