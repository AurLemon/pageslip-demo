USE book_lab;

-- 三条题定 SQL。分别在主键基线与建立二级索引后运行。
EXPLAIN SELECT * FROM book WHERE book_name LIKE '数据库%';
EXPLAIN SELECT * FROM book WHERE category='计算机' AND price BETWEEN 20 AND 50 AND status='在售';
EXPLAIN SELECT * FROM book WHERE seller_id='2023001';

EXPLAIN ANALYZE SELECT * FROM book WHERE book_name LIKE '数据库%';
EXPLAIN ANALYZE SELECT * FROM book WHERE category='计算机' AND price BETWEEN 20 AND 50 AND status='在售';
EXPLAIN ANALYZE SELECT * FROM book WHERE seller_id='2023001';

-- 二级索引建好后，对照两个返回同一批记录的等值谓词。
EXPLAIN SELECT * FROM book WHERE book_name='数据库';
EXPLAIN SELECT * FROM book WHERE UPPER(book_name)='数据库';
EXPLAIN ANALYZE SELECT * FROM book WHERE book_name='数据库';
EXPLAIN ANALYZE SELECT * FROM book WHERE UPPER(book_name)='数据库';
