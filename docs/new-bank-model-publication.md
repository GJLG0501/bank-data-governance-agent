# Publicación en PostgreSQL principal de desarrollo

Fecha: 22 de octubre de 2026, America/Mexico_City. Esta etapa corresponde a la
autorización explícita de publicar el modelo enero–junio 2026 en la base original
de desarrollo. El [ensayo aislado anterior](new-bank-model-data-load.md) conserva
su evidencia histórica; no se sustituye por esta publicación.

## Destino y autorización

El adaptador nuevo `scripts/new_bank_publication.py` permite exclusivamente:

- Contenedor `bank-data-governance-agent-dev-bank-postgres-1`.
- ID `56bf7ea7a9f9f9d8a3c03d12162d973855f6299648e54b2c79eea931977a27a2`.
- Base `bank_governance_synthetic_dev`, propietario `bank_governance_dev`.
- Volumen `bank-data-governance-agent-dev_bank-postgres-data`.
- Dirección publicada `127.0.0.1:5434` hacia `5432/tcp`.
- PostgreSQL 17.11 y pgvector 0.8.7.

No acepta DSN, host, puerto, SQL, semilla, generador o nombres de destino
arbitrarios. Los comandos que habilitan publicación requieren
`--authorize-active-development` y el estado explícito del respaldo de esta
publicación. Una invocación del cargador/arnés aislados continúa rechazando el
destino activo; no se eliminó su protección. La API privada de transporte de
publicación solo recibe SQL de los archivos derivados fijados por hash y del
renderer compartido del cargador, sometido además a comprobaciones de alcance.
La comprobación de texto no se presenta como un firewall para SQL arbitrario.

Las escrituras persistentes quedan en `dim` y `cfg`. Para cumplir ese límite
y conservar exactamente siete tablas nuevas, la identidad operacional se almacena
mediante `COMMENT ON SCHEMA cfg`, en un JSON con formato
`bank-model-dataset-comment-v1` y el mismo manifiesto completo. No se crea
`bank_model_control` en la base activa, ni una octava tabla de control. El ensayo
anterior mantiene su tabla de control original sin cambios.

El comentario se confirma junto con los datos, después de los mismos controles
de contenido y finanzas y antes del único COMMIT de carga. Se comprueba en cada
repetición y verificación; comentario ajeno, identidad distinta, parcial o contenido
alterado provocan error. Solo la primera carga escribe el comentario. El ensayo
aislado de esta adaptación comprobó también que su `xmin` no cambia al repetir.
El comentario no es una descripción editable libremente en pgAdmin: contiene la
identidad del dataset y su modificación invalida la verificación.

No se cambió el generador `1.0.0`, las fórmulas financieras, los originales
upstream ni los bytes de 001/002. El modo de almacenamiento es operacional y no
forma parte del contenido/identidad del dataset. No se crearon roles, vistas,
herramientas analíticas, documentos RAG o embeddings.

## Preflight y respaldo previo

Antes de escribir se comprobaron motor Docker, health, identidad, propietario,
permisos CONNECT/CREATE/TEMP, volumen y único contenedor usuario, puerto publicado,
ausencia de `dim`/`cfg`, cero transacciones de cliente abiertas/preparadas y cero
event triggers activos. Coincidieron el snapshot completo de los objetos
protegidos y ambas huellas históricas. Los tres upstream y las migraciones
conservan sus SHA-256 aprobados; el generador reprodujo exactamente el manifiesto
de referencia y el dataset aislado superó su verificación de contenido/finanzas.

El respaldo es nuevo, completo y custom; no se reutilizó el anterior. Se creó
con `pg_dump --no-password --format=custom`, sin filtros de tablas/esquemas y
con default READ ONLY. Se copió de forma binaria a la carpeta local ignorada por
Git, fuera del volumen persistente. Se exportaron roles sin contraseñas, sin
importar roles o cambiar credenciales del origen.

