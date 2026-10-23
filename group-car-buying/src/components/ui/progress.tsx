import { cn } from "@/lib/utils";

export function Progress({ value, max, className }: { value: number; max: number; className?: string }) {
  const pct = Math.min(100, Math.round((value / Math.max(1, max)) * 100));
  return (
    <div className={cn("h-2.5 w-full overflow-hidden rounded-full bg-muted", className)} role="progressbar" aria-valuenow={value} aria-valuemax={max}>
      <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}
