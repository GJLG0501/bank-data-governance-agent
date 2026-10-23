--
-- PostgreSQL database cluster dump
--

\restrict BfAzkuOwDbIlKa6e11mpjjltr5S15IfQykkRC275htaCfmil2eD2A3vVMkfP2AQ

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






\unrestrict BfAzkuOwDbIlKa6e11mpjjltr5S15IfQykkRC275htaCfmil2eD2A3vVMkfP2AQ

--
-- PostgreSQL database cluster dump complete
--

