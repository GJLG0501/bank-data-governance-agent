# Consolidación arquitectónica: ejecución y entrega

Fecha: 22 de octubre de 2026. **Se consolidó código funcional en `bank_governance`, con compatibilidad de CLI/imports, fábrica de proveedores, contexto estructurado, recuperación optativa y grafo LangGraph mínimo.** El default sigue siendo `legacy_metadata` con su contrato histórico y recuperación semántica; para el catálogo nuevo, la respuesta sigue siendo extractiva por defecto. La generación híbrida no se promueve por haber pasado el refactor. No se implementaron Data Analyst, Data Quality operativo, MCP ni Streamlit.

El [informe estructurado de la etapa previa](architecture-consolidation-validation.json) conserva versiones, hashes y resultados anteriores a seguridad. La ampliación vigente de autorización está en la **sección 13** y [security-validation.json](security-validation.json); los hashes de la etapa previa no identifican el código posterior. La guía vigente es [architecture.md](architecture.md); las decisiones están en [architecture-decisions.md](architecture-decisions.md). Los resultados desfavorables de la [evaluación A/B/C](new-bank-data-steward-reasoning-evaluation.md) permanecen intactos.

## 1. Estado inicial y protección del trabajo

La rama inicial era `main`, commit `6550ca5e966839c426b62b4fa33155cd9b4ec32b`. Existían modificaciones sin commit en `.gitignore`, `scripts/data_steward_agent.py`, `scripts/knowledge_corpus.py`, `tests/test_agent_integration.py` y `tests/test_data_steward_agent.py`; también numerosos archivos nuevos de las etapas bancarias/RAG/experimentales aún sin seguimiento. No se hizo reset, clean, stash, rebase ni commit.

Se creó `refactor/architecture-consolidation-20261022` conservando ese estado. Antes de editar código se inventariaron **97 archivos no ignorados**: nombres, tamaños, SHA-256 y definiciones/imports AST de Python. La copia local reversible está en `.local-validation/architecture_20261022_204840/workspace-before.zip` (661,971 bytes); el inventario y candidatos a cambio en `inventory-before.json` del mismo directorio. `.local-validation/architecture-current.txt` identifica ese expediente. No contiene `.env` ni la base PostgreSQL. No se borró `.local-validation/`.

La auditoría enumeró el repositorio y sus dependencias; profundizó en runtime, retriever, contratos, tests, configuración, lockfile y documentación de integración/gobernanza/publicación/evaluación. Las comprobaciones iniciales confirmaron contenedor, volumen, base y puerto originales, y capturaron huellas antes de refactorizar. Dos intentos de captura fallaron antes de obtener el informe: un error de quoting PowerShell y una consulta de lectura que usaba `id` en lugar de `corpus_id` en `corpora`. Se corrigió únicamente la consulta; no se modificó PostgreSQL.

## 2. Inventario y deuda detectada

| Grupo inicial | Estado y decisión |
| --- | --- |
| `scripts/data_steward_agent.py` | Runtime funcional con CLI, configuración, proveedor, prompts, herramienta, memoria y validación juntos. Extraído por responsabilidades; entrada antigua conservada. |
| `scripts/steward_catalog.py` | Selección de corpus funcional, mezclada con scripts operativos. Servicio trasladado a `retrieval.py`; import anterior conservado. |
| `knowledge_corpus.py`, builders y retriever nuevo | Corpus legado y nuevo válidos, con manifiestos y alcance. Se conservan sus implementaciones probadas detrás de adaptadores; no se reingiere nada. |
| `bank_data`, integración, generación y publicación | Operaciones explícitas con restricciones propias. Conservadas; nunca son pasos implícitos de arranque del agente. |
| Experimentos de razonamiento y contexto | No aprobados para defaults, pero consumidores de pruebas e informes históricos. Conservados y diferenciados de la ruta híbrida nueva; no se borran métricas negativas. |
| `tests/` | Cobertura histórica amplia con marcadores; algunos tests escriben incluso con rollback. Conservada. Solo la suite sin servicios y un conjunto local pequeño fueron ejecutados. |
| `docs/`, JSON de resultados | Cronología útil pero README desactualizado. Documentos históricos intactos; README y arquitectura central nuevos permiten orientación sin leer toda la historia. |
| `.local-validation/`, dumps y estados | Artefactos excluidos de Git. Conservados; no se limpian ni publican automáticamente. |
| Dependencias | LangGraph ausente; proveedor generativo acoplado a Ollama. Se añade LangGraph y extra Gemini opcional, con pruebas simuladas. |

