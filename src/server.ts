import { createServer } from 'node:http'

import type { IncomingMessage, ServerResponse } from 'node:http'
import { createDatabase } from './db.js'
import {
	RequestError,
	readBookFilter,
	readLimit,
	readPort,
	readSeller,
	readText,
	readTransferBody,
} from './validation.js'

const host = process.env.HOST ?? '127.0.0.1'
const port = readPort(process.env.PORT ?? '8080')
const database = createDatabase({
	host: process.env.MYSQL_HOST ?? '127.0.0.1',
	port: readPort(process.env.MYSQL_PORT ?? '33484'),
	user: process.env.MYSQL_USER ?? 'pageslip',
	password: process.env.MYSQL_PASSWORD ?? 'pageslip-local',
})

interface Route {
	method: 'GET' | 'POST'
	handle: (request: IncomingMessage, url: URL) => object | Promise<object>
}

const routes = new Map<string, Route>([
	[
		'/',
		{
			method: 'GET',
			handle: () => ({
				project: '页笺 / PageSlip',
				description: '校园二手书与模拟钱包的 MySQL 课程实践',
				examples: {
					health: '/health',
					title: '/api/books/title?prefix=数据库',
					filter:
						'/api/books/filter?category=计算机&minPrice=20&maxPrice=50&status=在售',
					seller: '/api/books/seller?sellerId=2023001',
					accounts: '/api/accounts',
					transfer: {
						method: 'POST',
						path: '/api/transfers',
						body: { fromId: 1, toId: 2, amount: '500.00' },
					},
				},
			}),
		},
	],
	[
		'/health',
		{
			method: 'GET',
			handle: async () => {
				try {
					await database.ping()
				} catch {
					throw new RequestError(
						503,
						'DATABASE_UNAVAILABLE',
						'暂时无法连接 MySQL。',
					)
				}
				return { status: 'ok', database: 'MySQL' }
			},
		},
	],
	[
		'/api/books/title',
		{
			method: 'GET',
			handle: async (_request, { searchParams }) => ({
				books: await database.searchTitle(
					readText(searchParams.get('prefix'), '书名前缀', 120),
					readLimit(searchParams),
				),
			}),
		},
	],
	[
		'/api/books/filter',
		{
			method: 'GET',
			handle: async (_request, { searchParams }) => ({
				books: await database.filterBooks(readBookFilter(searchParams)),
			}),
		},
	],
	[
		'/api/books/seller',
		{
			method: 'GET',
			handle: async (_request, { searchParams }) => ({
				books: await database.searchSeller(
					readSeller(searchParams.get('sellerId')),
					readLimit(searchParams),
				),
			}),
		},
	],
	[
		'/api/accounts',
		{
			method: 'GET',
			handle: async () => ({ accounts: await database.listAccounts() }),
		},
	],
	[
		'/api/transfers',
		{
			method: 'POST',
			handle: async (request) => {
				const transfer = await readTransferBody(request)
				await database.transfer(transfer)
				return { status: 'committed', ...transfer }
			},
		},
	],
])

const transferErrors = new Map([
	[
		'INVALID_TRANSFER',
		new RequestError(400, 'INVALID_TRANSFER', '转账参数无效。'),
	],
	[
		'ACCOUNT_NOT_FOUND',
		new RequestError(404, 'ACCOUNT_NOT_FOUND', '转出账号或转入账号不存在。'),
	],
	[
		'INSUFFICIENT_FUNDS',
		new RequestError(409, 'INSUFFICIENT_FUNDS', '转出账户余额不足。'),
	],
])

function readError(error: unknown): RequestError {
	if (error instanceof RequestError) return error

	if (typeof error === 'object' && error !== null) {
		const dbError = error as {
			sqlState?: unknown
			sqlMessage?: unknown
			code?: unknown
		}
		if (
			dbError.sqlState === '45000' &&
			typeof dbError.sqlMessage === 'string'
		) {
			const transferError = transferErrors.get(dbError.sqlMessage)
			if (transferError) return transferError
		}
		if (
			dbError.code === 'ER_LOCK_DEADLOCK' ||
			dbError.code === 'ER_LOCK_WAIT_TIMEOUT'
		) {
			return new RequestError(
				409,
				'TRANSACTION_CONFLICT',
				'数据库事务遇到锁冲突，请重试。',
			)
		}
	}

	return new RequestError(500, 'INTERNAL_ERROR', '服务暂时无法完成此操作。')
}

function send(response: ServerResponse, status: number, body: object): void {
	response.writeHead(status, {
		'Content-Type': 'application/json; charset=utf-8',
		'Cache-Control': 'no-store',
	})
	response.end(JSON.stringify(body))
}

async function serve(
	request: IncomingMessage,
	response: ServerResponse,
): Promise<void> {
	try {
		const url = new URL(request.url ?? '/', 'http://localhost')
		const route = routes.get(url.pathname)
		if (!route) throw new RequestError(404, 'NOT_FOUND', '这个接口不存在。')
		if (request.method !== route.method) {
			response.setHeader('Allow', route.method)
			throw new RequestError(
				405,
				'METHOD_NOT_ALLOWED',
				'这个接口不支持当前请求方式。',
			)
		}
		send(response, 200, await route.handle(request, url))
	} catch (error) {
		if (response.destroyed) return
		const { status, code, message } = readError(error)
		send(response, status, { error: { code, message } })
	}
}

const server = createServer(
	{ headersTimeout: 10000, requestTimeout: 15000 },
	(request, response) => {
		void serve(request, response)
	},
)

server.listen(port, host, () => {
	console.info(`页笺 API 已启动，端口 ${port}`)
})

function shutdown(): void {
	server.close(() => {
		void database.close().catch(() => {
			process.exitCode = 1
		})
	})
}

process.once('SIGINT', shutdown)
process.once('SIGTERM', shutdown)
