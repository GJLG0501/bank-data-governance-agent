/*
Dimensiones iniciales para el laboratorio financiero PostgreSQL.
Universo: 5,000 clientes; productos CHEQUES, AHORRO, C_PERSONAL y TDC.
ADVERTENCIA: script destructivo; DROP TABLE elimina las tablas existentes.
dim_txn no tiene PK/UNIQUE, como se solicitó. Los JOIN a dim_txn deben usar
cve_producto + cve_txn para no multiplicar movimientos.
*/
BEGIN;
CREATE SCHEMA IF NOT EXISTS dim;

DROP TABLE IF EXISTS dim.dim_cliente CASCADE;
CREATE TABLE dim.dim_cliente (
  num_cte INTEGER NOT NULL PRIMARY KEY,
  fec_alta DATE,
  fec_nac DATE,
  tipo_persona VARCHAR(10),
  genero_cte VARCHAR(10),
  segmento_cte VARCHAR(20),
  giro_empresa VARCHAR(30),
  cve_territorio VARCHAR(255),
  cve_dir VARCHAR(255),
  cve_subdir VARCHAR(255),
  cve_sucursal INTEGER,
  cve_promotor VARCHAR(10),
  CHECK (tipo_persona IN ('PF','PM')),
  CHECK (genero_cte IN ('HOMBRE','MUJER','NO APLICA'))
);

----------- INSERTAMOS CLIENTES EN LA TABLA  
INSERT INTO dim.dim_cliente(num_cte)
SELECT generate_series(1,5000);

-- Distribución exacta: 4,800 PF (96%) y 200 PM (4%).
UPDATE dim.dim_cliente
SET tipo_persona = CASE WHEN num_cte <= 4800 THEN 'PF' ELSE 'PM' END;

-- Género PF exacto: 2,496 hombres y 2,304 mujeres (52%/48%).
UPDATE dim.dim_cliente
SET genero_cte = CASE
  WHEN tipo_persona='PM' THEN 'NO APLICA'
  WHEN num_cte <= 2496 THEN 'HOMBRE'
  ELSE 'MUJER'
END;

-- Fechas sintéticas determinísticas.
UPDATE dim.dim_cliente
SET fec_nac = DATE '1945-01-01' + MOD(num_cte * 37, 21915)::INTEGER
WHERE tipo_persona='PF';
UPDATE dim.dim_cliente
SET fec_nac = DATE '1960-01-01' + MOD(num_cte * 53, 23742)::INTEGER
WHERE tipo_persona='PM';
UPDATE dim.dim_cliente
SET fec_alta = DATE '2000-01-01' + MOD(num_cte * 97, 7305)::INTEGER;

------------------------------Validando de que todos los clientes PF sean mayores de edad  
SELECT
    COUNT(*) AS total_clientes_pf,
    COUNT(*) FILTER (
        WHERE fec_nac IS NULL
    ) AS sin_fecha_nacimiento,
    COUNT(*) FILTER (
        WHERE fec_nac IS NOT NULL
          AND AGE(DATE '2026-07-15', fec_nac) < INTERVAL '18 years'
    ) AS menores_de_edad,
    COUNT(*) FILTER (
        WHERE fec_nac IS NOT NULL
          AND AGE(DATE '2026-07-15', fec_nac) >= INTERVAL '18 years'
    ) AS mayores_de_edad
FROM dim.dim_cliente
WHERE tipo_persona = 'PF';

--- Agregandop el segmento al que pértenecen los clientes

UPDATE dim.dim_cliente
SET segmento_cte = CASE
  WHEN MOD(num_cte,100) < 5 THEN 'PREMIUM'
  WHEN MOD(num_cte,100) < 25 THEN 'PREFERENTE'
  ELSE 'MASIVO'
END;

