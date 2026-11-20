USE book_lab;

CREATE TABLE IF NOT EXISTS book (
    id INT UNSIGNED NOT NULL PRIMARY KEY,
    book_name VARCHAR(120) NOT NULL,
    author VARCHAR(60) NOT NULL,
    category VARCHAR(30) NOT NULL,
    price DECIMAL(8, 2) NOT NULL CHECK (price >= 0),
    book_condition VARCHAR(20) NOT NULL,
    seller_id CHAR(7) NOT NULL,
    listed_at DATETIME NOT NULL,
    status ENUM('在售', '已售') NOT NULL
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
