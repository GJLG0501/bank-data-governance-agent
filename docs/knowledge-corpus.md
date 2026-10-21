# Corpus documental y recuperación semántica

Esta etapa recupera evidencia del catálogo sintético. No genera respuestas con
un LLM, SQL a partir de preguntas, agentes ni una interfaz de chat. No introduce
políticas oficiales de Banamex ni controles de seguridad basados en prompts.

## Fuente y documentos

La única fuente indexada es `data/source/bank_metadata.json`, versión `1.0` del
dataset `SYNTHETIC_BANK_METADATA`. No se consultan ni vectorizan filas de
`CUSTOMER`, `TRANSACTION` o `LOAN`. Tampoco se indexan los rangos didácticos del
generador ni documentación externa como si fueran definiciones oficiales.

Se construyen **24 documentos LangChain `Document`**:

| Tipo | Cantidad | Contenido |
| --- | ---: | --- |
| Catálogo | 1 | Nombre, versión y descripción originales. |
| Tabla | 3 | Nombre, descripción y lista exacta de columnas. |
| Campo | 14 | Nombre calificado y definición JSON íntegra: tipo lógico, significado, valores permitidos, unidades y referencias, cuando existen. |
| Relación | 2 | `TRANSACTION.customer_id` y `LOAN.customer_id` → `CUSTOMER.customer_id`, conservando el valor original de `foreign_key`. |
| Ausencia explícita | 4 | Cada frase original de `known_absences_for_exercise`. |

No se traducen ni reescriben las descripciones originales. Un campo ausente como
`CUSTOMER.credit_score` aparece con tipo documental `explicit_absence`, nunca
como una definición de campo existente. La frase sobre comisiones de conversión
conserva su carácter de información no especificada: no afirma que las comisiones
estén incluidas ni excluidas.

Cada documento incluye `source`, `source_version`, `source_sha256`,
`dataset_name`, `table`, `field`, `kind`, `json_pointer`, `renderer_version` y
`chunk_sha256`. `table` o `field` son `null` cuando no aplican, como en el resumen
del catálogo. La procedencia se puede localizar por ruta de archivo y JSON
Pointer. El SHA-256 de la fuente corresponde a los bytes exactos del archivo;
una edición de contenido o de formato constituye otra revisión de ingestión.

`data/corpus/bank_metadata.documents.jsonl` es un artefacto UTF-8 reproducible y
revisable, con una línea por documento. No contiene vectores, credenciales ni
registros bancarios. Los documentos son breves y se separan por significado,
sin cortes arbitrarios que separen valores permitidos o llaves de su campo.
Si el catálogo crece, habrá que revisar el tamaño de cada fragmento respecto
del contexto del modelo; esta versión no es un segmentador genérico.

## Modelo y persistencia

Se utiliza `langchain_ollama.OllamaEmbeddings` con el modelo local instalado
`bge-large:latest`. Antes del DDL se genera un embedding de prueba y se mide su
longitud real. En este equipo devolvió **1,024 componentes**, finitos y no nulos.
Cada lote documental y cada embedding de consulta se validan contra esa dimensión.
No se fuerza la dimensión ni se infiere únicamente del nombre del modelo.

Identidad observada del modelo:

```text
name: bge-large:latest
digest: b3d71c92805938e2c9d78e6f35e82d7cc1bd77e05b47dd2ab3016240f4021c15
dimension: 1024
```

Se crean exclusivamente dos tablas en el esquema `bank_knowledge`:

- `corpora`: identidad de la fuente, versión del renderizador, modelo, digest,
  dimensión y cantidad esperada de documentos.
- `documents`: identificador UUID, referencia al corpus, texto original,
  metadatos JSONB y `embedding vector(1024)` en la instalación verificada.

`sql/002-create-knowledge-corpus.sql` es una plantilla con dimensión dinámica;
el comando de ingestión la aplica después de medir el modelo. No debe ejecutarse
directamente con placeholders pendientes. No cambia la extensión `vector`,
Compose, las tablas ni los índices bancarios. Para estos 24 fragmentos la búsqueda
coseno es exacta; no se necesita un índice aproximado HNSW/IVFFlat.

La conexión reutiliza `scripts.bank_data.settings()`, `.env` y el puerto local
`127.0.0.1:5434`. La ingestión persiste los `Document` y sus embeddings con
Psycopg en una transacción. La recuperación usa el adaptador oficial
`langchain_postgres.PGVectorStore` sobre esas mismas columnas. Su conexión usa
SQLAlchemy y asyncpg, compatible con el bucle de eventos de Windows sin cambiar
la política global de asyncio. Las URL se construyen con `URL.create` para
tratar correctamente caracteres especiales de las credenciales.

Las versiones Python están fijadas en `uv.lock`; el digest del modelo también
queda en cada documento indexado. `latest` puede cambiar: para reproducir una
evaluación entre equipos se necesita el mismo digest, no solo el mismo nombre.
No se descarga ni sustituye un modelo automáticamente si no está instalado.

## Identificadores, repetición y cambios

Los UUID se derivan de forma determinista de la fuente, su hash, el JSON Pointer,
el renderizador y, para los registros almacenados, la identidad del modelo.
La repetición con la misma fuente y modelo verifica el corpus y responde
`sin cambios`: conserva 24 filas y no recalcula los embeddings documentales.
Siempre realiza la sonda breve para comprobar el modelo real.

