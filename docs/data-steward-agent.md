# Primer agente Data Steward en terminal

El agente conversa sobre el catálogo bancario **sintético**. Usa Ollama local con
`llama3.1:latest` y la recuperación documental existente. No consulta registros
bancarios individuales, no genera ni ejecuta SQL y no incorpora interfaces web,
dashboards, herramientas de escritura ni una arquitectura multiagente.

## Compatibilidad y arquitectura

Se inspeccionaron `pyproject.toml`, `uv.lock`, la configuración, el recuperador y
las pruebas antes de implementar esta etapa. Las versiones verificadas son:

| Componente | Versión |
| --- | --- |
| Python fijado por el proyecto | 3.13.5 |
| `langchain-core` | 1.6.12 |
| `langchain-ollama` | 1.1.0 |
| `langchain-postgres` | 0.0.19 |
| Cliente Python `ollama` | 0.6.3 |

Se reutilizan los componentes actuales de LangChain; no se necesita instalar el
paquete monolítico `langchain`, LangChain Classic ni LangGraph. `uv.lock` conserva
las versiones resueltas. Pydantic y LangSmith, ya instalados transitivamente, se
declaran ahora como dependencias directas por sus esquemas y el contexto que
deshabilita el trazado remoto. **No se conecta a un servicio LangSmith** ni se
configuran claves de API o servicios de pago.

El modelo local `llama3.1:latest` declara capacidades `completion` y `tools`.
Se comprobó además una llamada nativa real a `search_data_catalog` mediante
`ChatOllama.bind_tools`. El digest observado fue:

```text
46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e
```

El agente es una orquestación pequeña con primitivas de LangChain:

1. `ChatOllama.bind_tools` recibe la pregunta y el historial limitado y selecciona
   hasta dos búsquedas documentales mediante `AIMessage.tool_calls`.
2. El ejecutor permite exclusivamente `search_data_catalog`, valida sus argumentos
   y devuelve `ToolMessage` estructurados. No interpreta texto `Action:`/`ReAct`
   como instrucciones ejecutables.
3. El mismo modelo sintetiza en español con
   `with_structured_output(AnswerDraft, method="json_schema")`.
4. El programa valida las etiquetas de evidencia y construye las referencias
   desde los metadatos recuperados, no desde enlaces o fuentes redactados por el LLM.

No se depende de `tool_choice`: la integración de Ollama instalada lo ignora.
Si el modelo no llama a la herramienta, se realiza un único reintento nativo.
Si vuelve a omitirla, no se publica su respuesta de memoria: se informa que falta
evidencia y que el modelo no invocó la herramienta. No se cambia de modelo ni de
arquitectura automáticamente. Si la instalación no declara soporte de herramientas,
se detiene con un mensaje explícito; la alternativa disponible para revisión es
el comando anterior `scripts.knowledge_corpus search`.

## Única herramienta disponible

`search_data_catalog(question: str)` reutiliza
`scripts.knowledge_corpus.RetrievalSession.search(question, k=5)`. La sesión
reutiliza el pool de recuperación entre preguntas. No hay un segundo pipeline de
embeddings, una nueva colección ni llamadas a `ingest` desde el agente.

La evidencia de cada resultado contiene:

- Contenido original del fragmento y etiqueta local `E1`, `E2`, etc.
- Identificador real del documento almacenado.
- Fuente, versión, tabla, campo, tipo documental y JSON Pointer.
- Similitud coseno, cuando el recuperador la proporciona.

Las etiquetas `E1` no son identificadores persistentes: se reinician en cada
pregunta. Las referencias visibles conservan los UUID reales de los documentos.
Cada respuesta fundamentada debe seleccionar evidencia del turno actual. Una
referencia inventada se rechaza; un campo solicitado o afirmado no puede
fundamentarse con evidencia de otro campo. Las relaciones también pueden sustentar
su clave destino explícita. No se muestran enlaces libres o bloques SQL generados
por el modelo como si fueran referencias verificadas.

El resultado estructurado distingue:

| Estado | Significado |
| --- | --- |
| `grounded` | Respuesta basada en documentos recuperados y con referencias validadas. No es una certificación automática de verdad. |
| `explicit_absence` | La evidencia incluye una ausencia explícita del catálogo; se presenta como tal. |
| `insufficient_evidence` | No se obtuvo evidencia suficiente o la respuesta no superó los controles de procedencia. No permite concluir inexistencia global. |
| `capability_unavailable` | La solicitud corresponde a una capacidad fuera de esta etapa, como registros individuales o SQL. No es una decisión de permisos. |