Deuda concreta: contratos de evidencia dependientes del agente, configuración generativa dispersa, recuperación bloqueada por vocabulario previo a búsqueda vectorial, contexto sin período estructurado, validación generativa por literales incapaz de probar implicación semántica y falta de medición de tokens. Las guardas Docker fijadas al entorno son una dependencia operativa deliberada que se conserva; no se presenta como portabilidad completa. Algunos preflights históricos fijan hashes de código de otra etapa y rechazarán cambios intencionales actuales: no se relajaron para facilitar una publicación.

## 3. Plan ejecutado y cambios acotados

Se siguieron estas fases: inventario/copia/rama y huellas; extracción del runtime; configuración/proveedores; contratos/contexto/herramienta; recuperación y validación híbridas optativas; LangGraph mínimo; borradores; pruebas, conservación y documentación. La primera extracción se verificó con **52/52** tests del agente y contratos previos antes de ampliar funcionalidades.

Solo seis archivos preexistentes difieren respecto al inventario inicial por esta tarea: `scripts/data_steward_agent.py`, `scripts/steward_catalog.py`, `.env.example`, `README.md`, `pyproject.toml` y `uv.lock`. El resto de modificaciones anteriores sigue distinguible en el inventario y no fue sobrescrito. Los archivos nuevos de esta tarea son el paquete, tres archivos de tests, los borradores y la documentación central/validación.

### Reemplazos y eliminación justificada

| Componente | Consumidores | Cambio y justificación |
| --- | --- | --- |
| Implementación del script del agente | CLI antigua, imports de tests y evaluadores históricos | Reemplazada por un adaptador al módulo `bank_governance.steward`. La implementación se conserva distribuida en el paquete y la copia local; los imports antiguos mantienen identidad para monkeypatches y consumidores. |
| Implementación de `steward_catalog` | Evaluación y sesiones nuevas | Consolidada en `bank_governance.retrieval.catalog_session`, con reexport en el archivo antiguo. No hay dos implementaciones divergentes. |
| Prompt `NEW_SYNTHESIS` | Rama que construía mensajes luego reemplazados antes de invocar el modelo nuevo | Se eliminó ese código muerto al extraer prompts. Las rutas efectivas de selección, legado y experimento se conservan y sus pruebas pasan. |
| README de la primera etapa | Usuarios nuevos | Sustituido por guía del estado actual; el original está en Git y en la copia previa. Las instrucciones históricas de datos/RAG siguen en sus documentos. |

No se eliminaron archivos de experimentos ni tests. No se borraron fuentes, informes, respaldos, manifiestos, migraciones o corpus. Tampoco se retiraron dependencias históricas usadas: se evitó inferir que una dependencia operacional era innecesaria solo porque no aparece en el agente nuevo.

## 4. Estructura final resumida

```text
bank_governance/
  config.py              # proveedor/modelo y parámetros generativos
  providers.py           # Ollama / Gemini opcional / métricas seguras
  contracts.py           # evidencia, afirmaciones y especialistas
  context.py             # estado volátil y referentes
  database.py            # lectura publicada interna con guardas
  retrieval.py           # sesiones, reformulación y RRF optativos
  tools.py               # search_data_catalog
  steward.py             # especialista real y sesiones
  prompts.py, policy.py   # instrucciones y alcance
  validation.py          # validación del experimento conservado
  hybrid.py              # afirmaciones atómicas optativas
  coordinator.py         # LangGraph mínimo
  cli.py, __main__.py
scripts/                  # wrappers compatibles + operación/historia
tests/
  test_architecture.py    # proveedores, contexto, recuperación, grafo, CLI
  test_architecture_live.py
  test_concept_drafts.py
  ...                     # cobertura previa conservada
docs/
  architecture.md, architecture-decisions.md
  architecture-consolidation-report.md
  architecture-consolidation-validation.json
  drafts/new-bank-concepts/  # siete Markdown + sources.json
  ...                     # informes históricos intactos
data/, sql/, compose.yaml  # estado original conservado
```

No se creó una jerarquía por cada especialista futuro. Los servicios compartidos se documentan en [architecture.md](architecture.md), con diagrama y flujo de preguntas.

