import { NextResponse } from "next/server";
import { z } from "zod";
import { AppError } from "./errors";

type Handler<C> = (req: Request, ctx: C) => Promise<Response | unknown>;

/** Wraps a route handler: AppErrors become { error } with their status; anything else is a logged 500. */
export function route<C = unknown>(fn: Handler<C>) {
  return async (req: Request, ctx: C): Promise<Response> => {
    try {
      const out = await fn(req, ctx);
      return out instanceof Response ? out : NextResponse.json(out ?? { ok: true });
    } catch (err) {
      if (err instanceof AppError) return NextResponse.json({ error: err.message }, { status: err.status });
      if (err instanceof z.ZodError) {
        return NextResponse.json({ error: err.issues[0]?.message ?? "Invalid input" }, { status: 400 });
      }
      console.error(err);
      return NextResponse.json({ error: "Something went wrong" }, { status: 500 });
    }
  };
}

export async function body<T extends z.ZodType>(req: Request, schema: T): Promise<z.infer<T>> {
  const json = await req.json().catch(() => {
    throw new AppError("Invalid JSON body");
  });
  return schema.parse(json);
}

export type IdParams = { params: Promise<{ id: string }> };

const uuid = z.string().uuid();
export async function idParam(ctx: IdParams): Promise<string> {
  const { id } = await ctx.params;
  if (!uuid.safeParse(id).success) throw new AppError("Not found", 404);
  return id;
}
