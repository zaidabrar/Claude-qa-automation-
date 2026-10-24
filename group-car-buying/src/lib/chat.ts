import { one, query } from "./db";
import { AppError } from "./errors";
import type { SessionUser } from "./session";

export interface ChatMessage {
  id: number;
  kind: "chat" | "dealer_qa" | "system";
  body: string;
  created_at: Date;
  author: string;
  mine: boolean;
}

/** Buyers in the group and dealers invited to its RFP can read and post. Dealers post as "Dealer Q&A". */
async function access(groupId: string, user: SessionUser): Promise<"buyer" | "dealer" | "admin" | null> {
  if (user.role === "admin") return "admin";
  if (user.role === "dealer" && user.dealer_id) {
    const r = await one("SELECT 1 FROM rfps WHERE group_id = $1 AND dealer_id = $2", [groupId, user.dealer_id]);
    return r ? "dealer" : null;
  }
  const m = await one("SELECT 1 FROM group_members WHERE group_id = $1 AND user_id = $2 AND status IN ('active', 'locked')", [groupId, user.id]);
  return m ? "buyer" : null;
}

export async function listMessages(groupId: string, user: SessionUser, afterId = 0): Promise<ChatMessage[]> {
  if (!(await access(groupId, user))) throw new AppError("Join the group to see the chat", 403);
  const rows = await query<{ id: number; kind: ChatMessage["kind"]; body: string; created_at: Date; user_id: string; name: string | null; role: string }>(
    `SELECT msg.id, msg.kind, msg.body, msg.created_at, msg.user_id, u.name, u.role
       FROM messages msg JOIN users u ON u.id = msg.user_id
      WHERE msg.group_id = $1 AND msg.id > $2 ORDER BY msg.id LIMIT 200`,
    [groupId, afterId],
  );
  // Dealers stay anonymous in chat too, so buyers can't shortcut the sealed-bid comparison.
  return rows.map((r) => ({
    id: r.id,
    kind: r.kind,
    body: r.body,
    created_at: r.created_at,
    author: r.role === "dealer" ? "Dealer (verified)" : r.role === "admin" ? "Team" : firstName(r.name),
    mine: r.user_id === user.id,
  }));
}

export async function postMessage(groupId: string, user: SessionUser, body: string): Promise<void> {
  const role = await access(groupId, user);
  if (!role) throw new AppError("Join the group to chat", 403);
  const text = body.trim();
  if (!text || text.length > 1000) throw new AppError("Message must be 1–1000 characters");
  // Keep phone numbers out of chat so deals stay on-platform; dealers get contacts on lock-in.
  if (/(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}/.test(text)) throw new AppError("Please don't share phone numbers in group chat");
  await query("INSERT INTO messages (group_id, user_id, kind, body) VALUES ($1, $2, $3, $4)", [
    groupId,
    user.id,
    role === "dealer" ? "dealer_qa" : "chat",
    text,
  ]);
}

function firstName(name: string | null): string {
  return name?.trim().split(/\s+/)[0] || "Buyer";
}