## 5. Contratos, contexto y Data Steward

Los contratos históricos conservan campos e imports; `AgentReply` incorpora `validation_results` al final para mantener compatibilidad de argumentos posicionales. Los contratos nuevos incluyen `AtomicClaim`, `VerificationOperation`, `AtomicExplanation`, `SpecialistRequest` y `SpecialistResult`. Una operación es un objeto tipado, nunca SQL ejecutable.

El contexto de sesión conserva pregunta, conceptos, identificador SQL, producto, período, modelo/corpus, referente pendiente, evidencia del turno y límites. El historial continúa siendo acotado; no se guarda en disco y no se añadieron Redis, almacenamiento ni checkpointer. Al comenzar otro turno se vacían los IDs de evidencia. Las preguntas y punteros previos ayudan a recuperar, pero no acreditan hechos ni citas del turno actual.

El modo `hybrid_experimental` permite que el LLM relacione documentos y proponga explicaciones; Python valida citas, identificadores y operaciones documentales. Se distinguen:

- `verified_literal`: texto exacto de la fuente actual.
- `operation_verified_semantics_unverified`: operación correcta según las fuentes citadas; el texto natural no queda certificado.
- `review_required`: interpretación sin comprobación automática suficiente, visible como propuesta pendiente de revisión.
- `rejected`: afirmación descartada con motivo conservado en el resultado.

Se comprueban mes anterior dentro de febrero–junio, signo de producto/código, identidad literal de una fórmula y nulabilidad del DDL upstream. No se consultan filas ni se implementa el motor de reglas operativo de Data Quality. El estado `explanation_requires_review` evita promover una inferencia solo por tener citas. El código también puede explicar una ausencia pertinente documentada aunque el LLM elija insuficiencia: la ficha debe pertenecer al turno y coincidir con un término de la pregunta actual. No se declara resuelta la implicación semántica general.

La referencia extractiva sigue disponible sin esa lógica nueva. El generativo experimental anterior y el contexto conceptual temporal siguen diferenciados para reproducir la evaluación A=53/62, B=46/62 y C=47/62. No se ejecutó otra evaluación completa para intentar aumentar esas puntuaciones ni se alteraron sus resultados.

## 6. Proveedores y versiones reales

Se midieron instalaciones antes de elegir APIs: `langchain-core 1.6.12`, `langchain-ollama 1.1.0`, `langchain-postgres 0.0.19`, `pydantic 2.14.1`, `psycopg 3.3.6`, `pytest 9.1.1`; LangGraph y Gemini no estaban instalados. Tras resolver y sincronizar: **LangGraph 1.2.16** instalado. El lock resuelve `langchain-google-genai 4.4.2` en el extra `cloud`, que **no se instaló ni invocó**. La resolución ajustó `tenacity` de 9.2.1 a 9.1.4 y `websockets` de 17.3 a 16.1.1; la suite final pasó con esas versiones.

La fábrica devuelve un modelo LangChain, identidad y configuración separada. Ollama conserva el modelo local y parámetros originales, verifica digest y soporte de herramientas. Gemini requiere selección explícita, modelo explícito, `BANK_ALLOW_CLOUD=true` y credencial de entorno; fuerza Developer API y no prueba ni invoca el servicio en el constructor. Los tests usan un constructor simulado. Un modelo remoto se identifica por nombre: no se inventa un digest inmutable. La declaración de capacidades y un binding exitoso no prueban compatibilidad de cualquier modelo; fallos de invocación se informan sin fallback.

Las credenciales no forman parte de `LLMConfig`, de la identidad ni de logs. `.env.example` no incluye claves. Los embeddings conservan su configuración y digest independientemente del proveedor generativo. Claude se contempla como extensión de fábrica, no como proveedor funcional.

Las APIs se contrastaron con la documentación oficial de [StateGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) y [ChatGoogleGenerativeAI](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai). Se utilizaron las clases y métodos de las versiones resueltas, no un ejemplo histórico de otro framework.

## 7. Recuperación, contexto efectivo y borradores

