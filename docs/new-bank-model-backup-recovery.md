# Respaldo, ensayo y conservación — procedimiento preparado

La publicación posterior en desarrollo realizó otro respaldo completo y un
ensayo de restauración de su copia local, con resultados y recuperación en
[publicación principal](new-bank-model-publication.md). El backup anterior y los
ejemplos siguientes conservan su ámbito y fecha; no son el respaldo vigente de
esa publicación ni autorizan restaurar sobre la base activa.

Estado: procedimiento manual de la entrega inicial. Posteriormente se realizó un [respaldo y ensayo real con otro contenedor y volumen](new-bank-model-runtime-validation.md), usando `scripts.new_bank_runtime_validation`, con conservación exacta del origen. Para futuras pruebas de este proyecto debe usarse esa ruta estrictamente aislada; el ejemplo manual de la sección 4 usa otra base en la misma instancia y **no cumple el requisito posterior de contenedor separado**. No mezclar ambas rutas. Los comandos de este documento no se ejecutan automáticamente ni autorizan nuevas operaciones; no se reinicia Docker ni se sustituyen volúmenes del origen.

Estado del ejemplo manual de la sección 4: **no ejecutado**. El ensayo completado y sus resultados corresponden exclusivamente a la ruta de contenedor separado del reporte enlazado.

## Condiciones previas

- Ejecutar desde la raíz Git `bank-data-governance-agent`, PowerShell, con Docker disponible y PostgreSQL 17 ya iniciado. No ejecutar `compose up`, comandos de limpieza o inicialización como parte de este procedimiento.
- Disponer de un destino local **fuera del repositorio y del volumen Docker**, con espacio suficiente y ACL limitada al usuario responsable. Respaldos y reportes no se versionan ni se pegan en el chat. El dump puede contener información sensible aunque este laboratorio sea sintético.
- El usuario/contraseña existentes se mantienen. Los comandos usan el usuario/base configurados **dentro** del contenedor, sin imprimir `.env` ni pasar contraseñas por argumentos. `--no-password` impide prompts interactivos inesperados. Si la autenticación local del contenedor no basta, detenerse y configurar un `PGPASSFILE` externo con permisos restringidos según el procedimiento del operador; no agregar contraseñas a estos archivos, variables de shell escritas literalmente, logs o Git.
- La ejecución inicial debe detenerse antes de cambios de esquema. Acordar una ventana sin escrituras/DDL/ingestiones concurrentes para alinear los snapshots con el dump. `pg_dump` es consistente por sí mismo, pero una instantánea SQL tomada antes/después es otra transacción: **no** comparten snapshot automáticamente. Si hay escritores, coordinar `--snapshot` exportado en un procedimiento posterior o cancelar esta ruta sencilla.
- Verificar permisos para leer todos los objetos de la base y, para el ensayo, crear una base distinta. No usar el rol del agente como rol de administración. No crear ni cambiar roles en la base activa durante la inspección.

Se utiliza formato custom de base completa, sin selección por tabla/esquema: incluye datos, manifiestos y embeddings, DDL, índices y ACL de objetos. `pg_dump` no incluye roles/globales de clúster; se registran aparte sin contraseñas. [Alcance de pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html).

## 1. Inspección y parámetros de la ejecución futura

Los bloques siguientes son para copiar **solo después de autorización**. Comprobar `$LASTEXITCODE` inmediatamente después de cada programa nativo; `$ErrorActionPreference` por sí solo no cubre todos esos fallos.

```powershell
$ErrorActionPreference = 'Stop'
$RunId = 'pre-new-bank-' + [guid]::NewGuid().ToString('N')
$BackupRoot = Join-Path $env:LOCALAPPDATA 'BankGovernanceBackups'
$RunDirectory = Join-Path $BackupRoot $RunId
if (Test-Path -LiteralPath $RunDirectory) { throw 'El destino ya existe' }
New-Item -ItemType Directory -Path $RunDirectory | Out-Null
$ContainerDump = '/tmp/' + $RunId + '.dump'
$DumpPath = Join-Path $RunDirectory 'database.dump'

docker compose ps
if ($LASTEXITCODE -ne 0) { throw 'Fallo al inspeccionar Docker' }
docker compose exec -T bank-postgres pg_dump --version
if ($LASTEXITCODE -ne 0) { throw 'pg_dump no disponible' }
docker compose exec -T bank-postgres pg_restore --version
if ($LASTEXITCODE -ne 0) { throw 'pg_restore no disponible' }

$Preflight = Get-Content -Raw -Encoding UTF8 'sql/integration/checks/preflight.sql' |
    docker compose exec -T bank-postgres sh -c 'exec psql -X --no-password --set=ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
if ($LASTEXITCODE -ne 0) { throw 'Preflight fallido' }
$Preflight | Set-Content -Encoding UTF8 (Join-Path $RunDirectory 'preflight.txt')
```

