import { z } from "zod";
import { body, idParam, route, type IdParams } from "@/lib/api";
import { listMessages, postMessage } from "@/lib/chat";
import { requireUser } from "@/lib/session";

export const GET = route<IdParams>(async (req, ctx) => {
  const user = await requireUser();
  const after = Number(new URL(req.url).searchParams.get("after")) || 0;
  return { messages: await listMessages(await idParam(ctx), user, after) };
});

export const POST = route<IdParams>(async (req, ctx) => {
  const user = await requireUser();
  const { body: text } = await body(req, z.object({ body: z.string() }));
  await postMessage(await idParam(ctx), user, text);
  return { ok: true };
});
