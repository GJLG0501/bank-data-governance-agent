-- Generado por scripts.bank_data; no editar a mano.

-- SHA256 del catalogo normalizado: defc30151b3b1af259f539213bce2f6cde928d11d7638a2fcda46b7496242de7

-- Supuestos educativos: docs/synthetic-data.md. No modifica vector.

CREATE TABLE IF NOT EXISTS "CUSTOMER" (
    "customer_id" TEXT NOT NULL,
    "segment" TEXT NOT NULL,
    "risk_level" TEXT NOT NULL,
    "annual_income" DOUBLE PRECISION NOT NULL,
    CONSTRAINT "customer_pk" PRIMARY KEY ("customer_id"),
    CONSTRAINT "customer_customer_id_nonempty" CHECK (length(btrim("customer_id")) > 0),
    CONSTRAINT "customer_segment_nonempty" CHECK (length(btrim("segment")) > 0),
    CONSTRAINT "customer_segment_allowed" CHECK ("segment" IN ('MASS', 'PREMIER', 'PRIVATE')),
    CONSTRAINT "customer_risk_level_nonempty" CHECK (length(btrim("risk_level")) > 0),
    CONSTRAINT "customer_risk_level_allowed" CHECK ("risk_level" IN ('LOW', 'MEDIUM', 'HIGH')),
    CONSTRAINT "customer_annual_income_range" CHECK ("annual_income" >= 60000 AND "annual_income" <= 12000000)
);

CREATE TABLE IF NOT EXISTS "TRANSACTION" (
    "transaction_id" TEXT NOT NULL,
    "customer_id" TEXT NOT NULL,
    "amount" DOUBLE PRECISION NOT NULL,
    "channel" TEXT NOT NULL,
    "merchant_category" TEXT NOT NULL,
    CONSTRAINT "transaction_pk" PRIMARY KEY ("transaction_id"),
    CONSTRAINT "transaction_transaction_id_nonempty" CHECK (length(btrim("transaction_id")) > 0),
    CONSTRAINT "transaction_customer_id_nonempty" CHECK (length(btrim("customer_id")) > 0),
    CONSTRAINT "transaction_customer_id_fk" FOREIGN KEY ("customer_id") REFERENCES "CUSTOMER" ("customer_id") ON DELETE RESTRICT,
    CONSTRAINT "transaction_amount_range" CHECK ("amount" >= 10 AND "amount" <= 250000),
    CONSTRAINT "transaction_channel_nonempty" CHECK (length(btrim("channel")) > 0),
    CONSTRAINT "transaction_channel_allowed" CHECK ("channel" IN ('BRANCH', 'ATM', 'MOBILE', 'WEB')),
    CONSTRAINT "transaction_merchant_category_nonempty" CHECK (length(btrim("merchant_category")) > 0)
);

CREATE TABLE IF NOT EXISTS "LOAN" (
    "loan_id" TEXT NOT NULL,
    "customer_id" TEXT NOT NULL,
    "balance" DOUBLE PRECISION NOT NULL,
    "interest_rate" DOUBLE PRECISION NOT NULL,
    "dpd" INTEGER NOT NULL,
    CONSTRAINT "loan_pk" PRIMARY KEY ("loan_id"),
    CONSTRAINT "loan_loan_id_nonempty" CHECK (length(btrim("loan_id")) > 0),
    CONSTRAINT "loan_customer_id_nonempty" CHECK (length(btrim("customer_id")) > 0),
    CONSTRAINT "loan_customer_id_fk" FOREIGN KEY ("customer_id") REFERENCES "CUSTOMER" ("customer_id") ON DELETE RESTRICT,
    CONSTRAINT "loan_balance_range" CHECK ("balance" >= 1000 AND "balance" <= 3000000),
    CONSTRAINT "loan_interest_rate_range" CHECK ("interest_rate" >= 5 AND "interest_rate" <= 60),
    CONSTRAINT "loan_dpd_range" CHECK ("dpd" >= 0 AND "dpd" <= 365)
);
