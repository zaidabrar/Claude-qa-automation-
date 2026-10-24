import { Pool, types, type PoolClient, type QueryResultRow } from "pg";

// Rupee amounts and counts fit comfortably in a JS number; parse BIGINT/NUMERIC instead of returning strings.
types.setTypeParser(types.builtins.INT8, (v) => Number(v));
types.setTypeParser(types.builtins.NUMERIC, (v) => Number(v));

declare global {
  // Reuse one pool across Next.js dev hot reloads.
  var __pgPool: Pool | undefined;
}

export const pool: Pool =
  globalThis.__pgPool ?? new Pool({ connectionString: process.env.DATABASE_URL, max: 10 });
if (process.env.NODE_ENV !== "production") globalThis.__pgPool = pool;

export type Db = Pick<PoolClient, "query">;

export async function query<T extends QueryResultRow>(text: string, params: unknown[] = [], db: Db = pool): Promise<T[]> {
  const res = await db.query<T>(text, params);
  return res.rows;
}

export async function one<T extends QueryResultRow>(text: string, params: unknown[] = [], db: Db = pool): Promise<T | null> {
  const rows = await query<T>(text, params, db);
  return rows[0] ?? null;
}

export async function tx<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }
}
