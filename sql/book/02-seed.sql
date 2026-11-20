USE book_lab;

DROP PROCEDURE IF EXISTS seed_book;
DELIMITER //
CREATE PROCEDURE seed_book()
BEGIN
    -- 取五位十进制数的笛卡尔积，一次 INSERT 写入 100,000 条合成记录。
    INSERT INTO book (id, book_name, author, category, price, book_condition,
                      seller_id, listed_at, status)
    WITH digits AS (
        SELECT 0 AS d UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
        UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6
        UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
    ),
    book_ids AS (
        SELECT 1 + a.d + 10 * b.d + 100 * c.d + 1000 * e.d + 10000 * f.d AS n
        FROM digits a CROSS JOIN digits b CROSS JOIN digits c
        CROSS JOIN digits e CROSS JOIN digits f
    ),
    subjects AS (
        SELECT n, CASE
            WHEN MOD(n, 23) < 4 THEN '计算机'
            ELSE ELT(1 + MOD(n, 5), '文学', '经管', '语言', '理工', '考试')
        END AS category
        FROM book_ids
    )
    SELECT n,
           CASE
               WHEN MOD(n, 1000) = 0 THEN '数据库'
               WHEN MOD(n, 100) = 37 THEN CONCAT('数据库', ELT(
                   1 + MOD(n DIV 100, 8), '原理', '系统导论', '设计实训', '开发手册',
                   '查询优化', '系统概论', '应用基础', '实践教程'
               ))
               ELSE CONCAT(category, ELT(
                   1 + MOD(n DIV 101, 8), '导读', '练习册', '学习笔记', '精选题目',
                   '课程讲义', '基础读本', '习题解析', '实践教程'
               ), '（第', 1 + MOD(n DIV 811, 5), '版）')
           END,
           CONCAT(ELT(1 + MOD(n DIV 73, 8), '陈', '林', '许', '黄', '周', '郑', '王', '吴'),
                  ELT(1 + MOD(n DIV 127, 8), '平', '明', '然', '琳', '晓', '文', '安', '清')),
           category,
           8 + MOD(n * 113, 9800) / 100,
           ELT(1 + MOD(n DIV 11, 3), '九成新', '八成新', '七成新'),
           CASE WHEN MOD(n, 911) = 0 THEN '2023001'
                ELSE CAST(2024000 + MOD(n * 13, 399) AS CHAR) END,
           DATE_ADD('2025-09-01 08:00:00', INTERVAL MOD(n * 7919, 31536000) SECOND),
           IF(MOD(n, 7) < 5, '在售', '已售')
    FROM subjects
    ORDER BY n;
END//
DELIMITER ;

CALL seed_book();
