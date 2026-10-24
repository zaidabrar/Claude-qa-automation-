import Link from "next/link";
import { Car } from "lucide-react";
import { one } from "@/lib/db";
import { currentUser } from "@/lib/session";
import { LogoutButton } from "./logout-button";

export async function Header() {
  const user = await currentUser();
  const unread = user
    ? (await one<{ n: number }>("SELECT count(*)::int AS n FROM notifications WHERE user_id = $1 AND read_at IS NULL", [user.id]))?.n ?? 0
    : 0;
  return (
    <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur">
      <div className="container flex h-14 items-center justify-between gap-2">
        <Link href="/" className="flex items-center gap-2 font-bold">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-primary-foreground"><Car className="h-5 w-5" /></span>
          <span>Saath Gaadi</span>
        </Link>
        <nav className="flex items-center gap-1 text-sm font-medium">
          {user?.role === "dealer" ? (
            <Link className="rounded-md px-3 py-2 hover:bg-accent" href="/dealer">Dashboard</Link>
          ) : user?.role === "admin" ? (
            <Link className="rounded-md px-3 py-2 hover:bg-accent" href="/admin">Admin</Link>
          ) : (
            <Link className="rounded-md px-3 py-2 hover:bg-accent" href="/groups">Groups</Link>
          )}
          {user ? (
            <>
              <Link className="relative rounded-md px-3 py-2 hover:bg-accent" href="/me">
                Me
                {unread > 0 && <span className="absolute right-0.5 top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] text-primary-foreground">{unread}</span>}
              </Link>
              <LogoutButton />
            </>
          ) : (
            <Link className="rounded-md bg-primary px-3 py-2 text-primary-foreground" href="/login">Log in</Link>
          )}
        </nav>
      </div>
    </header>
  );
}
