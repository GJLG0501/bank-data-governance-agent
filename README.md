# Bank Data Governance Agent

MVP educativo para Data Steward y Data Analyst, exclusivamente con datos bancarios
sintéticos. Incluye PostgreSQL 17 con pgvector y un conjunto relacional reproducible
de 1,000 clientes, 5,000 transacciones y 500 préstamos, además de un corpus del
catálogo con embeddings locales, recuperación semántica y un primer agente Data
Steward conversacional en terminal. No implementa herramientas SQL, acceso a
registros individuales, dashboards ni interfaces web.

## Requisitos y ubicación

- Windows con PowerShell, Docker Desktop iniciado en modo de contenedores Linux y Docker Compose v2 o posterior.
- `uv`; `.python-version` fija Python 3.13.5 para reproducir el ejercicio. `uv` puede instalarlo si hace falta. PostgreSQL funciona de forma independiente en Docker.
- Puerto local `5434` disponible.

Ejecuta todos los comandos desde la raíz Git `bank-data-governance-agent`, donde
están este README, `pyproject.toml` y `compose.yaml`. Si estás en la carpeta
superior `Agente de IA Banamex`, entra primero con:

```powershell
Set-Location .\bank-data-governance-agent
```

El proyecto Python ya está inicializado con `uv`. Usa `psycopg[binary]` para
PostgreSQL, `python-dotenv` para la configuración local y `pytest` para pruebas.
El corpus utiliza LangChain, OllamaEmbeddings y PGVectorStore.
El agente reutiliza esas dependencias con ChatOllama y tool calling nativo.
`uv.lock` fija las versiones resueltas para el equipo.
Para preparar o sincronizar su entorno conservando paquetes que ya existan en
un entorno virtual local:

```powershell
uv sync --locked --inexact
```

## Configuración local

Crea `.env` una sola vez, si todavía no existe, y edítalo antes del primer inicio:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
code .env
```

`POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` definen el usuario, la
contraseña y la base de desarrollo. Los valores de `.env.example` son ficticios;
cambia la contraseña local. `.env` y `.venv` están excluidos de Git.
Las variables con estos nombres definidas en PowerShell tienen prioridad sobre
`.env`. No compartas la salida de `docker compose config` sin `--quiet`, ya que
puede mostrar la contraseña resuelta.

## Levantar PostgreSQL

```powershell
docker compose config --quiet
docker compose up -d --wait --wait-timeout 120 bank-postgres
```

La primera ejecución descarga la imagen
`pgvector/pgvector:0.8.7-pg17-bookworm`, mantenida por el proyecto pgvector, y crea:

| Recurso | Nombre o valor |
| --- | --- |
| Proyecto Compose | `bank-data-governance-agent-dev` |
| Contenedor | `bank-data-governance-agent-dev-bank-postgres-1` |
| Volumen persistente | `bank-data-governance-agent-dev_bank-postgres-data` |
| Red | `bank-data-governance-agent-dev_bank-postgres-network` |
| Conexión desde Windows | `127.0.0.1:5434` |
| Puerto dentro del contenedor | `5432` |

El volumen se monta en `/var/lib/postgresql/data`, la ruta de datos de PostgreSQL
17. El script SQL se monta en modo de solo lectura y activa `vector` en la base
indicada por `POSTGRES_DB` durante la primera inicialización del volumen vacío.
El healthcheck usa `pg_isready` por TCP; `--wait` espera a que esté saludable.

Usa los nombres definidos aquí sin sobrescribir el nombre del proyecto con `-p`
o `COMPOSE_PROJECT_NAME`. No se utilizan volúmenes ni redes externos.
Si el puerto `5434` está ocupado, revisa qué servicio lo utiliza antes de iniciar;
no detengas contenedores de otros proyectos.

## Verificar

Estado del servicio y disponibilidad de PostgreSQL:

```powershell
docker compose ps
docker compose exec bank-postgres sh -c 'pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Debe aparecer `healthy` y `accepting connections`. Consulta la versión de
PostgreSQL y la extensión habilitada, utilizando las variables dentro del
contenedor para no escribir la contraseña en los comandos:

