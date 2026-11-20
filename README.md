# 页笺 / PageSlip

页笺是一个校园二手教材交易的课程原型。期末，同学可以按书名、预算或卖家学号找书，付款环节用模拟账户表示。这个项目以福建理工大学《数据库与向量数据库》的两项实践为背景。

| 任务 | 实验 |
| --- | --- |
| 4 / 实验项目 | 10 个账户，转账提交与回滚，三种读异常，四级隔离，死锁与固定锁顺序 |
| 5 / 结课项目 | 存储过程生成 100,000 条书目，比较三种查询的索引计划，以及书名列使用 `UPPER()` 的影响 |

账户与图书使用合成数据。转账、并发时序、执行计划和时间均由本地 MySQL 实际运行得出。两份独立课堂汇报在 PPT 中呈现实验过程、数据和 SQL。

## 复现实验

需要 Docker Compose、Python 3.10+ 和可用的本机端口 33484。下列命令会初始化专用 MySQL 实例，实验脚本会重设测试账户并重建书目表。

```sh
docker compose up -d --wait
python3 sql/bank/run.py --output .evidence/bank
python3 sql/book/collect.py --output .evidence/book
```

- [任务 4](sql/bank/) 使用独立 MySQL 会话执行转账、并发和隔离实验，生成 `bank.json` 和分会话的终端记录。
- [任务 5](sql/book/README.md) 先运行主键基线，再创建二级索引，最后对比普通等值和 `UPPER()`。执行计划、完整结果集校验和计时样本写入证据目录。

## 本地 API

使用 Node.js 24+ 和 pnpm。完成上述数据库实验后，两个测试库即可供 API 查询。

```sh
pnpm install --frozen-lockfile
pnpm build
pnpm start
```

默认访问 `http://127.0.0.1:8080/` 查看参数示例。需要改端口或数据库连接时，将 `.env.example` 复制到 `.env` 再调整。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 检查 MySQL 连接 |
| GET | `/api/books/title?prefix=数据库` | 书名前缀查询 |
| GET | `/api/books/filter?category=计算机&minPrice=20&maxPrice=50&status=在售` | 分类、价格与状态筛选 |
| GET | `/api/books/seller?sellerId=2023001` | 查指定卖家的书目 |
| GET | `/api/accounts` | 查看模拟账户余额 |
| POST | `/api/transfers` | 提交模拟转账 |

三个图书查询可指定 `limit`，范围为 1 到 100。转账金额使用十进制字符串。下面的请求会把 1 号账户的模拟余额转给 2 号账户。

```sh
curl -fsS http://127.0.0.1:8080/api/transfers \
  -H 'Content-Type: application/json' \
  -d '{"fromId":1,"toId":2,"amount":"500.00"}'
```

按 Ctrl+C 关闭 API。用 `docker compose stop` 停止数据库并保留实验数据卷。
