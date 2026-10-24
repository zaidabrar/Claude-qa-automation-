"use client";

export function MarkRead() {
  return (
    <button
      className="text-sm font-medium text-primary"
      onClick={async () => {
        await fetch("/api/notifications/read", { method: "POST" });
        window.location.reload();
      }}
    >
      Mark all read
    </button>
  );
}
