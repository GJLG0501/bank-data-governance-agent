# Catálogo semántico y RAG del nuevo modelo bancario

Validación del 22 de octubre de 2026. Estado: **corpus construido y validado exclusivamente en PostgreSQL aislado**. Se indexaron 82 documentos y la repetición devolvió `sin cambios`. Aprobaron 169 pruebas, incluidas 30 de recuperación real. El agente Data Steward conserva su implementación y herramienta anteriores. No se ingirieron documentos ni embeddings nuevos en PostgreSQL principal.

La evidencia verificable está en [new-bank-model-rag-validation.json](new-bank-model-rag-validation.json). Los resultados de esta tarea se cuentan por separado de las 193 pruebas de la publicación anterior.

## Archivos de esta entrega

Todos los siguientes archivos son nuevos:

| Archivo | Función |
| --- | --- |
| `scripts/new_bank_catalog.py` | Constructor y validador del catálogo con procedencia por afirmación |
| `data/source/new_bank_model/catalog.json` | Catálogo normalizado, modelo `new_bank_2026`, versión `1.0.0` |
| `scripts/new_bank_documents.py` | Constructor reutilizable de `langchain_core.documents.Document` |
| `data/corpus/new_bank_model.documents.jsonl` | Corpus documental reproducible, sin filas bancarias |
| `data/corpus/new_bank_model.documents.manifest.json` | Cobertura, IDs y hashes de contenido |
| `data/corpus/new_bank_model.index-manifest.json` | Identidad del corpus vectorizado y hashes binarios de sus 82 vectores |
| `sql/rag/001_new_bank_knowledge.sql` | Almacenamiento separado y verificación estricta de compatibilidad |
| `scripts/new_bank_rag.py` | Preparación de vectores, ingestión aislada, retriever y evaluación |
| `tests/test_new_bank_rag_unit.py` | 35 pruebas sin servicios ni conexiones |
| `tests/test_new_bank_rag_postgres.py` | 17 pruebas reales de ingestión, integridad y aislamiento |
| `tests/test_new_bank_rag_retrieval.py` | 30 pruebas reales de recuperación en español |
| `tests/fixtures/new_bank_retrieval_cases.json` | Preguntas y evidencia esperada por ID de entrada |
| `docs/new-bank-model-rag.md` | Diseño, ejecución, resultados y límites |
| `docs/new-bank-model-rag-validation.json` | Evidencia de ejecución, conservación y resultados por pregunta |

No se modificaron archivos anteriores de la aplicación, dependencias, SQL originales, migraciones bancarias 001/002 ni corpus anterior. La modificación preexistente de `.gitignore` y los archivos de entregas anteriores quedan fuera de los cambios de esta tarea. Los artefactos locales de ejecución se conservan bajo `.local-validation/`, excluido de Git; allí permanecen el paquete de vectores y los JUnit. No se publicaron respaldos ni secretos.

## Fuentes y significado del catálogo

Las fuentes principales son los tres SQL originales de `sql/upstream/`; se verificaron sus bytes. Las fuentes del MVP complementan, sin sustituir, el modelo recibido:

| ID | Fuente | Origen |
| --- | --- | --- |
| U1 | `sql/upstream/001_dimensiones_cliente_producto_txn.sql` | Modelo recibido |
| U2 | `sql/upstream/002_generar_cuentas_y_saldos_enero_2026.sql` | Modelo recibido |
| U3 | `sql/upstream/003_generar_transacciones_y_saldos_feb_jun_2026.sql` | Modelo recibido |
| M2 | `sql/integration/002_new_bank_integrity.sql` | Propuestas y restricciones del MVP |
| G1 | `docs/new-bank-model-governance.md` | Especificación del MVP |
| P1 | `docs/new-bank-model-integration-plan.md` | Decisiones de integración del MVP |

