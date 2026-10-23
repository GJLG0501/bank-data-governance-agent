/*
Script: 002_generar_cuentas_y_saldos_enero_2026.sql

Objetivo:
- Generar 5,000 cuentas por producto para los 5,000 clientes existentes.
- Asignar una cuenta de cada producto a cada cliente.
- Registrar el saldo inicial y el saldo de enero de 2026 en
  cfg.fact_sdos_captacoloca_m.

Productos y rangos de cuenta:
  CHEQUES    : 100000 - 104999
  AHORRO     : 200000 - 204999
  TDC        : 300000 - 304999
  C_PERSONAL : 400000 - 404999

Rangos inclusivos de saldo:
  CHEQUES    :  8,000.00 -  12,000.00
  AHORRO     :      5.00 -  10,000.00
  TDC        : 10,000.00 - 120,000.00
  C_PERSONAL : 50,000.00 -  85,000.00

Importante:
- Este script NO elimina datos existentes.
- Para evitar duplicados, se detiene si ya existen registros de enero de
  2026 para cualquiera de estos productos en cfg.fact_sdos_captacoloca_m.
- La tabla de saldos mensuales funciona aquí como registro de cuenta/saldo
  para enero. No se crea una tabla maestra independiente de cuentas.
*/

CREATE TABLE cfg.fact_sdos_captacoloca_m (
	num_cta int4 NULL,
	num_cte int4 NULL,
	cve_producto varchar(40) NULL,
	fec_alta date NULL,
	cve_mes_alta int4 NULL,
	saldo_apertura numeric(18, 2) NULL,
	saldo_mes numeric(18, 2) NULL,
	fec_informacion int4 NULL,
	dominio varchar(20) NULL
);

BEGIN;

DO $$
DECLARE
    v_clientes INTEGER;
    v_productos INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO v_clientes
      FROM dim.dim_cliente;

    IF v_clientes <> 5000 THEN
        RAISE EXCEPTION
            'Se esperaban 5000 clientes en dim.dim_cliente; se encontraron %.',
            v_clientes;
    END IF;

    SELECT COUNT(*)
      INTO v_productos
      FROM dim.dim_producto
     WHERE cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
       AND activo IS TRUE;

    IF v_productos <> 4 THEN
        RAISE EXCEPTION
            'Se esperaban los 4 productos activos CHEQUES, AHORRO, TDC y C_PERSONAL; se encontraron %.',
            v_productos;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM cfg.fact_sdos_captacoloca_m
         WHERE cve_mes_alta = 202601
           AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
    ) THEN
        RAISE EXCEPTION
            'Ya existen registros para estos productos con cve_mes_alta = 202601 en cfg.fact_sdos_captacoloca_m. Revise los datos antes de volver a ejecutar el script.';
    END IF;
END
$$;

WITH clientes AS (
    SELECT
        num_cte,
        ROW_NUMBER() OVER (ORDER BY num_cte) - 1 AS consecutivo
    FROM dim.dim_cliente
),
parametros AS (
    SELECT *
    FROM (VALUES
        ('CHEQUES'::VARCHAR(40), 100000::INTEGER,  8000::NUMERIC,  12000::NUMERIC, 'CAPTACION'::VARCHAR(20)),
        ('AHORRO'::VARCHAR(40),  200000::INTEGER,     5::NUMERIC,  10000::NUMERIC, 'CAPTACION'::VARCHAR(20)),
        ('TDC'::VARCHAR(40),     300000::INTEGER, 10000::NUMERIC, 120000::NUMERIC, 'COLOCACION'::VARCHAR(20)),
        ('C_PERSONAL'::VARCHAR(40),400000::INTEGER,50000::NUMERIC, 85000::NUMERIC, 'COLOCACION'::VARCHAR(20))
    ) AS p(cve_producto, cuenta_inicial, saldo_minimo, saldo_maximo, dominio)
),
cuentas AS (
    SELECT
        (p.cuenta_inicial + c.consecutivo)::INTEGER AS num_cta,
        c.num_cte,
        p.cve_producto,
        DATE '2026-01-01' AS fec_alta,
        202601::INTEGER AS cve_mes_alta,
        ROUND(
            (
                p.saldo_minimo
                + RANDOM()::NUMERIC * (p.saldo_maximo - p.saldo_minimo)
            ),
            2
        )::NUMERIC(18,2) AS saldo_inicial,
        p.dominio
    FROM clientes c
    CROSS JOIN parametros p
)
INSERT INTO cfg.fact_sdos_captacoloca_m (
    num_cta,
    num_cte,
    cve_producto,
    fec_alta,
    cve_mes_alta,
    saldo_apertura,
    saldo_mes,
    fec_informacion,
    dominio
)
SELECT
    num_cta,
    num_cte,
    cve_producto,
    fec_alta,
    cve_mes_alta,
    saldo_inicial,
    saldo_inicial,
    20260131::INTEGER AS fec_informacion,
    dominio
