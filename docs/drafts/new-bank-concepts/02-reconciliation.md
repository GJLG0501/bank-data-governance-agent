# Borrador: de movimientos positivos al cierre

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG.

Fuentes: `rule.growth`, `rule.amounts.deposits`, `rule.amounts.personal`, `rule.amounts.card`, `rule.reconciliation`. Ver [sources.json](sources.json).

**Fuente explícita:** los importes de movimientos se almacenan positivos. Los signos dependen de producto y código. El generador fija el crecimiento y redondea el cierre por cuenta y mes.

**Explicación pedagógica derivada:** supongamos un cierre anterior de 10,000.00 en captación durante marzo. Objetivo: 10,100.00; incremento: 100.00; retiro: 500.00; depósito: 600.00. Entonces 10,000.00 + 600.00 − 500.00 = 10,100.00.

Para TDC, cierre anterior supuesto 20,000.00 y crecimiento de marzo 2.2%: objetivo 20,440.00; compras 400.00; disposiciones 400.00; pagos 360.00. El neto es +440.00. Para C_PERSONAL, cierre anterior supuesto 60,000.00: objetivo 61,320.00; pago 3,000.00; disposición 4,320.00; neto +1,320.00.

Los ejemplos son números didácticos, no consultas a cuentas del dataset. **Inferencia técnica:** el signo es imprescindible para conciliar; sumar todos los importes positivos falla. **Propuesta del MVP:** comprobar faltantes y huérfanos antes de exigir igualdad exacta al centavo. **Dato desconocido:** moneda e interés contractual; estos crecimientos no los definen.