El catálogo registra el SHA-256 completo de cada archivo. Cada afirmación lleva ID, texto, clasificación y una o más referencias con ruta, SHA-256 del archivo, líneas inicial/final inclusivas y SHA-256 del fragmento. Las líneas empiezan en 1; el hash del fragmento usa las líneas UTF-8 unidas con LF, sin salto final. Las referencias del corpus añaden JSON Pointer a la entrada y a cada afirmación del catálogo. Se comprueban archivo, rango, contenido y puntero.

Se distinguen 100 afirmaciones `upstream_explicit`, 47 `technical_inference` y 25 `mvp_proposal`: 172 en total. Las restricciones del MVP no se presentan como políticas oficiales del banco. La ausencia de un atributo en los SQL se clasifica como inferencia técnica sobre esas fuentes; no demuestra que ese atributo no exista en otros sistemas.

`original_tables` contiene las cinco tablas recibidas; `auxiliary_tables` separa `cfg.ref_txn_modelo` y `cfg.ref_cuenta_modelo`. Las 42 entradas de campos conservan tipo físico, declaración, nulabilidad, PK y DEFAULT originales. El atributo `nullable_mvp` distingue restricciones posteriores sin reescribir `nullable_upstream`. `dim.dim_txn` continúa documentada sin PK ni UNIQUE; el catálogo auxiliar usa producto/código.

Las relaciones documentan las claves de JOIN, cardinalidades esperadas y diferencias entre definición física y generación sintética. Los productos y las nueve combinaciones producto/código provienen de los INSERT originales. Las reglas cubren importes, signos, crecimiento mensual, fechas, calendarios y conciliación. Se preservan `dominio` de origen y el nombre y significado temporal de `saldo_apertura`.

Se documentan expresamente moneda no especificada, `credit_score` ausente, falta de correspondencia acreditada entre LOAN y C_PERSONAL, significado de nacimiento para PM no aclarado y atributos bancarios no modelados. Los 44 casos cronológicos y otras cifras observadas pertenecen a la validación de un dataset concreto; no se insertaron como definiciones del esquema.

## Corpus reproducible

Cada entrada se convierte en un documento semántico completo. Los 82 fragmentos tienen como máximo 624 caracteres; las referencias extensas permanecen en metadatos. El texto identifica modelo, versión y clasificación de cada afirmación. No contiene filas de clientes, cuentas, saldos, movimientos ni embeddings anteriores.

| Tipo | Documentos |
| --- | ---: |
| Modelo | 1 |
| Tablas originales | 5 |
| Campos | 42 |
| Productos | 4 |
| Combinaciones producto/transacción | 9 |
| Relaciones | 3 |
| Reglas financieras | 5 |
| Reglas temporales | 2 |
| Ambigüedades y ausencias | 7 |
| Referencias auxiliares | 2 |
| Limitaciones sintéticas | 1 |
| Propuestas de gobernanza | 1 |
| **Total** | **82** |

Los IDs documentales son UUID5 de modelo, versión, SHA del catálogo, versión del renderer e ID estable de entrada. El UUID del corpus añade la identidad del embedding al manifiesto documental; los IDs almacenados incorporan ese UUID. Cambiar fuentes, contenido, renderer o embedding produce otra identidad. La validación reconstruye el texto esperado, además de comprobar hashes: recalcular el hash de un texto inventado no lo vuelve válido.

Identidades de esta ejecución:

- Catálogo SHA-256: `5728b7a92fb618bf2e29083d9072522ad2c897dc9b176556f37dabb39c44fa65`.
- Contenido documental agregado: `77311b6c11c14b75a984f4a14b3267a69647e46c478c52719fe235dc17a5579a`.
- `model_id`: `new_bank_2026`.
- `corpus_id`: `8dbc359e-53db-5df8-bbec-418b1add756e`.
- Vectores SHA-256 agregado: `08b5555ffede84edfc6b4a399f83c4c4eb1705ed997fc5b6d56829a5798e57d9`.