| Evidencia | Resultado |
| --- | --- |
| Archivo relativo a la raíz del repositorio | `.local-validation/publication_5633c5adfe064c179b28a5335b556a52/database.dump` |
| Tamaño | 207,336 bytes |
| SHA-256 | `520d400787acc685ea630833edc3cae91e3596c0369d92cc48382938d25ddca5` |
| pg_dump / pg_restore --list | Código 0 / código 0 |
| Contenido | CUSTOMER, TRANSACTION, LOAN, corpora, documents, vector, esquemas y demás objetos de la base |
| Verificación de la copia local | Firma PGDMP, tamaño/hash, listado idéntico después de copiar al contenedor aislado |
| Restauración real de esa copia | Código 0, `--exit-on-error --single-transaction` |
| Base de restauración | `nbm_case_9065d649f8d74222_publication_fresh_backup_9f511a9c` |
| Contenedor de restauración | `nbm-pg17-validation-9065d649f8d74222bd04dc58a0e54835` |
| Datos/esquema/embeddings recuperados | Snapshot protegido exactamente igual al origen |

El estado privado `publication.json` conserva ruta absoluta del respaldo,
conteos/huellas antes/después, firmas, hashes del código revisado, fases y códigos
de salida. Antes de cada escritura se revalida contenedor/volumen/health, respaldo,
manifiesto y que no hayan cambiado el código revisado ni los archivos protegidos.
Después del respaldo se repitió el preflight antes de la primera migración.

## Procedimiento reproducible y recuperación

La preparación y publicación no son comandos de mantenimiento genéricos. Una
nueva ejecución requiere revisar la autorización y el estado real. `backup`
exige que `dim`/`cfg` estén ausentes; no debe ejecutarse de nuevo una vez publicados.
Para verificar la publicación existente se usa `verify` con su estado registrado.

```powershell
$IsolatedState = '.local-validation\9065d649f8d74222bd04dc58a0e54835\state.json'
# Los dos pasos siguientes corresponden al estado PREVIO a esta publicación.
.\.venv\Scripts\python.exe -m scripts.new_bank_publication preflight --isolated-state $IsolatedState
.\.venv\Scripts\python.exe -m scripts.new_bank_publication backup --isolated-state $IsolatedState --authorize-active-development

$PublicationState = '.local-validation\publication_5633c5adfe064c179b28a5335b556a52\publication.json'
.\.venv\Scripts\python.exe -m scripts.new_bank_publication publish --publication-state $PublicationState --authorize-active-development
.\.venv\Scripts\python.exe -m scripts.new_bank_publication verify --publication-state $PublicationState
```

La aplicación usa los dos archivos 001 y 002 derivados, sin modificar sus bytes,
en su orden y en sus transacciones propias. El mismo bloqueo asesor `(7262026,1)`
coordina migraciones/cargas. La carga usa el renderer compartido, staging temporal,
bloqueos SHARE ROW EXCLUSIVE, transacción READ COMMITTED, conteos/hashes SQL y
validación financiera independiente antes de COMMIT. Semilla `202601`, algoritmo
`sha256-rounded-uniform-v1`. No se ejecutan los SQL upstream.

Una interrupción entre las dos migraciones puede dejar una fase parcial de
estructura vacía; el adaptador se detiene y exige inspección antes de reanudar.
Un fallo de carga revierte datos y manifiesto, conservando la estructura aplicada.
No se ejecutan reparaciones o borrados automáticos. Una publicación ya verificada
se puede repetir con la misma autorización y estado; verifica contenido y responde
sin cambios. Otra identidad o estructura provoca rechazo.

La recuperación utiliza el archivo local arriba identificado. Primero comprobar
su SHA-256 y restaurar con PostgreSQL 17 + pgvector en una base nueva del contenedor
aislado, como ya se ensayó; comparar el snapshot completo y las huellas históricas.
El rol propietario `bank_governance_dev` ya existe allí. No restaurar sobre la
base activa ni ejecutar `--clean`, reset, borrado de tablas o volúmenes. Cualquier
cambio de servicio para adoptar una recuperación requiere una revisión separada.
Se conservan dump, roles sin contraseñas, listados, snapshots y bases de ensayo.
El backup sigue en el mismo equipo: no acredita copia externa, PITR o RTO.

## Consulta en pgAdmin

