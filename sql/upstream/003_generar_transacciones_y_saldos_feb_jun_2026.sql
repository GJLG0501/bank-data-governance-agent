/*
Script: 003_generar_transacciones_y_saldos_feb_jun_2026.sql

Objetivo:
- Generar movimientos mensuales para cada cuenta entre febrero y junio de 2026.
- Calcular los importes para que el saldo de cierre de cada mes cumpla el
  crecimiento objetivo definido por producto.
- Insertar los movimientos en cfg.fact_txn_captacoloca_d.
- Insertar los saldos de cierre mensuales en cfg.fact_sdos_captacoloca_m.

Crecimiento mensual respecto al saldo de cierre del mes anterior:
  Febrero 2026: Captación 2.0%; Colocación 3.0%.
  Marzo-junio 2026: Captación 1.0%; Colocación 2.2%.

Signo económico de las transacciones:
  CHEQUES/AHORRO : depósito suma; retiro resta.
  C_PERSONAL     : disposiciones suman deuda; pagos la reducen.
  TDC            : compras y disposiciones suman deuda; pagos la reducen.

Los importes almacenados en saldo_txn son positivos. El efecto de suma/resta
se determina por cve_txn/desc_txn. Cada cuenta tendrá una transacción de cada
tipo aplicable por mes.

Distribución de importes:
  CHEQUES/AHORRO:
      retiro = 5% del saldo anterior
      depósito = retiro + incremento objetivo
  C_PERSONAL:
      pago = 5% del saldo anterior
      disposición = pago + incremento objetivo
  TDC:
      compras = 2% del saldo anterior
      disposiciones = 2% del saldo anterior
      pagos = compras + disposiciones - incremento objetivo

Estas reglas producen importes positivos y garantizan que el saldo objetivo
se alcance exactamente al centavo, salvo restricciones de datos existentes.

Importante:
- No elimina datos existentes.
- Se detiene si detecta movimientos previos para febrero-junio de 2026 o
  saldos mensuales previos a esos meses para los cuatro productos.
- Requiere que el script de cuentas/saldos de enero haya terminado bien:
  20,000 cuentas con cierre de enero registrado con fec_informacion = 20260131.
*/

CREATE TABLE cfg.fact_txn_captacoloca_d (
	num_cta int4 NULL,
	num_cte int4 NULL,
	cve_producto varchar(40) NULL,
	fec_txn date NULL,
	cve_mes_txn int4 NULL,
	saldo_txn numeric(18, 2) NULL,
	cve_txn int4 NULL,
        desc_txn varchar(40) NULL,
	fec_informacion int4 NULL,
	dominio varchar(20) NULL
);

BEGIN;

DO $$
DECLARE
    v_clientes INTEGER;
    v_cuentas_enero INTEGER;
    v_mes INTEGER;
    v_mes_anterior INTEGER;
    v_fecha_mes DATE;
    v_fecha_anterior INTEGER;
    v_fecha_informacion INTEGER;
    v_tasa NUMERIC(8,6);
    v_movimientos_esperados INTEGER;
    v_movimientos_generados INTEGER;
    v_saldos_generados INTEGER;
