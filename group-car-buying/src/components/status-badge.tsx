import { Badge } from "./ui/badge";

const LABELS: Record<string, { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline" }> = {
  open: { label: "Forming", variant: "default" },
  bidding: { label: "Dealers bidding", variant: "warning" },
  decision: { label: "Bids revealed", variant: "success" },
  closed: { label: "Closed", variant: "secondary" },
  expired: { label: "Expired", variant: "destructive" },
  no_bids: { label: "No bids", variant: "destructive" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = LABELS[status] ?? { label: status, variant: "outline" as const };
  return <Badge variant={s.variant}>{s.label}</Badge>;
}