FROM cuentas;

-- Validación 1: total esperado por producto (5,000 cada uno).
SELECT
    cve_producto,
    COUNT(*) AS registros_enero,
    COUNT(DISTINCT num_cta) AS cuentas_distintas,
    COUNT(DISTINCT num_cte) AS clientes_asignados,
    MIN(num_cta) AS cuenta_minima,
    MAX(num_cta) AS cuenta_maxima,
    MIN(saldo_apertura) AS saldo_minimo_generado,
    MAX(saldo_apertura) AS saldo_maximo_generado,
    MIN(saldo_mes) AS saldo_mes_minimo,
    MAX(saldo_mes) AS saldo_mes_maximo
FROM cfg.fact_sdos_captacoloca_m
WHERE cve_mes_alta = 202601
  AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
GROUP BY cve_producto
ORDER BY CASE cve_producto
    WHEN 'CHEQUES' THEN 1
    WHEN 'AHORRO' THEN 2
    WHEN 'TDC' THEN 3
    WHEN 'C_PERSONAL' THEN 4
    ELSE 5
END;

-- Validación 2: deben existir 20,000 registros y 20,000 cuentas distintas.
SELECT
    COUNT(*) AS total_registros,
    COUNT(DISTINCT num_cta) AS total_cuentas_distintas,
    COUNT(DISTINCT num_cte) AS clientes_con_cuenta,
    COUNT(*) FILTER (WHERE saldo_apertura IS NULL) AS saldos_apertura_nulos,
    COUNT(*) FILTER (WHERE saldo_mes IS NULL) AS saldos_mes_nulos
FROM cfg.fact_sdos_captacoloca_m
WHERE cve_mes_alta = 202601
  AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL');

-- Validación 3: detectar saldos fuera del rango autorizado.
SELECT
    num_cta,
    num_cte,
    cve_producto,
    saldo_apertura,
    CASE
        WHEN cve_producto = 'CHEQUES'
             AND saldo_apertura BETWEEN 8000 AND 12000 THEN 'OK'
        WHEN cve_producto = 'AHORRO'
             AND saldo_apertura BETWEEN 5 AND 10000 THEN 'OK'
        WHEN cve_producto = 'TDC'
             AND saldo_apertura BETWEEN 10000 AND 120000 THEN 'OK'
        WHEN cve_producto = 'C_PERSONAL'
             AND saldo_apertura BETWEEN 50000 AND 85000 THEN 'OK'
        ELSE 'FUERA DE RANGO'
    END AS validacion
FROM cfg.fact_sdos_captacoloca_m
WHERE cve_mes_alta = 202601
  AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
  AND NOT (
        (cve_producto = 'CHEQUES' AND saldo_apertura BETWEEN 8000 AND 12000)
     OR (cve_producto = 'AHORRO' AND saldo_apertura BETWEEN 5 AND 10000)
     OR (cve_producto = 'TDC' AND saldo_apertura BETWEEN 10000 AND 120000)
     OR (cve_producto = 'C_PERSONAL' AND saldo_apertura BETWEEN 50000 AND 85000)
  )
ORDER BY cve_producto, num_cta;

-- Validación 4: cada cliente debe tener exactamente una cuenta por producto.
SELECT
    num_cte,
    COUNT(*) AS cuentas_asignadas,
    COUNT(DISTINCT cve_producto) AS productos_distintos
FROM cfg.fact_sdos_captacoloca_m
WHERE cve_mes_alta = 202601
  AND cve_producto IN ('CHEQUES', 'AHORRO', 'TDC', 'C_PERSONAL')
GROUP BY num_cte
HAVING COUNT(*) <> 4
    OR COUNT(DISTINCT cve_producto) <> 4
ORDER BY num_cte;

COMMIT;