```powershell
@'
SELECT current_database(), current_user, current_setting('server_version') AS postgres_version;
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
'@ | docker compose exec -T bank-postgres sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

La versión del servidor debe comenzar con `17` y la segunda consulta debe devolver
una fila con `vector` y versión `0.8.7`. Estas consultas no crean tablas ni datos.
Puedes comprobar también el puerto publicado desde Windows:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 5434
```

Para diagnosticar un fallo de arranque:

```powershell
docker compose logs --tail 100 bank-postgres
```

## Detener y volver a iniciar

Detén únicamente este servicio, conservando contenedor y volumen:

```powershell
docker compose stop bank-postgres
```

Para iniciarlo de nuevo:

```powershell
docker compose up -d --wait --wait-timeout 120 bank-postgres
```

Si necesitas retirar el contenedor y la red de este proyecto, puedes usar
`docker compose down` **sin opciones de eliminación de volúmenes**. El volumen
persistente se conserva y se reutiliza en el siguiente inicio. No elimines
volúmenes ni ejecutes comandos de limpieza global de Docker.

Los scripts de inicialización y las variables `POSTGRES_*` solo configuran una
instancia nueva con volumen vacío. Cambiar `.env` después del primer inicio no
cambia usuarios, contraseñas ni bases existentes. Si falta `vector` en un volumen
ya inicializado de este proyecto, puedes aplicar únicamente el script idempotente:

```powershell
docker compose exec -T bank-postgres sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/001-enable-vector.sql'
```

Esta configuración y su usuario administrador son exclusivamente para desarrollo
local. El agente de terminal solo interpreta documentos del catálogo; herramientas
SQL, acceso a registros individuales e interfaces web quedan fuera del alcance.

## Crear y poblar las tablas sintéticas

La fuente de verdad es `data/source/bank_metadata.json`. Es una copia idéntica
del original entregado como `bank_metadata_simple (1).json`, que se conserva sin
modificaciones. Las tablas mantienen los nombres y campos del catálogo:

| Tabla | Clave primaria | Relación | Filas iniciales |
| --- | --- | --- | --- |
| `"CUSTOMER"` | `customer_id` | Cliente padre | 1,000 |
| `"TRANSACTION"` | `transaction_id` | `customer_id` → `"CUSTOMER".customer_id` | 5,000 |
| `"LOAN"` | `loan_id` | `customer_id` → `"CUSTOMER".customer_id` | 500 |

Se crean en `public`. Los nombres de tablas llevan comillas dobles en SQL para
conservar sus mayúsculas. La muestra tiene cinco transacciones por cliente y
500 prestatarios distintos. Todos los identificadores son ficticios (`SYN-*`)
y no se generan datos personales.

Desde la raíz del repositorio, con `.env` preparado y Docker iniciado:

```powershell
uv sync --locked --inexact
docker compose up -d --wait --wait-timeout 120 bank-postgres
uv run --locked --inexact python -m scripts.bank_data migrate
uv run --locked --inexact python -m scripts.bank_data generate
uv run --locked --inexact python -m scripts.bank_data verify
```

`migrate` aplica `sql/001-create-bank-tables.sql` en una transacción y comprueba
que las columnas y restricciones coincidan con el catálogo. Se puede repetir
sin borrar ni adaptar tablas existentes; si hay diferencias, falla de forma
segura. La migración se ejecuta explícitamente sobre el volumen existente:
no depende de reiniciar Docker ni cambia la configuración de `vector`.

`generate` utiliza la semilla fija `20261020`. Si las tres tablas están vacías,
carga toda la muestra en una transacción. Si ya contienen la misma muestra,
responde `sin cambios` y no duplica registros. Si encuentra una carga parcial,
filas adicionales o valores diferentes, se cancela sin insertar ni reemplazar.
Una semilla distinta también se rechaza cuando ya hay datos de otra semilla.