La mejora `--retrieval-mode hybrid` es optativa. La búsqueda semántica y las guardas actuales se conservan; la nueva capa añade coincidencia por términos/nombres sobre el manifiesto ya verificado, expansión temporal general y fusión RRF. Siempre devuelve documentos de la identidad esperada, con límites. Puede hacer dos consultas semánticas por llamada de herramienta y nunca crea embeddings documentales. No se añadió DDL ni se aplicó un índice. Para 82 fichas no había necesidad demostrada de FTS/GIN; esa opción queda documentada para una medición futura en aislamiento.

La primera comprobación real encontró un fallo: «¿Cuál es el cierre que abre mayo?» recuperaba las dos fichas de apertura y otras reglas, pero «¿Y en el mes siguiente?» devolvía cero resultados. El contexto tenía junio y un concepto temporal; la reformulación solo incorporaba ese tema si la nueva consulta contenía palabras temporales. Se corrigió el enlace general entre referente temporal y período, y se añadió un test con una paráfrasis diferente. No hay una respuesta especial para la frase conocida.

La misma ejecución mostró que el modo extractivo podía escoger solo `temporal.calendar` pese a recibir las fichas de apertura. La prueba de recuperación se precisó para distinguir evidencia recibida de evidencia elegida; no se da por resuelta la calidad de selección o la explicación explícita de cada mes. Se conservó el primer fallo en `.local-validation/architecture-live-first-failure.json`. La repetición se limitó al conjunto pequeño, sin ciclo de ajuste para un porcentaje perfecto.

El runtime instrumentado registra solo metadatos: tokens reportados, caracteres, contexto configurado, duración, fase, modelo/proveedor, herramientas, tamaño de evidencia y número de intentos del backend. Un indicador de truncamiento es una sospecha, no una medición exacta de la ventana efectiva. No se registran preguntas, contenido documental, secretos ni razonamiento interno. El trazado remoto se deshabilita también al invocar LangGraph.

Los siete borradores están en `docs/drafts/new-bank-concepts/`: temporalidad, conciliación, productos/signos, granos/JOIN, definición física/semántica, ausencias y recorrido conceptual de calidad. Cada uno diferencia fuente explícita, inferencia técnica, explicación pedagógica, propuesta MVP y dato desconocido. `sources.json` conserva las afirmaciones originales y sus referencias/hash; los ejemplos usan Decimal y procedencia verificable. **No son una versión 2 del corpus, no se publicaron ni se generaron embeddings.**

## 8. Estado real de LangGraph y especialistas

El grafo utiliza la biblioteca instalada: estado tipado, nodo de enrutamiento, nodo Steward real y nodo de capacidad no disponible. Propaga respuesta, citas y resultados de validación; sanitiza errores y rechaza un modelo de datos distinto al de la sesión. El enrutamiento usa capacidad explícita y guardas limitadas de intención; no se afirma que entienda cualquier solicitud compuesta.

No agrega llamadas LLM. Tampoco ejecuta paralelo, reintentos de negocio ni consultas analíticas. Data Analyst y Data Quality tienen sus capacidades declaradas como `implemented=False`; no se instancian agentes ficticios. Una sesión es mutable y debe usarse secuencialmente, sin compartirla entre solicitudes concurrentes. La coordinación futura necesitará aislamiento de sesiones y reglas de resultados parciales.

## 9. Pruebas ejecutadas y alcance

| Verificación | Resultado |
| --- | --- |
| Primera extracción: agente y contratos históricos | 52/52 aprobadas |
| Primera suite sin servicios | 222 aprobadas, 305 omitidas |
| Suite final sin servicios, incluidos nuevos contratos/proveedores/contexto/grafo/CLI/borradores | **237 aprobadas, 306 omitidas, cero fallos** |
| Ensayo real pequeño inicial | Un test falló en el tercer turno por pérdida del referente temporal; conservado |
| Ensayo pequeño tras corrección | **Un test real con cinco preguntas aprobado**; ejecutado junto a 30 tests con mocks (31/31 en esa invocación) |
| CLI instalada | `bank-steward --help`, salida 0 |
| Dependencias fijadas | `uv lock --check --offline`, 67 paquetes resueltos, salida 0; requirió acceso a la caché local fuera del sandbox |
| Formato de cambios | `git diff --check`, sin errores; avisos de conversión LF/CRLF de Git |

La suite final tiene 543 casos recolectados; 306 se omitieron por requerir servicios o ensayos explícitos. No se consideran aprobados. Los tests históricos de escritura/rollback no se lanzaron sobre PostgreSQL activo. Las suites completas de 50/62 casos reales no se repitieron: esta tarea priorizó mocks y una integración representativa pequeña.