Conectar al servidor de desarrollo con host `127.0.0.1`, puerto `5434`, base
`bank_governance_synthetic_dev` y el usuario existente `bank_governance_dev`.
Usar las credenciales locales actuales sin copiarlas a SQL, documentación o Git.
En el árbol: Databases → bank_governance_synthetic_dev → Schemas → **Refresh**;
expandir `dim` y `cfg`, luego Tables → **Refresh**. Las cinco tablas originales
están separadas de CUSTOMER/TRANSACTION/LOAN en public y del corpus bank_knowledge.

En Query Tool ejecutar únicamente consultas, por ejemplo:

```sql
BEGIN READ ONLY;
SELECT current_database(), current_user, version();

SELECT schemaname, tablename
FROM pg_catalog.pg_tables
WHERE schemaname IN ('dim', 'cfg')
ORDER BY schemaname, tablename;

SELECT 'dim.dim_cliente' AS tabla, COUNT(*) AS filas FROM dim.dim_cliente
UNION ALL SELECT 'dim.dim_producto', COUNT(*) FROM dim.dim_producto
UNION ALL SELECT 'dim.dim_txn', COUNT(*) FROM dim.dim_txn
UNION ALL SELECT 'cfg.ref_cuenta_modelo', COUNT(*) FROM cfg.ref_cuenta_modelo
UNION ALL SELECT 'cfg.ref_txn_modelo', COUNT(*) FROM cfg.ref_txn_modelo
UNION ALL SELECT 'cfg.fact_sdos_captacoloca_m', COUNT(*) FROM cfg.fact_sdos_captacoloca_m
UNION ALL SELECT 'cfg.fact_txn_captacoloca_d', COUNT(*) FROM cfg.fact_txn_captacoloca_d;

SELECT * FROM dim.dim_producto ORDER BY cve_producto;
SELECT * FROM dim.dim_txn ORDER BY cve_producto, cve_txn;
SELECT * FROM cfg.fact_sdos_captacoloca_m
ORDER BY num_cta, cve_producto, fec_informacion LIMIT 12;
SELECT * FROM cfg.fact_txn_captacoloca_d
ORDER BY num_cta, cve_producto, cve_mes_txn, cve_txn LIMIT 12;

SELECT obj_description('cfg'::regnamespace, 'pg_namespace')::jsonb
       ->'manifest'->>'dataset_sha256' AS dataset_sha256;
COMMIT;
```

Estas consultas manuales no se integran al agente. No unir el catálogo solo por
código, no normalizar `dominio` crudo, no sumar saldos de varios cortes como flujos
y no atribuir una moneda a los importes.

## Resultado final de la publicación

Estado: **published_verified**. Evidencia estructurada y conteos por mes/producto:
[new-bank-model-publication-validation.json](new-bank-model-publication-validation.json).
Docker y PostgreSQL permanecen healthy; identidad, volumen y puerto originales
coinciden. Se confirmaron exactamente siete tablas permanentes en `dim`/`cfg`,
20,000 cuentas distintas y ausencia del esquema adicional `bank_model_control`.

| Migración realmente aplicada | SHA-256 | Resultado |
| --- | --- | --- |
| 001_new_bank_schemas_tables.sql | `27d7e522cc7c166f3577831e17f9bd22ce9d1c8b8fe2e69bc001b896d1f99c4a` | Código 0 |
| 002_new_bank_integrity.sql | `11fb5d9e104b872a16c1e25c23aef8fb3ac9a74fa72cf40f57eb04b1caa29db8` | Código 0 |

Se conservaron las 42 columnas originales, las dos referencias y las restricciones
aprobadas. `dim.dim_txn` conserva sus cinco columnas sin PK/UNIQUE/FK. La firma
completa final coincide con la validada en PostgreSQL aislado.

| Tabla nueva | Filas confirmadas |
| --- | ---: |
| dim.dim_cliente | 5,000 |
| dim.dim_producto | 4 |
| dim.dim_txn | 9 |
| cfg.ref_cuenta_modelo | 20,000 |
| cfg.ref_txn_modelo | 9 |
| cfg.fact_sdos_captacoloca_m | 120,000 |
| cfg.fact_txn_captacoloca_d | 225,000 |

