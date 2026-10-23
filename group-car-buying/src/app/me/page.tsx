import Link from "next/link";
import { redirect } from "next/navigation";
import { Countdown } from "@/components/countdown";
import { StatusBadge } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { maskPhone } from "@/lib/phone";
import { currentUser } from "@/lib/session";
import { listNotifications, myGroups } from "@/lib/users";
import { MarkRead } from "./mark-read";

export const dynamic = "force-dynamic";

export default async function MePage() {
  const user = await currentUser();
  if (!user) redirect("/login?next=/me");
  const [groups, notes] = await Promise.all([user.role === "buyer" ? myGroups(user.id) : Promise.resolve([]), listNotifications(user.id)]);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-bold">{user.name ?? "Your account"}</h1>
        <p className="text-sm text-muted-foreground">
          {maskPhone(user.phone)} · {user.pan_verified ? "PAN verified ✓" : <Link className="text-primary underline" href="/onboarding">Verify PAN</Link>}
        </p>
      </section>

      {user.role === "buyer" && (
        <section>
          <h2 className="text-lg font-bold">My groups</h2>
          {groups.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">You haven&apos;t joined a group yet. <Link className="text-primary underline" href="/groups">Find one</Link>.</p>
          ) : (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {groups.map((g) => (
                <Link key={g.group_id} href={`/groups/${g.group_id}`}>
                  <Card className="p-4 hover:shadow-md">
                    <div className="flex justify-between gap-2">
                      <p className="font-semibold">{g.model} {g.variant} · {g.city_name}</p>
                      <StatusBadge status={g.status} />
                    </div>
                    <p className="mt-2 text-sm">{g.current_size}/{g.target_size} joined{g.status === "open" && <> · <Countdown to={g.deadline} /></>}</p>
                    <Progress className="mt-2" value={g.current_size} max={g.target_size} />
                    {g.member_status === "locked" && <p className="mt-2 text-xs font-semibold text-success">Locked in</p>}
                  </Card>
                </Link>
              ))}
            </div>
          )}
        </section>
      )}

      <section>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">Notifications</h2>
          {notes.some((n) => !n.read_at) && <MarkRead />}
        </div>
        <div className="mt-3 space-y-2">
          {notes.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet.</p>}
          {notes.map((n) => (
            <Card key={n.id} className={`p-3 ${n.read_at ? "opacity-70" : "border-primary/40"}`}>
              <p className="text-sm font-semibold">{n.title}</p>
              <p className="text-sm text-muted-foreground">{n.body}</p>
              <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                <span>{new Date(n.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
                {n.group_id && <Link className="text-primary" href={`/groups/${n.group_id}`}>Open group</Link>}
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