DROP TABLE IF EXISTS dim.dim_producto CASCADE;
CREATE TABLE dim.dim_producto (
  cve_producto VARCHAR(40) NOT NULL PRIMARY KEY,
  cve_dominio VARCHAR(20) NOT NULL,
  grupo_producto VARCHAR(20) NOT NULL,
  cve_subproducto VARCHAR(40) NOT NULL,
  descripcion VARCHAR(100),
  activo BOOLEAN DEFAULT TRUE,
  CHECK (cve_dominio IN ('DEPOSITS','LENDING','TDC'))
);
INSERT INTO dim.dim_producto
  (cve_producto,cve_dominio,grupo_producto,cve_subproducto,descripcion)
VALUES
  ('CHEQUES','DEPOSITS','CAPTACION','CHEQUES','Cuenta de Cheques'),
  ('AHORRO','DEPOSITS','CAPTACION','AHORRO','Cuenta de Ahorro'),
  ('C_PERSONAL','LENDING','COLOCACION','C_PERSONAL','Crédito Personal'),
  ('TDC','TDC','COLOCACION','TDC','Tarjeta de Crédito');

DROP TABLE IF EXISTS dim.dim_txn CASCADE;
-- Sin PK/UNIQUE: cve_txn puede repetirse entre productos.
CREATE TABLE dim.dim_txn (
  cve_producto VARCHAR(40) NOT NULL,
  cve_dominio VARCHAR(20) NOT NULL,
  grupo_producto VARCHAR(20) NOT NULL,
  cve_txn INTEGER NOT NULL,
  desc_txn VARCHAR(40) NOT NULL
);
INSERT INTO dim.dim_txn
  (cve_producto,cve_dominio,grupo_producto,cve_txn,desc_txn)
VALUES
  ('CHEQUES','DEPOSITS','CAPTACION',100,'DEPOSITO'),
  ('CHEQUES','DEPOSITS','CAPTACION',200,'RETIRO'),
  ('AHORRO','DEPOSITS','CAPTACION',100,'DEPOSITO'),
  ('AHORRO','DEPOSITS','CAPTACION',200,'RETIRO'),
  ('C_PERSONAL','LENDING','COLOCACION',300,'PAGOS'),
  ('C_PERSONAL','LENDING','COLOCACION',450,'DISPOSICIONES'),
  ('TDC','TDC','COLOCACION',300,'PAGOS'),
  ('TDC','TDC','COLOCACION',400,'COMPRAS'),
  ('TDC','TDC','COLOCACION',450,'DISPOSICIONES');
COMMIT;

-- VALIDACIONES
SELECT COUNT(*) AS total_clientes,
       COUNT(DISTINCT num_cte) AS clientes_unicos,
       MIN(num_cte) AS min_cliente, MAX(num_cte) AS max_cliente
FROM dim.dim_cliente;

SELECT tipo_persona, COUNT(*) AS clientes,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),2) AS porcentaje
FROM dim.dim_cliente GROUP BY tipo_persona ORDER BY tipo_persona;

SELECT genero_cte, COUNT(*) AS clientes,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),2) AS porcentaje
FROM dim.dim_cliente WHERE tipo_persona='PF'
GROUP BY genero_cte ORDER BY genero_cte;

SELECT MIN(fec_alta) AS min_fec_alta, MAX(fec_alta) AS max_fec_alta,
       COUNT(*) FILTER (WHERE fec_alta IS NULL) AS altas_nulas,
       COUNT(*) FILTER (WHERE fec_nac IS NULL) AS fec_nac_nulas
FROM dim.dim_cliente;

SELECT * FROM dim.dim_producto ORDER BY cve_producto;
SELECT * FROM dim.dim_txn ORDER BY cve_producto,cve_txn;

-- Informa de códigos de transacción repetidos entre productos.
SELECT cve_txn, COUNT(*) AS filas,
       COUNT(DISTINCT cve_producto) AS productos
FROM dim.dim_txn
GROUP BY cve_txn HAVING COUNT(*)>1
ORDER BY cve_txn;