Para `CUSTOMER.credit_score` existe la frase original
`There is no CUSTOMER.credit_score field.`. Para `CUSTOMER.favorite_color` no hay
una definición ni una ausencia explícita equivalente: la respuesta debe reconocer
insuficiencia. El corpus tampoco define umbrales oficiales de aprobación de crédito.
La frase sobre comisiones de conversión solo indica que no se especifica si se
incluyen; no autoriza afirmar que se incluyen o excluyen.

## Preparación y ejecución

Ejecuta desde la raíz Git `bank-data-governance-agent`. PostgreSQL, Ollama y el
corpus de 24 documentos deben estar disponibles. Esta etapa no reinicializa datos
ni reingiere el corpus automáticamente.

```powershell
uv sync --locked --inexact
docker compose ps
ollama list
```

En el equipo verificado ya está instalado `llama3.1:latest`. En otro equipo,
puedes instalarlo explícitamente con `ollama pull llama3.1`; no hace falta si ya
aparece en la lista. Conserva `bge-large:latest` para los embeddings existentes.

Conversación interactiva:

```powershell
uv run --locked --inexact python -m scripts.data_steward_agent chat
```

Ejemplo de secuencia:

```text
Tú: ¿Qué significa CUSTOMER.annual_income?
Tú: ¿Y en qué unidad se expresa?
Tú: ¿Cuáles son los valores permitidos de CUSTOMER.risk_level?
Tú: salir
```

El historial conserva como máximo cuatro pares completos de pregunta/respuesta
en memoria y se descarta al terminar. No hay una base de conversaciones, archivos
de historial ni continuidad entre procesos. El historial sirve para resolver
preguntas de seguimiento; los hechos se recuperan de nuevo en cada turno. Las
preguntas fallidas no se incorporan como turnos completados.

Una pregunta y salida verificable para automatización:

```powershell
uv run --locked --inexact python -m scripts.data_steward_agent ask "Que significa LOAN.dpd?"
uv run --locked --inexact python -m scripts.data_steward_agent ask "Existe CUSTOMER.credit_score?" --json
```

`--json` incluye respuesta, estado, evidencia, referencias, llamadas a herramientas
y cantidades recuperadas/citadas. Una respuesta de insuficiencia o capacidad no
disponible es un resultado normal. Los errores de servicios o validación del
modelo devuelven código de salida 1 y un mensaje por `stderr`, sin DSN ni trazas
con payloads. En `chat`, un error de turno se muestra y permite otra pregunta.
`salir`, EOF o Ctrl+C terminan la sesión.

La configuración opcional de `.env` es:

```dotenv
OLLAMA_CHAT_MODEL=llama3.1:latest
OLLAMA_CHAT_TIMEOUT=180
```

Se reutiliza `OLLAMA_BASE_URL`; `OLLAMA_EMBEDDING_MODEL` sigue siendo independiente.
Las variables del shell tienen prioridad. No reemplaces un `.env` ya configurado.
La temperatura es cero y se fija una semilla, pero las respuestas no tienen
garantía de coincidencia textual entre hardware, versiones o cambios del tag
`latest`. La sesión comprueba que el modelo configurado exista y soporte herramientas.

## Depuración local

```powershell
uv run --locked --inexact python -m scripts.data_steward_agent chat --debug
uv run --locked --inexact python -m scripts.data_steward_agent ask "Que significa annual_income?" --json --debug
```

Los eventos breves se envían por `stderr`, separados del JSON de `stdout`:
`tool_started`, `tool_finished` y `answer_references`. Muestran el nombre de
herramienta, cantidades, UUID y JSON Pointers. No registran la pregunta, argumentos,
contraseñas, DSN, texto completo de fragmentos ni razonamiento interno del modelo.
No se crean logs de archivo. El trazado remoto se deshabilita en las llamadas del
agente incluso si el shell tiene `LANGSMITH_TRACING` habilitado.

`retrieved_document_count` indica documentos únicos entregados por la herramienta.
`used_document_count` indica referencias seleccionadas y validadas, no una medición
de la atención o del razonamiento interno del LLM. Para revisar el texto exacto de
la evidencia se puede utilizar deliberadamente la salida `--json` del corpus sintético.

## Ejemplos ejecutados con el modelo real

Pregunta: **¿Qué significa CUSTOMER.annual_income y en qué unidad se expresa?**

