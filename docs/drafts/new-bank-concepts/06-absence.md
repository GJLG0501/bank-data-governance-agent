# Borrador: explicar ausencias sin inventar información

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG.

Fuentes: `absence.currency`, `absence.banking_features`, `absence.credit_score`, `absence.legacy_mapping`, `absence.pm_birth`. Ver [sources.json](sources.json).

**Inferencia técnica verificada sobre las fuentes:** los SQL no especifican moneda, tasa contractual, puntaje crediticio alternativo o equivalencias automáticas con LOAN/CUSTOMER. Las fichas documentan esas ausencias; no prueban lo que existe en un banco real u otro sistema.

**Explicación pedagógica derivada:** a «¿los importes están en USD?» corresponde explicar «los SQL no especifican moneda; no puede concluirse USD» con la ficha de ausencia. No hace falta borrar esa explicación mediante una abstención genérica. A un campo desconocido sin evidencia corresponde abstenerse sin afirmar su inexistencia universal.

**Fuente explícita:** las columnas físicas existentes siguen siendo las declaradas en los tres SQL. **Propuesta del MVP:** distinguir `explicit_absence`, evidencia insuficiente y capacidad no disponible. **Dato desconocido:** los valores externos solicitados, no completarlos con conocimiento general del LLM ni con el corpus legado.
