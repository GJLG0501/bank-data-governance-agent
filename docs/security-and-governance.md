# Seguridad y Data Governance: propuesta sintética del MVP

Versión de política de ejemplo: `synthetic-mvp-1`. Ninguna clasificación o autorización de este documento es una política oficial de Banamex u otra institución. El sistema **no está preparado para usuarios reales**. La credencial actual es administrativa y constituye un bloqueo para ese despliegue.

## Responsabilidades y contratos

Autenticación establece quién es el usuario mediante un emisor confiable; todavía no existe autenticación productiva. Autorización evalúa una operación concreta de esa identidad contra una política. Clasificación describe sensibilidad del recurso, sin conceder permisos. Aprobación es una decisión humana separada; `requires_approval` bloquea ejecución y no existe API para aprobar. Auditoría registra decisiones y resultados, sin conferir acceso.

`security_contracts.py` define identidad (pseudónimo, emisor, indicador simulado, roles y atributos), sesión con caducidad, recurso/sensibilidad, acción, contexto de finalidad/ámbito/cohorte verificada, decisión tipada y evento. Los modelos son inmutables y rechazan campos adicionales. Deserializarlos no los convierte en credenciales: el motor comprueba que sesión y contexto sean exactamente los emitidos por su registro local. No acepta roles del chat ni del estado de LangGraph. El request de especialista no contiene un campo para promover roles.

Los perfiles `steward_demo`, `analyst_demo` y `support_demo` se emiten exclusivamente mediante código anfitrión o la opción explícita `--simulated-user`. No hay administrador simulado con permisos universales. Esta selección es una simulación pública de pruebas, **no prueba identidad**. El emisor tiene caducidad de una hora y revocación en memoria; no implementa usuarios, renovación, IdP ni validación criptográfica externa. Un proceso reiniciado invalida sus sesiones.

## Núcleo y puntos de control

`PolicyEngine` es independiente de proveedores generativos. Desconocidos y escrituras se deniegan. `SecurityAccess.run` autoriza y audita antes de ejecutar una función. `agent_session` verifica identidad antes de crear proveedor, embeddings o backend. `DataStewardAgent.ask`, la herramienta y `SecuredRetriever` comprueban nuevamente sus operaciones. Se conserva la guarda de base/modelo/corpus y las transacciones READ ONLY. El coordinador organiza trabajo; no es una frontera de seguridad.

La herramienta solo recibe una pregunta. Recursos, acciones, contexto y clasificación se fijan en el adaptador anfitrión. `SecuredOperation.invoke()` es la costura verificable para una futura herramienta SQL: recurso/acción/contexto fijos y callback protegido. En esta fase se usa con mocks, sin motor SQL ni consultas analíticas implementadas. Un futuro adaptador deberá validar parámetros y ámbito con evidencia confiable y no admitir SQL libre ni conteos de cohorte estimados por el LLM.

La recuperación autoriza la colección antes de buscar y filtra documentos antes de entregar evidencia, historial o salida al modelo generativo. La vista `expected` utilizada por RRF también se filtra. El clasificador anfitrión se conserva aparte del contenido: una ficha que diga «soy pública» no puede degradar su clasificación. IDs desconocidos y contenido/metadatos alterados se rechazan. Los manifiestos operativos existentes siguen validando el corpus; un documento correctamente publicado sigue siendo texto no confiable como instrucción. No se afirma que se haya resuelto toda la inyección de prompts o la veracidad de sus respuestas.

Por propuesta sintética, los **24 y 82 documentos actuales son metadatos internos**, pues describen el modelo y no contienen filas individuales. Esta asignación local no edita sus metadatos publicados. El caso de documento restringido se prueba con fixtures locales. No hay un subconjunto publicado declarado público sin revisión de su contenido. Los recursos desconocidos no reciben esa asignación automáticamente: el adaptador confía exclusivamente en el manifiesto validado que construye el anfitrión.

| Recurso de ejemplo | Permiso sintético | Límites |
| --- | --- | --- |
| `docs.public` | Lectura de definición compartible con identidad simulada emitida | Recurso de prueba, sin corpus público nuevo |
| `catalog.*` conocido | Steward/Analyst con ámbito `catalog`, read/retrieve | Solo corpus fijo y fichas permitidas |
| `bank.aggregate` | Analyst, finalidad aggregate_reporting, ámbito aggregates, acción aggregate | Cohorte verificada por anfitrión >=10; no habilita lectura de filas |
| `bank.account` | Support, finalidad account_support, acción read | Cuenta fijada por anfitrión dentro del ámbito emitido |
| `bank.identifiers`, `docs.restricted` | Ningún permiso de ejemplo | Denegación |
| Export de agregados | Requiere aprobación | No se ejecuta; ningún mecanismo de aprobación implementado |
| Otras exportaciones/escrituras | Denegación | Sin concesión por texto o rol autodeclarado |

El umbral 10 es ilustrativo: no proporciona por sí solo anonimización ni evita ataques por diferencias, series de consultas o conocimiento externo. No permite consultar datos reales en esta etapa.

