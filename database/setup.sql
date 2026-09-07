-- File for re/initializing the database setup
-- DROP DATABASE receipts;
CREATE DATABASE receipts;
\c receipts;

-- Create receipts table based on data_schema.md
-- status = state-machine state (D1): pending_review | approved | rejected | escalated
-- verdict lives in its own table below (AI opinion), NOT here (human/final state) —
-- keeping them separate is what lets C6 query "approved" without caring how it got there.

CREATE TABLE receipts (
    receipt_id SERIAL PRIMARY KEY,
    receipt_date DATE,
    merchant VARCHAR(60),
    line_items JSONB NOT NULL,
    total_amount NUMERIC(10, 2),
    tax NUMERIC(10, 2),
    payment_method VARCHAR(30),
    category VARCHAR(60),
    currency VARCHAR(10),
    submitter VARCHAR(60),
    raw_file_reference VARCHAR(255),
    source_channel VARCHAR(60),
    status VARCHAR(30) NOT NULL DEFAULT 'pending_review',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI verdicts (C3/C4 write here). Append-only, never UPDATE/DELETE a row —
-- if A4 retunes the prompt and re-runs it, insert a new row. That's what makes
-- the audit trail immutable per C1/D4's acceptance criteria: every verdict a
-- receipt ever got is still there, not overwritten by the latest one.
CREATE TABLE verdicts (
    verdict_id SERIAL PRIMARY KEY,
    receipt_id INT NOT NULL REFERENCES receipts(receipt_id),
    verdict VARCHAR(20) NOT NULL CHECK (verdict IN ('compliant', 'flagged', 'high_risk')),
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Human decisions (D2 writes here on approve/reject click). Also append-only —
-- an escalation-after-reject is a new row, not an edit to the reject row.
CREATE TABLE decisions (
    decision_id SERIAL PRIMARY KEY,
    receipt_id INT NOT NULL REFERENCES receipts(receipt_id),
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('approved', 'rejected', 'escalated')),
    decided_by VARCHAR(60) NOT NULL,
    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE INDEX idx_verdicts_receipt_id ON verdicts(receipt_id);
CREATE INDEX idx_decisions_receipt_id ON decisions(receipt_id);