BEGIN
    SELECT COUNT(DISTINCT num_cte)
      INTO v_clientes
      FROM dim.dim_cliente;

    IF v_clientes <> 5000 THEN
        RAISE EXCEPTION
            'Se esperaban 5000 clientes; se encontraron %.', v_clientes;
    END IF;

    SELECT COUNT(*)
      INTO v_cuentas_enero
      FROM cfg.fact_sdos_captacoloca_m
     WHERE fec_informacion = 20260131
       AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL');

    IF v_cuentas_enero <> 20000 THEN
        RAISE EXCEPTION
            'Se esperaban 20000 saldos de enero (fec_informacion=20260131); se encontraron %.',
            v_cuentas_enero;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM cfg.fact_txn_captacoloca_d
         WHERE cve_mes_txn BETWEEN 202602 AND 202606
           AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
    ) THEN
        RAISE EXCEPTION
            'Ya existen transacciones de febrero a junio de 2026 para estos productos. El script se detuvo para evitar duplicados.';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM cfg.fact_sdos_captacoloca_m
         WHERE fec_informacion IN (20260228, 20260331, 20260430, 20260531, 20260630)
           AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
    ) THEN
        RAISE EXCEPTION
            'Ya existen saldos mensuales de febrero a junio de 2026 para estos productos. El script se detuvo para evitar duplicados.';
    END IF;

    -- Tabla temporal para calcular una vez los importes y reutilizarlos
    -- tanto para movimientos como para saldos de cierre.
    CREATE TEMP TABLE tmp_calculo_mes (
        num_cta INTEGER,
        num_cte INTEGER,
        cve_producto VARCHAR(40),
        cve_dominio VARCHAR(20),
        grupo_producto VARCHAR(20),
        fec_alta DATE,
        cve_mes_alta INTEGER,
        saldo_anterior NUMERIC(18,2),
        saldo_objetivo NUMERIC(18,2),
        incremento_objetivo NUMERIC(18,2),
        importe_1 NUMERIC(18,2),
        importe_2 NUMERIC(18,2),
        importe_3 NUMERIC(18,2)
    ) ON COMMIT DROP;

    FOR v_mes IN 202602..202606 LOOP
        v_mes_anterior := CASE
            WHEN v_mes % 100 = 2 THEN 202601
            ELSE v_mes - 1
        END;

        v_fecha_mes := TO_DATE(v_mes::TEXT || '01', 'YYYYMMDD');
        v_fecha_informacion :=
            TO_CHAR((v_fecha_mes + INTERVAL '1 month - 1 day')::DATE, 'YYYYMMDD')::INTEGER;

        v_fecha_anterior :=
            TO_CHAR((v_fecha_mes - INTERVAL '1 day')::DATE, 'YYYYMMDD')::INTEGER;

        TRUNCATE TABLE tmp_calculo_mes;

        INSERT INTO tmp_calculo_mes (
            num_cta, num_cte, cve_producto, cve_dominio, grupo_producto,
            fec_alta, cve_mes_alta, saldo_anterior, saldo_objetivo,
            incremento_objetivo, importe_1, importe_2, importe_3
        )
        SELECT
            ant.num_cta,
            ant.num_cte,
            ant.cve_producto,
            CASE
                WHEN ant.cve_producto IN ('CHEQUES', 'AHORRO') THEN 'DEPOSITS'
                WHEN ant.cve_producto = 'C_PERSONAL' THEN 'LENDING'
                WHEN ant.cve_producto = 'TDC' THEN 'TDC'
            END AS cve_dominio,
            CASE
                WHEN ant.cve_producto IN ('CHEQUES', 'AHORRO') THEN 'CAPTACION'
                ELSE 'COLOCACION'
            END AS grupo_producto,
            ant.fec_alta,
            ant.cve_mes_alta,
            ant.saldo_mes::NUMERIC(18,2) AS saldo_anterior,
            ROUND(
                ant.saldo_mes *
                (1 + CASE
                    WHEN v_mes = 202602 AND ant.cve_producto IN ('CHEQUES', 'AHORRO')
                        THEN 0.02
                    WHEN v_mes = 202602 AND ant.cve_producto IN ('TDC', 'C_PERSONAL')
                        THEN 0.03
                    WHEN ant.cve_producto IN ('CHEQUES', 'AHORRO')
                        THEN 0.01
                    ELSE 0.022
                END),
                2
            )::NUMERIC(18,2) AS saldo_objetivo,
            (
                ROUND(
                    ant.saldo_mes *
                    (1 + CASE
                        WHEN v_mes = 202602 AND ant.cve_producto IN ('CHEQUES', 'AHORRO')
                            THEN 0.02
                        WHEN v_mes = 202602 AND ant.cve_producto IN ('TDC', 'C_PERSONAL')
                            THEN 0.03
                        WHEN ant.cve_producto IN ('CHEQUES', 'AHORRO')
                            THEN 0.01
                        ELSE 0.022
                    END),
                    2
                ) - ant.saldo_mes
            )::NUMERIC(18,2) AS incremento_objetivo,
            CASE
                WHEN ant.cve_producto IN ('CHEQUES', 'AHORRO')
                    THEN ROUND(ant.saldo_mes * 0.05, 2)
                WHEN ant.cve_producto = 'C_PERSONAL'
                    THEN ROUND(ant.saldo_mes * 0.05, 2)
                WHEN ant.cve_producto = 'TDC'
                    THEN ROUND(ant.saldo_mes * 0.02, 2)
            END::NUMERIC(18,2) AS importe_1,
            CASE
                WHEN ant.cve_producto IN ('CHEQUES', 'AHORRO')
                    THEN ROUND(ant.saldo_mes * 0.05, 2)
                WHEN ant.cve_producto = 'C_PERSONAL'
                    THEN ROUND(ant.saldo_mes * 0.05, 2)
                WHEN ant.cve_producto = 'TDC'
                    THEN ROUND(ant.saldo_mes * 0.02, 2)
            END::NUMERIC(18,2) AS importe_2,
            CASE
                WHEN ant.cve_producto = 'TDC'
                    THEN ROUND(ant.saldo_mes * 0.02, 2)
                ELSE NULL
            END::NUMERIC(18,2) AS importe_3
        FROM cfg.fact_sdos_captacoloca_m ant
        WHERE ant.fec_informacion = v_fecha_anterior
          AND ant.cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL');

        IF (SELECT COUNT(*) FROM tmp_calculo_mes) <> 20000 THEN
            RAISE EXCEPTION
                'Mes %: se esperaban 20000 cuentas con saldo anterior; se encontraron %.',
                v_mes, (SELECT COUNT(*) FROM tmp_calculo_mes);
        END IF;

        -- Insertar movimientos. saldo_txn guarda el importe positivo;
        -- el signo se interpreta por el código de transacción.
        INSERT INTO cfg.fact_txn_captacoloca_d (
            num_cta, num_cte, cve_producto, fec_txn, cve_mes_txn,
            saldo_txn, cve_txn, desc_txn, fec_informacion, dominio
        )
        SELECT
            c.num_cta, c.num_cte, c.cve_producto,
            (v_fecha_mes + INTERVAL '14 days')::DATE,
            v_mes,
            CASE
                WHEN c.cve_producto IN ('CHEQUES', 'AHORRO')
                    THEN c.importe_1 + c.incremento_objetivo
                WHEN c.cve_producto = 'C_PERSONAL'
                    THEN c.importe_1 + c.incremento_objetivo
                WHEN c.cve_producto = 'TDC'
                    THEN c.importe_1
            END::NUMERIC(18,2),
            CASE
                WHEN c.cve_producto IN ('CHEQUES', 'AHORRO') THEN 100
                WHEN c.cve_producto = 'C_PERSONAL' THEN 450
                WHEN c.cve_producto = 'TDC' THEN 400
            END,
            CASE
                WHEN c.cve_producto IN ('CHEQUES', 'AHORRO') THEN 'DEPOSITO'
                WHEN c.cve_producto = 'C_PERSONAL' THEN 'DISPOSICIONES'
                WHEN c.cve_producto = 'TDC' THEN 'COMPRAS'
            END,
            v_fecha_informacion,
            c.cve_dominio
        FROM tmp_calculo_mes c

        UNION ALL

        SELECT
            c.num_cta, c.num_cte, c.cve_producto,
            (v_fecha_mes + INTERVAL '14 days')::DATE,
            v_mes,
            CASE
                WHEN c.cve_producto IN ('CHEQUES', 'AHORRO')
                    THEN c.importe_2
                WHEN c.cve_producto = 'C_PERSONAL'
                    THEN c.importe_2
                WHEN c.cve_producto = 'TDC'
                    THEN c.importe_1 + c.importe_2 - c.incremento_objetivo
            END::NUMERIC(18,2),
            CASE
                WHEN c.cve_producto IN ('CHEQUES', 'AHORRO') THEN 200
                WHEN c.cve_producto IN ('C_PERSONAL', 'TDC') THEN 300
            END,
            CASE
                WHEN c.cve_producto IN ('CHEQUES', 'AHORRO') THEN 'RETIRO'
                WHEN c.cve_producto IN ('C_PERSONAL', 'TDC') THEN 'PAGOS'
            END,
            v_fecha_informacion,
            c.cve_dominio
        FROM tmp_calculo_mes c

        UNION ALL

        SELECT
            c.num_cta, c.num_cte, c.cve_producto,
            (v_fecha_mes + INTERVAL '14 days')::DATE,
            v_mes,
            c.importe_3::NUMERIC(18,2),
            450,
            'DISPOSICIONES',
            v_fecha_informacion,
            c.cve_dominio
        FROM tmp_calculo_mes c
        WHERE c.cve_producto = 'TDC';

        GET DIAGNOSTICS v_movimientos_generados = ROW_COUNT;

        v_movimientos_esperados := 45000;
        IF v_movimientos_generados <> v_movimientos_esperados THEN
            RAISE EXCEPTION
                'Mes %: se esperaban % movimientos y se generaron %.',
                v_mes, v_movimientos_esperados, v_movimientos_generados;
        END IF;

        -- Validar que no haya importes de transacción nulos o <= 0.
        IF EXISTS (
            SELECT 1
              FROM cfg.fact_txn_captacoloca_d
             WHERE cve_mes_txn = v_mes
               AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
               AND (saldo_txn IS NULL OR saldo_txn <= 0)
        ) THEN
            RAISE EXCEPTION
                'Mes %: se detectaron importes de transacción nulos o no positivos.',
                v_mes;
        END IF;

        -- Registrar el saldo de cierre del mes; cve_mes_alta permanece 202601
        -- porque representa el mes de apertura de la cuenta.
        INSERT INTO cfg.fact_sdos_captacoloca_m (
            num_cta, num_cte, cve_producto, fec_alta, cve_mes_alta,
            saldo_apertura, saldo_mes, fec_informacion, dominio
        )
        SELECT
            c.num_cta,
            c.num_cte,
            c.cve_producto,
            c.fec_alta,
            c.cve_mes_alta,
            c.saldo_anterior,
            c.saldo_objetivo,
            v_fecha_informacion,
            c.cve_dominio
        FROM tmp_calculo_mes c;

        GET DIAGNOSTICS v_saldos_generados = ROW_COUNT;

        IF v_saldos_generados <> 20000 THEN
            RAISE EXCEPTION
                'Mes %: se esperaban 20000 saldos y se insertaron %.',
                v_mes, v_saldos_generados;
        END IF;

        RAISE NOTICE
            'Mes % procesado: % movimientos, % saldos. Fecha de información %.',
            v_mes, v_movimientos_generados, v_saldos_generados, v_fecha_informacion;
    END LOOP;
