# Publicación del RAG bancario en PostgreSQL principal

Fecha de ejecución: 22 de octubre de 2026 (America/Mexico_City). Estado: **publicado y verificado**. El [informe de validación](new-bank-model-rag-publication-validation.json) conserva conteos, hashes por tabla y resultados de pruebas. Esta publicación afecta únicamente al esquema `bank_knowledge_new_bank` de la base de desarrollo.

## Preflight y respaldo

Antes de escribir se comprobó el contenedor `bank-data-governance-agent-dev-bank-postgres-1`, su ID `56bf7ea7a9f9f9d8a3c03d12162d973855f6299648e54b2c79eea931977a27a2`, el volumen `bank-data-governance-agent-dev_bank-postgres-data`, estado healthy y base `bank_governance_synthetic_dev` en `127.0.0.1:5434`. El esquema RAG nuevo estaba ausente. Las siete tablas `dim`/`cfg`, el dataset y las cinco tablas antiguas coincidían con las huellas de la publicación anterior. Se verificaron el manifiesto de 82 documentos, los hashes de las fuentes, las referencias por afirmación, los IDs deterministas y el paquete de vectores validado en aislamiento. El modelo local `bge-large:latest` conservaba digest `b3d71c92805938e2c9d78e6f35e82d7cc1bd77e05b47dd2ab3016240f4021c15` y dimensión 1024.

Se creó **un respaldo completo actualizado**, formato custom de `pg_dump`, antes de publicar:

- Ruta local excluida de Git: `.local-validation/rag_publication_de16f528d08e4c40b98e2264628f270c/database.dump`.
- Tamaño: 3,276,477 bytes.
- SHA-256: `b54bcb36ca8e204eb6d30705804b1c7f02aa566ace1d26de42128327e04034a3`.
- `pg_dump` y `pg_restore --list`: códigos de salida 0. Se copió también el archivo local al contenedor aislado y su listado coincidió exactamente con el del archivo original. Incluye CUSTOMER, TRANSACTION, LOAN, el corpus anterior, tablas `dim`/`cfg` y la extensión vector.

El archivo está fuera del volumen PostgreSQL activo. No se restauró sobre la base principal ni se registraron contraseñas. No se reutilizó el respaldo de una etapa anterior.

## Estructura y publicación

Se aplicó la estructura ya probada `sql/rag/001_new_bank_knowledge.sql`: esquema `bank_knowledge_new_bank`, tablas `corpora` y `documents`, claves, FK, restricciones de alcance y checksums de contenido/vector. La migración verifica compatibilidad estructural en vez de confiar solo en existencia. La primera creación del esquema y la ingestión de los 82 documentos se ejecutaron dentro de **una misma transacción**; un error revierte ambas. Los embeddings se tomaron del paquete local validado. No hubo llamadas al LLM ni generación de embeddings durante la transacción.

Identidad publicada:

| Elemento | Valor |
| --- | --- |
| Modelo | `new_bank_2026` |
| Versión del catálogo | `1.0.0` |
| Corpus ID | `8dbc359e-53db-5df8-bbec-418b1add756e` |
| Documentos / IDs distintos | 82 / 82 |
| Dimensión | 1024 |
| SHA-256 agregado de vectores | `08b5555ffede84edfc6b4a399f83c4c4eb1705ed997fc5b6d56829a5798e57d9` |

El manifiesto, cada documento, sus metadatos y cada checksum binario coincidieron con el entorno aislado. La primera ingestión respondió `indexado`; la segunda, `sin cambios`. El contenido y los vectores fueron idénticos antes y después de repetirla. Un manifiesto o conjunto parcial/incompatible se rechaza; las pruebas de ese comportamiento permanecen en el ensayo aislado.

El primer comando de publicación terminó antes de ejecutar SQL porque la comprobación del encabezado de la migración no contemplaba su comentario inicial. Se ajustó ese control y se volvió a verificar el preflight y el mismo respaldo vigente. La transacción posterior completó la publicación. No hubo un estado parcial en PostgreSQL principal.

## Recuperación y aislamiento

Se añadió al `CatalogRetriever` la selección explícita `published=True`. Esa ruta exige `state=None`, usa el contenedor y base activos fijados y abre transacciones **READ ONLY**; filtra cada búsqueda por `model_id` y `corpus_id`. La ruta aislada sigue disponible y no se modificó `search_data_catalog` ni el agente LangChain. Las 30 preguntas de evaluación aprobaron contra el corpus publicado (MRR 0.9167), incluidas las relaciones, signos, fechas y ambigüedades. Las siete búsquedas reales del corpus antiguo aprobaron después de publicar. Los resultados antiguos siguen limitados a `bank_knowledge`; las búsquedas nuevas leen `bank_knowledge_new_bank` con alcance explícito en el SQL. Los dos espacios de documentos no se mezclaron.

## Conservación y pruebas

| Datos de la base principal | Antes | Después |
| --- | ---: | ---: |
| CUSTOMER | 1,000 | 1,000 |
| TRANSACTION | 5,000 | 5,000 |
| LOAN | 500 | 500 |
| Cinco tablas originales del nuevo modelo | 350,013 | 350,013 |
| Dos referencias auxiliares | 20,009 | 20,009 |
| Corpus anterior | 24 | 24 |
| Corpus nuevo | 0 | 82 |

El dataset bancario conserva SHA-256 `a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b`. Las huellas por tabla, las 100,000 conciliaciones y los hashes de documentos, metadatos y vectores antiguos coinciden antes/después. Se recalcularon las huellas históricas de los 6,500 registros anteriores y 24 documentos. El informe JSON registra los valores individuales.

Pruebas ejecutadas para esta publicación: 35 unitarias del nuevo RAG, 30 consultas semánticas publicadas, siete consultas reales del RAG antiguo, nueve pruebas reales del agente Data Steward anterior y 37 comprobaciones bancarias de solo lectura y estáticas: **118 aprobadas, sin fallos ni omisiones**. Las 169 pruebas reportadas en el ensayo aislado son una validación anterior y no se suman a esta cifra.

Archivos de esta etapa: nuevo `scripts/new_bank_rag_publication.py`, nuevo `tests/test_new_bank_rag_published_readonly.py`, ajuste de lectura publicada en `scripts/new_bank_rag.py`, este documento y `docs/new-bank-model-rag-publication-validation.json`. Los SQL originales, las migraciones bancarias, los datos y el agente no se modificaron. El respaldo y los resultados JUnit permanecen en `.local-validation/`.

## Riesgos y siguiente integración

Las 30 preguntas son una evaluación finita; la similitud vectorial por sí sola no valida respuestas arbitrarias. La abstención y selección por grupo requieren ampliar paráfrasis y casos adversos antes de exponer el catálogo a usuarios finales. El backend publicado depende hoy del contenedor de desarrollo fijado y su propietario; antes de otro entorno deben diseñarse credenciales y permisos de lectura específicos. El respaldo se verificó como archivo y listado completo; esta etapa no incluyó un ensayo de restauración de este respaldo nuevo.

Para integrar Data Steward en una etapa posterior, conviene un adaptador de recuperación que requiera `model_id` y `corpus_id`, seleccione `new_bank_2026` de forma predeterminada y permita el modelo anterior solo mediante selección técnica explícita. Debe entregar texto, puntuación, referencias y clasificación por afirmación; el agente tendrá que citar esas evidencias y reconocer ausencias. La elección del proveedor LLM debe mantenerse independiente de la selección del corpus. Esta etapa no cambia el agente ni implementa Data Analyst, Data Quality, coordinador, LangGraph o MCP.
