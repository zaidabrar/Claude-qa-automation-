"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { ChatMessage } from "@/lib/chat";
import { api } from "@/lib/client";
import { cn } from "@/lib/utils";

export function Chat({ groupId, canPost }: { groupId: string; canPost: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const lastId = useRef(0);
  const list = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    try {
      const r = await api<{ messages: ChatMessage[] }>(`/api/groups/${groupId}/messages?after=${lastId.current}`);
      if (r.messages.length) {
        lastId.current = r.messages[r.messages.length - 1].id;
        setMessages((m) => [...m, ...r.messages]);
        requestAnimationFrame(() => list.current?.scrollTo({ top: list.current.scrollHeight }));
      }
    } catch {
      /* transient; next poll retries */
    }
  }, [groupId]);

  useEffect(() => {
    poll();
    const t = setInterval(() => !document.hidden && poll(), 4000);
    return () => clearInterval(t);
  }, [poll]);

  return (
    <Card className="flex h-[480px] flex-col">
      <div className="flex items-center gap-2 border-b p-3 font-semibold"><MessageCircle className="h-4 w-4" />Group chat & dealer Q&A</div>
      <div ref={list} className="flex-1 space-y-2 overflow-y-auto p-3">
        {messages.length === 0 && <p className="text-center text-sm text-muted-foreground">No messages yet. Say hi 👋</p>}
        {messages.map((m) => (
          <div key={m.id} className={cn("max-w-[85%] rounded-lg px-3 py-2 text-sm", m.mine ? "ml-auto bg-primary text-primary-foreground" : m.kind === "dealer_qa" ? "bg-amber-100 text-amber-950 dark:bg-amber-500/15 dark:text-amber-100" : "bg-muted")}>
            {!m.mine && <p className="text-xs font-semibold opacity-80">{m.author}</p>}
            <p className="whitespace-pre-wrap break-words">{m.body}</p>
          </div>
        ))}
      </div>
      {canPost && (
        <form
          className="flex gap-2 border-t p-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!text.trim()) return;
            setError(null);
            try {
              await api(`/api/groups/${groupId}/messages`, { body: { body: text } });
              setText("");
              poll();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Message the group…" maxLength={1000} />
          <Button size="icon" type="submit" aria-label="Send"><Send className="h-4 w-4" /></Button>
        </form>
      )}
      {error && <p className="px-3 pb-2 text-xs text-destructive">{error}</p>}
    </Card>
  );
}
