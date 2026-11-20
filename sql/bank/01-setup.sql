USE bank_lab;

CREATE TABLE IF NOT EXISTS account (
    account_id INT PRIMARY KEY,
    account_name VARCHAR(40) NOT NULL,
    balance DECIMAL(12,2) NOT NULL CHECK (balance >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- The ten accounts are generated fixtures for a dedicated lab schema.
DELETE FROM account WHERE account_id = 11;
INSERT INTO account (account_id, account_name, balance) VALUES
    (1, '张三', 1000.00), (2, '李四', 2000.00),
    (3, '王五', 3000.00), (4, '赵六', 4000.00),
    (5, '周七', 5000.00), (6, '吴八', 6000.00),
    (7, '郑九', 7000.00), (8, '冯十', 8000.00),
    (9, '蒋十一', 9000.00), (10, '沈十二', 10000.00)
AS fixture
ON DUPLICATE KEY UPDATE
    account_name = fixture.account_name, balance = fixture.balance;

DROP PROCEDURE IF EXISTS transfer_funds;
DELIMITER //
CREATE PROCEDURE transfer_funds(
    IN p_from_id INT,
    IN p_to_id INT,
    IN p_amount DECIMAL(12,2),
    IN p_lab_abort BOOLEAN
)
BEGIN
    DECLARE low_balance DECIMAL(12,2) DEFAULT NULL;
    DECLARE high_balance DECIMAL(12,2) DEFAULT NULL;
    DECLARE from_balance DECIMAL(12,2);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    IF p_from_id IS NULL OR p_to_id IS NULL OR p_from_id = p_to_id
        OR p_amount IS NULL OR p_amount <= 0
        OR p_lab_abort IS NULL OR p_lab_abort NOT IN (0, 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_TRANSFER';
    END IF;

    -- Both transfer directions lock the lower ID first.
    SELECT balance INTO low_balance
    FROM account WHERE account_id = LEAST(p_from_id, p_to_id) FOR UPDATE;
    SELECT balance INTO high_balance
    FROM account WHERE account_id = GREATEST(p_from_id, p_to_id) FOR UPDATE;

    IF low_balance IS NULL OR high_balance IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ACCOUNT_NOT_FOUND';
    END IF;

    SET from_balance = IF(p_from_id < p_to_id, low_balance, high_balance);

    IF from_balance < p_amount THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INSUFFICIENT_FUNDS';
    END IF;

    UPDATE account SET balance = balance - p_amount
    WHERE account_id = p_from_id;

    IF p_lab_abort THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LAB_ABORT_AFTER_DEBIT';
    END IF;

    UPDATE account SET balance = balance + p_amount
    WHERE account_id = p_to_id;

    COMMIT;
END//
DELIMITER ;
