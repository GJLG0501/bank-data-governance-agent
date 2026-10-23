# Validación real de respaldo, restauración y migraciones

Este reporte conserva el estado de la etapa de esquema vacío. La carga completa
autorizada posteriormente, sus verificaciones y el estado más reciente del
entorno aislado se documentan en [carga reproducible](new-bank-model-data-load.md).
La publicación autorizada posterior en la base principal tiene su propio
[reporte y respaldo vigente](new-bank-model-publication.md); este documento
conserva la evidencia de la etapa de esquema vacío.

Fecha de revisión: 21 de octubre de 2026, America/Mexico_City. Resultado: **89 pruebas aprobadas: 24 estáticas y 65 sobre PostgreSQL real**. No se aplicó ninguna migración a la base activa ni se cargó el dataset nuevo.

## Identidad y alcance comprobados

Se reanudó la tarea después de la confirmación del usuario de que la interrupción anterior provino de una pausa manual de Docker. Se volvió a comprobar el estado antes de respaldar.

| Recurso activo protegido | Valor comprobado |
| --- | --- |
| Contenedor | `bank-data-governance-agent-dev-bank-postgres-1` |
| ID completo | `56bf7ea7a9f9f9d8a3c03d12162d973855f6299648e54b2c79eea931977a27a2` |
| Base | `bank_governance_synthetic_dev` |
| Puerto | `127.0.0.1:5434` → `5432/tcp` |
| Volumen | `bank-data-governance-agent-dev_bank-postgres-data` |
| PostgreSQL / pgvector | 17.11 / 0.8.7 |
| Usuario/propietario de la base | `bank_governance_dev` |
| Estado | Healthy; CONNECT, TEMP y CREATE disponibles; sin otras transacciones de cliente abiertas al iniciar el respaldo. |

El volumen original tenía un solo usuario: el contenedor original. Se confirmó ausencia de `dim` y `cfg` en la base activa, tanto antes como después del ensayo. No se ejecutaron comandos para iniciar, detener, recrear o reemplazar el servicio activo.

## Respaldo realizado

Directorio local: `.local-validation/9065d649f8d74222bd04dc58a0e54835/`, dentro de la raíz del proyecto. Se agregó `.local-validation/` a `.gitignore` **antes** de escribir archivos y se verificó la exclusión mediante `git check-ignore`. El respaldo no se añadió a Git ni se publicó en un servicio remoto.

| Propiedad | Resultado |
| --- | --- |
| Archivo | `.local-validation/9065d649f8d74222bd04dc58a0e54835/database.dump` |
| Formato | Custom de PostgreSQL; base completa, sin filtros de tablas/esquemas. |
| Tamaño | 207,336 bytes. |
| SHA-256 | `6d361a97ca2a2f49388ded5773282aff7e0d5b60c187db96f762805af64a3d3d` |
| Salida de pg_dump | Código 0. |
| pg_restore --list | Código 0; datos de CUSTOMER, TRANSACTION, LOAN, corpora, documents y definición de extensión vector presentes. |
| Restauración real | Código 0; copia **del archivo local** restaurada con `--exit-on-error --single-transaction`. |

Se utilizó salida de archivo dentro de `/tmp` del contenedor original y copia binaria con `docker cp`; el dump no atravesó un pipeline de texto de PowerShell. Se verificó nuevamente el hash local antes de copiarlo al contenedor de ensayo. `pg_dump` y los snapshots del origen se ejecutaron con transacciones de lectura/default READ ONLY. El origen no recibió DDL/DML de aplicación.

También se guardaron el listado del archivo y los roles mediante `pg_dumpall --roles-only --no-role-passwords`. No se mostraron variables de entorno, contraseñas, hashes de contraseñas o DSN. Los roles del origen no se modificaron. El rol propietario necesario ya existe en el contenedor nuevo porque se creó como su usuario inicial; no fue necesario importar roles ni relajar permisos durante la restauración.

El respaldo tiene una copia local fuera del volumen original, pero sigue en el mismo equipo. No se ha validado una copia en otro equipo/medio, recuperación completa del clúster, PITR o un RTO garantizado.

## Aislamiento utilizado

| Recurso de pruebas | Valor |
| --- | --- |
| Contenedor | `nbm-pg17-validation-9065d649f8d74222bd04dc58a0e54835` |
| ID | `30f2f67bde407bcba30f26f4057df6edd29ed54aabef17c0c3ea9af7b1e92079` |
| Base principal | `nbm_validation_9065d649f8d74222bd04dc58a0e54835` |
| Volumen propio | `nbm-validation-9065d649f8d74222bd04dc58a0e54835` |
| Imagen | Mismo ID de imagen que el contenedor original, obtenido mediante inspección; sin descargar otra imagen. |
| Versión restaurada | PostgreSQL 17.11 y pgvector 0.8.7. |
| Red / puertos publicados | `none` / ninguno. |
| Montajes | Solo su volumen propio de datos; ningún montaje del volumen activo. |