El último hash ordena pares `id:embedding_sha256`; cada hash individual usa `Vector.to_binary()`, contrastado con `public.vector_send()` en PostgreSQL. Los manifiestos versionados contienen hashes y procedencia, no los vectores completos.

## Embeddings y almacenamiento aislado

Se utilizó Ollama local con `bge-large:latest`, digest `b3d71c92805938e2c9d78e6f35e82d7cc1bd77e05b47dd2ab3016240f4021c15`, dimensión 1024. Se verificaron identidad y dimensión antes de preparar vectores. La consulta comprueba el digest antes y después de generar su embedding. La ingestión CLI vuelve a comprobarlo antes de escribir. No interviene un proveedor generativo.

El destino fue el contenedor ya existente `nbm-pg17-validation-9065d649f8d74222bd04dc58a0e54835`, base `nbm_validation_9065d649f8d74222bd04dc58a0e54835`, volumen `nbm-validation-9065d649f8d74222bd04dc58a0e54835`. PostgreSQL 17.11, pgvector 0.8.7, red `none`, sin puertos publicados y con volumen exclusivo. Se comprobaron ID del contenedor, etiqueta, montaje, usuarios del volumen y manifiesto previo de migraciones.

El contenedor principal conserva su ID original y el puerto `127.0.0.1:5434`; no es un destino admitido por el transporte de escritura. Después de la reanudación manual de Docker se repitieron identidad y huellas antes de la primera escritura RAG.

El esquema nuevo `bank_knowledge_new_bank` contiene:

- `corpora`: UUID, modelo y manifiesto completo; identidad compuesta para las relaciones.
- `documents`: UUID, corpus/modelo, contenido, metadatos, `vector(1024)` y checksum binario; FK compuesta, NOT NULL, PK y CHECK de alcance, contenido y vector.

La migración compara columnas, tipos, nulabilidad, defaults, restricciones, índices y relaciones con referencias temporales. Rechaza propietarios inesperados, estructuras incompletas, tipos incompatibles, triggers, reglas, RLS y objetos ajenos. No da por compatible un objeto solo porque existe. No contiene operaciones destructivas. Se ejecutó solamente en el entorno aislado.

La ingestión usa transacción, lock y staging temporal, comprueba todas las filas y checksums antes de COMMIT y vuelve a verificar lo almacenado. No reemplaza corpus parciales o diferentes. Primera ingestión: `indexado`, 82 documentos. Repetición: `sin cambios`, mismas filas, metadatos y vectores, sin volver a generar embeddings documentales. El esquema principal aislado termina con **1 corpus y 82 vectores de 1024 dimensiones**.

Las pruebas crearon bases adicionales con prefijo `nbm_case_9065d649f8d74222_rag_` dentro del mismo contenedor aislado. Se conservaron, incluidas las usadas durante el ajuste del arnés; sus nombres están en el informe JSON. Algunas contienen estructuras deliberadamente incompatibles o un corpus señuelo. No representan el corpus validado de la base aislada principal y no se limpiaron automáticamente.

## Recuperación y pertinencia

`CatalogRetriever` requiere explícitamente `model_id`, `corpus_id`, manifiesto y estado aislado. Aplica ambos filtros en cada consulta pgvector. Valida el corpus completo al abrir la sesión y comprueba ID, contenido, metadatos y hash binario de cada resultado. Devuelve fragmento, distancia/similitud coseno, referencias por afirmación y clasificación. `search()` conserva las claves de resultado del retriever anterior; `retrieve()` añade estado `evidence`/`no_evidence` y contexto. No se modificó `search_data_catalog`.

La búsqueda habitual ordena por distancia coseno. Para listados plurales de productos de un único grupo reconocido en el catálogo, prioriza los documentos de productos de ese grupo y después ordena por coseno. Expone `retrieval_strategy` y `selection_priority`; no altera las puntuaciones. Las consultas con negación o grupos ambiguos no aplican esa preferencia. No se generan consultas SQL libres: se usa una plantilla fija y literales escapados.

