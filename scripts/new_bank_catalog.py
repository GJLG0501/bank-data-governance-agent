"""Offline, reviewed semantic catalog of the immutable U1/U2/U3 laboratory.

Extract physical declarations/catalog rows; curate meanings and qualify every claim.
Never reads customer/account rows, connects to a service or executes upstream SQL.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from scripts import new_bank_integration as design

ROOT=design.ROOT
MODEL_ID="new_bank_2026"
VERSION="1.0.0"
CATALOG_PATH=ROOT/"data/source/new_bank_model/catalog.json"
CLASSIFICATIONS={"upstream_explicit","technical_inference","mvp_proposal"}
M2="sql/integration/002_new_bank_integrity.sql"
M2_HASH="11fb5d9e104b872a16c1e25c23aef8fb3ac9a74fa72cf40f57eb04b1caa29db8"


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_inventory():
    design.verify_sources()
    sources={key:{"id":key,"path":path,"sha256":sha,"origin":"upstream"}
             for key,path,sha,_ in design.SOURCES}
    if hashlib.sha256((ROOT/M2).read_bytes()).hexdigest()!=M2_HASH:
        raise ValueError("Reviewed MVP migration checksum mismatch")
    sources["M2"]={"id":"M2","path":M2,"sha256":M2_HASH,"origin":"mvp"}
    for key,path in (("G1","docs/new-bank-model-governance.md"),("P1","docs/new-bank-model-integration-plan.md")):
        sources[key]={"id":key,"path":path,"sha256":hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),"origin":"mvp"}
    for source in sources.values():
        source["line_count"]=len((ROOT/source["path"]).read_text(encoding="utf-8").splitlines())
    return sources


def reference(sources,key,lo,hi=None):
    source=sources[key]
    hi=lo if hi is None else hi
    lines=(ROOT/source["path"]).read_text(encoding="utf-8").splitlines()
    if not 1<=lo<=hi<=len(lines):
        raise ValueError("Invalid source line range")
    return {"source_id":key,"path":source["path"],"sha256":source["sha256"],
            "line_start":lo,"line_end":hi,"excerpt_sha256":digest("\n".join(lines[lo-1:hi]))}


def ddl_tables(sources):
    tables={}
    for key in ("U1","U2","U3"):
        text=(ROOT/sources[key]["path"]).read_text(encoding="utf-8")
        for match in re.finditer(r"CREATE TABLE\s+(dim\.\w+|cfg\.\w+)\s*\((.*?)\n\);",text,re.S):
            name=match[1]
            start=text[:match.start()].count("\n")+1
            end=text[:match.end()].count("\n")+1
            columns={}
            offset=text[:match.start(2)].count("\n")+1
            for index,line in enumerate(match[2].splitlines()):
                col=re.match(r"\s*(\w+)\s+(INTEGER|INT4|DATE|VARCHAR\(\d+\)|NUMERIC\(\d+,\s*\d+\)|BOOLEAN)(.*)",line,re.I)
                if not col:
                    continue
                field,kind,rest=col.groups()
                physical=re.sub(r"\s+","",kind.upper()).replace("INT4","INTEGER")
                columns[field]={"physical_type":physical,"upstream_declaration":line.strip().rstrip(','),
                    "nullable_upstream":"NOT NULL" not in rest.upper() and "PRIMARY KEY" not in rest.upper(),
                    "primary_key_upstream":"PRIMARY KEY" in rest.upper(),
                    "default_upstream":"TRUE" if "DEFAULT TRUE" in rest.upper() else None,
                    "source_ref":reference(sources,key,offset+index)}
            tables[name]={"source_id":key,"columns":columns,"source_ref":reference(sources,key,start,end)}
    if set(tables)!={t.name for t in design.ORIGINAL_TABLES} or sum(len(t["columns"]) for t in tables.values())!=42:
        raise ValueError("Original DDL coverage mismatch")
    return tables


def insert_rows(sources,table):
    text=(ROOT/sources["U1"]["path"]).read_text(encoding="utf-8")
    block=text.split("INSERT INTO "+table,1)[1].split("VALUES",1)[1].split(';',1)[0]
    return [ast.literal_eval('('+row+')') for row in re.findall(r'\(([^()]*)\)',block)]


def build_catalog():
    sources=source_inventory()
    ddls=ddl_tables(sources)
    entries={}
    def refs(*ranges):
        return [reference(sources,*r) for r in ranges]
    def claim(text,classification,*ranges):
        return {"classification":classification,"text":text,"source_refs":refs(*ranges)}
    def add(identifier,kind,title,claims,attributes=None,terms=()):
        if identifier in entries:
            raise ValueError("Duplicate semantic ID")
        entries[identifier]={"id":identifier,"kind":kind,"title":title,"attributes":attributes or {},
            "query_terms":list(terms),"claims":[dict(item,id=f"{identifier}.c{i}") for i,item in enumerate(claims,1)]}
    explicit=lambda text,*r:claim(text,"upstream_explicit",*r)
    inference=lambda text,*r:claim(text,"technical_inference",*r)
    proposal=lambda text,*r:claim(text,"mvp_proposal",*r)
    add("model.overview","model","Modelo bancario sintético dim/cfg enero–junio 2026",[
        explicit("U1/U2/U3 definen cinco tablas originales: tres dimensiones y dos hechos; clientes y cuentas con cuatro productos y cierres/movimientos sintéticos de enero a junio de 2026.",("U1",1,6),("U2",4,27),("U3",4,44)),
        inference("Es un ejercicio sintético acotado, no una descripción completa de operaciones bancarias reales ni de políticas oficiales del banco.",("U1",1,6),("U3",11,37))],
        {"original_tables":list(ddls),"original_column_count":42},("modelo","laboratorio","tablas","sintético"))
    descriptions={
      "dim.dim_cliente":("Dimensión de clientes sintéticos","Una fila por num_cte; PK num_cte. El generador asigna tipo, género, fechas y segmento; seis atributos adicionales no se pueblan."),
      "dim.dim_producto":("Catálogo de cuatro productos","Una fila por cve_producto, con dominio técnico, grupo, subproducto, descripción y activo."),
      "dim.dim_txn":("Catálogo de definiciones producto/código","Nueve definiciones. No tiene PK, UNIQUE ni FK originales; cve_txn puede repetirse entre productos."),
      "cfg.fact_sdos_captacoloca_m":("Saldos mensuales de cuenta/producto","Grano lógico: cuenta, producto y corte mensual. Enero registra la cuenta/saldo inicial; febrero–junio registran cierres mensuales."),
      "cfg.fact_txn_captacoloca_d":("Movimientos de cuenta/producto/mes/tipo","Grano sintético: una operación de cada tipo aplicable por cuenta/producto/mes. Todas ocurren el día 15, no una serie diaria completa.")}
    for name,table in ddls.items():
        title,description=descriptions[name]
        key=table["source_id"]
        extra=("U1",100,119) if name=="dim.dim_txn" else ("U2",4,27) if "sdos" in name else ("U3",20,34) if "fact_txn" in name else (key,table["source_ref"]["line_start"],table["source_ref"]["line_end"])
        add("table."+name,"table",name+" — "+title,[
            dict(classification="upstream_explicit",text="Columnas físicas: "+", ".join(table["columns"])+".",source_refs=[table["source_ref"]]),
            inference(description,extra)],{"table":name,"origin":"upstream","columns":list(table["columns"]),
                "primary_key_upstream":[n for n,c in table["columns"].items() if c["primary_key_upstream"]],"foreign_keys_upstream":[]},(name,title))
    client={
      "num_cte":("Identificador sintético de cliente", "Se insertan los enteros 1 a 5,000 como num_cte.",("U1",29,35)),
      "fec_alta":("Fecha de alta del cliente", "Alta del cliente = DATE '2000-01-01' + MOD(num_cte*97,7305) días; no es la apertura de su cuenta.",("U1",45,53)),
      "fec_nac":("Fecha sintética fec_nac para PF y PM", "PF: 1945-01-01 + MOD(num_cte*37,21915) días. PM: 1960-01-01 + MOD(num_cte*53,23742) días. La referencia de edad PF es 2026-07-15.",("U1",45,70)),
      "tipo_persona":("Tipo de cliente PF/PM", "U1 asigna PF a num_cte<=4800 y PM al resto; son categorías del laboratorio.",("U1",33,35)),
      "genero_cte":("Género sintético del cliente", "Para PF: HOMBRE hasta num_cte 2496 y MUJER después; para PM: NO APLICA. El DDL admite esas tres cadenas.",("U1",25,26),("U1",37,43)),
      "segmento_cte":("Segmento sintético del cliente", "segmento_cte contiene PREMIUM si MOD(num_cte,100)<5, PREFERENTE si es <25 y MASIVO en otro caso. Es una asignación sintética por identificador, no una segmentación bancaria oficial.",("U1",72,79))}
    product={
      "cve_producto":("Clave de producto","Productos: CHEQUES, AHORRO, C_PERSONAL y TDC."),
      "cve_dominio":("Dominio técnico de producto","CHEQUES/AHORRO usan DEPOSITS; C_PERSONAL usa LENDING; TDC usa TDC."),
      "grupo_producto":("Grupo del producto: captación o colocación","CHEQUES y AHORRO pertenecen a CAPTACION; C_PERSONAL y TDC a COLOCACION."),
      "cve_subproducto":("Clave de subproducto","En los cuatro registros generados, cve_subproducto coincide con cve_producto; no se declara UNIQUE separado."),
      "descripcion":("Descripción del producto","Descripciones: Cuenta de Cheques, Cuenta de Ahorro, Crédito Personal y Tarjeta de Crédito."),
      "activo":("Estado activo del producto","activo tiene DEFAULT TRUE y admite NULL en el DDL; la carga de enero exige los cuatro productos activos IS TRUE.")}
    txn={"cve_producto":("Producto de la definición de transacción","cve_producto identifica a qué producto pertenece cada definición; debe acompañar a cve_txn."),
         "cve_dominio":("Dominio técnico de transacción","DEPOSITS, LENDING o TDC, de acuerdo con el producto del catálogo."),
         "grupo_producto":("Grupo de transacción","CAPTACION para CHEQUES/AHORRO y COLOCACION para C_PERSONAL/TDC."),
         "cve_txn":("Código de tipo de transacción","El código cve_txn se interpreta junto con producto. 100 y 200 se repiten entre CHEQUES/AHORRO; 300 y 450 entre C_PERSONAL/TDC; 400 corresponde a TDC."),
         "desc_txn":("Descripción del tipo de transacción","Las descripciones literales son DEPOSITO, RETIRO, PAGOS, COMPRAS o DISPOSICIONES según producto/código; no son identificadores de eventos.")}
    balances={
      "num_cta":("Identificador de cuenta sintética","Cuenta = base de producto + ROW_NUMBER() por num_cte - 1; una por producto/cliente.",("U2",83,114)),
      "num_cte":("Cliente dueño de la cuenta y del saldo","num_cte proviene de dim_cliente al crear las cuentas, y se hereda a los siguientes cierres.",("U2",83,114),("U3",324,340)),
      "cve_producto":("Producto del saldo mensual","El saldo corresponde a CHEQUES, AHORRO, C_PERSONAL o TDC; no equivale a una tabla del modelo anterior.",("U2",89,114)),
      "fec_alta":("Fecha de apertura de la cuenta","fec_alta de saldos es siempre 2026-01-01 en el laboratorio, y se conserva en los seis cortes. No es fec_alta de dim_cliente.",("U2",100,104),("U3",324,340)),
      "cve_mes_alta":("Mes de apertura de la cuenta, no mes del saldo","cve_mes_alta permanece 202601 en enero–junio: representa la cohorte de apertura. No debe usarse para identificar el mes del cierre.",("U2",100,104),("U3",324,340)),
      "saldo_apertura":("Saldo de inicio del mes; apertura de cuenta solo en enero","En enero saldo_apertura=saldo_mes=saldo_inicial de cuenta. Desde febrero es el cierre del mes calendario anterior. En marzo representa el cierre de febrero, no el saldo inicial de enero.",("U2",127,137),("U3",170,198),("U3",324,340)),
      "saldo_mes":("Saldo de cierre mensual","En enero igual al saldo inicial; después es saldo_objetivo redondeado a dos decimales, calculado desde el cierre del mes anterior.",("U2",127,137),("U3",170,198),("U3",324,340)),
      "fec_informacion":("Corte de información del saldo YYYYMMDD","Entero con el último día del mes: 20260131, 20260228, 20260331, 20260430, 20260531 y 20260630. Distingue los cortes; no es el mes de alta.",("U2",127,137),("U3",135,146)),
      "dominio":("Dominio crudo del saldo cambia de vocabulario","Enero guarda grupo CAPTACION/COLOCACION; febrero–junio guardan dominio técnico DEPOSITS/LENDING/TDC. Son vocabularios diferentes del campo recibido.",("U2",89,112),("U3",159,167),("U3",324,340))}
    movements={
      "num_cta":("Cuenta del movimiento","Se hereda la cuenta del saldo del mes anterior; se interpreta con producto y cliente dueño.",("U3",220,222),("U3",232,239)),
      "num_cte":("Cliente dueño del movimiento","El cliente procede del saldo/cuenta anterior, no de una equivalencia con CUSTOMER.",("U3",156,158),("U3",232,239)),
      "cve_producto":("Producto del movimiento","Producto y código determinan conjuntamente descripción y signo económico.",("U3",15,34),("U3",248,256)),
      "fec_txn":("Fecha sintética de operación","Todas las transacciones de febrero–junio ocurren el día 15 del mes; el modelo no define horas ni secuencia intradía.",("U3",135,143),("U3",232,239)),
      "cve_mes_txn":("Mes de la transacción YYYYMM","Mes de operación entre 202602 y 202606; diferente de cve_mes_alta=202601 y del corte entero YYYYMMDD.",("U3",135,143),("U3",232,239)),
      "saldo_txn":("Importe positivo del movimiento, no importe con signo ni saldo","saldo_txn es un importe positivo almacenado. Para calcular movimiento neto hay que aplicar el signo económico de la combinación producto/cve_txn. No representa el saldo posterior.",("U3",15,37)),
      "cve_txn":("Código de tipo de movimiento por producto","Usar cve_producto junto con cve_txn; no unir solo por código porque se repite en otros productos.",("U1",5,6),("U1",111,119),("U3",248,282)),
      "desc_txn":("Descripción literal del movimiento","Descripción según CASE de producto/tipo: DEPOSITO, RETIRO, PAGOS, COMPRAS o DISPOSICIONES. Debe concordar con el catálogo compuesto.",("U3",248,282)),
      "fec_informacion":("Corte de información del movimiento YYYYMMDD","Último día del mes de operación, diferente de fec_txn (día 15) y del mes YYYYMM.",("U3",135,146),("U3",258,259)),
      "dominio":("Dominio técnico del movimiento","En todos los movimientos febrero–junio se guarda DEPOSITS/LENDING/TDC según producto; no CAPTACION/COLOCACION.",("U3",159,167),("U3",258,259))}
    for table,definition in ddls.items():
        for field,physical in definition["columns"].items():
            subject=table+'.'+field
            claims=[dict(classification="upstream_explicit",text=f"{subject}: tipo físico {physical['physical_type']}; "
                +("admite NULL" if physical["nullable_upstream"] else "NOT NULL")
                +("; clave primaria original" if physical["primary_key_upstream"] else "")
                +("; DEFAULT TRUE" if physical["default_upstream"] else "")+" en el DDL recibido.",source_refs=[physical["source_ref"]])]
            if table=="dim.dim_cliente":
                if field in client:
                    title,text,*rr=client[field]
                    claims.append(explicit(text,*rr))
                else:
                    title="Atributo no poblado: "+field
                    claims.append(inference(f"{field} no se puebla en U1 y permanece NULL. Los archivos no proporcionan catálogo ni definición de negocio suficiente; no inventar significado a partir de la abreviatura.",("U1",12,79)))
            elif table=="dim.dim_producto":
                title,text=product[field]
                claims.append(explicit(text,("U1",82,97),("U2",57,68)) if field=="activo" else
                              inference(text,("U1",82,97)) if field=="cve_subproducto" else explicit(text,("U1",82,97)))
            elif table=="dim.dim_txn":
                title,text=txn[field]
                claims.append(explicit(text,("U1",100,119)))
            else:
                title,text,*rr=(balances if table==design.BALANCE.name else movements)[field]
                # Meanings follow assignments; interpretive cautions are marked inference.
                claims.append(inference(text,*rr))
            attrs={k:v for k,v in physical.items() if k!="source_ref"}
            attrs.update(table=table,column=field,origin="upstream")
            attrs['nullable_mvp']=False if table in (design.BALANCE.name,design.MOVEMENT.name) else physical['nullable_upstream']
            if table in (design.BALANCE.name,design.MOVEMENT.name):
                claims.append(proposal("En el esquema derivado del MVP esta columna del hecho es NOT NULL; ese refuerzo no procede del DDL original nullable.",
                    ("M2",188,261) if table==design.BALANCE.name else ("M2",263,355)))
            add("field."+subject,"field",subject+" — "+title,claims,attrs,(subject,field,title))
    products=insert_rows(sources,"dim.dim_producto")
    transactions=insert_rows(sources,"dim.dim_txn")
    if len(products)!=4 or len(transactions)!=9:
        raise ValueError("Original catalog coverage mismatch")
    parameters={p[0]:p for p in design.PRODUCT_ROWS}
    for product,domain,group,subproduct,description in products:
        pp=parameters[product]
        add("product."+product,"product",product+" — "+description,[
            explicit(f"{product}: {description}; dominio {domain}; grupo {group}; subproducto {subproduct}. "+("Producto de captación." if group=="CAPTACION" else "Producto de colocación."),("U1",94,97)),
            explicit(f"Por cliente se genera una cuenta {product}, rango {pp[3]}–{pp[3]+4999}; saldo inicial entre {pp[4]} y {pp[5]}. No extrapolar esos máximos de enero a otros meses.",("U2",4,27),("U2",83,114))],
            {"product":product,"domain":domain,"group":group,"subproduct":subproduct,"description":description},(product,description,group))
    for product,domain,group,code,description in transactions:
        sign=-1 if (product in ('CHEQUES','AHORRO') and code==200) or (product in ('C_PERSONAL','TDC') and code==300) else 1
        add(f"transaction.{product}.{code}","transaction",f"{product} código {code}: {description}",[
            explicit(f"El código {code} para {product} significa {description}. Dominio {domain}, grupo {group}.",("U1",111,119)),
            explicit(f"{product}/{code} {'suma' if sign==1 else 'resta'} al saldo económico del producto (signo {sign:+d}). El importe se almacena positivo; para colocación, pagos reducen deuda y compras/disposiciones la incrementan.",("U3",15,34))],
            {"product":product,"code":code,"description":description,"economic_sign":sign},(product,str(code),description))
    add("relationship.transaction_catalog","relationship","JOIN dim.dim_txn con cfg.fact_txn_captacoloca_d",[
        explicit("Relacionar por cve_producto + cve_txn, nunca solo cve_txn, para no multiplicar los movimientos. dim_txn no tiene PK/UNIQUE.",("U1",5,6),("U1",100,119)),
        inference("Cardinalidad esperada: una definición por par producto/código frente a muchos movimientos. Comprobar que cada par tiene exactamente una definición; incluso el JOIN compuesto multiplica filas si se duplican pares. No ocultarlo con DISTINCT.",("U1",100,119),("U3",20,22))],
        {"left":"dim.dim_txn","right":design.MOVEMENT.name,"join_columns":["cve_producto","cve_txn"],"expected_cardinality":"1:N"},("join","relación","catálogo transacciones","multiplicación"))
    add("relationship.account_owner","relationship","Relación cliente, cuenta y producto",[
        explicit("U2 cruza clientes con cuatro productos y asigna cuenta por orden de num_cte; todos los clientes reciben una cuenta por producto. Enero funciona como registro de cuentas/saldos; no hay maestro de cuentas independiente upstream.",("U2",4,27),("U2",83,114)),
        inference("Hechos a cliente por num_cte y a producto por cve_producto; comprobar cuenta/producto/cliente coherentes entre meses y movimientos. Una cuenta tiene varios cierres y movimientos; las FK no vienen en los DDL originales.",("U1",12,27),("U1",82,90),("U2",30,40),("U3",47,58))],{},("cliente","cuenta","dueño","relaciones","cardinalidad"))
    add("relationship.balance_movement","relationship","JOIN de saldos y movimientos al grano mensual",[
        inference("Agregar movimientos por num_cta+cve_producto+cve_mes_txn antes de comparar con el saldo del mismo corte. Un JOIN directo de cada movimiento al saldo repite el saldo dos o tres veces; no sumar cierres de varios meses como flujo.",("U3",20,34),("U3",324,340)),
        inference("Relacionar al cierre anterior del mes calendario exacto, no a cualquier fila previa disponible. cve_mes_alta no identifica el mes del cierre.",("U3",135,146),("U3",220,222),("U3",324,340))],{},("join","saldo","movimientos","corte","cardinalidad"))
    add("rule.growth","financial_rule","Crecimiento mensual sintético de captación y colocación",[
        explicit("Febrero 2026: captación 2.0% y colocación 3.0%. Marzo, abril, mayo y junio: captación 1.0% y colocación 2.2%. CHEQUES/AHORRO son captación; C_PERSONAL/TDC colocación.",("U1",94,97),("U3",11,13)),
        explicit("Cierre objetivo = ROUND(saldo anterior*(1+tasa),2); incremento objetivo = cierre objetivo - saldo anterior. Se redondea por cuenta y mes, no una tasa agregada.",("U3",170,198)),
        inference("El crecimiento impuesto no define interés contractual, rentabilidad, mora ni una política de tasas bancarias reales.",("U3",11,37))],
        {"growth_february":{"CAPTACION":"0.02","COLOCACION":"0.03"},"growth_march_june":{"CAPTACION":"0.01","COLOCACION":"0.022"}},("tasa","crecimiento","captación","colocación","abril","interés"))
    for identifier,title,text,lo,hi in [
      ("deposits","Captación: depósitos y retiros","CHEQUES/AHORRO: retiro=ROUND(anterior*0.05,2); depósito=retiro+incremento objetivo. Depósito suma y retiro resta.",25,27),
      ("personal","Colocación C_PERSONAL: pagos y disposiciones","C_PERSONAL: pago=ROUND(anterior*0.05,2); disposición=pago+incremento objetivo. Disposición suma deuda y pago la reduce.",28,30),
      ("card","Colocación TDC: compras, disposiciones y pagos","TDC: compras=ROUND(anterior*0.02,2); disposiciones=ROUND(anterior*0.02,2); pagos=compras+disposiciones-incremento objetivo. Compras/disposiciones suman deuda, pagos restan.",31,34)]:
        add("rule.amounts."+identifier,"financial_rule",title,[explicit(text,("U3",lo,hi),("U3",199,219),("U3",240,282))],{},("importe","fórmula","pagos","depósitos","retiros","compras","disposiciones"))
    add("rule.reconciliation","financial_rule","Conciliación exacta y signo económico de saldo_txn",[
        explicit("Los importes saldo_txn se almacenan positivos. Aplicar signo por producto/código y sumar el neto para alcanzar el cierre objetivo al centavo.",("U3",15,37)),
        proposal("Validar apertura del mes + suma firmada de movimientos = cierre sin tolerancia de un centavo. Comprobar faltantes y huérfanos antes de restar; no reemplazarlos por cero. La regla del MVP no debe confundirse con el filtro de ejemplo >0.01 de U3.",("G1",93,100))],{},("conciliación","neto","saldo_txn","signo","positivo"))
    add("temporal.calendar","temporal_rule","Fechas y períodos: apertura, operación y corte",[
        explicit("Cuenta abierta 2026-01-01, cohorte cve_mes_alta=202601; las operaciones febrero–junio se ubican el día 15; fec_informacion es el último día del mes. Enero define saldo inicial y no movimientos.",("U2",100,104),("U2",127,137),("U3",135,146),("U3",232,239),("U3",324,340)),
        inference("No intercambiar fec_alta del cliente, fec_alta de cuenta, cve_mes_txn, cve_mes_alta y fec_informacion: tienen granos y significados diferentes.",("U1",45,53),("U2",30,40),("U3",47,58))],{},("fechas","períodos","cve_mes_alta","fec_informacion","enero","febrero","marzo"))
    add("temporal.opening_balance","temporal_rule","Qué representa saldo_apertura en marzo",[
        inference("saldo_apertura cambia de alcance temporal: enero registra saldo inicial de cuenta; en febrero–junio guarda el inicio del mes, igual al cierre calendario anterior. En marzo es el cierre de febrero. No debe fijarse al saldo de enero.",("U2",127,137),("U3",170,198),("U3",324,340))],{},("saldo_apertura","apertura","marzo","febrero"))
    add("ambiguity.raw_domain","ambiguity","dominio de enero frente a febrero–junio",[
        inference("dominio crudo de saldos usa CAPTACION/COLOCACION en enero y DEPOSITS/LENDING/TDC después. El catálogo distingue grupo_producto de cve_dominio.",("U1",94,97),("U2",89,112),("U3",159,167),("U3",324,340)),
        proposal("Conservar dominio de origen y derivar una normalización claramente identificada, sin corregir los valores crudos.",("G1",74,79))],{},("dominio","grupo","enero","febrero","normalización"))
    all_upstream=tuple((key,1,sources[key]["line_count"]) for key in ("U1","U2","U3"))
    for identifier,title,text,terms in [
      ("currency","Moneda de los importes no especificada","Los tres SQL no especifican moneda ni unidad monetaria. No se puede concluir MXN, pesos, USD u otra divisa. No heredar moneda del catálogo antiguo.",("moneda","divisa","unidad","MXN","pesos","USD")),
      ("credit_score","Ausencia de columna credit_score","No existe una columna credit_score en ninguna de las cinco tablas originales del nuevo modelo. Los SQL tampoco definen un puntaje crediticio alternativo; no inventarlo.",("credit_score","score","puntaje crediticio")),
      ("pm_birth","Significado no aclarado de fec_nac en PM (personas morales)","U1 genera fec_nac para clientes PM con una fórmula sintética. No explica su significado jurídico ni autoriza llamarla fecha de constitución. La regla de 18 años se evalúa para PF a 2026-07-15, no para PM ni a fecha de alta.",("fec_nac","PM","personas morales","constitución","nacimiento")),
      ("legacy_mapping","No hay equivalencia automática entre LOAN y C_PERSONAL","Los archivos no establecen equivalencias entre LOAN del modelo anterior y C_PERSONAL, ni entre CUSTOMER y dim_cliente o sus segmentos. No relacionarlos automáticamente por códigos o nombres parecidos.",("LOAN","C_PERSONAL","CUSTOMER","equivalencia","modelo anterior")),
      ("banking_features","Características bancarias no definidas por los SQL","No se proporcionan límite de crédito, mora/DPD, tasa contractual, interés, canal, comercio, hora ni orden intradía en el modelo nuevo. El sufijo _d no garantiza detalle diario completo.",("límite","mora","DPD","canal","comercio","diario","hora")),
      ("unknown_client_fields","Atributos de cliente desconocidos o no poblados","giro_empresa, cve_territorio, cve_dir, cve_subdir, cve_sucursal y cve_promotor están declarados pero no poblados por U1. No se proporciona una definición completa ni sus catálogos de referencia.",("giro_empresa","cve_territorio","cve_dir","cve_subdir","cve_sucursal","cve_promotor"))]:
        add("absence."+identifier,"ambiguity",title,[inference(text,*all_upstream)],{},terms)
    add("limitation.synthetic_generation","limitation","Supuestos del generador y alcance del conocimiento documental",[
        explicit("U2 obtiene saldo inicial mediante ROUND(mínimo+RANDOM()*(máximo-mínimo),2); U3 impone crecimientos y una operación por tipo/mes. Todos los clientes reciben los cuatro productos.",("U2",83,114),("U3",11,34)),
        inference("No hay un historial de eventos reales. Las fechas de nacimiento y alta se generan independientemente; los conteos observados de anomalías son resultados de validación de una versión de dataset, no definiciones permanentes ni políticas bancarias.",("U1",45,70),("U3",11,37))],{},("sintético","aleatorio","RANDOM","anomalías","calidad","políticas"))
    for table,lo,hi in [(design.REF_TXN,100,132),(design.REF_ACCOUNT,132,184)]:
        text=("Referencia auxiliar del MVP con clave (cve_producto,cve_txn), descripción, signo y versión; permite FK sin agregar PK/UNIQUE a dim.dim_txn."
              if table==design.REF_TXN else "Referencia auxiliar del MVP de cuenta/producto/cliente, con unicidad de cuenta/producto y cliente/producto; preserva el dueño para FK desde los hechos.")
        add("auxiliary."+table.name,"auxiliary_table",table.name+" — agregada por el MVP, no upstream",[
            proposal(text,("M2",lo,hi))],{"table":table.name,"origin":"mvp","columns":[n for n,_ in table.columns]},(table.name,"auxiliar","gobernanza","integridad"))
    add("proposal.governance_constraints","proposal","Restricciones derivadas y separación entre modelos",[
        proposal("Las migraciones derivadas agregan NOT NULL, claves, FK y CHECK revisados a los hechos y referencias. No son restricciones recibidas en los cinco DDL originales ni políticas oficiales del banco. No alteran la definición sin PK/UNIQUE de dim_txn.",("M2",188,355)),
        proposal("El RAG del MVP recupera conocimiento documental, no filas bancarias ni respuestas analíticas calculadas. No ingerir automáticamente todo el plan como verdad del modelo.",("P1",500,508))],{},("restricciones","NULL","FK","gobernanza","MVP","política","analítica"))
    result={"catalog_format":"new-bank-semantic-catalog-v1","model_id":MODEL_ID,"catalog_version":VERSION,
            "language":"es","upstream_release":None,"official_bank_policy":False,"currency":None,
            "sources":sources,"entries":dict(sorted(entries.items())),
            "original_tables":list(ddls),"auxiliary_tables":[design.REF_TXN.name,design.REF_ACCOUNT.name],
            "scope":"Documentación del esquema y generador; sin filas ni estadísticas observadas de calidad de dataset."}
    validate_catalog(result)
    return result


def validate_catalog(catalog):
    sources=source_inventory()
    if catalog["sources"]!=sources or catalog["model_id"]!=MODEL_ID or catalog["catalog_version"]!=VERSION:
        raise ValueError("Catalog identity/source mismatch")
    entries=catalog["entries"]
    expected_fields={"field."+t.name+'.'+n for t in design.ORIGINAL_TABLES for n,_ in t.columns}
    actual_fields={key for key,e in entries.items() if e["kind"]=="field"}
    if actual_fields!=expected_fields:
        raise ValueError("Catalog field coverage mismatch")
    expected_counts={"table":5,"field":42,"product":4,"transaction":9,"auxiliary_table":2}
    counts=Counter(e["kind"] for e in entries.values())
    if any(counts[key]!=count for key,count in expected_counts.items()):
        raise ValueError("Catalog kind coverage mismatch")
    for key,entry in entries.items():
        if key!=entry["id"] or not entry["claims"] or not entry["title"]:
            raise ValueError("Invalid semantic entry")
        for index,claim in enumerate(entry["claims"],1):
            if claim["classification"] not in CLASSIFICATIONS or not claim["text"] or claim["id"]!=f"{key}.c{index}" or not claim["source_refs"]:
                raise ValueError("Invalid claim identity/classification")
            for ref in claim["source_refs"]:
                if ref!=reference(sources,ref["source_id"],ref["line_start"],ref["line_end"]):
                    raise ValueError("Unverifiable source reference")
                if sources[ref["source_id"]]["origin"]=="mvp" and claim["classification"]!="mvp_proposal":
                    raise ValueError("MVP source misrepresented as upstream/inference")
    return counts


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"))
    args=parser.parse_args(argv)
    catalog=build_catalog()
    text=json.dumps(catalog,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if args.command=="build":
        CATALOG_PATH.write_text(text,encoding="utf-8",newline="\n")
    elif CATALOG_PATH.read_bytes()!=text.encode("utf-8"):
        raise ValueError("Catalog artifact differs from reviewed builder")
    print(json.dumps({"entries":len(catalog["entries"]),"kinds":dict(validate_catalog(catalog)),
                      "sha256":digest(text),"path":str(CATALOG_PATH.relative_to(ROOT))}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