Las cinco tablas recibidas suman **350,013** filas; las referencias auxiliares
suman **20,009** y no se cuentan como upstream. Hay 20,000 cierres por mes de enero
a junio, 5,000 por producto. Febrero–junio tienen 45,000 movimientos por mes:
10,000 CHEQUES, 10,000 AHORRO, 10,000 C_PERSONAL y 15,000 TDC; enero no tiene
movimientos. El reporte JSON conserva además rangos y sumas exactas por corte.

Resultado financiero: **100,000 conciliaciones exactas** de febrero–junio,
diferencia máxima `0.00`, cero en los 18 contadores de violaciones bloqueantes.
Concuerdan continuidad, crecimiento, importe, signo, cuenta/dueño, dominios crudos,
fechas, catálogos, relaciones y cardinalidades. La moneda sigue siendo NULL/no
especificada en la procedencia. No se aplicó tolerancia de un centavo.

Identidad final: `a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b`,
idéntica al ensayo aislado y al [manifiesto de referencia](../data/source/new_bank_model/dataset-202601.manifest.json).
Se comprobaron los siete hashes de contenido SQL contra la referencia. La segunda
carga en la base activa respondió **sin cambios**, sin duplicar filas ni modificar
el manifiesto; las verificaciones completas antes/después de esa repetición
coinciden exactamente. Transporte/guardas y transacción de primera carga tomaron
6.634 s, sin incluir preparación/serialización anteriores; no es una medición SLA.

### Conservación antes/después y criterios de calidad

| Objeto protegido | Antes del respaldo | Después de publicación y regresiones |
| --- | ---: | ---: |
| CUSTOMER | 1,000 | 1,000 |
| TRANSACTION | 5,000 | 5,000 |
| LOAN | 500 | 500 |
| bank_knowledge.corpora | 1 | 1 |
| bank_knowledge.documents | 24 | 24 |

Coinciden snapshots completos de filas, columnas/defaults, restricciones, índices
y extensión/dimensiones vectoriales. Los 24 documentos mantienen sus embeddings
de dimensión 1,024. Se repitió la comprobación después de todas las pruebas vivas.
Las huellas históricas se calcularon con el mismo método que antes de publicar:

- Registros anteriores: `30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5`.
- Documentos/metadatos/embeddings: `63a6313e870be8268ce7bd85ee0eb8401ebbece4bb6f529b211c4796a6db0847`.

También coinciden los hashes de los archivos del agente, corpus, fuente y
generador anteriores. El agente LangChain conserva `search_data_catalog`; su
recuperación y respuestas con evidencia se probaron después de la publicación,
sin ingestión ni herramientas SQL nuevas.

Se preservan **44 PF con `fec_alta < fec_nac`** y **1,027 PF con
`age(fec_alta,fec_nac) < interval '18 years'`**. La intersección medida es **44**:
no son categorías mutuamente excluyentes y no deben sumarse como casos distintos.
A la fecha upstream `2026-07-15` hay cero PF menores de 18. Se conserva asimismo
el significado no aclarado de `fec_nac` en 200 PM, los cuatro productos para todos
los clientes, el vocabulario distinto de `dominio` en enero y el significado
mensual de `saldo_apertura`. Nada se corrigió silenciosamente.

### Pruebas de esta tarea, separadas de la evidencia histórica

| Suite realmente ejecutada | Aprobadas |
| --- | ---: |
| Anterior: datos sintéticos, documentos y agente con mocks, sin PostgreSQL | 87 |
| Anterior: recuperación real Ollama/pgvector | 7 |
| Anterior: agente real con llama3.1 y corpus existente | 9 |
| Nuevo modelo: contratos estáticos y generador, sin servicios | 42 |
| Nuevo modelo: cargador aislado existente | 13 |
| Publicación: autorización/alcance, sin servicios | 15 |
| Publicación: adaptación de manifiesto, restore y carga real aislada | 7 |
| Publicación: aceptación posterior READ ONLY en la base activa | 13 |
| **Total actual** | **193** |