Revisar manualmente nombre de base, versión 17, `transaction_read_only=on`, extensión y versión esperada de pgvector, propietarios y cualquier objeto ya existente en `dim`/`cfg`. Los cinco objetos protegidos deben existir. La inspección no verifica el esquema creando objetos temporales: [preflight.sql](../sql/integration/checks/preflight.sql) solo realiza SELECT en una transacción READ ONLY.

Los datos actuales documentados son 1,000 CUSTOMER, 5,000 TRANSACTION, 500 LOAN y 24 documentos. Son una referencia histórica, no un permiso para regenerar o sustituir un estado distinto. Registrar y revisar cualquier diferencia.

## 2. Snapshot verificable del modelo anterior

[legacy_snapshot.sql](../sql/integration/checks/legacy_snapshot.sql) devuelve **un JSON** con conteos, hashes SHA-256 de todas las columnas de cada tabla protegida, firmas de columnas/restricciones/índices, extensión y dimensiones de embeddings. Para documentos, la fila completa incluye `embedding`; por ello cambiar un componente cambia el hash. No se llama al modelo ni se recalculan vectores. El hash incluye todos los corpus presentes, no solo uno seleccionado.

```powershell
$BeforeText = Get-Content -Raw -Encoding UTF8 'sql/integration/checks/legacy_snapshot.sql' |
    docker compose exec -T bank-postgres sh -c 'exec psql -X --no-password --quiet --tuples-only --no-align --set=ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
if ($LASTEXITCODE -ne 0) { throw 'Snapshot anterior fallido' }
$Before = ($BeforeText -join "`n") | ConvertFrom-Json
if ($Before.snapshot_format -ne 'legacy-protected-v1' -or $Before.protected.relations_found -ne 5) {
    throw 'Snapshot incompleto o formato inesperado'
}
if ($Before.protected.vectors.null_embeddings -ne 0) { throw 'Embeddings nulos: revisar antes de seguir' }
($BeforeText -join "`n") | Set-Content -Encoding UTF8 (Join-Path $RunDirectory 'legacy-before.json')

Get-FileHash -Algorithm SHA256 -LiteralPath @(
    'data/source/bank_metadata.json', 'data/corpus/bank_metadata.documents.jsonl',
    'sql/upstream/001_dimensiones_cliente_producto_txn.sql',
    'sql/upstream/002_generar_cuentas_y_saldos_enero_2026.sql',
    'sql/upstream/003_generar_transacciones_y_saldos_feb_jun_2026.sql'
) | Select-Object Path,Hash | ConvertTo-Json |
    Set-Content -Encoding UTF8 (Join-Path $RunDirectory 'source-file-hashes.json')
```

El snapshot usa orden por PK y JSONB canónico con formato de fechas/float fijo, bajo REPEATABLE READ READ ONLY. Es adecuado para el volumen actual; `string_agg` no es una solución de hashing por streaming para tablas empresariales grandes. No comparar estos hashes con los hashes semánticos de `docs/agent-validation.json`: son métodos diferentes. Comparar siempre snapshots del mismo formato y PostgreSQL/pgvector compatibles. La sección `context` puede diferir en nombre de base durante el ensayo; se compara la sección `protected`.

## 3. Dump completo y verificación básica

```powershell
docker compose exec -T bank-postgres sh -c 'exec pg_dump --no-password -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file="$1"' sh $ContainerDump
if ($LASTEXITCODE -ne 0) { throw 'Respaldo incompleto: no continuar' }
docker compose cp "bank-postgres:$ContainerDump" $DumpPath
if ($LASTEXITCODE -ne 0) { throw 'No se pudo extraer el respaldo fuera del contenedor' }
if (-not (Test-Path -LiteralPath $DumpPath -PathType Leaf)) { throw 'No existe el dump local' }
if ((Get-Item -LiteralPath $DumpPath).Length -le 0) { throw 'Dump vacio' }

$DumpHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $DumpPath).Hash
$DumpHash | Set-Content -Encoding ASCII (Join-Path $RunDirectory 'database.sha256')
$ArchiveList = docker compose exec -T bank-postgres pg_restore --list $ContainerDump
if ($LASTEXITCODE -ne 0) { throw 'El archivo no se puede listar' }
$ArchiveList | Set-Content -Encoding UTF8 (Join-Path $RunDirectory 'archive-list.txt')

$Roles = docker compose exec -T bank-postgres sh -c 'exec pg_dumpall --no-password --roles-only --no-role-passwords -U "$POSTGRES_USER"'
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron registrar definiciones de roles sin contrasenas' }
$Roles | Set-Content -Encoding UTF8 (Join-Path $RunDirectory 'roles-without-passwords.sql')
```

No redirigir un dump binario por `>` o pipelines de texto de PowerShell: se crea mediante `--file` dentro del contenedor y se copia como archivo. Verificar tamaño/hash de la copia local y conservar además una copia en otro medio protegido según las posibilidades del laboratorio. Registrar versión de PostgreSQL/pgvector, imagen Compose, ruta/hash, hora UTC y responsable en una evidencia local sin secretos. No pegar `docker compose config` resuelto ni el entorno completo en reportes.

Verificar en el listado que se incluyen las tres tablas antiguas, `bank_knowledge.corpora`, `bank_knowledge.documents`, sus TABLE DATA y los objetos necesarios de la extensión vector. El índice del archivo no demuestra que todos los datos sean restaurables. Se exige el ensayo siguiente. `--no-role-passwords` evita que el respaldo de roles almacene hashes de contraseñas; los roles/globales no se importan automáticamente en la instancia activa. [Opciones de pg_dumpall](https://www.postgresql.org/docs/17/app-pg-dumpall.html).

## 4. Ensayo en una base nueva aislada

El ensayo usa la misma instancia y los roles existentes para conservar propietarios/ACL sin alterarlos. Esto crea una base adicional; no modifica tablas de la activa, pero consume disco/CPU. Comprobar capacidad y ejecutar solo cuando esté autorizado. No ensayar por primera vez en el destino activo ni usar opciones de restauración que borren objetos o elijan el nombre de base del archivo.

Comprobar primero que la copia local coincide con el hash registrado, copiarla nuevamente a un **archivo distinto** del contenedor y ensayar esa copia. Así se prueba el respaldo recuperado del equipo, no únicamente el archivo que quedó originalmente en `/tmp`.

```powershell
$ExpectedHash = (Get-Content -Raw (Join-Path $RunDirectory 'database.sha256')).Trim()
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $DumpPath).Hash -ne $ExpectedHash) {
    throw 'El respaldo local cambio'
}
$RestoreDb = 'nbm_restore_' + [guid]::NewGuid().ToString('N')
if ($RestoreDb -notmatch '^nbm_restore_[a-f0-9]{32}$') { throw 'Nombre aislado invalido' }
$RestoreArchive = '/tmp/' + $RestoreDb + '.dump'
docker compose cp $DumpPath "bank-postgres:$RestoreArchive"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo copiar el archivo local para el ensayo' }

$ActiveDb = docker compose exec -T bank-postgres sh -c 'exec psql -X --no-password --quiet --tuples-only --no-align --set=ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT current_database()"'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo identificar la base activa' }
if (($ActiveDb -join '').Trim() -eq $RestoreDb) { throw 'El destino coincide con la base activa' }

# createdb falla si el destino existe; no se reutiliza ni se reemplaza.
docker compose exec -T bank-postgres sh -c 'exec createdb --no-password -U "$POSTGRES_USER" --template=template0 "$1"' sh $RestoreDb
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear una base nueva aislada' }
$StartRestore = [DateTime]::UtcNow
docker compose exec -T bank-postgres sh -c 'exec pg_restore --no-password --exit-on-error --single-transaction -U "$POSTGRES_USER" --dbname="$1" "$2"' sh $RestoreDb $RestoreArchive
if ($LASTEXITCODE -ne 0) { throw 'Ensayo fallido: conservar evidencia, no reintentar sobre esa base' }
$RestoreSeconds = ([DateTime]::UtcNow - $StartRestore).TotalSeconds

