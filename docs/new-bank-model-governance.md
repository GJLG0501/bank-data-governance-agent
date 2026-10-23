# Especificación técnica de integración — versión 1.0.0

Estado actual: [publicado y verificado en la base principal de desarrollo](new-bank-model-publication.md), después de respaldo nuevo y ensayos aislados. Este documento concreta las decisiones aprobadas para la etapa 1 del [plan de integración](new-bank-model-integration-plan.md). Los controles son del MVP educativo, no políticas oficiales de Banamex. Las notas de entrega inicial «no aplicado a la base activa» y de pruebas solo estáticas que siguen son históricas. Las [65 pruebas de migraciones](new-bank-model-runtime-validation.md) y la [carga aislada completa](new-bank-model-data-load.md) mantienen su propia evidencia. No se publicó el nuevo modelo en el corpus ni se agregaron herramientas al agente.

## Archivos y reproducción sin servicios

Desde la raíz Git del proyecto:

```powershell
.\.venv\Scripts\python.exe -m scripts.new_bank_integration check
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_new_bank_integration_static.py
```

`scripts/new_bank_integration.py` solo utiliza la biblioteca estándar. No importa controladores de base, no carga `.env`, no genera datos, no hace llamadas de red y no ofrece un comando de aplicación. `render` escribe exclusivamente el manifiesto y las dos migraciones, dentro de rutas fijas; `check` exige igualdad de bytes con el renderer. Ambos comprueban antes las huellas upstream fijadas en el código. Cambiar un original no debe resolverse actualizando automáticamente su huella.

El manifiesto [manifest.json](../data/source/new_bank_model/manifest.json) registra procedencia, tres hashes, cinco tablas originales, dos auxiliares, dependencia U1→U2→U3, decisiones, calendario, distribuciones y volúmenes. `source_release=null` indica que no se recibió una versión upstream; `adaptation_version=1.0.0` es nuestra versión, no una versión del proveedor. `currency=null` significa unidad no proporcionada. Los volúmenes son de la **carga futura**: las migraciones no insertan ninguna fila.

Inventario de esta entrega (nueve archivos nuevos):

| Archivo | Propósito |
| --- | --- |
| `data/source/new_bank_model/manifest.json` | Fuente, versiones, decisiones y volúmenes. |
| `scripts/new_bank_integration.py` | Renderer/verificador sin acceso a servicios. |
| `sql/integration/001_new_bank_schemas_tables.sql` | Estructura original y guardas de compatibilidad. |
| `sql/integration/002_new_bank_integrity.sql` | Auxiliares e integridad revisada. |
| `sql/integration/checks/preflight.sql` | Inspección futura READ ONLY. |
| `sql/integration/checks/legacy_snapshot.sql` | Snapshot futuro de datos, esquema y embeddings protegidos. |
| `docs/new-bank-model-governance.md` | Esta especificación y límites de aceptación. |
| `docs/new-bank-model-backup-recovery.md` | Respaldo, ensayo y conservación paso a paso. |
| `tests/test_new_bank_integration_static.py` | Pruebas de archivos y contratos sin PostgreSQL. |

Verificación local de esta entrega: **24 pruebas estáticas aprobadas**, renderer `check` correcto y cuatro bloques PowerShell del procedimiento analizados sintácticamente sin ejecutarlos. La suite bloquea conexiones y el generador antiguo durante sus pruebas; no solicita fixtures de base o dataset. Se ejecutó exclusivamente el archivo nuevo, con la caché de pytest deshabilitada por restricciones del directorio local. No se ejecutaron comandos Docker, SQL, respaldo/restauración, generación de datos o reindexación. Los originales, código/configuración previos y corpus conservan sus huellas de archivo; esto no sustituye un futuro snapshot del estado vivo.

## Diseño y verificación de las migraciones

1. [001_new_bank_schemas_tables.sql](../sql/integration/001_new_bank_schemas_tables.sql): crea/verifica `dim`, `cfg` y las cinco tablas, con sus 42 columnas, tipos, longitudes, orden, defaults, nulabilidad y restricciones originales. Se conservan las dos PK, tres CHECK y la ausencia de PK/UNIQUE en `dim_txn`.
2. [002_new_bank_integrity.sql](../sql/integration/002_new_bank_integrity.sql): exige los esquemas y tablas anteriores; prepara `cfg.ref_txn_modelo` y `cfg.ref_cuenta_modelo`, y agrega NOT NULL, claves, FK y CHECK aprobados para los hechos. No agrega restricciones a `dim.dim_txn`, ni cambia las definiciones originales de cliente/producto. No crea vistas, roles, herramientas analíticas o almacenamiento RAG.