END
$$;

COMMIT;

-- VALIDACIÓN 1: movimientos por mes y producto.
SELECT
    cve_mes_txn,
    cve_producto,
    COUNT(*) AS movimientos,
    COUNT(DISTINCT num_cta) AS cuentas_con_movimientos,
    MIN(saldo_txn) AS importe_minimo,
    MAX(saldo_txn) AS importe_maximo
FROM cfg.fact_txn_captacoloca_d
WHERE cve_mes_txn BETWEEN 202602 AND 202606
  AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
GROUP BY cve_mes_txn, cve_producto
ORDER BY cve_mes_txn,
         CASE cve_producto
             WHEN 'CHEQUES' THEN 1
             WHEN 'AHORRO' THEN 2
             WHEN 'TDC' THEN 3
             WHEN 'C_PERSONAL' THEN 4
             ELSE 5
         END;

-- VALIDACIÓN 2: saldos por mes/producto y crecimiento observado.
WITH saldos AS (
    SELECT
        num_cta,
        num_cte,
        cve_producto,
        fec_informacion,
        saldo_mes,
        LAG(saldo_mes) OVER (
            PARTITION BY num_cta, cve_producto
            ORDER BY fec_informacion
        ) AS saldo_mes_anterior
    FROM cfg.fact_sdos_captacoloca_m
    WHERE fec_informacion BETWEEN 20260131 AND 20260630
      AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
)
SELECT
    TO_CHAR(TO_DATE(fec_informacion::TEXT, 'YYYYMMDD'), 'YYYY-MM') AS mes,
    cve_producto,
    COUNT(*) AS cuentas,
    MIN(saldo_mes) AS saldo_minimo,
    MAX(saldo_mes) AS saldo_maximo,
    ROUND(
        AVG(100.0 * (saldo_mes - saldo_mes_anterior) / NULLIF(saldo_mes_anterior, 0)),
        4
    ) AS crecimiento_promedio_pct,
    COUNT(*) FILTER (
        WHERE saldo_mes_anterior IS NOT NULL
          AND saldo_mes <> ROUND(
              saldo_mes_anterior *
              (1 + CASE
                    WHEN fec_informacion = 20260228
                         AND cve_producto IN ('CHEQUES', 'AHORRO') THEN 0.02
                    WHEN fec_informacion = 20260228
                         AND cve_producto IN ('TDC', 'C_PERSONAL') THEN 0.03
                    WHEN cve_producto IN ('CHEQUES', 'AHORRO') THEN 0.01
                    ELSE 0.022
              END),
              2
          )
    ) AS cuentas_con_crecimiento_incorrecto
