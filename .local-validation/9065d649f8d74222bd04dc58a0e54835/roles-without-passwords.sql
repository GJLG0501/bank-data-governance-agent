--
-- PostgreSQL database cluster dump
--

\restrict Kx2o66MfKdNkCBATPTsBKQJpmJzektWOxG7sNYtKstpGV2alvK947fItAU5oZxb

SET default_transaction_read_only = off;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

--
-- Roles
--

CREATE ROLE bank_governance_dev;
ALTER ROLE bank_governance_dev WITH SUPERUSER INHERIT CREATEROLE CREATEDB LOGIN REPLICATION BYPASSRLS;

--
-- User Configurations
--






\unrestrict Kx2o66MfKdNkCBATPTsBKQJpmJzektWOxG7sNYtKstpGV2alvK947fItAU5oZxb

--
-- PostgreSQL database cluster dump complete
--

