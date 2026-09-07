-- File for re/initializing the database setup
-- DROP DATABASE receipts;
CREATE DATABASE receipts;
\c receipts;

-- Create receipts table based on data_schema.md

CREATE TABLE receipts (
    receipt_id SERIAL PRIMARY KEY,
    receipt_date DATE,
    merchant VARCHAR(60),
