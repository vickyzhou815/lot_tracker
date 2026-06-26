-- This file is automatically run by the official MySQL Docker image
-- the FIRST time the container starts with an empty data directory
-- (i.e. the first time mysql-data volume is created). This is a
-- documented behavior of the mysql:8.0 image: any .sql or .sh file
-- placed in /docker-entrypoint-initdb.d/ inside the container runs
-- once, in alphabetical order, on that first startup only.
--
-- This is the same CREATE TABLE statements we ran by hand on your
-- Mac's MySQL earlier - now automated, so a fresh deployment doesn't
-- require manually re-typing schema setup.

CREATE TABLE IF NOT EXISTS lots (
    lot_id VARCHAR(50) PRIMARY KEY,
    wafer_count INT NOT NULL,
    current_step VARCHAR(20) NOT NULL,
    current_eqp_id VARCHAR(50) NOT NULL,
    current_state VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS lot_events (
    event_id INT AUTO_INCREMENT PRIMARY KEY,
    lot_id VARCHAR(50) NOT NULL,
    step_id VARCHAR(20) NOT NULL,
    eqp_id VARCHAR(50) NOT NULL,
    state VARCHAR(20) NOT NULL,
    hold_reason VARCHAR(30) NULL,
    timestamp DATETIME NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id)
);
