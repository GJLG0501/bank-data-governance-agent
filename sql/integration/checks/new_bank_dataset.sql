-- Read-only, independently expressed SQL acceptance rules for the U1/U2/U3 universe.
-- No tolerance, missing-as-zero, implicit code sign, or current-date dependency.
WITH products(product,domain,grp,base,lo,hi,types) AS (VALUES
 ('CHEQUES','DEPOSITS','CAPTACION',100000,8000.00,12000.00,2),
 ('AHORRO','DEPOSITS','CAPTACION',200000,5.00,10000.00,2),
 ('TDC','TDC','COLOCACION',300000,10000.00,120000.00,3),
 ('C_PERSONAL','LENDING','COLOCACION',400000,50000.00,85000.00,2)),
months(cut,previous,month) AS (VALUES (20260131,NULL::int,202601),(20260228,20260131,202602),
 (20260331,20260228,202603),(20260430,20260331,202604),(20260531,20260430,202605),(20260630,20260531,202606)),
net AS MATERIALIZED (
 SELECT t.num_cta,t.cve_producto,t.cve_mes_txn,COUNT(*) AS events,
  COUNT(r.cve_txn) AS known_events,SUM(t.saldo_txn*r.signo_economico) AS net
 FROM cfg.fact_txn_captacoloca_d t LEFT JOIN cfg.ref_txn_modelo r
  ON (t.cve_producto,t.cve_txn)=(r.cve_producto,r.cve_txn)
 GROUP BY t.num_cta,t.cve_producto,t.cve_mes_txn),
grid AS MATERIALIZED (
 SELECT p.*,m.*,c.id,a.num_cte AS account_owner,s.num_cte AS balance_owner,
  s.num_cta AS balance_found,s.saldo_apertura AS opening,s.saldo_mes AS closing,s.dominio,
  s.fec_alta,s.cve_mes_alta,prior.num_cta AS prior_found,prior.saldo_mes AS prior_closing,
  n.events,n.known_events,n.net,
  CASE WHEN m.month=202602 THEN CASE WHEN p.grp='CAPTACION' THEN 0.02 ELSE 0.03 END
       ELSE CASE WHEN p.grp='CAPTACION' THEN 0.01 ELSE 0.022 END END AS rate
 FROM products p CROSS JOIN months m CROSS JOIN generate_series(1,5000) c(id)
 LEFT JOIN cfg.ref_cuenta_modelo a ON (a.num_cta,a.cve_producto)=(p.base+c.id-1,p.product)
 LEFT JOIN cfg.fact_sdos_captacoloca_m s ON (s.num_cta,s.cve_producto,s.fec_informacion)=(p.base+c.id-1,p.product,m.cut)
 LEFT JOIN cfg.fact_sdos_captacoloca_m prior ON (prior.num_cta,prior.cve_producto,prior.fec_informacion)=(p.base+c.id-1,p.product,m.previous)
 LEFT JOIN net n ON (n.num_cta,n.cve_producto,n.cve_mes_txn)=(p.base+c.id-1,p.product,m.month)),
event_rules AS MATERIALIZED (
 SELECT t.*,s.num_cta AS balance_found,
 CASE
  WHEN t.cve_producto IN ('CHEQUES','AHORRO') AND t.cve_txn=200 THEN round(s.saldo_apertura*0.05,2)
  WHEN t.cve_producto IN ('CHEQUES','AHORRO') AND t.cve_txn=100 THEN round(s.saldo_apertura*0.05,2)+s.saldo_mes-s.saldo_apertura
  WHEN t.cve_producto='C_PERSONAL' AND t.cve_txn=300 THEN round(s.saldo_apertura*0.05,2)
  WHEN t.cve_producto='C_PERSONAL' AND t.cve_txn=450 THEN round(s.saldo_apertura*0.05,2)+s.saldo_mes-s.saldo_apertura
  WHEN t.cve_producto='TDC' AND t.cve_txn IN (400,450) THEN round(s.saldo_apertura*0.02,2)
  WHEN t.cve_producto='TDC' AND t.cve_txn=300 THEN 2*round(s.saldo_apertura*0.02,2)-(s.saldo_mes-s.saldo_apertura)
 END AS expected
 FROM cfg.fact_txn_captacoloca_d t LEFT JOIN cfg.fact_sdos_captacoloca_m s
  ON (s.num_cta,s.cve_producto,s.fec_informacion)=(t.num_cta,t.cve_producto,t.fec_informacion)),
