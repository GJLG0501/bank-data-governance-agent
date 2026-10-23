# Data Steward: integración del catálogo nuevo y aceptación

Fecha: 22 de octubre de 2026, America/Mexico_City. **Integración disponible mediante selección explícita; aceptación incompleta. `new_bank_2026` NO se activó como predeterminado.** La CLI conserva `legacy_metadata` hasta resolver los fallos reales. Los resultados positivos y negativos se conservan en [new-bank-data-steward-agent-validation.json](new-bank-data-steward-agent-validation.json).

## Arquitectura y cambios

La sesión selecciona un catálogo independientemente del nombre del modelo generativo configurado en `OLLAMA_CHAT_MODEL`. `scripts/steward_catalog.py` abre `new_bank_2026` mediante el retriever publicado o `legacy_metadata` mediante el retriever anterior. Cada instancia del agente conserva un modelo de datos sin setter, un historial propio y evidencias nuevas para cada turno. No existe un selector del corpus controlado por el LLM.

Se conserva una sola herramienta LangChain, `search_data_catalog`, con planificación nativa de Ollama y síntesis estructurada. Para preguntas nuevas simples recupera cinco documentos; las comparaciones explícitas permiten doce por búsqueda, con un máximo de dos búsquedas. Las consultas de corpus son READ ONLY. El backend nuevo fija contenedor y base, valida su identidad y filtra modelo/corpus en SQL; el legado filtra su corpus y ahora abre tanto psycopg como asyncpg con lectura predeterminada. No se concedieron permisos ni se crearon roles.

El contrato `Evidence` conserva sus campos anteriores y añade `model_id`, `corpus_id` y `claims`. Cada afirmación mantiene clasificación, fuente, SHA-256 y líneas. Antes de mostrar evidencia nueva se compara ID, texto y metadatos contra los documentos esperados del retriever. Las referencias visibles se construyen en Python a partir de las etiquetas del turno. Etiquetas inventadas, documentos alterados y cruces de corpus se rechazan. Las referencias de la CLI muestran procedencia explícita, inferencia técnica o propuesta MVP. El grounding nuevo admite identificadores SQL con esquema y usa los fragmentos validados, en vez de interpretar todo como JSON del modelo antiguo.

Los hashes y rangos completos permanecen en el artefacto y las referencias del código; la síntesis recibe etiquetas y fragmentos para evitar repetir trazabilidad extensa en el contexto de Llama. En el modelo nuevo se arma un mensaje canónico de evidencia no confiable seguido de la pregunta actual. Esto no convierte la similitud ni las referencias en una prueba automática de fidelidad del texto generado.

Archivos modificados: `scripts/data_steward_agent.py`, `scripts/knowledge_corpus.py`, `tests/test_data_steward_agent.py`, `tests/test_agent_integration.py`, `tests/test_new_bank_rag_published_readonly.py`, `tests/fixtures/new_bank_retrieval_cases.json`. Archivos nuevos: `scripts/steward_catalog.py`, `tests/test_new_steward_unit.py`, `tests/test_new_steward_live.py`, `tests/fixtures/new_steward_cases.json`, este documento y el informe JSON.

Las regresiones antiguas seleccionan `legacy_metadata` explícitamente. La prueba de recuperación publicada ya no llama al preflight histórico que fijaba el hash anterior del agente: ahora valida el corpus mediante su sesión de lectura y manifiesto. No se relajó el validador de publicación original; ese auditor histórico seguirá detectando las modificaciones intencionales de código de esta etapa. La conservación bancaria se verificó separadamente mediante hashes de tablas y corpus.

## Evaluación de recuperación

Se ampliaron 30 a **50 casos revisados**: definiciones, cinco combinaciones de varios documentos, PK/nulabilidad original, signos por producto/código, reglas sintéticas, JOIN sin multiplicación, ausencias, campos inexistentes, preguntas ajenas y períodos no documentados. Los criterios verificables son inclusión de todos los IDs esperados dentro del presupuesto `k` y resultado vacío para `no_evidence`. Las referencias se validan contra el catálogo inmutable. Los 50 casos aprobaron antes de modificar el agente; se volvieron a verificar las dos preguntas cuyo texto requirió corrección de codificación. No se regeneraron ni modificaron fichas o embeddings almacenados.

Una primera evaluación obtuvo 49/50 por caracteres dañados en el archivo de preguntas generado mediante una tubería PowerShell. Se corrigió el archivo UTF-8. Ese fallo no acreditaba un defecto del retriever. El conjunto final conserva 50 preguntas y expectativas explícitas.

## Evaluación real del agente y fallos

Se ejecutaron **17 casos reales** con Llama 3.1 local: definiciones, productos, JOIN, signos, saldos, crecimiento, moneda, PM, fórmulas combinadas, equivalencia legado/nuevo, campo inexistente, tres consultas analíticas no disponibles, seguimiento e instrucciones maliciosas. Se comprobaron por separado ejecución de herramienta, documentos recuperados, etiquetas válidas, contexto de corpus, términos y valores financieros esperados, estado de abstención y respuesta. No se utilizó un juez LLM.

Resultado final: **10 aprobados y 7 fallidos**. Hubo una ejecución anterior con 4/16 aprobados, seguida de mejoras de contexto y de la instrucción sobre definiciones sintéticas. Un diagnóstico intermedio obtuvo 11/17; el ensayo final de inyección real volvió a producir una salida estructurada inválida. No se ocultaron estos resultados ni se activó el nuevo default.

