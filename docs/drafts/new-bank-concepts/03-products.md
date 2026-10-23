# Borrador: productos y dirección económica

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG.

Fuentes: `product.CHEQUES`, `product.AHORRO`, `product.C_PERSONAL`, `product.TDC`, `transaction.TDC.300`, `transaction.TDC.400`, `transaction.TDC.450`. Ver [sources.json](sources.json).

**Fuente explícita:** CHEQUES/AHORRO corresponden a captación; C_PERSONAL/TDC a colocación en este modelo sintético. Las definiciones de movimientos utilizan pares producto/código.

**Explicación pedagógica derivada:** en captación un depósito aumenta el saldo y un retiro lo reduce. En colocación una disposición aumenta deuda y un pago la reduce. En TDC las compras también aumentan deuda. «Aumentar saldo» no significa universalmente aumentar el patrimonio o el dinero disponible del cliente.

**Inferencia técnica verificada:** un pago TDC/300 tiene signo −1, una compra TDC/400 signo +1 y una disposición TDC/450 signo +1. El código aislado no sustituye la identidad compuesta del catálogo.

**Propuesta del MVP:** acompañar cada interpretación con producto, código y alcance. **Dato desconocido:** contabilidad oficial, tasas contractuales, límite de crédito o criterios de elegibilidad; no se infieren del generador.