El arnés verifica nombre, ID, etiqueta del ensayo, base, montajes, red y puertos antes de permitir una escritura. Rechaza el contenedor/base activos y cualquier destino que no corresponda al manifiesto del ensayo. Se probó explícitamente ese rechazo.

El servidor de ensayo usa autenticación local trust y un usuario administrador únicamente dentro del contenedor sin red ni puertos publicados; no es una configuración para producción ni una modificación de credenciales del origen. El acceso de las pruebas es por `docker exec` y socket local.

## Restauración y conservación del modelo anterior

Los snapshots de `legacy_snapshot.sql` se compararon por su sección `protected`, excluyendo el nombre de base del contexto. Coinciden conteos, hashes de todas las columnas de las filas —incluido `embedding`—, firmas de columnas/defaults, restricciones, índices, extensión y dimensiones vectoriales.

| Objeto | Activa antes | Restaurada | Activa después | Restaurada después de migraciones/pruebas |
| --- | ---: | ---: | ---: | ---: |
| CUSTOMER | 1,000 | 1,000 | 1,000 | 1,000 |
| TRANSACTION | 5,000 | 5,000 | 5,000 | 5,000 |
| LOAN | 500 | 500 | 500 | 500 |
| bank_knowledge.corpora | 1 | 1 | 1 | 1 |
| bank_knowledge.documents | 24 | 24 | 24 | 24 |

Los 24 embeddings conservan dimensión 1,024, sin NULL. Además se reprodujeron los métodos de huella histórica de `docs/agent-validation.json`, sin regenerar la muestra ni los embeddings:

| Huella | Antes / restaurada / después |
| --- | --- |
| Datos bancarios | `30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5` |
| Documentos, metadatos y embeddings | `63a6313e870be8268ce7bd85ee0eb8401ebbece4bb6f529b211c4796a6db0847` |

Para los datos se usa JSON ordenado por PK y claves, con separadores compactos y tipos FLOAT restituidos como float de Python, equivalente a `scripts.bank_data.fingerprint`. Para documentos se usa `SELECT id,corpus_id,content,metadata,embedding::text ORDER BY id`, serialización JSON de la matriz con claves ordenadas/separadores compactos y UUID como texto. Las dos huellas coinciden exactamente con la referencia histórica. Las huellas SQL del snapshot son otro método y se comparan solo entre snapshots del mismo formato.

## Migraciones reales

Se ejecutaron únicamente en la base aislada principal, después de verificar la restauración.

| Migración | SHA-256 del archivo probado | Resultado |
| --- | --- | --- |
| 001 | `27d7e522cc7c166f3577831e17f9bd22ce9d1c8b8fe2e69bc001b896d1f99c4a` | Código 0; cinco tablas y 42 columnas con tipos/longitudes/defaults/nulabilidad originales. |
| 002 | `11fb5d9e104b872a16c1e25c23aef8fb3ac9a74fa72cf40f57eb04b1caa29db8` | Código 0; auxiliares e integridad adicional correctos. |

Resultado final: siete tablas, 54 columnas contando auxiliares, cuatro PK, cinco UNIQUE, dieciocho CHECK y seis FK; nueve índices que respaldan PK/UNIQUE. Todas las restricciones están validadas y las tablas pertenecen al propietario esperado. `dim.dim_txn` conserva sus cinco columnas y sigue sin PK, UNIQUE o FK.

La repetición de 001 y 002 conserva exactamente la firma completa del modelo y los datos/embeddings restaurados. **Las siete tablas nuevas de la base principal del ensayo contienen cero filas al finalizar.** No se ejecutó ninguno de los SQL upstream ni el generador del nuevo dataset.

## Pruebas ejecutadas y problema corregido

| Grupo | Cantidad | Resultado |
| --- | ---: | --- |
| Estáticas existentes del paquete de integración | 24 | Aprobadas; hashes originales, fidelidad de DDL, manifiesto, alcance de escritura y ausencia de operaciones destructivas. |
| Runtime: restauración y separación de recursos | 2 | Aprobadas. |
| Runtime: estructura 001/002, repetición, fixture válido y cuatro productos | 8 | Aprobadas. |
| Runtime: NOT NULL en todas las columnas de hechos | 19 | Rechazo con SQLSTATE 23502. |
| Runtime: claves duplicadas | 7 | Rechazo con SQLSTATE 23505. |
| Runtime: huérfanos y dueño de cuenta incorrecto | 6 | Rechazo con SQLSTATE 23503. |
| Runtime: fechas, importes, NaN, crecimiento, dominio y catálogo | 14 | Rechazo con SQLSTATE 23514. |
| Runtime: estructuras incompatibles / adopción de datos | 7 | Rechazo con SQLSTATE P0001 y firma previa conservada. |
| Runtime: bloqueo de escritura al origen y conservación final | 2 | Aprobadas. |
| **Total** | **89** | **24 estáticas + 65 runtime; ejecución final sin fallos ni omisiones.** |