Una revisión de fuente, renderizador o digest genera otro corpus y otros UUID.
Las búsquedas se filtran al corpus exacto del catálogo y modelo actuales; no
mezclan revisiones ni espacios vectoriales. Si cambia el catálogo o modelo,
hay que ejecutar `ingest` antes de consultar. Si la dimensión cambia, se rechaza
la operación sin adaptar ni eliminar la tabla anterior: requiere diseñar una
migración documental separada. Una carga parcial o contenido modificado bajo
una identidad existente se rechaza sin sobrescribirlo.

Un bloqueo transaccional coordina ingestiones concurrentes. DDL, manifiesto y
documentos se confirman juntos; cualquier fallo revierte la operación completa.
No hay comandos de borrado o reinicialización del corpus. El digest se comprueba
también al terminar la ingestión y la consulta para detectar cambios de modelo
durante su ejecución.

## Uso desde PowerShell

Desde la raíz Git, con PostgreSQL y Ollama iniciados:

```powershell
uv sync --locked --inexact
ollama list
# Solo si no esta instalado en ese equipo:
# ollama pull bge-large
uv run --locked --inexact python -m scripts.knowledge_corpus build
uv run --locked --inexact python -m scripts.knowledge_corpus probe
uv run --locked --inexact python -m scripts.knowledge_corpus ingest
uv run --locked --inexact python -m scripts.knowledge_corpus search "Que significa CUSTOMER.annual_income y en que unidad se expresa?" --k 5
uv run --locked --inexact python -m scripts.knowledge_corpus search "Does CUSTOMER have a credit_score field?" --k 5
uv run --locked --inexact python -m scripts.knowledge_corpus evaluate
```

`build` no requiere base de datos ni Ollama. `probe` solo consulta Ollama.
`ingest` crea el almacenamiento documental y devuelve el número de documentos,
UUID del corpus e identidad real del modelo. `search` y `evaluate` son consultas
de recuperación y no alteran registros. Las variables opcionales de `.env` son:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=bge-large:latest
```

No reemplaces un `.env` ya configurado por `.env.example`: los valores anteriores
siguen funcionando y estas dos opciones tienen los defaults indicados.

La función importable es:

```python
from scripts.knowledge_corpus import retrieve
fragments = retrieve("What does LOAN.dpd mean?", k=5)
```

Para varias preguntas en un proceso se puede reutilizar `RetrievalSession`, que
cierra el pool al salir del contexto. Cada resultado incluye texto, fuente,
versión, tabla/campo, JSON Pointer, `cosine_distance` y `cosine_similarity`.
Se usa `cosine_similarity = 1 - cosine_distance`: mayor similitud es más cercano;
menor distancia es más cercano. La similitud coseno suele estar entre -1 y 1
con posibles diferencias numéricas mínimas; **no es una probabilidad de verdad**.

## Evaluación y límites

`tests/fixtures/retrieval_cases.json` contiene siete preguntas sobre ingreso
anual, riesgo, mora, ambas relaciones y ausencia de `credit_score`, incluyendo
una paráfrasis en inglés sin el nombre del campo. La evaluación exige recuperar
los JSON Pointers esperados entre los primeros cinco resultados. En la ejecución
documentada las siete recuperaron la evidencia esperada, todas en primer lugar.
El reporte [retrieval-evaluation.json](retrieval-evaluation.json) conserva las
puntuaciones reales; pequeñas diferencias entre hardware y ejecuciones son normales.
Este conjunto pequeño no demuestra calidad general, cobertura lingüística ni
robustez ante preguntas arbitrarias. No se traduce la pregunta automáticamente.

```powershell
# Pruebas locales sin servicios externos (integracion y recuperacion omitidas):
uv run --locked --inexact python -m pytest -q
# Pruebas originales y almacenamiento PostgreSQL aislado, sin Ollama:
uv run --locked --inexact python -m pytest -q --run-db-tests
# Todas, con Ollama iniciado y corpus previamente ingerido:
uv run --locked --inexact python -m pytest -q --run-db-tests --run-retrieval-tests
```

Los 56 tests anteriores se conservan. Los nuevos verifican fidelidad al JSON,
metadatos, UUID, dimensión, aislamiento entre modelos, repetición, rollback y
recuperación real. Solo las pruebas de contratos de almacenamiento usan vectores
de prueba; las siete consultas semánticas llaman al modelo Ollama real. Las
pruebas de escritura viven en esquemas aislados y sus transacciones se revierten;
las pruebas semánticas solo leen el corpus preparado.

Un resultado cercano **no garantiza que una afirmación sea verdadera**, que el
fragmento responda la pregunta completa ni que el catálogo esté actualizado.
La búsqueda devuelve los vecinos más cercanos incluso para preguntas sin
respuesta: no implementa abstención ni un umbral de veracidad. Una ausencia se
puede afirmar aquí porque existe una frase explícita en el catálogo; no encontrar
otro campo no demuestra por sí solo que ese campo no exista en todos los sistemas.

La similitud **no autoriza acceso a información restringida**. Este MVP usa una
conexión de desarrollo con el usuario existente y no implementa autenticación de
usuarios finales, permisos por documento ni aislamiento entre organizaciones.
Esos controles tendrían que aplicarse en la base y en la aplicación antes de
tratar información restringida; ni un prompt ni un resultado de recuperación
pueden sustituirlos. El alcance actual es exclusivamente el catálogo sintético.

## Referencias oficiales

- [OllamaEmbeddings en LangChain](https://docs.langchain.com/oss/python/integrations/embeddings/ollama).
- [PGVectorStore sobre tablas existentes](https://docs.langchain.com/oss/python/integrations/vectorstores/pgvectorstore).
- [Modelo bge-large en Ollama](https://ollama.com/library/bge-large).