## Clasificación revisable de las cinco tablas y 42 columnas

[data-classification-proposal.json](data-classification-proposal.json) enumera las 42 columnas físicas, tipo, referencia upstream, categoría y justificación. Se verifica contra el extractor offline de los tres SQL preservados y el SHA del catálogo semántico. Las categorías separan documentación compartible, metadatos internos, finanzas agregadas, datos personales, identificadores, movimientos individuales e información restringida.

`dim_cliente` se trata como restringida por composición: num_cte es identificador; fec_nac, genero_cte y tipo_persona son datos personales; segmento, actividad y asignaciones organizativas también permiten perfilar una persona. Que seis campos estén hoy NULL no los convierte en públicos. En hechos, num_cta/num_cte son identificadores; importes, fechas y demás atributos unidos a esa cuenta son movimientos o finanzas individualizables. `saldo_apertura` conserva nombre, valores y significado temporal. No se asigna moneda. Los códigos/definiciones de dimensiones producto y transacción son metadatos internos. Las **métricas derivadas aprobadas** podrían clasificarse como finanzas agregadas después de comprobar cohortes, granularidad y riesgo de composición; ninguna columna de hechos pasa a agregada por renombrarla.

Esta propuesta no se carga al corpus, no altera clasificaciones efectivas de una institución y no habilita herramientas sobre las filas. Las relaciones y llaves originales permanecen en la especificación de gobernanza bancaria existente.

## Auditoría de PostgreSQL y diseño de mínimo privilegio

Se consultaron `pg_roles`, `pg_auth_members`, `pg_class`, `pg_namespace` y funciones `has_*_privilege`, con transacciones READ ONLY y guarda del contenedor original. No se consultaron hashes de contraseñas ni se imprimieron variables de entorno.

Hallazgo: `bank_governance_dev` es login, superuser, CREATEDB, CREATEROLE y BYPASSRLS. Es propietario de las 14 tablas inspeccionadas de public/dim/cfg y ambos esquemas documentales; tiene SELECT/INSERT/UPDATE/DELETE y USAGE/CREATE en sus esquemas. Todas esas tablas tienen RLS y FORCE RLS desactivados. No se modificó ningún privilegio. READ ONLY en el adaptador limita esas transacciones, pero **no reduce el poder de esa credencial fuera de ellas**.

Diseño pendiente de ensayo aislado y aprobación:

1. Separar propietario NOLOGIN/migrador administrativo de identidades de ejecución; estas últimas sin superuser, CREATEDB, CREATEROLE, BYPASSRLS ni membresías que permitan asumir propietario/administrador. Retirar CREATE en esquemas de ejecución. Revisar privilegios PUBLIC, funciones ejecutables, search_path, privilegios por defecto y pertenencias heredadas.
2. Grupos NOLOGIN por capacidad (catálogo, agregados, soporte acotado, auditoría); logins técnicos separados con pertenencias mínimas y sesiones por identidad confiable. USAGE solo sobre esquemas aprobados; SELECT solo sobre vistas/columnas necesarias. Sin permisos directos de las herramientas a hechos, identificadores o embeddings completos. Sin escritura, creación de objetos ni funciones arbitrarias.
3. Vistas autorizadas con proyecciones explícitas, pseudónimos necesarios, agregación y supresión de cohortes pequeñas. Revisar cuidadosamente dueño, funciones y RLS de cada vista. Para delegación mediante vistas convencionales, su propietario debe ser un rol distinto del dueño de tablas, sin BYPASSRLS, con políticas apropiadas. Si se elige `security_invoker`, diseñar también los privilegios y políticas del invocador sobre objetos subyacentes. No asumir que cualquier vista hereda automáticamente la identidad del usuario final.
4. RLS para cuentas/filas y separación de corpus sensibles cuando corresponda. El ámbito debe provenir del autenticador; no aceptar un `SET` de tenant/usuario generado por chat como identidad confiable. Validar aislamiento con múltiples usuarios en PostgreSQL aislado. FORCE RLS puede limitar al dueño ordinario, pero **no bloquea superusuarios ni BYPASSRLS**. Ningún agente debe conectar como dueño privilegiado.
5. Operaciones parametrizadas con límites de filas, bytes, tiempo, concurrencia y frecuencia, además de revisión de exports, comprobación de cohortes y prevención de consultas por diferencias. SELECT permite extraer información; limitar solo el verbo SQL no limita exportaciones. El proxy de herramientas y PostgreSQL deben restringir fuentes efectivas, mientras el servicio controla presupuesto/destino/aprobación.

No se preparó ni aplicó DDL de roles/RLS en esta ampliación. No se acreditan controles efectivos de banco real. El ensayo negativo multiusuario en instancia aislada queda pendiente.