Una comprobación conservadora de tema e intención rechaza preguntas ajenas, campos desconocidos, solicitudes de saldos actuales y crecimiento fuera del período documentado. Las ausencias documentadas —por ejemplo moneda— sí son evidencia recuperable. El umbral mínimo es 0.35; ni ese valor ni una similitud alta prueban la corrección de una respuesta.

La primera evaluación solo con coseno obtuvo 27/28: omitió CHEQUES del top 5 de productos de captación, aunque recuperó la definición del grupo. Se corrigió la cobertura de listados mediante la selección por grupo y se añadieron dos casos de generalización. El catálogo y los embeddings se conservaron.

| Evaluación final | Resultado |
| --- | ---: |
| 12 preguntas solicitadas | 12/12 |
| Casos adicionales | 14/14 |
| Preguntas sin evidencia | 4/4 |
| Total | **30/30** |
| MRR de 26 preguntas con evidencia | **0.9167** |

La pertinencia se verifica mediante IDs de evidencia esperados en top 5, procedencia validada y ausencia de contaminación; algunas preguntas requieren varios documentos. El MRR mide la primera evidencia pertinente y no la cobertura completa. Las puntuaciones y documentos recuperados de cada pregunta figuran en el informe JSON. Las pruebas no evalúan respuestas generadas por un LLM.

## Pruebas y conservación

Se ejecutaron primero las pruebas sin escritura a PostgreSQL. Resultados finales, sin fallos ni pruebas omitidas:

| Grupo | Aprobadas |
| --- | ---: |
| Nuevo catálogo/retriever sin servicios | 35 |
| Ingestión, restricciones y aislamiento PostgreSQL | 17 |
| Recuperación nueva con Ollama y pgvector | 30 |
| Regresión unitaria del corpus y agente anteriores | 56 |
| Recuperación real del corpus anterior, solo lectura | 7 |
| Estáticas de fuentes y migraciones bancarias | 24 |
| **Total** | **169** |

Las 17 pruebas reales cubren ingestión completa, repetición idéntica, fallo intermedio con rollback, esquemas incompletos, tipos incompatibles, corpus parcial, manifiesto alterado, contenido alterado y restricciones de NULL, unicidad, FK, metadatos, hash, dimensión y modelo. Una prueba introduce un corpus señuelo con un vector idéntico en una base de caso: el retriever no lo devuelve. Las pruebas negativas transaccionales se revierten y las pruebas persistentes quedan exclusivamente en las bases aisladas registradas.

Se corrigió un defecto del arnés: un literal SQL multilínea enviado por una tubería de Windows podía cambiar LF por CRLF y disparar el CHECK de contenido antes de probar unicidad. El arnés ahora conserva esos bytes mediante codificación hexadecimal. El corpus almacenado mediante COPY ya conservaba el contenido correcto.

La comparación final comprobó esquema, contenido, metadatos y embeddings anteriores en ambos entornos. Conservación en PostgreSQL principal:

| Objeto | Antes | Después |
| --- | ---: | ---: |
| CUSTOMER | 1,000 | 1,000 |
| TRANSACTION | 5,000 | 5,000 |
| LOAN | 500 | 500 |
| `bank_knowledge.corpora` | 1 | 1 |
| `bank_knowledge.documents` | 24 | 24 |
| Nuevo esquema RAG | Ausente | Ausente |

Las cinco tablas bancarias nuevas conservan 350,013 registros; las referencias auxiliares, 20,009. Se conservaron 20,000 cuentas y 100,000 conciliaciones exactas. Huellas históricas, recalculadas con el mismo procedimiento anterior:

- Datos bancarios anteriores: `30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5`.
- Documentos, metadatos y embeddings anteriores: `63a6313e870be8268ce7bd85ee0eb8401ebbece4bb6f529b211c4796a6db0847`.
- Dataset nuevo publicado: `a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b`.

