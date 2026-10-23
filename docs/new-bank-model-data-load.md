# Carga reproducible del laboratorio bancario

Este reporte corresponde a la etapa aislada, ya completada. La publicación
posterior autorizada en desarrollo se documenta en
[publicación principal](new-bank-model-publication.md). La CLI aislada descrita
aquí conserva su protección; la publicación utiliza otra entrada explícita.

Esta implementación corresponde a la etapa 2 del [plan](new-bank-model-integration-plan.md).
La única escritura autorizada es en el contenedor aislado del
[ensayo de restauración](new-bank-model-runtime-validation.md). La base activa
`bank_governance_synthetic_dev` no es un destino admitido por el cargador.
Los resultados medidos se registran al final de este documento después del ensayo.

## Algoritmo, procedencia y dinero

`scripts/new_bank_model.py`, generador `1.0.0`, implementa el contrato
`sha256-rounded-uniform-v1` de [gobernanza](new-bank-model-governance.md#algoritmo-futuro).
La semilla de referencia es el entero `202601`; admite otra semilla para preparar
otra identidad, pero no reemplaza un dataset cargado. U1, U2 y U3 permanecen intactos.
No se ejecuta ninguno de ellos. Los catálogos, fechas, asignaciones de cuenta,
distribuciones y fórmulas proceden de esos tres archivos y del manifiesto de diseño.

Para enero se serializan `account`, `algorithm`, `model_id`, `product`, `seed`
como JSON con claves ordenadas, separadores compactos, UTF-8 y sin salto final.
Sean `H` el SHA-256 como entero big-endian, `D=2**256`, `lo/hi` los límites en
centavos y `W=hi-lo`: el resultado es `lo + (2*W*H+D)//(2*D)` centavos.
Conserva el muestreo uniforme aproximado continuo redondeado y el menor peso de
los extremos; no es la secuencia de RANDOM(), ni una distribución uniforme exacta
de frecuencias o de centavos enteros. No se fuerza la presencia de los extremos.

Después se usa Decimal con precisión local 38 y ROUND_HALF_UP al centavo. Cada
mes depende del cierre del mes calendario previo. Las tasas son 2%/3% en febrero
y 1%/2.2% después, según captación/colocación. Depósitos y disposición personal
compensan el retiro/pago del 5% y el incremento; compras/disposiciones TDC son
2%, y sus pagos son la diferencia necesaria. Los importes se guardan positivos.
El signo pertenece al par producto/código. Enero no tiene movimientos.
No hay cálculos monetarios con float. Los tiempos de ejecución sí son segundos
de reloj, ajenos a los datos financieros.

Se preservan `dominio` crudo y el significado mensual de `saldo_apertura`.
No se asigna moneda, no se interpreta crecimiento como interés contractual y
no se corrigen las anomalías cronológicas de clientes.

## Identidad y representación canónica

Cada tabla se ordena por su clave lógica indicada en `sort_keys` del manifiesto.
Se serializa cada fila como un array JSON, en orden físico de columnas. Cada
valor no NULL es texto: enteros sin separadores, fechas ISO, booleanos `true/false`
y dinero de escala 2; NULL es el literal JSON `null`. UTF-8, Unicode literal,
separación JSON `, `, LF entre filas, sin LF final. PostgreSQL calcula la misma
representación mediante `jsonb_build_array(columna::text,...)`, orden de producto
con COLLATE C y SHA-256 incorporado. Se registran conteo y hash de las siete tablas.

La identidad global es el SHA-256 del manifiesto sin su propia huella, JSON
compacto con claves ordenadas. Incluye versión de manifiesto/adaptación/generador,
algoritmo, semilla, período, moneda NULL, fuentes, migraciones, claves y hashes
de contenido. No incluye tiempos, nombres del destino o fecha de ejecución;
estos son evidencia operacional separada, no contenido del dataset.

El [manifiesto de diseño](../data/source/new_bank_model/manifest.json) conserva
la clave histórica `future_generator`, ahora marcada como implementada en el
módulo separado. El manifiesto de dataset es otro contrato y no reemplaza la
procedencia ni los SQL originales.

## Transacción y límites de escritura

Cada operación de base exige un `--state` explícito del ensayo anterior, dentro
del directorio ignorado `.local-validation/`. No se carga `.env`, no existe DSN
predeterminado ni conexión TCP. Antes de escribir se comprueban nombres, ID completo,
etiqueta, volumen propio, único contenedor usuario de ese volumen, red `none`,
ausencia de puertos, versión PostgreSQL 17, rol y firmas 001/002. Se rechazan
la base/contenedor activos, bases no registradas, estructuras distintas y fuentes
o migraciones cuyos bytes hayan cambiado respecto de la evidencia aprobada.

La transacción es explícitamente READ COMMITTED. Toma el mismo bloqueo asesor
`(7262026,1)` que las migraciones y bloqueos SHARE ROW EXCLUSIVE sobre las siete
tablas. El segundo cargador toma un snapshot nuevo después de esperar al primero.
Los bloqueos de tabla impiden escrituras ordinarias durante la verificación;
un administrador externo sigue teniendo capacidad para alterar el laboratorio.

En esa transacción se crea `bank_model_control.datasets(model_id TEXT PRIMARY KEY,
manifest JSONB NOT NULL)` solamente si no existe el esquema de control y las siete
tablas están vacías. Es un objeto auxiliar operacional, separado de las cinco
tablas upstream y de las dos referencias; contiene una fila, no se suma al
volumen de origen. No se crean roles ni vistas. Un esquema de control incompleto,
otra definición, propietario o mecanismos de modificación inesperados se rechazan.
La definición se comprueba también al repetir, sin depender de IF NOT EXISTS.

Orden de COPY: clientes, productos, dim_txn, referencia de transacciones,
referencia de cuentas, saldos, movimientos, en tablas temporales de sesión.
Solo en primera carga se insertan desde ellas en las siete tablas persistentes.
Esto evita interpretar los marcadores de NULL de COPY como metacomandos dentro
de una rama omitida de psql. Al repetir también se prepara staging temporal;
ninguna fila persistente se modifica. COPY es STDIN por `docker exec` y
socket local; los datos no se envían a servicios externos ni al agente.

Antes del único COMMIT se verifican hashes/conteos y la consulta SQL independiente
[new_bank_dataset.sql](../sql/integration/checks/new_bank_dataset.sql). Construye
la malla de 5,000 clientes × cuatro productos × seis cortes, comprueba dueños,
cortes previos exactos, tasas, dominio, fórmulas, huérfanos y JOIN sin multiplicación.
No sustituye faltantes por cero ni acepta una diferencia de un centavo.
Las restricciones 002 y los hashes de todo el contenido validan también claves,
nulabilidad crítica, fechas y catálogos. Los seis NULL no proporcionados de cliente
se conservan y comprueban como tales.

Los datos y el manifiesto se confirman juntos. Error o cierre de conexión antes
de COMMIT revierte ambos, incluso el esquema de control creado durante esa carga.
La repetición con identidad y contenido iguales verifica todo y responde
`sin cambios`, sin actualizar filas ni el manifiesto. Datos parciales, semilla,
versión, manifiesto o contenido distinto se rechazan; no se completan ni borran.
Si el cliente pierde la respuesta al COMMIT, repetir inspecciona el estado real.
No existe reset ni limpieza automática.

## CLI y pruebas

Desde la raíz del repositorio, después de revisar que el ensayo es el autorizado:

```powershell
$RunState = '.local-validation\9065d649f8d74222bd04dc58a0e54835\state.json'
.\.venv\Scripts\python.exe -m scripts.new_bank_model inspect --state $RunState
# Sin conexión: genera, calcula huellas y manifiesto; no escribe archivos.
.\.venv\Scripts\python.exe -m scripts.new_bank_model prepare --seed 202601
.\.venv\Scripts\python.exe -m scripts.new_bank_model manifest --seed 202601
# Escritura exclusivamente aislada; no aplica migraciones implícitas.
.\.venv\Scripts\python.exe -m scripts.new_bank_model load --state $RunState --seed 202601
.\.venv\Scripts\python.exe -m scripts.new_bank_model verify --state $RunState --seed 202601

# Fuentes, estructura y generador sin PostgreSQL.
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_new_bank_integration_static.py tests/test_new_bank_model.py
# Pruebas del cargador: crean bases nuevas en el MISMO contenedor aislado.
$env:BANK_MODEL_LOAD_TEST_STATE = (Resolve-Path $RunState).Path
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_new_bank_model_postgres.py
```

La CLI devuelve tiempos de generación, hashing, serialización COPY, transacción
con validación y verificación. `prepare/manifest` imprimen metadatos y hashes;
los registros se preparan en memoria. La verificación regenera la referencia
con la semilla solicitada y consulta el destino en REPEATABLE READ READ ONLY.
No modificar el archivo de referencia ni el código para aceptar una discrepancia.

La suite previa de 65 casos de migración se ejecutó **antes** de cargar, pues sus
fixtures requieren las siete tablas vacías. Después de una carga no ejecutar esa
suite contra la base poblada del ensayo; para repetir sus casos se necesita otro
ensayo vacío autorizado. La suite nueva del cargador crea sus propias bases de
casos y puede repetirse sin borrar nada. Sin su variable explícita se omite.

Pruebas negativas: destino equivocado dentro de la sesión SQL; fallo después de
copiar saldos; centavo incorrecto con hash recalculado para que el control financiero
lo detecte; dos cargas concurrentes; repetición; otra semilla/versión; parcial sin
manifiesto; control o índice incompatibles; rechazo del origen antes de invocar
Docker. Se conserva evidencia local y todas las bases de casos. Las bases negativas
con filas/estructuras incompatibles son evidencia deliberada, no datasets aceptados.

## Riesgos y revisión posterior

El dataset y sus claves mensuales son sintéticos y acotados a enero–junio 2026.
Las anomalías originales, la moneda indefinida, `fec_nac` de PM y la elegibilidad
de todos los productos siguen pendientes de definición de negocio. La referencia
auxiliar no cambia la ausencia de PK/UNIQUE de `dim_txn`.

El ensayo utiliza un rol administrador en un contenedor sin red. No constituye
un despliegue con permisos mínimos, vistas analíticas o autorización del agente.
Los datos completos y el SQL COPY se preparan en memoria; el tamaño es apropiado
para este MVP y no acredita escalabilidad de producción. Los tiempos dependen
del equipo y no son un SLA. Se conservan bases/volumen de prueba; no hay limpieza.

Una carga futura en la base activa requiere otra revisión, respaldo vigente y
adaptador de destino explícitamente autorizado: este cargador la rechaza.
La presente tarea se detiene al validar la carga aislada.

## Resultado medido del ensayo completo

Revisión: 21 de octubre de 2026, America/Mexico_City. **Carga confirmada únicamente
en el entorno aislado; base activa conservada.** Evidencia completa de conteos,
sumas exactas, mínimos/máximos, controles, tiempos, identidad y concurrencia:
[new-bank-model-data-load-validation.json](new-bank-model-data-load-validation.json).
Referencia reproducible: [dataset-202601.manifest.json](../data/source/new_bank_model/dataset-202601.manifest.json).
No contiene filas bancarias, contraseñas ni embeddings.

| Destino comprobado | Valor |
| --- | --- |
| Contenedor | `nbm-pg17-validation-9065d649f8d74222bd04dc58a0e54835` |
| ID completo | `30f2f67bde407bcba30f26f4057df6edd29ed54aabef17c0c3ea9af7b1e92079` |
| Base | `nbm_validation_9065d649f8d74222bd04dc58a0e54835` |
| Volumen | `nbm-validation-9065d649f8d74222bd04dc58a0e54835` |
| PostgreSQL / pgvector | 17.11 / 0.8.7 |
| Red / puertos | none / ninguno |

Antes de escribir se comprobó que las siete tablas estaban vacías, la firma
completa coincidía con 002, el volumen tenía un solo contenedor usuario y el
destino no era el original. También se verificó nuevamente la huella del backup
custom anterior, que conserva su SHA-256 `6d361a97ca2a2f49388ded5773282aff7e0d5b60c187db96f762805af64a3d3d`.
No fue necesario repetir respaldo, restauración o aplicación de migraciones.
001/002 conservan exactamente los hashes que figuran en el reporte anterior.

### Filas realmente confirmadas

| Tabla | Filas |
| --- | ---: |
| dim.dim_cliente | 5,000 |
| dim.dim_producto | 4 |
| dim.dim_txn | 9 |
| cfg.fact_sdos_captacoloca_m | 120,000 |
| cfg.fact_txn_captacoloca_d | 225,000 |
| **Cinco tablas upstream** | **350,013** |
| cfg.ref_cuenta_modelo (auxiliar) | 20,000 |
| cfg.ref_txn_modelo (auxiliar) | 9 |
| bank_model_control.datasets (control operacional) | 1 |

Cada celda siguiente muestra **saldos / movimientos**, con conteos consultados
al destino después de COMMIT y nuevamente después de repetir:

| Corte de 2026 | CHEQUES | AHORRO | C_PERSONAL | TDC |
| --- | ---: | ---: | ---: | ---: |
| 31 enero | 5,000 / 0 | 5,000 / 0 | 5,000 / 0 | 5,000 / 0 |
| 28 febrero | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 15,000 |
| 31 marzo | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 15,000 |
| 30 abril | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 15,000 |
| 31 mayo | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 15,000 |
| 30 junio | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 10,000 | 5,000 / 15,000 |
| **Total por producto** | **30,000 / 50,000** | **30,000 / 50,000** | **30,000 / 50,000** | **30,000 / 75,000** |

20,000 cuentas distintas: 5,000 por producto, cuatro por cliente. Distribuciones
reales: PF 4,800 / PM 200; HOMBRE 2,496 / MUJER 2,304 / NO APLICA 200;
PREMIUM 250 / PREFERENTE 1,000 / MASIVO 3,750. Los seis atributos no poblados
de cliente permanecen NULL en las 5,000 filas.

### Conciliación e identidad verificadas

Los **100,000 pares cuenta/mes de febrero a junio** concilian exactamente; máxima
diferencia absoluta `0.00`. Los 18 contadores de violaciones son cero. Las seis
fechas, continuidad mensual, tasas por cuenta, importes positivos, fórmulas por
producto/código, dominio crudo, asignación y dueño de cuenta, catálogos y JOIN
cumplen las validaciones. Enero contiene 20,000 cierres sin movimientos.
Los hashes SQL coinciden con los del generador, antes de COMMIT y en las dos
verificaciones independientes posteriores. `dim.dim_txn` sigue sin PK/UNIQUE/FK.

Identidad global: `a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b`.
Es la huella del manifiesto canónico, no el SHA-256 de los bytes indentados
del archivo JSON. Semilla `202601`, generador `1.0.0`, algoritmo
`sha256-rounded-uniform-v1`.

| Tabla | SHA-256 del contenido canónico |
| --- | --- |
| dim.dim_cliente | `6c6c9347e8a1511a3ded30348d20e4a0a3d2a7c5017fc6b8758a061a145df66c` |
| dim.dim_producto | `7fc8155a706390c67aea7f9c2b80802bd58b864961c5b1d3034a81c2f543fbb9` |
| dim.dim_txn | `ccdd75284ddffd3b04541d6dac69e03d5c306ff58aa1320af6d8f8e80249d633` |
| cfg.ref_txn_modelo | `59716d997b6d8de85fc7495e5cc54b206bce5b59617531158c1d77bc9dc324d4` |
| cfg.ref_cuenta_modelo | `e0e694ad4eb187219cf4e9c4996d4b191313e3b6bd4e98e38e241aea04076218` |
| cfg.fact_sdos_captacoloca_m | `05a8a3fca8bd52ebbbc98b4b18343a1961b6d83a6ef25b3641325d9ed02345f7` |
| cfg.fact_txn_captacoloca_d | `3bd42112026556770dcf8841786b462dfa9216b60a98e768f62e7e21e618eb69` |

### Repetición, concurrencia y tiempos

La segunda carga de la base principal del ensayo respondió **sin cambios** y
sus datos/manifiesto coinciden exactamente. En la base auxiliar
`nbm_case_9065d649f8d74222_loader_atomic_0baaf195`, dos invocaciones concurrentes
produjeron una respuesta `cargado` y otra `sin cambios`, sin duplicados, con
el mismo hash. La repetición adicional en esa base conservó incluso `xmin` del
manifiesto, comprobando que no se actualizó su fila.

| Medida | Segundos |
| --- | ---: |
| Generación de filas | 0.764 |
| Orden/serialización canónica y hashes | 2.436 |
| Serialización COPY | 1.914 |
| Transacción inicial, staging e integridad/hash/finanzas incluidos | 8.436 |
| Llamada completa de carga, guardas y rehash de entrada incluidos | 14.541 |
| Verificación independiente, después de guardas | 3.268 |
| Segunda carga completa | 9.869 |

Las medidas son de una ejecución local; preparación, carga, dos verificaciones,
repetición y conservación tomaron 39.573 segundos en conjunto. No sumar las medidas
anidadas de la tabla como tiempos independientes.

### Pruebas y problemas encontrados

| Suite | Resultado final |
| --- | ---: |
| Contratos estáticos del paquete de integración | 24 aprobadas |
| Generador, referencias y SQL sin servicios | 18 aprobadas |
| Migraciones/restauración/seguridad anteriores, antes de cargar | 65 aprobadas |
| Cargador real, rollback, calidad, concurrencia e identidades | 13 aprobadas |
| **Total de casos distintos** | **120 aprobadas** |

La suite real del cargador terminó con 13/13 en 126.89 s. La regresión previa
24+65 terminó con 89/89 en 58.12 s. Se mantuvieron los casos anteriores; solo se
actualizó la aserción estática que antes exigía que el generador aún no estuviera
implementado. Ahora exige el módulo separado y mantiene el renderer sin acceso
a servicios. Los archivos JUnit están en el directorio local ignorado del ensayo.

Durante el desarrollo las pruebas detectaron y permitieron corregir tres errores
del cargador: alias `found` ambiguo frente a FOUND de PL/pgSQL; booleano `t/f` de
psql usado como identificador SQL en lugar de literal convertido; y marcadores
COPY interpretados dentro de una rama omitida. Se corrigieron el alias, el cast
y el staging temporal. No hubo que cambiar fórmulas financieras, datos fuente,
restricciones aprobadas ni migraciones para conseguir los resultados. Las
transacciones fallidas revirtieron sus escrituras. En un intento concurrente
previo una conexión llegó a confirmar una copia válida en su propia base auxiliar;
se conserva allí, y las ejecuciones finales usaron otra base auxiliar nueva.
No se borró ni se reinicializó ninguna base, tabla, contenedor o volumen.

La prueba del centavo deliberado recalculó su hash de entrada: aun así falló por
la validación financiera, dejando cero filas confirmadas y sin esquema de control
en ese caso. El fallo inyectado tras insertar saldos también dejó cero filas.
Datos parciales, estructura/control incompatibles, otra semilla y otra versión
se rechazaron sin reemplazo o reparación automática.

Se conservan **26 bases auxiliares** en total en el contenedor del ensayo,
incluidas las de tareas anteriores, las de la regresión 65 y las iteraciones del
cargador. Nombres exactos en `.local-validation/9065d649f8d74222bd04dc58a0e54835/state.json`.
Algunas contienen a propósito una fila o estructura incompatible; no confundirlas
con la base principal aislada validada. No se suministra ni ejecuta limpieza.

### Conservación y anomalías

Antes/después de la carga y pruebas: CUSTOMER 1,000; TRANSACTION 5,000; LOAN 500;
corpora 1; documentos 24, todos con embedding de dimensión 1,024. Coinciden tanto
los snapshots SQL completos como las huellas históricas calculadas con el mismo
método anterior, en la base activa y su copia restaurada:

| Contenido protegido | SHA-256 histórico, sin cambio |
| --- | --- |
| 6,500 registros anteriores | `30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5` |
| Documentos, metadatos y embeddings | `63a6313e870be8268ce7bd85ee0eb8401ebbece4bb6f529b211c4796a6db0847` |

La base activa continúa healthy en el contenedor, base, volumen y puerto 5434
originales, sin `dim`/`cfg`. No se alteraron el agente, corpus, embeddings,
credenciales o SQL upstream. No se implementaron herramientas analíticas ni UI.

Anomalías de fuente **preservadas y clasificadas**: 44 PF con alta anterior al
nacimiento; 1,027 PF menores de 18 al alta (incluye esos 44); cero PF menores de
18 a la referencia upstream 2026-07-15. Persisten `fec_nac` de significado no
aclarado en 200 PM, todos los productos para todos los clientes, 20,000 dominios
de enero expresados como grupo y la semántica temporal de `saldo_apertura`.
Estas excepciones no son fallos de conciliación ni se han corregido. La moneda
continúa no especificada.

### Archivos de esta tarea

Nuevos: `scripts/new_bank_model.py`, las dos consultas
`sql/integration/checks/model_structure.sql` y `new_bank_dataset.sql`, las suites
`tests/test_new_bank_model.py` y `test_new_bank_model_postgres.py`, este documento,
el reporte JSON y `data/source/new_bank_model/dataset-202601.manifest.json`.
Modificados: renderer `scripts/new_bank_integration.py`, manifiesto de diseño,
aserción estática de implementación, notas de gobernanza y enlace del reporte de
runtime. Los SQL 001/002 mantienen sus bytes originales. `.gitignore` ya excluía
los artefactos privados antes de esta tarea; no se publicó nada en GitHub.

**Fin de la tarea: dataset completo verificado únicamente en aislamiento.
La carga o migraciones de la base activa quedan pendientes de revisión.**