Cada archivo tiene BEGIN/COMMIT explícitos, `search_path=pg_catalog`, tiempos máximos y el mismo bloqueo asesor transaccional. No contiene carga de datos, operaciones de borrado o actualizaciones de valores. Debe utilizarse posteriormente en una sesión PostgreSQL 17 dedicada, con parada del cliente ante el primer error. No envolver archivos con COMMIT propio en otro runner que espere controlar una única transacción externa. Las dos migraciones son transacciones **separadas**: si 002 falla, 001 puede haber dejado estructura base vacía; repetir 001 y luego 002 es el camino previsto, sin reset.

El guard compara:

- Propietario: esquemas/tablas deben pertenecer al rol que ejecuta la migración. Una pertenencia a otro rol o ser superusuario no sustituye esa coincidencia conservadora. Elegir el propietario antes de aplicar; no se incluye cambio automático de dueño.
- Clase y persistencia: tabla ordinaria permanente, sin partición/herencia, RLS, políticas, triggers de usuario o reglas. Índices ajenos a PK/UNIQUE aprobadas, índices inválidos o no preparados también provocan rechazo.
- Columnas: nombre/orden, tipo y modificador, NOT NULL, default, identidad, generación, collation, dimensiones y columnas retiradas. No acepta columnas extra ni un simple tipo base con longitud distinta.
- Restricciones: PK/UNIQUE/CHECK se comparan con definiciones canónicas producidas por el mismo servidor. FK se comparan estructuralmente por columnas ordenadas, tabla/columnas de destino, acciones RESTRICT, modo de match, validación y diferibilidad. No basta coincidir en el nombre.

Para normalizar tipos/defaults/CHECK sin adivinar la representación interna de PostgreSQL, el SQL prepara referencias **temporales vacías** y dos funciones auxiliares en `pg_temp`. No crea un esquema permanente de referencia. Esos objetos se descartan al cerrar la sesión por el ciclo de vida de PostgreSQL; no se incluyen comandos de borrado. Las referencias no tienen FK a tablas permanentes; las FK se comprueban mediante catálogos. El rol futuro necesita permiso TEMP en la base. Nombres temporales UUID evitan colisiones al repetir en una sesión.

Se exige el conjunto de restricciones base y solo se admite el subconjunto explícitamente revisado de ampliaciones; no se aceptan restricciones desconocidas, duplicadas, deshabilitadas/no validadas o más permisivas. El perfil de columnas debe ser exactamente base o final, sin mezcla arbitraria de nulabilidad. Una expresión equivalente pero escrita de otra forma puede rechazarse: se privilegia detenerse frente a adoptar objetos desconocidos.

002 comprueba el estado antes de cualquier refuerzo. Si falta algún refuerzo y la tabla contiene filas, aborta y revierte su transacción. No rellena referencias auxiliares, no corrige filas y no aplica NOT VALID. Si el perfil final ya existe, repetir no agrega restricciones ni altera datos. 001 reconoce también el perfil aprobado por 002 para que repetir la secuencia sea seguro. Un objeto compatible no equivale a un dataset de contenido validado: las comprobaciones de carga de la sección siguiente siguen siendo obligatorias.