$RestoredText = Get-Content -Raw -Encoding UTF8 'sql/integration/checks/legacy_snapshot.sql' |
    docker compose exec -T bank-postgres sh -c 'exec psql -X --no-password --quiet --tuples-only --no-align --set=ON_ERROR_STOP=1 -U "$POSTGRES_USER" --dbname="$1"' sh $RestoreDb
if ($LASTEXITCODE -ne 0) { throw 'Snapshot del ensayo fallido' }
$Restored = ($RestoredText -join "`n") | ConvertFrom-Json
$ExpectedProtected = $Before.protected | ConvertTo-Json -Depth 100 -Compress
$RestoredProtected = $Restored.protected | ConvertTo-Json -Depth 100 -Compress
if ($Restored.snapshot_format -ne $Before.snapshot_format -or $ExpectedProtected -cne $RestoredProtected) {
    throw 'Los datos, estructura o embeddings restaurados difieren'
}
($RestoredText -join "`n") | Set-Content -Encoding UTF8 (Join-Path $RunDirectory 'legacy-restored.json')
```

La comparación JSON usa el orden estable del JSONB emitido por las dos consultas. Exige igualdad exacta de conteos, valores (incluidos vectores), tipos/defaults/restricciones/índices y versión de extensión. Una métrica de similitud semántica o el número de documentos por sí solos no demostrarían conservación de embeddings.

Si se restaura en otra instancia, preparar los roles/propietarios necesarios mediante una revisión separada y con contraseñas fuera de los archivos. Los archivos de extensión pgvector compatibles deben estar instalados en el servidor de ensayo. El dump incluye su definición y `pg_restore` podrá crearla en la base nueva; no es necesario reinstalar o alterar la extensión de la base activa. No asumir que un archivo de roles sin contraseñas permite recuperar automáticamente autenticación o tablespaces personalizados. No se promete recuperación completa de clúster ni PITR con este procedimiento de una sola base.

## 5. Confirmar conservación de la base activa

Antes de autorizar cualquier migración, repetir `legacy_snapshot.sql` contra `$POSTGRES_DB`, parsear el JSON y comparar `protected` con `$Before.protected` usando el mismo procedimiento. Guardar `legacy-after-backup.json`. Cualquier diferencia cancela la ventana: puede haber escrituras concurrentes o estado inesperado; no regenerar datos ni reindexar para forzar coincidencia.

Después de una futura aplicación autorizada de 001/002, y después de cada futura carga, repetir esa misma comparación y los hashes de fuentes/JSONL. La etapa no se acepta si los cinco objetos protegidos difieren. Las migraciones no tienen referencias de escritura a ellos, pero el control independiente sigue siendo necesario. No usar `scripts.bank_data verify`: crea estructura de referencia/bloqueos aunque después los revierta.

Evidencia de aceptación: inspección aprobada; hash de dump local y copia recuperada; listado; restauración con exit code cero; igualdad de `protected`; snapshots vigentes de la activa; fuentes/JSONL intactos; tiempo de ensayo y decisión de revisión. Un dump existente sin ensayo correcto no habilita la escritura.

## 6. Recuperación ante un problema futuro

- Si una migración falla antes de su COMMIT, la sesión debe cerrarse y su transacción se revierte. Revisar el error y conservar evidencia. No continuar después de errores ni retirar restricciones para «hacer pasar» el archivo.
- Si se detecta un problema confirmado después de COMMIT, suspender el uso del nuevo modelo. El agente y corpus antiguos mantienen su configuración. Restaurar el respaldo comprobado en **otra base nueva**, validar y preparar una conmutación explícita revisada; no restaurar encima de la activa ni reemplazar su volumen.
- El punto de recuperación es el del dump. Escritos posteriores no están incluidos y deben conciliarse antes de conmutar. Tiempo de recuperación: el medido en el ensayo, sin prometer un RTO no probado.
- No se incluye limpieza automática de bases de ensayo, archivos de contenedor o respaldos: requieren identificar los destinos y una autorización separada. Registrar lo que queda creado tras el ensayo para evitar acumulación inadvertida. Ninguna operación de limpieza forma parte de esta entrega.

Las opciones de formato custom, destino explícito y error inmediato se documentan en [pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) y [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html). La restauración ejecuta definiciones provenientes del archivo: usar únicamente el respaldo local de procedencia revisada.
