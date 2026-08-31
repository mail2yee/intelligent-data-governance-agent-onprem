-- Fake business data for the "customer-capacity-allocation" catalog
-- product's real underlying database (see docker-compose.yml's
-- fab-business-db service and HANDOFF.md's "Real NL-to-SQL against
-- business data" section). Auto-run by the postgres image's own
-- docker-entrypoint-initdb.d mechanism on first container start (only
-- - never re-runs against an existing data volume, matching every
-- other init-once script in this repo).
--
-- Table/column names here are what
-- wren/business_capacity_plan/models/*.yml's MDL actually declares -
-- keep both in sync if either changes. Entirely fictional company
-- names/numbers, not real business data.

CREATE TABLE capacity_plan (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    product_node VARCHAR(20) NOT NULL,
    week_start DATE NOT NULL,
    allocated_capacity INT NOT NULL,
    actual_wafer_starts INT NOT NULL,
    utilization_pct NUMERIC(5, 2) NOT NULL
);

CREATE TABLE customer_commitment (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    commitment_quarter VARCHAR(10) NOT NULL,
    committed_volume INT NOT NULL,
    confirmed_volume INT NOT NULL,
    status VARCHAR(20) NOT NULL
);

CREATE TABLE wafer_start_actuals (
    id SERIAL PRIMARY KEY,
    lot_id VARCHAR(20) NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    product_node VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    wafer_count INT NOT NULL,
    fab_line VARCHAR(20) NOT NULL
);

INSERT INTO capacity_plan (customer_name, product_node, week_start, allocated_capacity, actual_wafer_starts, utilization_pct) VALUES
    ('Acme Semiconductor', 'N5', '2026-08-03', 1200, 1150, 95.83),
    ('Acme Semiconductor', 'N5', '2026-08-10', 1200, 1180, 98.33),
    ('Acme Semiconductor', 'N5', '2026-08-17', 1250, 1240, 99.20),
    ('Nova Photonics', 'N7', '2026-08-03', 800, 720, 90.00),
    ('Nova Photonics', 'N7', '2026-08-10', 800, 790, 98.75),
    ('Nova Photonics', 'N7', '2026-08-17', 850, 810, 95.29),
    ('Zenith Circuits', 'N5', '2026-08-03', 600, 540, 90.00),
    ('Zenith Circuits', 'N5', '2026-08-10', 600, 610, 101.67),
    ('Zenith Circuits', 'N5', '2026-08-17', 650, 630, 96.92);

INSERT INTO customer_commitment (customer_name, commitment_quarter, committed_volume, confirmed_volume, status) VALUES
    ('Acme Semiconductor', '2026-Q3', 15000, 14800, 'Confirmed'),
    ('Acme Semiconductor', '2026-Q4', 16000, 12000, 'Tentative'),
    ('Nova Photonics', '2026-Q3', 9500, 9500, 'Confirmed'),
    ('Nova Photonics', '2026-Q4', 10000, 6000, 'Tentative'),
    ('Zenith Circuits', '2026-Q3', 7200, 7100, 'Confirmed'),
    ('Zenith Circuits', '2026-Q4', 7800, 4000, 'Tentative');

INSERT INTO wafer_start_actuals (lot_id, customer_name, product_node, start_date, wafer_count, fab_line) VALUES
    ('LOT-A1001', 'Acme Semiconductor', 'N5', '2026-08-17', 25, 'FAB-3'),
    ('LOT-A1002', 'Acme Semiconductor', 'N5', '2026-08-18', 25, 'FAB-3'),
    ('LOT-A1003', 'Acme Semiconductor', 'N5', '2026-08-19', 24, 'FAB-3'),
    ('LOT-N2001', 'Nova Photonics', 'N7', '2026-08-17', 20, 'FAB-2'),
    ('LOT-N2002', 'Nova Photonics', 'N7', '2026-08-18', 22, 'FAB-2'),
    ('LOT-Z3001', 'Zenith Circuits', 'N5', '2026-08-17', 18, 'FAB-3'),
    ('LOT-Z3002', 'Zenith Circuits', 'N5', '2026-08-18', 21, 'FAB-3');