Las cinco preguntas finales comprobaron moneda extractiva, recuperación indirecta de mayo, seguimiento al mes siguiente, ausencia documentada en híbrido y propuesta sobre abril. Hubo **10 llamadas locales al modelo**, máximo reportado **1,154 tokens de entrada**, contexto configurado 8,192 y cero indicadores de truncamiento. La respuesta híbrida de abril quedó en `explanation_requires_review`, con una afirmación rechazada y otra no certificada semánticamente. No demuestra aceptación del razonamiento general. Gemini se probó solo con mocks; **cero llamadas cloud**.

Los tests nuevos comprueban proveedor local, remoto simulado, selección y configuración, rechazo de incompatibilidad, ausencia de secretos en identidad/errores, telemetría, referentes, recuperación por varias paráfrasis, alcance, operaciones documentales, ausencias, contratos, grafo, capacidades no implementadas, CLI y procedencia/aritmética de borradores. Los JUnit y respuestas están en `.local-validation/architecture-offline-final.xml`, `architecture-live-final.xml` y `architecture-live-results.json`.

## 10. Conservación antes/después

La comparación final, después del refactor y las preguntas reales, confirmó igualdad exacta de identidad, estructura/filas legadas, huellas históricas, siete tablas nuevas y corpus nuevo con contenido/metadatos/vectores. Se usaron exclusivamente transacciones READ ONLY.

| Objeto | Antes | Después |
| --- | ---: | ---: |
| CUSTOMER / TRANSACTION / LOAN | 1,000 / 5,000 / 500 | 1,000 / 5,000 / 500 |
| dim_cliente / dim_producto / dim_txn | 5,000 / 4 / 9 | 5,000 / 4 / 9 |
| Saldos / movimientos | 120,000 / 225,000 | 120,000 / 225,000 |
| Referencias auxiliares | 20,009 | 20,009 |
| Corpus legado / nuevo | 24 / 82 | 24 / 82 |

Contenedor original `bank-data-governance-agent-dev-bank-postgres-1`, volumen `bank-data-governance-agent-dev_bank-postgres-data`, base `bank_governance_synthetic_dev`, puerto `127.0.0.1:5434`, healthy. Sus identidades coinciden antes/después. Huellas históricas: datos `30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5`; corpus legado `63a6313e870be8268ce7bd85ee0eb8401ebbece4bb6f529b211c4796a6db0847`. La huella de comparación del corpus nuevo (contenido, metadatos y texto de vectores, ordenado por ID) fue `de75a01be9dc6da0114cf1248e7e4c88b9c220e2f7c77deb780ae55b530e58e7` en ambos momentos; no se confunde ese método con el agregado binario del manifiesto de publicación.

Los **44 archivos preexistentes protegidos** de `sql/`, `data/` y `docs/` inventariados permanecieron byte a byte iguales. Se preservaron los informes A/B/C y sus JSON, los SQL upstream y migraciones/manifiestos. Los nuevos documentos de arquitectura y borradores no forman parte de esos originales.

## 11. Comandos de uso reproducibles

Desde la raíz del repositorio, sin regenerar datos:

```powershell
uv sync --locked --inexact
uv run --locked --inexact bank-steward ask '¿Qué representa saldo_apertura?' --data-model new_bank_2026 --json --simulated-user steward_demo
uv run --locked --inexact python -m scripts.data_steward_agent chat --data-model new_bank_2026 --simulated-user steward_demo
uv run --locked --inexact bank-steward ask '¿Cuál es el cierre que abre mayo?' --data-model new_bank_2026 --retrieval-mode hybrid --coordinator --simulated-user steward_demo
uv run --locked --inexact bank-steward ask 'Calcula saldos' --data-model new_bank_2026 --coordinator --capability analytics --simulated-user steward_demo
uv run --locked --inexact python -m pytest -q -p no:cacheprovider
```

La solicitud analytics declara no disponible. Los comandos `ask/chat` necesitan PostgreSQL y Ollama existentes; ninguno ejecuta migraciones, carga o ingestión. El extra cloud y las variables requeridas están documentados en README, pero no son pasos de esta aceptación ni autorizan tráfico remoto automático.

## 12. Limitaciones y próximas tres tareas

