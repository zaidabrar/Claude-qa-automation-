"use client";

import { LogOut } from "lucide-react";

export function LogoutButton() {
  return (
    <button
      aria-label="Log out"
      className="rounded-md p-2 hover:bg-accent"
      onClick={async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        window.location.href = "/";
      }}
    >
      <LogOut className="h-4 w-4" />
    </button>
  );
}