Los cuatro productos se probaron con fixtures pequeños para febrero y marzo: tasas diferenciadas, signos económicos, redondeo y conciliación exacta. Se comprobó que la nulabilidad original de atributos de cliente/producto, la duplicación permitida en `dim_txn` y la anomalía cronológica del cliente 3552 no se corrigen o rechazan silenciosamente.

Casos de incompatibilidad: tipo de columna incorrecto, PK base faltante, índice ajeno, CHECK NOT VALID, tabla base con datos antes del refuerzo, propietario incorrecto y 002 sin preparación base. Se usaron bases auxiliares nuevas dentro del mismo contenedor de ensayo; no se cambiaron las estructuras incompatibles para hacerlas pasar.

La primera ejecución encontró un defecto del **arnés**, no de los SQL: un SELECT booleano devolvía `t` y el test intentaba parsearlo como JSON. Se corrigió mediante `to_jsonb(...)`, se hicieron únicos los nombres de bases de casos para permitir repetir sin borrar y se ejecutó la suite completa otra vez: **65/65 aprobadas**. No se modificaron el renderer de diseño ni las migraciones 001/002 para conseguir el resultado.

Las filas de fixtures de restricciones/finanzas siempre viven dentro de transacciones revertidas; si se provoca un error con ON_ERROR_STOP, cerrar la conexión revierte la transacción. El caso de rechazo de una tabla base poblada conserva deliberadamente su fila defectuosa en su base auxiliar para probar que la migración no la borra/adopta. Eso es evidencia de una prueba negativa, no una carga del dataset bancario.

## Evidencia local y repetición autorizada

Evidencia excluida de Git en el directorio del ensayo: `database.dump`, `backup.json`, `archive-list.txt`, `roles-without-passwords.sql`, `state.json`, `runtime-tests.xml`, snapshots antes/restaurado/activa-después/aislada-después y firma final de las tablas. Los archivos se conservaron para revisión; no se hizo limpieza de contenedores, volúmenes o bases.

Comandos usados desde la raíz Git:

```powershell
# Una preparación nueva produce OTRO respaldo, contenedor y volumen únicos.
# No repetir este paso sin revisar el alcance de la nueva ejecución.
.\.venv\Scripts\python.exe -m scripts.new_bank_runtime_validation prepare

# Suite aislada del ensayo ya existente. Requiere acceso a Docker.
$env:BANK_VALIDATION_STATE = Join-Path (Get-Location) '.local-validation\9065d649f8d74222bd04dc58a0e54835\state.json'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_new_bank_postgres_runtime.py

# Estáticas: no requieren Docker ni PostgreSQL.
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_new_bank_integration_static.py
.\.venv\Scripts\python.exe -m scripts.new_bank_integration check
```

Sin `BANK_VALIDATION_STATE` las pruebas runtime se omiten. No utilizan las fixtures antiguas `database`/`dataset` ni sus opciones de pruebas contra el origen. El arnés ofrece preparación y verificación; no ofrece aplicar migraciones a la base activa ni limpieza automática.

## Recursos conservados y riesgos pendientes

Se conservan el contenedor/volumen de ensayo y **doce bases auxiliares** de casos negativos de las dos ejecuciones, además de la base restaurada principal. Sus nombres exactos figuran en `state.json`. No hay puertos publicados ni un segundo contenedor usando el volumen original. La eliminación futura debe comprobar primero ID, etiqueta y montajes; no se incluye un comando destructivo en esta entrega.

Antes de autorizar la carga faltan el cargador determinista versionado y su manifiesto transaccional, validaciones completas de 20,000 cuentas/120,000 cierres/225,000 movimientos, concurrencia de cargas, perfil de rendimiento y decisiones pendientes de negocio. Los fixtures actuales no prueban el volumen completo, todas las fechas futuras ni realismo bancario. La moneda sigue no especificada y las anomalías originales siguen documentadas.

Los permisos mínimos del agente y las vistas analíticas son etapas posteriores; el ensayo usa un administrador únicamente en el servidor aislado. El backup local y este ensayo no sustituyen una política empresarial de respaldo. Para una futura escritura en la base activa será necesario repetir el preflight y obtener un respaldo vigente. **Esta entrega termina aquí, sin carga de datos nuevos ni migraciones en el origen.**

## Cambios de esta tarea en el repositorio

- Nuevo `scripts/new_bank_runtime_validation.py`: respaldo/restauración explícitos, guardas de identidad/aislamiento y snapshots de conservación; sin comandos de limpieza.
- Nuevo `tests/test_new_bank_postgres_runtime.py`: suite opt-in de PostgreSQL real, separada de las pruebas/fixtures anteriores.
- Nuevo `docs/new-bank-model-runtime-validation.md`: este reporte.
- Actualizados `.gitignore` y las notas de estado/enlaces en gobernanza y respaldo.
- Fuentes upstream, migraciones derivadas 001/002, manifiesto de diseño, agente, corpus, embeddings del origen y pruebas anteriores sin cambios.