Persisten límites de selección, ambigüedad de referentes, pertinencia lexical y suficiencia de contexto. La recuperación híbrida no fue sometida de nuevo al conjunto completo de 50 preguntas y no se activó por defecto. La ruta generativa no puede garantizar implicación semántica mediante citas u operaciones tipadas; las ausencias se resuelven con coincidencia de términos, un criterio finito que necesita casos adversos. No se generaliza una evaluación pequeña a aceptación total.

La instancia actual depende de un checkout con artefactos y guardas Docker fijadas; el wheel de código no distribuye por sí solo los datos/manifiestos del proyecto. El adaptador cloud no tiene validación real de servicio/costo ni revisión inmutable del modelo. El grafo no es un coordinador semántico completo, y una sesión no es segura para uso concurrente. Los publicadores históricos requieren revisión explícita de sus preflights antes de otra publicación; no se cambiaron sus controles para ignorar diferencias de código.

Las próximas tres tareas recomendadas, sujetas a revisión, son:

1. Revisar esta base y acordar la aceptación del nuevo catálogo/rutas optativas mediante una evaluación finita de recuperación, ausencias y afirmaciones, con versiones y evidencia congeladas antes de ejecutar; no modificar defaults por compilación.
2. Diseñar e implementar Data Analyst con operaciones parametrizadas de solo lectura, identidad del dataset, grano/período, límites y permisos, sin SQL libre del LLM; usar el contrato común y ensayar infraestructura en aislamiento.
3. Revisar los siete borradores y definir la aceptación semántica del híbrido; solo después evaluar una versión documental nueva y una eventual prueba cloud autorizada, conservando los corpus actuales.

La consolidación previa terminó con esos límites. La ampliación de seguridad que sigue sustituye el orden de prioridades anterior, sin afirmar que los especialistas futuros, la generación confiable o una versión 2 del RAG estén terminados.

## 13. Ampliación obligatoria: Data Governance y autorización transversal

Se implementó el núcleo `synthetic-mvp-1`, separado del LLM, y se declaró Data Governance como cuarta capacidad futura no implementada. Entrada del agente, herramienta y recuperación autorizan de forma independiente; omitir LangGraph no concede acceso. `SecuredOperation` representa el punto de control de un futuro adaptador SQL, probado con callbacks sintéticos. No se construyeron Analyst, Quality, Governance generativo ni un motor analítico.

**Control implementado y simulado.** Contratos congelados para identidad, roles/atributos, sesión, recurso/sensibilidad, acción, finalidad/ámbito, decisión y auditoría. El emisor local reconoce sus propios objetos de sesión/contexto; no confía en roles del mensaje ni en contratos deserializados/clonados. Default deny; sesiones de una hora y revocación volátil. `requires_approval` impide ejecutar; no hay aprobaciones reales. La CLI exige `--simulated-user steward_demo` para la demostración. Esa bandera no acredita identidad real. Sin identidad se bloquea antes de crear el proveedor o backend. Los arneses históricos de evaluación no se reejecutaron ni se les concedió acceso implícito: requerirían adaptación explícita del emisor antes de otro ensayo autorizado.

La recuperación filtra antes de entregar documentos al sintetizador y también protege los candidatos léxicos. Solo el manifiesto validado por el anfitrión fija los documentos conocidos; el texto recuperado no puede degradar sensibilidad. La clasificación sintética local considera internos los documentos actuales, sin cambiar sus metadatos publicados. [La propuesta de clasificación](data-classification-proposal.json) cubre exactamente cinco tablas y 42 columnas con tipos y fuentes originales. Ninguna columna financiera individual se declara agregada, ni se asigna moneda. No es una política oficial bancaria.

**Hallazgo de privilegios.** La auditoría SELECT encontró el login `bank_governance_dev` con superuser, BYPASSRLS, CREATEDB y CREATEROLE; propietario de las 14 tablas revisadas y con privilegios de escritura. RLS/FORCE RLS están desactivados en las 14. Esto bloquea el uso real: una política Python no reduce el poder de una credencial administrativa. Se documentaron roles mínimos separados de propietarios, vistas autorizadas, permisos por esquema/tabla/columna, RLS, ámbitos confiables y controles de exportación. No se cambiaron roles, membresías, permisos o políticas en PostgreSQL.

