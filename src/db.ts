import mysql from 'mysql2/promise'

import type { RowDataPacket } from 'mysql2/promise'

interface Book extends RowDataPacket {
	id: number
	book_name: string
	author: string
	category: string
	price: string
	book_condition: string
	seller_id: string
	listed_at: string
	status: '在售' | '已售'
}

interface Account extends RowDataPacket {
	account_id: number
	account_name: string
	balance: string
}

export interface Transfer {
	fromId: number
	toId: number
	amount: string
}

export interface BookFilter {
	category: string
	status: Book['status']
	minPrice: string
	maxPrice: string
	limit: number
}

export interface DatabaseOptions {
	host: string
	port: number
	user: string
	password: string
}

export function createDatabase(options: DatabaseOptions) {
	const pool = mysql.createPool({
		...options,
		charset: 'utf8mb4',
		dateStrings: true,
		connectionLimit: 5,
		queueLimit: 20,
		connectTimeout: 5000,
	})

	const bookColumns =
		'id, book_name, author, category, price, book_condition, seller_id, listed_at, status'

	return {
		ping: async () => {
			await pool.query('SELECT 1')
		},

		searchTitle: async (prefix: string, limit: number) => {
			const pattern = prefix.replace(/[!%_]/g, (char) => `!${char}`) + '%'
			const [rows] = await pool.execute<Book[]>(
				`SELECT ${bookColumns} FROM book_lab.book
				WHERE book_name LIKE ? ESCAPE '!' ORDER BY id LIMIT ?`,
				[pattern, limit],
			)
			return rows
		},

		filterBooks: async ({
			category,
			status,
			minPrice,
			maxPrice,
			limit,
		}: BookFilter) => {
			const [rows] = await pool.execute<Book[]>(
				`SELECT ${bookColumns} FROM book_lab.book
				WHERE category = ? AND status = ? AND price BETWEEN ? AND ? ORDER BY id LIMIT ?`,
				[category, status, minPrice, maxPrice, limit],
			)
			return rows
		},

		searchSeller: async (sellerId: string, limit: number) => {
			const [rows] = await pool.execute<Book[]>(
				`SELECT ${bookColumns} FROM book_lab.book WHERE seller_id = ? ORDER BY id LIMIT ?`,
				[sellerId, limit],
			)
			return rows
		},

		listAccounts: async () => {
			const [rows] = await pool.execute<Account[]>(
				'SELECT account_id, account_name, balance FROM bank_lab.account ORDER BY account_id',
			)
			return rows
		},

		transfer: async ({ fromId, toId, amount }: Transfer) => {
			await pool.execute('CALL bank_lab.transfer_funds(?, ?, ?, 0)', [
				fromId,
				toId,
				amount,
			])
		},

		close: () => pool.end(),
	}
}
