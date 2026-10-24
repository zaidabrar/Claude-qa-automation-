import { readFileSync } from "node:fs";
import path from "node:path";
import { Client } from "pg";

async function main() {
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();
  try {
    if (process.argv.includes("--reset")) {
      await client.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public;");
      console.log("schema reset");
    }
    await client.query(readFileSync(path.join(__dirname, "..", "db", "schema.sql"), "utf8"));
    console.log("schema applied");
  } finally {
    await client.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