**Auditoría y privacidad.** Eventos tipados con request UUID, pseudónimo simulado, agente/herramienta, recurso lógico, acción, política, decisión, tiempo/duración y resultado/motivo controlado. No guardan preguntas, secretos, tokens de sesión, documentos, excepciones o resultados SQL. La cola tiene 1,000 eventos volátiles; no equivale a un log de cumplimiento. El historial es por sesión y se vacía junto con evidencia/referentes al denegar por revocación/caducidad. No hay detector DLP para el texto libre: no usar PII real. Identidad real, retención durable, protección de cachés/exports y separación efectiva de PostgreSQL quedan pendientes. Las amenazas y fronteras se detallan en [security-and-governance.md](security-and-governance.md).

**Pruebas finales:** **265 aprobadas, 306 omitidas, 571 recolectadas**, sin activar servicios. Las 28 pruebas nuevas corresponden a 26 casos de seguridad (incluidos casos parametrizados) y dos de clasificación. Cubren definiciones permitidas, agregados autorizados, identificadores denegados, cuenta fuera de ámbito, falso administrador, documento malicioso, herramienta directa restringida, export masivo, acción no permitida sobre datos autorizados, falta de identidad, metadatos RAG restringidos y cohorte pequeña. También verifican expiración/revocación, contratos falsificados, auditoría sin payloads y Governance no implementado. Se comprueba explícitamente que una denegación no ejecuta el callback de datos ni entrega evidencia al sintetizador. Se conservaron las pruebas existentes y sus fixtures declaran ahora identidades simuladas cuando requieren autorización.

La primera suite completa encontró un bloqueo ACL de Windows al crear/limpiar el temporal de pytest; no fue un fallo de PostgreSQL ni un resultado aceptado. Se repitió fuera de esa restricción, con una carpeta temporal nueva; la suite final terminó con código 0 en 31.56 s. Evidencia: `.local-validation/security-offline-accepted.xml`; subconjunto final: `security-cases-final.xml`. **Cero llamadas LLM, cloud o ingestas** en esta ampliación. No se repitieron búsquedas A/B/C ni ensayos con Llama. No se ejecutaron DDL ni pruebas de permisos reales.

**Conservación:** consultas READ ONLY y guardas confirmaron el contenedor/ID, volumen original, base `bank_governance_synthetic_dev` y puerto `127.0.0.1:5434`, healthy. Antes/después coinciden exactamente los 6,500 registros legados; las siete tablas bancarias publicadas (350,013 filas originales y 20,009 referencias); los corpus de 24 y 82 documentos; contenido, metadatos, embeddings y privilegios. Huellas históricas: datos `30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5`; corpus legado `63a6313e870be8268ce7bd85ee0eb8401ebbece4bb6f529b211c4796a6db0847`; corpus nuevo por comparación ordenada de filas `de75a01be9dc6da0114cf1248e7e4c88b9c220e2f7c77deb780ae55b530e58e7`. No se confunde este método con el agregado del manifiesto.

Antes de esta ampliación se guardaron estado Git y SHA de 129 archivos en `.local-validation/security_20261022_212709/state-before.json`, junto con `workspace-before.zip`. `database-before.json`, `database-after.json`, `postgres-privileges*.json` y `conservation.json` del mismo directorio conservan la auditoría sin secretos ni filas individuales. El inventario de cambios y hashes del código evaluado está en [security-validation.json](security-validation.json). No se hizo commit ni se alteró la rama.

Archivos nuevos: `bank_governance/security_contracts.py`, `security.py`, `secured_retrieval.py`; `tests/test_security.py`, `test_classification.py`; `docs/security-and-governance.md`, `data-classification-proposal.json`, `security-validation.json`. Se actualizaron los seis módulos que integran el control, ocho archivos de tests/fixtures existentes y README/los tres documentos centrales de arquitectura. No se tocaron fuentes upstream, datos, corpus, embeddings, credenciales, dependencias ni informes experimentales previos.

**Siguiente orden propuesto, sujeto a revisión:** revisar políticas/clasificaciones sintéticas y modelo de identidad; diseñar y probar roles/vistas/RLS en PostgreSQL aislado sin privilegios administrativos en runtime; solo después considerar autenticación real y herramientas de los especialistas futuros. No se ejecuta ninguno de esos pasos automáticamente. Esta entrega se detiene con el núcleo verificable y los bloqueos productivos explícitos.
