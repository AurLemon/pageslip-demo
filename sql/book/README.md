# 任务 5 / 二手书检索

存储过程用五位十进制数的笛卡尔积生成 100,000 条合成书目。数据库前缀、完全同名书和指定卖家的数据都按固定规则生成。执行计划和计时由 MySQL 实际运行得出。

在工程根目录启动并初始化专用 MySQL 容器后，使用 Python 3.10 或更新版本执行：

`python3 sql/book/collect.py --output /tmp/pageslip-book-evidence`

脚本会重建演示库的 `book_lab.book`，运行造数、主键基线、二级索引和函数对照，结束时保留带索引的十万行测试表。脚本用 `docker compose exec -T db` 进入容器，可用 `PAGESLIP_DB_USER` 和 `PAGESLIP_DB_PASSWORD` 覆盖实验账号。

- `01-schema.sql` 建表，`02-seed.sql` 定义并调用造数存储过程。
- `03-indexes.sql` 建立书名、分类/状态/价格、卖家三个二级索引。
- `04-queries.sql` 记录题目指定的查询和函数对照。手工验证时在建索引前后各执行前三条查询的分析语句，再做等值与函数对照。
- `book.json` 保存表规模、数据分布、执行计划、分析树、计时样本和结果摘要校验。`before.txt`、`after.txt` 及 `function.txt` 保存对应的 MySQL 客户端原始表格。

`EXPLAIN.rows` 是优化器对当前访问步骤的估计，`scan_rows` 取 `EXPLAIN ANALYZE` 访问节点的实际输出行数。执行时间取一次预热后七次运行的根节点完成时间中位数，单位为毫秒，不含客户端进程启动和网络传输时间。测试前后对每条原始 `SELECT *` 的完整返回集求校验，同样检查等值与 `UPPER()` 对照的返回集。

[MySQL EXPLAIN 文档](https://dev.mysql.com/doc/refman/8.4/en/explain.html) / [MySQL 范围优化](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)