La verificación de firma considera los [atributos de columnas de PostgreSQL 17](https://www.postgresql.org/docs/17/catalog-pg-attribute.html). Las FK se inspeccionan por sus claves, destino, acciones y estado en [pg_constraint](https://www.postgresql.org/docs/17/catalog-pg-constraint.html). Las pruebas actuales son estáticas: aún no demuestran sintaxis ejecutada, compatibilidad de runtime, rollback o idempotencia real. Esa aceptación requerirá después una base aislada autorizada, nunca el fixture existente que escribe mediante rollback en esta tarea.

## Claves, relaciones y restricciones adicionales

| Objeto | Regla preparada | Justificación y límite |
| --- | --- | --- |
| `dim.dim_cliente` | PK original `num_cte`; CHECK originales de tipo/género; resto sin nuevos refuerzos. | Conserva posibilidad de NULL del DDL. Las distribuciones y fechas pobladas se validarán al cargar, no mediante una regla de elegibilidad inventada. |
| `dim.dim_producto` | PK original `cve_producto`; CHECK original de dominio; `activo DEFAULT TRUE` sigue nullable. | No se cambian sus seis columnas ni se supone que un estado activo futuro debe ocultar hechos históricos. |
| `dim.dim_txn` | Cinco columnas NOT NULL originales; **ninguna PK/UNIQUE/FK nueva**. | Códigos repetidos entre productos son válidos. El par producto/código debe ser único en el contenido revisado antes de derivar el auxiliar; no se deduplica silenciosamente. |
| `cfg.ref_txn_modelo` | PK `(cve_producto,cve_txn)`; UNIQUE `(cve_producto,cve_txn,desc_txn)`; FK de producto; CHECK con las nueve tuplas exactas de producto/código/descripción/dominio/grupo/signo y `regla_version='1.0.0'`. | Catálogo auxiliar del MVP, inicialmente vacío. La descripción y signo no pueden inventarse al poblarlo. Cada tupla proviene de U1 y el signo de U3. No sustituye ni altera `dim_txn`. |
| `cfg.ref_cuenta_modelo` | PK `(num_cta,cve_producto)`; UNIQUE del triple cuenta/producto/cliente y de cliente/producto; FK a cliente/producto; rangos de cuenta por producto y apertura/cohorte de enero. | Cuenta estable y una por producto/cliente en este dataset. El UNIQUE del triple permite FK de dueño desde ambos hechos. Es una tabla auxiliar nueva, no parte del modelo recibido. |
| Saldos | Las nueve columnas NOT NULL; UNIQUE `(num_cta,cve_producto,fec_informacion)`; FK compuesta a cuenta/producto/cliente. | Un solo cierre por cuenta/producto/corte, con dueño verificable. La referencia auxiliar asegura indirectamente las FK a cliente y producto. |
| Movimientos | Las diez columnas NOT NULL; UNIQUE `(num_cta,cve_producto,cve_mes_txn,cve_txn)`; FK de cuenta/dueño y FK de producto/código/descripción al auxiliar. | Solo una operación de cada tipo al mes en el generador actual. No usar esta clave para una fuente empresarial con varios eventos legítimos del mismo tipo. |

Todas las FK preparadas tienen ON UPDATE RESTRICT y ON DELETE RESTRICT; no eliminan ni propagan cambios. No se carga el catálogo auxiliar durante la migración. En la fase de carga, el orden será clientes/productos → `dim_txn` validada → catálogo auxiliar → cuentas auxiliares → saldos/movimientos. Los nuevos hechos con FK no admiten ejecutar directamente los upstream: se utilizará un cargador derivado revisado.

### CHECK de hechos y tratamiento de NULL

- Saldo de apertura, saldo mensual e importe de transacción deben ser positivos y menores que `Infinity` en NUMERIC. Con ello se excluyen también NaN y valores no finitos; la declaración NUMERIC(18,2) conserva la precisión original. Los saldos positivos son una regla de este dataset, no una prohibición universal de sobregiros.
- Saldos: apertura de cuenta `2026-01-01`, cohorte `202601` y uno de los seis cortes exactos. Enero exige apertura=cierre y rango inicial de cada producto. Febrero–junio exigen el objetivo de crecimiento calculado **desde el saldo de inicio del mismo registro**, redondeado al centavo. La igualdad con el cierre del mes anterior necesita validación entre filas al cargar.
- Movimientos: uno de los cinco meses febrero–junio; fecha finita, día 15 y año/mes iguales a `cve_mes_txn`; corte entre los cinco finales de mes y mismo año/mes. Esas listas finitas garantizan fechas reales para el calendario 2026 sin depender de conversiones que normalicen fechas inválidas. Extender el calendario exige otra versión revisada.
- `dominio` se valida **tal como lo produce la fuente**: en saldos de enero contiene grupo (`CAPTACION/COLOCACION`); en saldos posteriores y movimientos contiene dominio técnico (`DEPOSITS/LENDING/TDC`). No se normaliza, rellena ni actualiza.
- `saldo_apertura` se conserva con su nombre y valores: saldo inicial de cuenta en enero, saldo inicial del mes desde febrero. No se agrega una restricción que lo iguale al saldo de enero en meses posteriores.
- Los seis campos de cliente no poblados (`giro_empresa`, `cve_territorio`, `cve_dir`, `cve_subdir`, `cve_sucursal`, `cve_promotor`) siguen admitiendo NULL. No se usan cadenas vacías ni `NO APLICA` para ocultar información no proporcionada. Otros NULL permitidos por las dimensiones se describen como nulabilidad de esquema; el cargador validará completitud de los campos que sí genera U1.

Un CHECK con resultado NULL no rechaza una fila. La combinación de NOT NULL en hechos, FK y CHECK es necesaria; no se depende de CHECK para suplir NOT NULL. Las restricciones locales no garantizan todos los conteos o las identidades entre tablas. [Semántica de restricciones](https://www.postgresql.org/docs/17/ddl-constraints.html).

## Calidad: controles pendientes del cargador

En la entrega inicial no había cargador ni datos generados. La [implementación posterior](new-bank-model-data-load.md) aplica los siguientes controles de aceptación:

| Control | Resultado esperado | Tratamiento |
| --- | --- | --- |
| Manifiesto y fuentes | Tres hashes exactos, adaptación/algoritmo/semilla registrados, firmas compatibles. | Bloqueante. |
| Universo | IDs de cliente 1–5,000; 4,800 PF, 200 PM; 2,496 hombres y 2,304 mujeres PF; 200 PM NO APLICA; segmentos 250/1,000/3,750. | Bloqueante para este dataset. |
| Catálogos | Cuatro productos exactos, nueve pares transaccionales; cero duplicados del par incluso si son idénticos; descripciones/dominios/grupos correctos. Auxiliar coincide con los nueve registros y sus signos. | Bloqueante; no usar DISTINCT para encubrir repetidos. |
| Cuentas | 20,000, 5,000 por producto, cuatro por cliente; asignación por orden de `num_cte`; rangos y dueño invariables. Referencia auxiliar: 20,000 filas. | Bloqueante. |
| Fechas | Seis cierres por cuenta sin huecos; cinco meses de operaciones día 15; fechas de cliente calculadas exactamente desde U1, aun con anomalías. | Reglas de calendario bloqueantes; anomalías de realismo se reportan. |
| Cantidades de hechos | 120,000 saldos, 225,000 movimientos; 20,000 saldos por corte; 45,000 operaciones por mes, 10,000 por cada producto de dos tipos y 15,000 TDC. | Bloqueante. Los auxiliares no están incluidos en las 350,013 filas de las cinco tablas originales. |
| Continuidad | Inicio de mes = cierre del mes calendario previo por cuenta/producto/cliente; enero apertura=cierre. | Cero faltantes y diferencia exacta 0.00. |
| Movimientos | Importe y signo según producto/código; retiro/pago 5% en depósitos/personal; compras y disposición 2% TDC; resto por incremento objetivo. | Bloqueante. Guardar importe positivo, no signo negativo. |
| Conciliación | Inicio de mes + suma firmada de movimientos = cierre; objetivo por cuenta/mes con tasas del manifiesto. | Exactamente 0.00, incluyendo discrepancias de un centavo. Enero se valida aparte, sin movimientos inexistentes. |
| JOIN | Producto + código al catálogo; cuenta + producto + mes a movimientos ya agregados. | Cero huérfanos; cardinalidades y sumas no se inflan. |
| Repetición | Identidad y huellas iguales: sin cambios. Dataset parcial, modificado o diferente: rechazo. | Sin completar o reemplazar silenciosamente. |
| Conservación | Snapshot protegido antes/después y hashes de archivos previos iguales. | Bloqueante. |

La conciliación partirá de una malla de cuenta/producto/mes esperado y comparará mediante LEFT/FULL OUTER JOIN. Reportará falta de cierre o movimientos, huérfanos, código desconocido y NULL **antes** de calcular diferencias. No sustituir faltantes por cero ni usar `ELSE 0` para códigos desconocidos. No sumar saldos de varios cortes como si fueran flujo. El crecimiento sintético no representa intereses contractuales ni rentabilidad.

Anomalías a conservar/reportar: vocabulario de dominio por período; doble significado temporal de apertura; fechas independientes, por ejemplo el PF 3552 con alta 2003-04-24 anterior al nacimiento 2004-10-27; significado de `fec_nac` en PM; todos los productos asignados a todas las personas. No se introduce CHECK `fec_alta >= fec_nac` ni mayoría de edad al alta que rechace la muestra original. La validación de 18 años de U1 es a 2026-07-15. No se corrigen esas fechas ni se suponen reglas comerciales.

## Algoritmo futuro

Contrato versionado, inicialmente propuesto y ahora implementado en `scripts/new_bank_model.py`: `sha256-rounded-uniform-v1`, semilla inicial de referencia `202601`. Se conserva este encabezado para no romper referencias del manifiesto. La semilla es un entero explícito no secreto en el manifiesto de cada carga; cambiarla cambia el dataset y no autoriza reemplazar uno existente.

Para el saldo de enero de cada cuenta/producto:

1. Serializar JSON con claves `algorithm`, `model_id`, `seed`, `product`, `account`, `sort_keys=True`, separadores `(',',':')`, UTF-8, sin salto final; valores de algoritmo/modelo según el manifiesto, cuenta y semilla enteros.
2. Interpretar el SHA-256 del mensaje como entero sin signo big-endian `H`. Definir `D=2**256`, `U=H/D` (racional exacto en [0,1)).
3. Convertir mínimo/máximo a centavos enteros `lo`/`hi`, `W=hi-lo`. Calcular `centavos = lo + (2*W*H + D)//(2*D)`. Es el redondeo positivo HALF_UP de un valor uniforme aproximado del intervalo, sin usar float ni el estado aleatorio de sesión. Guardar `centavos/100` como decimal de escala 2.
4. Aplicar U3 con decimales exactos y ROUND_HALF_UP a dos lugares por cuenta y mes. Mantener fórmulas de importes, calendario, distribuciones determinísticas y signos originales.

Este muestreo conserva rangos inclusivos y el menor peso de los intervalos de redondeo de los extremos que tiene la fórmula continua de U2. La secuencia hash es determinística y no idéntica a RANDOM() ni una garantía de uniformidad exacta de frecuencias en 5,000 cuentas. No afirmar equivalencia bit a bit ni forzar que mínimo/máximo aparezcan. Una distribución uniforme de **centavos enteros** daría otro peso a los extremos; por eso se especifica el redondeo de un uniforme aproximado. Pruebas futuras deberán incluir vectores de referencia de este algoritmo, estabilidad entre procesos y tamaños de lote, límites y consistencia financiera.

## Campos propuestos para vistas futuras

No se crean vistas en esta etapa. Propuesta inicial para consumo de solo lectura:

| Campo derivado | Derivación/definición |
| --- | --- |
| `dominio_origen` | Alias del campo `dominio`, sin corrección. |
| `cve_dominio_catalogo`, `grupo_producto_catalogo` | JOIN por producto al catálogo validado. Mostrar junto al valor original. |
| `fecha_corte` | DATE derivado del entero, después de validación estricta. |
| `mes_corte` | Año/mes de `fecha_corte`, distinto de `cve_mes_alta`. |
| `saldo_inicio_mes` | Alias documentado de `saldo_apertura` de esa fila. |
| `saldo_inicial_cuenta` | Saldo de enero del mismo par cuenta/producto; grano controlado y único. |
| `importe_movimiento` | Alias de `saldo_txn`, positivo. |
| `signo_economico`, `movimiento_firmado` | Signo del auxiliar por producto/código; importe × signo. |
| `model_id`, `dataset_version`, `load_run_id` | Procedencia del futuro manifiesto de carga; sin inventarlos como columnas upstream. |
| `moneda` o `unidad_importe` | No asignar código ni símbolo; mostrar no especificada hasta recibir una definición aprobada. |

No definir mapeos a CUSTOMER/TRANSACTION/LOAN ni a sus segmentos/campos. El catálogo RAG antiguo, su JSONL y sus embeddings continúan aislados. Roles, permisos analíticos y auditoría de consultas se prepararán en su etapa específica; estos archivos no exponen una herramienta SQL.

## Antes de aplicar

Revisar las listas cerradas de meses/rangos y la unicidad sintética, el propietario/permiso TEMP, el plan de población de auxiliares y la evidencia de respaldo/restauración del [procedimiento](new-bank-model-backup-recovery.md). Quedan por confirmar moneda, semántica de PM y elegibilidad/cronología, sin bloquear la conservación literal de sus anomalías. No ejecutar upstream ni aplicar las migraciones hasta una autorización posterior y aceptación en una base aislada.
