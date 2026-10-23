# Borrador: apertura original y continuidad mensual

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG.

Fuentes: `temporal.opening_balance`, `temporal.calendar`, `field.cfg.fact_sdos_captacoloca_m.saldo_apertura`. La procedencia completa y hashes están en [sources.json](sources.json).

**Fuente explícita:** U2 asigna en enero el mismo saldo inicial a `saldo_apertura` y `saldo_mes`. U3 usa el cierre calendario anterior para construir los meses siguientes.

**Inferencia técnica verificada:** desde febrero, `saldo_apertura` representa el comienzo del mes actual. El cierre de ese mismo mes incorpora los movimientos: no debe identificarse automáticamente con su apertura.

**Explicación pedagógica derivada:** enero = apertura inicial; febrero = cierre de enero; marzo = cierre de febrero; abril = cierre de marzo; mayo = cierre de abril; junio = cierre de mayo. Estas correspondencias se verifican por calendario, cuenta y producto. Un hueco en abril no permite usar marzo como apertura de mayo sin reportar la falta del cierre de abril.

**Propuesta del MVP:** informar un faltante de continuidad en lugar de rellenarlo con cero o con cualquier fila previa. **Dato desconocido:** reglas para períodos fuera de enero–junio de 2026 y procesos bancarios reales de reapertura de cuentas.