Respuesta observada:

> CUSTOMER.annual_income significa el ingreso anual declarado y se expresa en MXN (pesos mexicanos) por año.

Referencia construida por el programa:
`data/source/bank_metadata.json#/tables/CUSTOMER/fields/annual_income`, versión
`1.0`, documento `1804f5dd-d1b8-59e1-bac6-4347ff047305`, similitud aproximada `0.790`.

Pregunta: **¿Existe el campo CUSTOMER.credit_score?**

Respuesta observada del modelo:

> No existe el campo CUSTOMER.credit_score.

La terminal la identifica como **ausencia explícitamente documentada en el catálogo
sintético**, con referencia
`data/source/bank_metadata.json#/known_absences_for_exercise/1`, documento
`09ce9964-69ca-51fd-91f3-f3c8ea9c81e3`, similitud aproximada `0.741`.

Para **¿Qué representa CUSTOMER.favorite_color?**, la respuesta observada fue:

> No encontré evidencia suficiente en el corpus recuperado para responder. Esto no demuestra que el dato o campo no exista fuera de este catálogo sintético.

Para un saldo del cliente ficticio `SYN-C-000001`, se devolvió el estado
`capability_unavailable` con cero llamadas a herramientas y ninguna referencia.
Estos son ejemplos de aceptación sintéticos; no se guarda automáticamente ninguna
conversación de usuarios.

## Pruebas y evidencia de conservación

```powershell
# Unitarias con mocks; no necesitan PostgreSQL ni Ollama:
uv run --locked --inexact python -m pytest -q tests/test_data_steward_agent.py
# Casos nuevos contra llama3.1 real y el corpus preparado:
uv run --locked --inexact python -m pytest -q tests/test_agent_integration.py --run-agent-tests
# Todas las pruebas originales y nuevas:
uv run --locked --inexact python -m pytest -q --run-db-tests --run-retrieval-tests --run-agent-tests
```

Las pruebas no exigen redacción exacta de las respuestas del modelo. Comprueban
tool calls nativos, procedencia, JSON Pointers, estados de evidencia, límites de
capacidades y una pregunta de seguimiento. Las unitarias cubren además Ollama o
PostgreSQL no disponibles, salida inválida, referencias inventadas, argumentos
incorrectos, historial acotado, terminal y ausencia de secretos en depuración.

Las 88 pruebas previas se mantienen. Las pruebas de escritura existentes siguen
utilizando sus esquemas aislados y rollback; los nuevos casos del agente solo
leen el corpus. [agent-validation.json](agent-validation.json) registra las versiones,
cantidades y huellas comparadas antes/después de validar la suite. Ese archivo
contiene métricas de aceptación, no historial de conversaciones.

## Límites conocidos

- El LLM puede equivocarse al interpretar o traducir una definición. Validar que
  una referencia existe no demuestra que toda la paráfrasis esté implicada por
  ella. Este MVP no incluye un verificador formal de cada afirmación; la evidencia
  original sigue disponible para revisión humana.
- Cinco vecinos semánticos pueden ser insuficientes o irrelevantes. No se toma
  una similitud alta como probabilidad de verdad ni como autorización de acceso.
- Los atajos para reconocer solicitudes de registros individuales o SQL delimitan
  la experiencia de esta etapa y pueden tener falsos positivos/negativos. **No son
  controles de seguridad o permisos.** La herramienta realmente expuesta no acepta
  SQL ni ofrece acceso a filas bancarias; no se implementan roles ficticios.
- El usuario de PostgreSQL de desarrollo sigue siendo el configurado previamente.
  No se implementan autenticación de usuarios finales, permisos por documento ni
  aislamiento entre organizaciones. Los prompts no sustituyen esos controles.
- Máximo dos búsquedas y hasta tres llamadas al modelo por pregunta, contando el
  reintento. No hay planificación abierta, herramientas adicionales ni acciones
  posteriores. Las pruebas del modelo local requieren recursos y servicios reales.

No se han incorporado herramientas SQL, generación de datos, cambios al corpus,
interfaces web ni servicios de pago. Esas etapas quedan pendientes de revisión.

## Referencias oficiales

- [ChatOllama: tool calling y salida estructurada](https://docs.langchain.com/oss/python/integrations/chat/ollama).
- [Modelos LangChain: herramientas y mensajes](https://docs.langchain.com/oss/python/langchain/models).
- [Soporte de herramientas en Ollama](https://ollama.com/blog/tool-support).