balance_groups AS (
 SELECT fec_informacion,cve_producto,COUNT(*) AS rows,MIN(saldo_mes)::text AS min_close,
  MAX(saldo_mes)::text AS max_close,SUM(saldo_apertura)::text AS opening_total,SUM(saldo_mes)::text AS closing_total
 FROM cfg.fact_sdos_captacoloca_m GROUP BY fec_informacion,cve_producto),
event_groups AS (
 SELECT cve_mes_txn,cve_producto,COUNT(*) AS rows,SUM(saldo_txn)::text AS positive_amount_total
 FROM cfg.fact_txn_captacoloca_d GROUP BY cve_mes_txn,cve_producto)
SELECT jsonb_build_object(
 'violations',jsonb_build_object(
  'missing_balances',(SELECT COUNT(*) FROM grid WHERE balance_found IS NULL),
  'ownership',(SELECT COUNT(*) FROM grid WHERE account_owner IS DISTINCT FROM id OR balance_owner IS DISTINCT FROM id),
  'continuity',(SELECT COUNT(*) FROM grid WHERE month>202601 AND (prior_found IS NULL OR opening IS DISTINCT FROM prior_closing)),
  'growth',(SELECT COUNT(*) FROM grid WHERE month>202601 AND closing IS DISTINCT FROM round(opening*(1+rate),2)),
  'january',(SELECT COUNT(*) FROM grid WHERE month=202601 AND (opening IS DISTINCT FROM closing OR opening NOT BETWEEN lo AND hi)),
  'raw_domain',(SELECT COUNT(*) FROM grid WHERE dominio IS DISTINCT FROM CASE WHEN month=202601 THEN grp ELSE domain END),
  'account_dates',(SELECT COUNT(*) FROM grid WHERE fec_alta IS DISTINCT FROM DATE '2026-01-01' OR cve_mes_alta IS DISTINCT FROM 202601),
  'missing_or_unknown_events',(SELECT COUNT(*) FROM grid WHERE month>202601 AND (events IS DISTINCT FROM types::bigint OR known_events IS DISTINCT FROM types::bigint)),
  'reconciliation',(SELECT COUNT(*) FROM grid WHERE month>202601 AND closing IS DISTINCT FROM opening+net),
  'event_formula',(SELECT COUNT(*) FROM event_rules WHERE balance_found IS NULL OR expected IS NULL OR saldo_txn IS DISTINCT FROM expected OR saldo_txn<=0),
  'event_dates',(SELECT COUNT(*) FROM event_rules WHERE fec_txn IS DISTINCT FROM make_date(cve_mes_txn/100,cve_mes_txn%100,15)
    OR cve_mes_txn NOT BETWEEN 202602 AND 202606 OR fec_informacion/100 IS DISTINCT FROM cve_mes_txn),
  'catalog_multiplication',abs(225000-(SELECT COUNT(*) FROM cfg.fact_txn_captacoloca_d t JOIN dim.dim_txn d
    ON (t.cve_producto,t.cve_txn)=(d.cve_producto,d.cve_txn))),
  'catalog_duplicates',(SELECT COUNT(*) FROM (SELECT cve_producto,cve_txn FROM dim.dim_txn GROUP BY 1,2 HAVING COUNT(*)<>1) d),
  'client_rules',(SELECT COUNT(*) FROM dim.dim_cliente WHERE
    num_cte NOT BETWEEN 1 AND 5000
    OR fec_alta IS DISTINCT FROM DATE '2000-01-01'+(num_cte*97%7305)
    OR fec_nac IS DISTINCT FROM CASE WHEN num_cte<=4800 THEN DATE '1945-01-01'+(num_cte*37%21915) ELSE DATE '1960-01-01'+(num_cte*53%23742) END
    OR tipo_persona IS DISTINCT FROM CASE WHEN num_cte<=4800 THEN 'PF' ELSE 'PM' END
    OR genero_cte IS DISTINCT FROM CASE WHEN num_cte>4800 THEN 'NO APLICA' WHEN num_cte<=2496 THEN 'HOMBRE' ELSE 'MUJER' END
    OR segmento_cte IS DISTINCT FROM CASE WHEN num_cte%100<5 THEN 'PREMIUM' WHEN num_cte%100<25 THEN 'PREFERENTE' ELSE 'MASIVO' END
    OR giro_empresa IS NOT NULL OR cve_territorio IS NOT NULL OR cve_dir IS NOT NULL
    OR cve_subdir IS NOT NULL OR cve_sucursal IS NOT NULL OR cve_promotor IS NOT NULL),
  'balance_group_counts',(SELECT COUNT(*) FROM balance_groups WHERE rows<>5000),
  'event_group_counts',(SELECT COUNT(*) FROM event_groups WHERE rows<>CASE WHEN cve_producto='TDC' THEN 15000 ELSE 10000 END),
  'client_orphans',(SELECT COUNT(*) FROM cfg.ref_cuenta_modelo a LEFT JOIN dim.dim_cliente c USING(num_cte) WHERE c.num_cte IS NULL),
  'product_orphans',(SELECT COUNT(*) FROM cfg.ref_cuenta_modelo a LEFT JOIN dim.dim_producto p USING(cve_producto) WHERE p.cve_producto IS NULL)
 ),
 'balances_by_cut_product',(SELECT jsonb_agg(to_jsonb(g) ORDER BY fec_informacion,cve_producto) FROM balance_groups g),
 'movements_by_month_product',(SELECT jsonb_agg(to_jsonb(g) ORDER BY cve_mes_txn,cve_producto) FROM event_groups g),
 'accounts_by_product',(SELECT jsonb_object_agg(cve_producto,n) FROM (SELECT cve_producto,COUNT(*) n FROM cfg.ref_cuenta_modelo GROUP BY 1) a),
 'clients_by_type',(SELECT jsonb_object_agg(tipo_persona,n) FROM (SELECT tipo_persona,COUNT(*) n FROM dim.dim_cliente GROUP BY 1) c),
 'clients_by_gender',(SELECT jsonb_object_agg(genero_cte,n) FROM (SELECT genero_cte,COUNT(*) n FROM dim.dim_cliente GROUP BY 1) c),
 'clients_by_segment',(SELECT jsonb_object_agg(segmento_cte,n) FROM (SELECT segmento_cte,COUNT(*) n FROM dim.dim_cliente GROUP BY 1) c),
 'reconciled_account_months',(SELECT COUNT(*) FROM grid WHERE month>202601 AND closing=opening+net),
 'max_absolute_reconciliation_difference',(SELECT MAX(abs(closing-opening-net))::text FROM grid WHERE month>202601),
 'january_without_movements',(SELECT COUNT(*)=0 FROM cfg.fact_txn_captacoloca_d WHERE cve_mes_txn=202601),
 'anomalies',jsonb_build_object(
  'classification','upstream_preserved_not_corrected',
  'pf_registration_before_birth',(SELECT COUNT(*) FROM dim.dim_cliente WHERE tipo_persona='PF' AND fec_alta<fec_nac),
  'pf_under_18_at_registration',(SELECT COUNT(*) FROM dim.dim_cliente WHERE tipo_persona='PF' AND age(fec_alta,fec_nac)<INTERVAL '18 years'),
  'pf_under_18_at_source_reference',(SELECT COUNT(*) FROM dim.dim_cliente WHERE tipo_persona='PF' AND age(DATE '2026-07-15',fec_nac)<INTERVAL '18 years'),
  'pm_birth_field_undefined',200,
  'january_group_domain_rows',20000,
  'all_clients_have_all_products',true,
  'currency',NULL)
)
