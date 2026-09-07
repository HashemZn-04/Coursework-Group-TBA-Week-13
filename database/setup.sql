-- File for re/initializing the database setup
-- DROP DATABASE receipts;
CREATE DATABASE receipts;
\c receipts;

-- Create receipts table based on data_schema.md

CREATE TABLE receipts (
    receipt_id SERIAL PRIMARY KEY,
    receipt_date DATE,
    merchant VARCHAR(60),
    line_items JSONB NOT NULL,
    total_amount INT,
    tax INT,
    payment_method VARCHAR(30),
    currency VARCHAR(10),
    submitter VARCHAR(60),
    raw_file_reference VARCHAR(255),
    source_channel VARCHAR(60),
    status VARCHAR(30),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

