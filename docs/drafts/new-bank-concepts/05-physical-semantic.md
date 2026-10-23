# Borrador: origen físico, significado y reglas MVP

Estado: propuesta pedagógica, pendiente de revisión. No publicado en RAG.

Fuentes: `field.cfg.fact_sdos_captacoloca_m.fec_informacion`, `ambiguity.raw_domain`, `absence.pm_birth`. Ver [sources.json](sources.json).

**Fuente explícita:** `fec_informacion` es INTEGER nullable en el DDL recibido. **Propuesta del MVP:** el hecho derivado refuerza esa columna con NOT NULL. Ambas declaraciones pertenecen a capas distintas y no se contradicen si se identifica su procedencia.

**Inferencia técnica verificada:** `dominio` conserva CAPTACION/COLOCACION en enero y DEPOSITS/LENDING/TDC después. Una categoría normalizada debe aparecer como derivación identificada, conservando el valor crudo.

**Explicación pedagógica derivada:** «la columna admite NULL upstream» describe una definición física; «la carga MVP exige un valor» describe un control añadido. Ninguna frase autoriza a atribuir al SQL original la restricción posterior.

**Dato desconocido:** el significado jurídico de `fec_nac` de personas morales. La fórmula sintética no acredita fecha de constitución. Tampoco las fechas anómalas deben corregirse silenciosamente.