**103** de esas pruebas corresponden al sistema anterior. No se afirma haber
repetido las **134 históricas**: sus 31 casos PostgreSQL de migraciones/ingestión
escriben en esquemas de prueba y no se ejecutaron contra la base activa bajo esta
autorización limitada a `dim`/`cfg`. Sus contratos actuales se complementaron con
snapshots históricos completos y consultas reales de conservación. Las 65 pruebas
históricas de migraciones del paquete nuevo tampoco se vuelven a contar como
ejecución actual; requieren un modelo vacío y comprobaciones de una etapa anterior.
No se sustituyen las 134 pruebas históricas por las 120 del paquete aislado.

Las pruebas aisladas nuevas incluyeron restore de la copia previa, firma exacta
001/002, rollback tras insertar saldos, dos cargas concurrentes con una sola
confirmación, repetición sin cambios incluso en el xmin del comentario, rechazo
de semilla/versión distinta y conservación de lo restaurado. Además se restauró
realmente el respaldo nuevo de esta publicación antes de autorizar SQL activo.
Las pruebas anteriores del cargador incluyeron el centavo deliberado, parcial,
control/estructura incompatible y bloqueo del destino activo por su entrada aislada.

Los 13 casos posteriores usan exclusivamente SELECT/READ ONLY sobre la publicación
y el respaldo; no crean fixtures de escritura. Repetición de esa aceptación:

```powershell
$env:BANK_PUBLICATION_STATE = (Resolve-Path '.local-validation\publication_5633c5adfe064c179b28a5335b556a52\publication.json').Path
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_new_bank_published_readonly.py
```

Los JUnit de las cinco ejecuciones finales se conservan en `.local-validation/`,
todos con cero fallos, errores y omisiones. Una primera ejecución unitaria anterior
encontró permisos insuficientes en el directorio temporal de pytest. Se repitió
sin modificar pruebas o permisos del proyecto, usando un directorio temporal nuevo
del ensayo y acceso permitido: 87/87 aprobaron. No hubo errores financieros,
de integridad o de huella en la publicación; no se realizaron reparaciones.

El arnés `new_bank_runtime_validation.finish` y las suites de etapas anteriores
que exigen `dim`/`cfg` ausentes no son verificadores de esta etapa publicada.
Se conservan sin debilitar esa condición: para la publicación usar el nuevo
`new_bank_publication verify` o la aceptación READ ONLY de arriba. No repetir
fixtures antiguas contra la base activa ni interpretar su requisito histórico
de ausencia de esquemas como un fallo de esta publicación autorizada.

### Cambios en archivos y riesgos pendientes

Nuevos:

- `scripts/new_bank_publication.py`: preflight, respaldo vigente, ensayo de su
  restauración, autorización fija, publicación y verificación.
- `tests/test_new_bank_publication.py`: controles de autorización y alcance.
- `tests/test_new_bank_publication_postgres.py`: ensayo real aislado.
- `tests/test_new_bank_published_readonly.py`: aceptación activa sin escrituras.
- Este documento y `docs/new-bank-model-publication-validation.json`.

Modificados: `scripts/new_bank_model.py` exclusivamente para compartir el renderer
con el modo de metadatos en `cfg`; enlaces/notas de estado en gobernanza, carga
aislada, validación runtime y respaldo. El generador, manifiestos de dataset,
fuentes upstream, migraciones 001/002 y lógica del agente no cambiaron. `.gitignore`
ya excluía los artefactos privados; no se publicó el respaldo ni otro archivo en
GitHub. Se conservaron los contenedores, volúmenes y bases de ensayo.

Pendientes: definición de moneda, significado de fechas PM, realismo/criterios de
elegibilidad y cronología, roles de permisos mínimos y una copia de respaldo fuera
del equipo. El catálogo sin clave y la unicidad mensual de movimientos son propios
del ejercicio, no un contrato universal de transacciones. Un propietario de esquema
puede alterar el comentario de control: no editarlo y mantener la verificación de
contenido antes de cualquier repetición. No hay errores bloqueantes conocidos.

**Publicación terminada y verificada. No se inicia el nuevo corpus RAG ni la
integración de herramientas analíticas, Gemini, MCP o Streamlit.**
