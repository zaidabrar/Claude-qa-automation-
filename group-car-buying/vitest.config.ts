import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    fileParallelism: false,
    env: {
      // Integration tests run only when TEST_DATABASE_URL points at a throwaway database; they reset its schema.
      DATABASE_URL: process.env.TEST_DATABASE_URL ?? "",
      SESSION_SECRET: "test-secret-0123456789abcdef0123456789",
      BOOKING_TOKEN_INR: "5000",
    },
  },
});