FROM saldos
GROUP BY fec_informacion, cve_producto
ORDER BY fec_informacion,
         CASE cve_producto
             WHEN 'CHEQUES' THEN 1
             WHEN 'AHORRO' THEN 2
             WHEN 'TDC' THEN 3
             WHEN 'C_PERSONAL' THEN 4
             ELSE 5
         END;

-- VALIDACIÓN 3: el saldo de cierre debe reconciliar con los movimientos.
-- Los importes de saldo_txn son positivos; se aplica el signo según cve_txn.
WITH movimientos AS (
    SELECT
        num_cta,
        cve_producto,
        cve_mes_txn,
        SUM(
            CASE
                WHEN cve_producto IN ('CHEQUES', 'AHORRO') AND cve_txn = 100
                    THEN saldo_txn
                WHEN cve_producto IN ('CHEQUES', 'AHORRO') AND cve_txn = 200
                    THEN -saldo_txn
                WHEN cve_producto = 'C_PERSONAL' AND cve_txn = 450
                    THEN saldo_txn
                WHEN cve_producto = 'C_PERSONAL' AND cve_txn = 300
                    THEN -saldo_txn
                WHEN cve_producto = 'TDC' AND cve_txn IN (400, 450)
                    THEN saldo_txn
                WHEN cve_producto = 'TDC' AND cve_txn = 300
                    THEN -saldo_txn
                ELSE 0
            END
        ) AS movimiento_neto
    FROM cfg.fact_txn_captacoloca_d
    WHERE cve_mes_txn BETWEEN 202602 AND 202606
      AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
    GROUP BY num_cta, cve_producto, cve_mes_txn
),
cierres AS (
    SELECT
        num_cta,
        cve_producto,
        fec_informacion,
        saldo_apertura,
        saldo_mes,
        TO_CHAR(TO_DATE(fec_informacion::TEXT, 'YYYYMMDD'), 'YYYYMM')::INTEGER AS mes
    FROM cfg.fact_sdos_captacoloca_m
    WHERE fec_informacion IN (20260228, 20260331, 20260430, 20260531, 20260630)
      AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
)
SELECT
    c.num_cta,
    c.cve_producto,
    c.mes,
    c.saldo_apertura,
    m.movimiento_neto,
    c.saldo_mes,
    ROUND(c.saldo_apertura + m.movimiento_neto, 2) AS saldo_recalculado,
    ROUND(c.saldo_mes - (c.saldo_apertura + m.movimiento_neto), 2) AS diferencia
FROM cierres c
JOIN movimientos m
  ON m.num_cta = c.num_cta
 AND m.cve_producto = c.cve_producto
 AND m.cve_mes_txn = c.mes
WHERE ABS(c.saldo_mes - (c.saldo_apertura + m.movimiento_neto)) > 0.01
ORDER BY c.mes, c.cve_producto, c.num_cta;