`verify` valida cantidades, tipos, nulos, categorías, rangos, claves, relaciones
y coherencia de los supuestos. Compara todas las filas con la muestra regenerada
y muestra cantidades, semilla y SHA-256. El resultado esperado contiene:

```json
{
  "counts": {"CUSTOMER": 1000, "TRANSACTION": 5000, "LOAN": 500},
  "seed": 20261020,
  "sha256": "30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5"
}
```

Para comprobar la repetición segura:

```powershell
uv run --locked --inexact python -m scripts.bank_data generate
uv run --locked --inexact python -m scripts.bank_data verify
```

Los comandos Python leen `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` de
`.env`, con prioridad para las variables del entorno. La conexión está limitada
a `127.0.0.1:5434`, el puerto exclusivo de este proyecto; no acepta destinos
remotos ni usa credenciales en argumentos. Los comandos fallidos devuelven código
de salida distinto de cero. Los mensajes de error de PostgreSQL no muestran DSN
ni contraseñas.

Los rangos y distribuciones están en
[docs/synthetic-data.md](docs/synthetic-data.md). Son **supuestos didácticos
inventados, no reglas reales de Banamex**. Allí se explican las unidades,
nulabilidad, distribución por segmento, tasas, mora, controles y una opción
de reinicialización con doble confirmación explícita. No necesitas esa opción
para repetir la generación. No la ejecutes para resolver conflictos sin antes
revisar los datos existentes.

## Pruebas automatizadas

Pruebas sin acceso a PostgreSQL (las de integración aparecen omitidas):

```powershell
uv run --locked --inexact python -m pytest -q
```

Para ejecutar también las pruebas de integración contra el PostgreSQL local:

```powershell
uv run --locked --inexact python -m pytest -q --run-db-tests
```

Las pruebas de integración crean esquemas aislados con nombres únicos y siempre
revierten su transacción completa, incluso si hay un fallo. No reemplazan datos
de `public`. Comprueban restricciones SQL, migración idempotente, carga atómica,
repetición sin duplicados, referencias y rechazo de datos preexistentes distintos.
Las pruebas sin base verifican además la huella fija y que otra semilla cambie
la muestra.

Si se actualiza intencionalmente el catálogo o los supuestos, regenera el SQL
local y revisa los cambios antes de aplicarlos:

```powershell
uv run --locked --inexact python -m scripts.bank_data render-sql
```

Este comando solo escribe el archivo SQL local; no conecta a PostgreSQL. Una
modificación de tablas ya existentes requiere una migración posterior revisada;
`migrate` nunca adapta ni destruye automáticamente un esquema incompatible.

## Corpus documental y búsqueda semántica

El corpus procede exclusivamente de `data/source/bank_metadata.json`. Contiene
24 documentos: un resumen, tres tablas, 14 campos, dos relaciones y cuatro
ausencias explícitas. Conserva los textos originales, unidades, categorías y
procedencia por tabla/campo, versión y JSON Pointer. No indexa filas bancarias
ni los supuestos del generador.

Se almacena por separado en `bank_knowledge.corpora` y `bank_knowledge.documents`.
La dimensión se mide antes de crear la columna vectorial. La instalación
verificada tiene `bge-large:latest` y devuelve 1,024 componentes.

Con Ollama iniciado, ejecuta desde esta carpeta:

```powershell
uv sync --locked --inexact
ollama list
uv run --locked --inexact python -m scripts.knowledge_corpus build
uv run --locked --inexact python -m scripts.knowledge_corpus probe
uv run --locked --inexact python -m scripts.knowledge_corpus ingest
uv run --locked --inexact python -m scripts.knowledge_corpus search "What does CUSTOMER.annual_income mean?" --k 5
uv run --locked --inexact python -m scripts.knowledge_corpus search "Does CUSTOMER have a credit_score field?" --k 5
uv run --locked --inexact python -m scripts.knowledge_corpus evaluate
```

Si falta el modelo en otro equipo, instálalo explícitamente con
`ollama pull bge-large`. No se sustituye automáticamente por un modelo generativo.
Las opciones `OLLAMA_BASE_URL` y `OLLAMA_EMBEDDING_MODEL` tienen los defaults de
`.env.example`; no necesitas reemplazar tu `.env` existente.

