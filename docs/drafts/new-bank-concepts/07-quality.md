# Borrador: recorrido conceptual de controles

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG. No implementa el especialista Data Quality.

Fuentes: `relationship.transaction_catalog`, `relationship.balance_movement`, `rule.reconciliation`, `temporal.calendar`, `absence.pm_birth`. Ver [sources.json](sources.json).

**Fuente explícita:** las fechas y reglas del generador delimitan enero–junio de 2026; los movimientos se ubican el día 15 y los cierres al final del mes.

**Inferencia técnica verificada:** primero revisar identidad y grano, después existencia de la referencia compuesta, coherencia de cuenta/producto y presencia del mes calendario anterior. Una diferencia numérica no es interpretable si falta un movimiento o el cierre base.

**Propuesta del MVP:** reportar nulos, duplicados, huérfanos, anomalías de fechas y diferencias de conciliación con versión del dataset y regla utilizada. Conservar DDL y valores originales; no convertir faltantes en cero ni aplicar reparaciones automáticas.

**Explicación pedagógica derivada:** si falta abril, comparar mayo directamente con marzo omite un período. El control debe producir «cierre previo faltante», no un cierre corregido. **Dato desconocido:** políticas reales para resolver esas anomalías o interpretación jurídica de PM. Este recorrido describe controles futuros, no resultados calculados por un agente ya implementado.
