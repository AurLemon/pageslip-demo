USE book_lab;

CREATE INDEX idx_book_name ON book (book_name);
CREATE INDEX idx_book_category_status_price ON book (category, status, price);
CREATE INDEX idx_book_seller ON book (seller_id);

ANALYZE TABLE book;