Repetir `ingest` responde `sin cambios`, sin duplicar documentos. La identidad
incluye el hash del catálogo, la versión del renderizador y el digest real del
modelo. Las consultas solo comparan contra esa misma revisión y espacio vectorial.
`search` devuelve fragmentos, procedencia, distancia y similitud coseno; no llama
a un LLM generativo ni construye respuestas o SQL a partir de la pregunta.

Para ejecutar también las pruebas reales de recuperación, tras ingerir el corpus:

```powershell
uv run --locked --inexact python -m pytest -q --run-db-tests --run-retrieval-tests
```

**La cercanía semántica no garantiza veracidad ni autoriza acceso a información
restringida.** Este MVP no incorpora permisos por documento ni controles basados
en prompts. Los supuestos y límites están detallados en
[docs/knowledge-corpus.md](docs/knowledge-corpus.md), con resultados observados en
[docs/retrieval-evaluation.json](docs/retrieval-evaluation.json).

## Agente Data Steward en terminal

El agente usa `llama3.1:latest` local y una única herramienta,
`search_data_catalog`, que reutiliza el recuperador existente. No crea otra
colección ni reingiere el corpus. Responde en español y adjunta referencias
construidas desde los UUID, fuentes y JSON Pointers realmente recuperados.

Con PostgreSQL, Ollama y el corpus anterior ya preparados:

```powershell
uv sync --locked --inexact
ollama list
uv run --locked --inexact python -m scripts.data_steward_agent chat
```

Escribe preguntas consecutivas y `salir` para terminar. El historial conserva
cuatro turnos en memoria y no se guarda entre sesiones. Para una sola pregunta:

```powershell
uv run --locked --inexact python -m scripts.data_steward_agent ask "Que significa CUSTOMER.annual_income?"
uv run --locked --inexact python -m scripts.data_steward_agent ask "Existe CUSTOMER.credit_score?" --json
uv run --locked --inexact python -m scripts.data_steward_agent ask "Que significa LOAN.dpd?" --debug
```

`--debug` muestra eventos breves por `stderr`: herramienta utilizada, documentos
recuperados y referencias citadas. `--json` permite revisar evidencia y estados
de respuesta. No se guardan conversaciones ni logs; el trazado remoto del agente
está deshabilitado. Los defaults opcionales son `OLLAMA_CHAT_MODEL=llama3.1:latest`
y `OLLAMA_CHAT_TIMEOUT=180`; no reemplaces tu `.env` existente.

El modelo instalado se verificó con tool calling real. No se agrega LangGraph ni
se interpretan acciones ReAct como texto. Una ausencia explícita (`credit_score`)
se distingue de una pregunta sin evidencia (`favorite_color`). Las solicitudes
de registros bancarios individuales indican que esa capacidad no está disponible;
esto no representa un sistema de permisos.

Pruebas con mocks y suite completa con servicios reales:

```powershell
uv run --locked --inexact python -m pytest -q tests/test_data_steward_agent.py
uv run --locked --inexact python -m pytest -q --run-db-tests --run-retrieval-tests --run-agent-tests
```

La arquitectura, errores, ejemplos reales y limitaciones están en
[docs/data-steward-agent.md](docs/data-steward-agent.md). Las métricas y huellas de
conservación están en [docs/agent-validation.json](docs/agent-validation.json).
La existencia de referencias no garantiza que la interpretación del LLM sea
correcta ni concede acceso a información restringida. No hay herramientas SQL
ni políticas oficiales de Banamex incorporadas.

## Referencias oficiales

- [Imagen Docker y activación de pgvector](https://github.com/pgvector/pgvector#docker).
- [Inicialización y persistencia de la imagen PostgreSQL](https://hub.docker.com/_/postgres).
- [Variables de entorno en Docker Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).
- [Restricciones de integridad en PostgreSQL 17](https://www.postgresql.org/docs/17/ddl-constraints.html).
- [Transacciones de Psycopg 3](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
