# Borrador: granos y multiplicación de JOIN

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG.

Fuentes: `relationship.account_owner`, `relationship.balance_movement`, `relationship.transaction_catalog`. Ver [sources.json](sources.json).

**Fuente explícita:** el catálogo de transacciones se interpreta por `cve_producto + cve_txn`; el DDL recibido de `dim_txn` no impone PK/UNIQUE.

**Inferencia técnica verificada:** un cierre tiene grano cuenta/producto/mes; varios movimientos pueden corresponder al mismo cierre. Agregar movimientos por ese grano antes de comparar evita repetir el saldo por cada movimiento. Una unión compuesta también multiplica si se duplican pares en la dimensión.

**Explicación pedagógica derivada:** dos movimientos y dos definiciones duplicadas de su mismo par producen cuatro filas de JOIN. Si cada movimiento vale 10 y 20, el total correcto es 30; el JOIN duplicado muestra 60. `DISTINCT` puede ocultar síntomas y también eliminar movimientos legítimos iguales.

**Propuesta del MVP:** validar unicidad del catálogo auxiliar y reportar duplicados de origen. **Dato desconocido:** maestro independiente de cuentas upstream o una equivalencia con las tablas legadas; no asumirlos.
