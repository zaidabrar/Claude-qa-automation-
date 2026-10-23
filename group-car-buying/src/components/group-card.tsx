import Link from "next/link";
import { Clock, MapPin, Users } from "lucide-react";
import type { GroupSummary } from "@/lib/groups";
import { formatLakh } from "@/lib/money";
import { Countdown } from "./countdown";
import { StatusBadge } from "./status-badge";
import { Card } from "./ui/card";
import { Progress } from "./ui/progress";

export function GroupCard({ g }: { g: GroupSummary }) {
  const left = Math.max(0, g.target_size - g.current_size);
  return (
    <Link href={`/groups/${g.id}`} className="block">
      <Card className="p-4 transition-shadow hover:shadow-md">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs font-medium text-muted-foreground">{g.make}</p>
            <h3 className="font-semibold leading-tight">{g.model} <span className="font-normal text-muted-foreground">{g.variant}</span></h3>
          </div>
          <StatusBadge status={g.status} />
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{g.city_name}</span>
          <span>{g.fuel} · {g.transmission}</span>
          <span>Ex-showroom {formatLakh(g.ex_showroom_price)}</span>
        </div>
        <div className="mt-3 flex items-center justify-between text-sm">
          <span className="inline-flex items-center gap-1 font-semibold"><Users className="h-4 w-4 text-primary" />{g.current_size}/{g.target_size} buyers joined</span>
          {g.status === "open" && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Clock className="h-3.5 w-3.5" /><Countdown to={g.deadline} /></span>
          )}
        </div>
        <Progress className="mt-2" value={g.current_size} max={g.target_size} />
        {g.status === "open" && left > 0 && left <= 5 && <p className="mt-2 text-xs font-medium text-primary">Only {left} more to unlock dealer bids</p>}
      </Card>
    </Link>
  );
}
