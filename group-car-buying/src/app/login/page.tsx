import { redirect } from "next/navigation";
import { LoginForm } from "./login-form";
import { currentUser } from "@/lib/session";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  if (await currentUser()) redirect(next ?? "/groups");
  return (
    <div className="mx-auto max-w-sm pt-8">
      <h1 className="text-2xl font-bold">Log in with your mobile</h1>
      <p className="mt-1 text-sm text-muted-foreground">We&apos;ll send a 6-digit OTP. Dealers use the number registered with us.</p>
      <LoginForm next={next?.startsWith("/") ? next : undefined} />
    </div>
  );
}
