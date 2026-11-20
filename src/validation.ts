import type { IncomingMessage } from 'node:http'

import type { BookFilter, Transfer } from './db.js'

export class RequestError extends Error {
	constructor(
		readonly status: number,
		readonly code: string,
		message: string,
	) {
		super(message)
	}
}

function invalid(message: string): never {
	throw new RequestError(400, 'INVALID_INPUT', message)
}

export function readPort(value: string): number {
	if (!/^\d{1,5}$/.test(value) || Number(value) < 1 || Number(value) > 65535) {
		throw new Error('端口必须是 1 至 65535 之间的整数。')
	}
	return Number(value)
}

export function readText(
	value: string | null,
	label: string,
	maxLength: number,
): string {
	const text = value?.trim()
	if (!text || Array.from(text).length > maxLength) {
		invalid(`${label}需要填写，且最多 ${maxLength} 个字符。`)
	}
	return text
}

export function readLimit(query: URLSearchParams): number {
	const limit = query.get('limit') ?? '20'
	if (!/^\d{1,3}$/.test(limit) || Number(limit) < 1 || Number(limit) > 100) {
		invalid('limit 必须是 1 至 100 之间的整数。')
	}
	return Number(limit)
}

export function readSeller(value: string | null): string {
	if (value === null || !/^\d{7}$/.test(value)) {
		invalid('sellerId 需要填写 7 位卖家学号。')
	}
	return value
}

function readMoney(value: unknown, label: string, wholeDigits: number): string {
	const amount = typeof value === 'number' ? String(value) : value
	const moneyPattern = new RegExp(`^\\d{1,${wholeDigits}}(?:\\.\\d{1,2})?$`)
	if (typeof amount !== 'string' || !moneyPattern.test(amount)) {
		invalid(
			`${label}需要填写非负金额，整数最多 ${wholeDigits} 位，小数最多两位。`,
		)
	}
	return amount
}

export function readBookFilter(query: URLSearchParams): BookFilter {
	const category = readText(query.get('category'), '分类', 30)
	const status = query.get('status') ?? '在售'
	if (status !== '在售' && status !== '已售') {
		invalid('status 可以是“在售”或“已售”。')
	}
	const minPrice = readMoney(query.get('minPrice'), '最低价', 6)
	const maxPrice = readMoney(query.get('maxPrice'), '最高价', 6)
	if (Number(minPrice) > Number(maxPrice)) invalid('最低价不能高于最高价。')

	return { category, status, minPrice, maxPrice, limit: readLimit(query) }
}

function isAccountId(value: unknown): value is number {
	return (
		typeof value === 'number' &&
		Number.isInteger(value) &&
		value >= 1 &&
		value <= 2147483647
	)
}

function readTransfer(input: unknown): Transfer {
	if (typeof input !== 'object' || input === null || Array.isArray(input)) {
		invalid('转账需要填写 fromId、toId 和 amount。')
	}

	const fields = input as Record<string, unknown>
	const { fromId, toId, amount } = fields
	if (
		Object.keys(fields).length !== 3 ||
		!isAccountId(fromId) ||
		!isAccountId(toId)
	) {
		invalid('转账需要填写整数账号 fromId、toId 和金额 amount。')
	}
	if (fromId === toId) invalid('转出账号和转入账号必须不同。')

	const formatted = readMoney(amount, '转账金额', 10)
	if (Number(formatted) <= 0) invalid('转账金额必须大于 0。')

	return { fromId, toId, amount: formatted }
}

export async function readTransferBody(
	request: IncomingMessage,
): Promise<Transfer> {
	const type = request.headers['content-type']
		?.split(';')[0]
		.trim()
		.toLowerCase()
	if (type !== 'application/json') {
		throw new RequestError(
			415,
			'UNSUPPORTED_MEDIA_TYPE',
			'请使用 application/json 提交转账。',
		)
	}

	const maxBytes = 8192
	if (Number(request.headers['content-length']) > maxBytes) {
		request.resume()
		throw new RequestError(413, 'BODY_TOO_LARGE', '请求正文不能超过 8 KiB。')
	}

	const chunks: Buffer[] = []
	let size = 0
	for await (const chunk of request.iterator({ destroyOnReturn: false })) {
		const data: Buffer = chunk
		size += data.length
		if (size > maxBytes) {
			request.resume()
			throw new RequestError(413, 'BODY_TOO_LARGE', '请求正文不能超过 8 KiB。')
		}
		chunks.push(data)
	}

	let input: unknown
	try {
		input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
	} catch {
		throw new RequestError(400, 'INVALID_JSON', '请求正文必须是有效的 JSON。')
	}
	return readTransfer(input)
}
