# Bank Data Governance Agent

MVP educativo de gobernanza bancaria con Python, uv, LangChain, LangGraph, PostgreSQL 17 y pgvector. Todos los datos son sintéticos.

**Data Steward es el único especialista implementado.** Consulta definiciones, relaciones y límites del catálogo mediante RAG. Data Analyst, Data Quality y Data Governance tienen contratos futuros y se declaran no disponibles. La autorización transversal es determinista y usa identidades sintéticas explícitas. Streamlit, MCP y coordinación multiagente completa siguen pendientes.

El modelo objetivo es `new_bank_2026`: 350,013 filas bancarias originales, 20,009 auxiliares, 82 documentos y 172 afirmaciones. El legado conserva CUSTOMER/TRANSACTION/LOAN (6,500 filas) y 24 documentos. Por aceptación pendiente, la CLI sigue usando `legacy_metadata` con su contrato histórico. Al seleccionar el modelo nuevo, la respuesta extractiva es el modo por defecto. Los corpus nunca se mezclan.

## Arquitectura

La CLI usa `bank_governance`: configuración → proveedor LangChain → Data Steward → herramienta documental → recuperación con corpus fijo → PostgreSQL en lectura. Contexto, contratos y validación se comparten. Un grafo LangGraph opcional enruta al Steward real y rechaza capacidades aún no implementadas, sin añadir llamadas LLM.

- [Arquitectura actual y diagrama](docs/architecture.md).
- [Auditoría, refactor y resultados](docs/architecture-consolidation-report.md).
- [Decisiones](docs/architecture-decisions.md).
- [Evaluación histórica A/B/C y limitaciones](docs/new-bank-data-steward-reasoning-evaluation.md).

## Instalación

Desde esta raíz Git, con PowerShell, uv, Docker Desktop y Ollama disponibles:

```powershell
uv sync --locked --inexact
```

`.python-version` conserva Python 3.13.5. `uv.lock` fija versiones; el paquete local instala el comando `bank-steward`. Los imports y comandos `python -m scripts.data_steward_agent` siguen siendo compatibles.

## Configuración

Si no existe configuración local:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

Edita `.env` en tu equipo; nunca lo publiques. Las variables de entorno prevalecen. PostgreSQL existente: `127.0.0.1:5434`, base `bank_governance_synthetic_dev`. Las credenciales locales ya configuradas no deben reemplazarse por los ejemplos. Embeddings: `OLLAMA_EMBEDDING_MODEL=bge-large:latest`, dimensión 1024; la selección del LLM generativo no cambia esos vectores.

Configuración generativa opcional: `BANK_LLM_PROVIDER=ollama`, `BANK_LLM_MODEL`, `BANK_LLM_CONTEXT=8192`, `BANK_LLM_OUTPUT_TOKENS=384`, `BANK_LLM_TIMEOUT`. Se mantienen `OLLAMA_CHAT_MODEL` y `OLLAMA_CHAT_TIMEOUT` como aliases compatibles. No se aumenta automáticamente el contexto ni se cambia de modelo si falla.

Gemini es un adaptador opcional probado con mocks, no una integración remota ya validada:

```powershell
uv sync --locked --inexact --extra cloud
```

Para usarlo en una fase autorizada se necesitan proveedor `gemini`, nombre de modelo explícito, `BANK_ALLOW_CLOUD=true` y `GOOGLE_API_KEY` o `GEMINI_API_KEY` exportada en el entorno. No hay fallback automático a cloud; no se efectuaron llamadas remotas durante este refactor. Claude queda pendiente.

## Servicios existentes

Comprobar estado y modelos locales:

```powershell
docker compose ps -a
ollama list
```

Si el contenedor original está detenido y sus recursos siguen siendo los mismos:

```powershell
docker compose start bank-postgres
```

No reinicialices volúmenes ni vuelvas a ejecutar SQL upstream, generación o ingestión para iniciar el agente. El servicio usa la imagen pgvector PostgreSQL 17 y el volumen persistente original. La provisión en otra máquina es un procedimiento explícito distinto; los scripts de publicación y sus guardas no se ejecutan desde la CLI de consulta. Véanse [respaldo y recuperación](docs/new-bank-model-backup-recovery.md) y [publicación RAG](docs/new-bank-model-rag-publication.md). Evita imprimir `docker compose config` resuelto: puede incluir secretos.

## Ejecutar Data Steward