El informe contiene conteos y hashes por tabla antes/después, firmas de esquema comparadas, hashes de archivos protegidos y sumarios JUnit. No se escribieron filas bancarias, corpus o embeddings en PostgreSQL principal.

## Reproducción controlada

Desde la raíz del repositorio, con el entorno Python existente:

```powershell
.\.venv\Scripts\python.exe -m scripts.new_bank_catalog check
.\.venv\Scripts\python.exe -m scripts.new_bank_documents check
.\.venv\Scripts\python.exe -m pytest tests/test_new_bank_rag_unit.py -q -p no:cacheprovider
```

La preparación documental `build` es local y determinista. La preparación vectorial es una operación distinta: comprueba el modelo local, no sobrescribe un bundle existente y conserva los vectores completos únicamente bajo `.local-validation/`. Los vectores de una nueva ejecución de Ollama deben verificarse; el paquete preparado evita regenerarlos al repetir ingestión.

Para verificar o consultar el corpus existente aislado, usando las identidades expresas de esta ejecución:

```powershell
$isolatedState = '.local-validation/9065d649f8d74222bd04dc58a0e54835/state.json'
$vectorBundle = '.local-validation/rag_adad9114dd7a49b78a2c6b4a9f8b0b1e/prepared_vectors.json'
.\.venv\Scripts\python.exe -m scripts.new_bank_rag verify --state $isolatedState --bundle $vectorBundle
.\.venv\Scripts\python.exe -m scripts.new_bank_rag search --state $isolatedState --bundle $vectorBundle --model-id new_bank_2026 --corpus-id 8dbc359e-53db-5df8-bbec-418b1add756e --question '¿Qué representa saldo_apertura en marzo?'
```

Las pruebas reales son optativas. `BANK_NEW_RAG_CONTEXT` debe apuntar al estado RAG local; no hay destino PostgreSQL implícito. La suite de almacenamiento crea y conserva bases de caso nuevas en el contenedor aislado, por lo que repetirla añade objetos de prueba. La suite de recuperación solo consulta:

```powershell
$env:BANK_NEW_RAG_CONTEXT = (Get-Content .local-validation/rag-current.txt -Raw).Trim()
.\.venv\Scripts\python.exe -m pytest tests/test_new_bank_rag_postgres.py --run-db-tests -q
.\.venv\Scripts\python.exe -m pytest tests/test_new_bank_rag_retrieval.py --run-db-tests --run-retrieval-tests -q
```

## Límites y siguiente decisión

El modelo sigue siendo sintético: no se infiere moneda, política oficial, interés contractual, significado de nacimiento para PM ni correspondencia automática entre sistemas. Las reglas de crecimiento son reglas del generador. El catálogo no sustituye consultas SQL futuras sobre datos ni contiene los resultados particulares de sus controles de calidad.

Los 30 casos son una evaluación finita. La abstención combina reglas conservadoras y umbral; requiere ampliar preguntas, paráfrasis, negaciones y casos adversos antes de uso general. El retriever devuelve evidencia y clasificaciones, no una respuesta bancaria definitiva. La preferencia por grupo se limita a listados sencillos. No se ha medido rendimiento a escala; 82 documentos usan búsqueda exacta, sin índice vectorial aproximado adicional.

El backend actual exige Docker y un estado de aislamiento verificado. Para conectar posteriormente Data Steward, conviene introducir un adaptador de recuperación con contexto obligatorio modelo/corpus y un contrato de evidencia común, preservando el corpus anterior como opción explícita. El agente deberá citar afirmaciones, separar inferencias y propuestas y reconocer ausencia de evidencia. Primero deben revisarse estos resultados y autorizarse almacenamiento, permisos de lectura y despliegue del corpus nuevo en el destino que corresponda.

En esta etapa no se cambia el agente, no se añaden herramientas SQL analíticas ni se implementan MCP, coordinación multiagente o infraestructura cloud. La integración del agente y la ingestión principal quedan pendientes de revisión.