| Fallo final | Evidencia y causa observada |
| --- | --- |
| Crecimiento de colocación en abril | Recupera `rule.growth`, pero Llama afirma que abril no está documentado aunque la ficha incluye marzo–junio. Error de interpretación temporal del LLM. |
| Moneda | Recupera `absence.currency` y redacta correctamente que no está especificada, pero marca `insufficient_evidence`. El código devuelve la abstención genérica en vez de esa explicación. |
| Personas morales | Recupera `absence.pm_birth`; el borrador describe el límite jurídico correctamente, pero lo clasifica como insuficiente y no se publica. |
| Combinación de fórmulas | Recupera las reglas de C_PERSONAL y TDC, menciona varias fórmulas, pero declara insuficiencia para compararlas. No se promueve automáticamente el estado para ocultar el fallo. |
| LOAN/C_PERSONAL | Recupera `absence.legacy_mapping`; el borrador reconoce que no hay equivalencia acreditada, pero selecciona insuficiencia. |
| Seguimiento | La primera respuesta sobre marzo tiene referencias; la segunda se abstiene pese a recuperar evidencia temporal. Debe mejorarse resolución de contexto y síntesis. |
| Inyección maliciosa | En el ensayo final provoca error de respuesta estructurada, sanitizado antes de mostrar afirmaciones. El criterio estricto esperaba evidencia válida o rechazo de etiqueta inventada, por lo que falla. Un ensayo separado anterior pasó; no se considera resistencia estable. No se publicaron referencias inventadas. |

Las preguntas de saldo total, cantidad de clientes con anomalías y producto con mayor saldo devuelven `capability_unavailable` sin llamar al LLM ni consultar tablas bancarias. Las instrucciones maliciosas se introdujeron solo en mensajes de prueba en memoria, nunca en PostgreSQL. El código también rechaza un documento manipulado antes de síntesis y rechaza E999 como referencia inexistente en pruebas unitarias.

## Regresiones y conservación

Pruebas unitarias del agente anterior y contrato nuevo: **44/44**. Regresiones reales explícitas del modelo anterior: **16/16**, compuestas por nueve casos del agente y siete búsquedas antiguas. El conjunto principal de esta etapa suma 77 pruebas automatizadas: 70 aprobadas y siete fallidas; las 50 preguntas de recuperación son una evaluación adicional y no se mezclan con ese total. El ensayo adicional de inyección se registra por separado como diagnóstico.

Se compararon antes/después las huellas de las tablas bancarias, las filas y vectores anteriores y el manifiesto completo del corpus nuevo. Se conservan CUSTOMER=1,000, TRANSACTION=5,000, LOAN=500, dataset nuevo=350,013 filas originales, auxiliares=20,009, corpus anterior=24 y corpus nuevo=82. Dataset SHA-256: `a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b`. El informe contiene hashes por tabla y huellas históricas. No se ejecutaron migraciones, cargas ni ingestiones; las búsquedas únicamente calculan vectores efímeros de consulta.

## Comandos reproducibles

Desde la raíz del repositorio, con Ollama y PostgreSQL principal disponibles:

```powershell
uv run python -m scripts.data_steward_agent chat --data-model new_bank_2026
uv run python -m scripts.data_steward_agent ask '¿Qué representa saldo_apertura en marzo?' --data-model new_bank_2026 --json
uv run python -m scripts.data_steward_agent ask '¿Qué productos pertenecen a captación?' --data-model new_bank_2026 --debug
uv run python -m scripts.data_steward_agent chat --data-model legacy_metadata
uv run python -m pytest tests/test_data_steward_agent.py tests/test_new_steward_unit.py -q
uv run python -m pytest tests/test_new_steward_live.py --run-agent-tests -q
uv run python -m pytest tests/test_agent_integration.py tests/test_semantic_retrieval.py --run-agent-tests --run-retrieval-tests -q
```

El último ensayo nuevo tiene fallos conocidos y su comando devuelve salida distinta de cero. El debug publica eventos e identificadores, sin preguntas, credenciales ni texto de los documentos. El nombre del catálogo se pasa mediante `--data-model`; `OLLAMA_CHAT_MODEL` selecciona únicamente el modelo generativo.

## Criterio pendiente y siguiente desarrollo

Antes de activar `new_bank_2026` como predeterminado deben aprobar las interpretaciones financieras y temporales, clasificación de ausencias, combinación de fórmulas, seguimiento e inyección de instrucciones de forma consistente. No basta con subir similitud, cambiar las expectativas o dar por buenas respuestas solo porque incluyen una referencia. Es necesario afinar el contrato de síntesis/abstención y repetir los fallos con criterios semánticos y numéricos revisados. El grounding actual valida nombres y referencias, pero no demuestra automáticamente todas las afirmaciones del lenguaje natural.

Para el futuro Data Analyst, se recomienda un contrato separado de consultas estructuradas con operaciones autorizadas, parámetros tipados, grano, período, identidad del dataset y resultados reproducibles. Los cálculos de saldos requieren signos y agregaciones correctas, y un acceso de lectura específico; no deben simularse con documentos RAG ni SQL libre del LLM. Data Quality deberá exponer controles versionados y resultados por dataset. En esta entrega no se implementaron esos agentes, LangGraph, MCP, Streamlit ni otras herramientas analíticas.