La autorización usa identidades **simuladas**, seleccionadas explícitamente con `--simulated-user steward_demo`; sin selección, se deniega antes de crear el modelo. No autentica usuarios reales. El rol PostgreSQL actual es superusuario: el despliegue real queda bloqueado hasta sustituirlo y ensayar permisos mínimos. Consulta [seguridad y gobernanza](docs/security-and-governance.md).

Catálogo nuevo explícito, conservando la referencia extractiva:

```powershell
uv run --locked --inexact bank-steward ask '¿Qué representa saldo_apertura?' --data-model new_bank_2026 --json --simulated-user steward_demo
uv run --locked --inexact python -m bank_governance chat --data-model new_bank_2026 --simulated-user steward_demo
```

Escribe `salir` para terminar. El historial es local, acotado y desaparece al cerrar la sesión.

Recuperación mejorada optativa y grafo mínimo:

```powershell
uv run --locked --inexact bank-steward ask '¿Cuál es el cierre que abre mayo?' --data-model new_bank_2026 --retrieval-mode hybrid --coordinator --simulated-user steward_demo
uv run --locked --inexact bank-steward ask 'Calcula saldos' --data-model new_bank_2026 --coordinator --capability analytics --simulated-user steward_demo
```

La segunda solicitud declara `capability_unavailable`; no ejecuta SQL analítico. La recuperación híbrida combina términos del manifiesto validado y búsqueda semántica con RRF, con presupuestos acotados. No requiere DDL ni nuevos embeddings documentales.

El modo `--response-mode hybrid_experimental` permite afirmaciones atómicas y operaciones documentales comprobables. El texto inferido se etiqueta como pendiente de revisión semántica; no está aceptado para uso por defecto. `grounded_generation_experimental` y `--conceptual-context-experiment` conservan los experimentos anteriores para reproducibilidad, sin publicar otro corpus.

`--debug` muestra solo eventos seguros: proveedor/modelo, herramientas, documentos, duración, tokens cuando se reportan e indicios de truncamiento. No registra preguntas, documentos completos, claves ni razonamiento interno. La ventana configurada no garantiza el contexto efectivo del proveedor. El tracing remoto se deshabilita.

## Pruebas

Suite sin servicios:

```powershell
uv run --locked --inexact python -m pytest -q -p no:cacheprovider
```

Las pruebas reales se omiten por defecto. En equipos con bloqueo ACL de pytest, usa `--basetemp` con una carpeta nueva dentro de `.local-validation/`; no reutilices carpetas con evidencias.

Comprobación local pequeña de cinco preguntas, solo lectura:

```powershell
uv run --locked --inexact python -m pytest tests/test_architecture_live.py --run-agent-tests -q -p no:cacheprovider
```

No habilites indiscriminadamente toda la suite con `--run-db-tests` en la base activa: algunas pruebas históricas crean objetos y escriben incluso si después hacen rollback. Sus ensayos corresponden a un entorno aislado. Las pruebas cloud del adaptador usan mocks, no claves ni tráfico remoto.

## Reglas y límites

- Producto/código se interpreta por `(cve_producto, cve_txn)`.
- Enero es apertura original; desde febrero `saldo_apertura` usa el cierre calendario anterior.
- Los SQL no declaran moneda. El crecimiento sintético no es interés contractual.
- El vocabulario original `dominio` y el DDL upstream se distinguen de clasificaciones y restricciones MVP.
- El Steward tiene únicamente herramientas documentales; no consulta filas bancarias ni concede permisos.
- Citas válidas y operaciones verificadas no garantizan toda la interpretación del LLM. Las anomalías se reportan, no se reparan silenciosamente.

Los [siete borradores conceptuales](docs/drafts/new-bank-concepts/01-temporal.md) son propuestas con procedencia y ejemplos, no documentos publicados ni una versión 2 del corpus.

## Operación e historia

`sql/upstream/`, migraciones, manifiestos, documentos y embeddings publicados se preservan. `scripts/` mantiene los generadores, publicadores y arneses explícitos; no constituyen pasos de arranque del agente. `.local-validation/`, respaldos y archivos `.env` están excluidos de Git y no se limpian automáticamente.

Para entender etapas anteriores: [integración](docs/new-bank-model-integration-plan.md), [gobernanza](docs/new-bank-model-governance.md), [publicación de datos](docs/new-bank-model-publication.md), [RAG](docs/new-bank-model-rag.md), [integración del agente](docs/new-bank-data-steward-agent.md) y [endurecimiento](docs/new-bank-data-steward-hardening.md). Esos informes conservan decisiones, métricas y resultados negativos; la arquitectura vigente se describe en el documento central.