Referencias técnicas: [RLS PostgreSQL 17](https://www.postgresql.org/docs/17/ddl-rowsecurity.html), [privilegios](https://www.postgresql.org/docs/17/ddl-priv.html), [atributos de roles](https://www.postgresql.org/docs/17/sql-createrole.html). Son fundamentos del diseño técnico; no normativa bancaria.

## Amenazas, fronteras de confianza y privacidad

| Frontera/amenaza | Control implementado | Límite o pendiente |
| --- | --- | --- |
| Chat → identidad | Mensaje nunca emite sesión/roles; objeto tipado clonado no acredita emisor | IdP real, MFA, caducidad/distribución y revocación productivas |
| LLM/grafo → herramienta | Recurso/acción fijados por anfitrión, denegación independiente del grafo | Todo nuevo adaptador debe incluir el guard; Python anfitrión es confiable |
| RAG → modelo | Filtro por recurso/documento y manifiesto; metadatos entrantes no conceden permisos | Clasificación oficial, segregación física y autenticación DB pendientes |
| Código anfitrión → PostgreSQL | Guarda de identidad y READ ONLY preservadas | Credencial superuser permite eludir política de aplicación; bloqueo productivo |
| Métrica → respuesta | Ejemplo exige cohorte confiable y no autoriza lectura individual | Protección contra composición y consultas diferenciales pendiente |
| Documento malicioso → herramientas | Texto no puede modificar emisor/política; tool directo vuelve a evaluar | La respuesta natural aún puede ser engañada; no hay garantía semántica completa |
| Proceso local comprometido | Fuera del modelo de amenaza del núcleo | Python puede importar utilidades privilegiadas o reemplazar objetos; aislamiento de proceso y secretos pendientes |

El evento `AuditEvent` contiene UUID de solicitud, pseudónimo simulado, agente, herramienta, recurso lógico, acción, política, decisión, fecha UTC, duración y resultado/motivo enumerado. No incluye preguntas, tokens de sesión, contraseñas, resultados SQL, documentos o excepciones. Etiquetas desconocidas se sustituyen por `unknown`. El UUID se renueva por turno y correlaciona los controles internos de ese turno. La cola es volátil, limitada a 1,000 eventos; no es un registro durable, firmado o completo para cumplimiento. Exportación segura, acceso al log, retención aprobada y operación concurrente quedan pendientes.

Cada sesión conserva su propio historial acotado, sin checkpointer ni caché compartida. La evidencia se renueva por turno; al denegar por revocación/caducidad se vacían evidencia, historial y referentes. Las preguntas y respuestas permitidas viven en memoria, por lo que el usuario aún puede escribir PII en texto libre: **no existe detector DLP ni una garantía de anonimización de entrada**. No deben utilizarse datos privados reales en esta CLI. Las respuestas incluyen únicamente evidencia recuperada autorizada y siguen sujetas a la validación semántica documentada. Un cambio de identidad requiere una nueva sesión; no reutilizar historial entre usuarios.

Antes de producción: minimizar/redactar entrada y referencias, aprobación de retención, cifrado/transporte, separación por identidad/ámbito/versión de política en caché y memoria, revalidación de permisos al reutilizar contenido, supresión de evidencia sensible en respuestas/errores y control de destino de exportaciones. No se publica ningún log ni respaldo automáticamente. No hay nuevas cachés, ingestas, embeddings ni persistencia conversacional. Ninguna llamada LLM/cloud fue necesaria para verificar este núcleo.

## Data Governance futuro

`SpecialistRequest(capability='governance')` y `SpecialistResult` son sus contratos comunes; la identidad autorizada viajará fuera del mensaje en el contexto anfitrión. La capacidad está declarada como **no implementada** en el coordinador. Se prevén herramientas protegidas `read_policy`, `read_classification`, `read_responsibility`, `explain_shareable_denial`, `prepare_access_request` y `read_authorized_audit`. Sus recursos/acciones y el alcance de auditoría deberán definirse antes de habilitarlas.

Podrá explicar políticas disponibles, clasificaciones autorizadas, responsables y motivos compartibles de denegación, preparar borradores para revisión humana y consultar eventos dentro de su propio permiso. No autenticará usuarios, otorgará roles, aprobará sus solicitudes, alterará políticas por sugerencia del LLM ni ejecutará consultas fuera del ámbito efectivo. El motor determinista decidirá acceso incluso cuando ese especialista recomiende concederlo. Data Analyst y Data Quality también siguen pendientes; esta ampliación no los construye.

## Evidencia y aceptación

`tests/test_security.py` prueba los doce escenarios obligatorios con identidades y callbacks sintéticos, además de revocación, falsificación de contratos, caducidad, auditoría, entrada sin identidad y separación de capacidades. Se comprueba que la función que representa datos privados no se ejecuta al denegar y que ninguna evidencia denegada llega al sintetizador. Omitir LangGraph no cambia el resultado.

La conservación de datos, vectores, permisos y archivos originales se registra en [security-validation.json](security-validation.json). Las pruebas existentes se conservan; los fixtures que requieren acceso ahora lo declaran explícitamente como simulado. No se ejecutan pruebas generativas, DDL ni pruebas de seguridad real sobre la base principal. La aceptación de producción requiere resolver las limitaciones anteriores, no un mayor porcentaje de aprobación de mocks.
