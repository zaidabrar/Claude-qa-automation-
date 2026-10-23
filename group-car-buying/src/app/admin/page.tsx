import { redirect } from "next/navigation";
import { StatusBadge } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { query } from "@/lib/db";
import { formatInr } from "@/lib/money";
import { currentUser } from "@/lib/session";
import { AdminAction } from "./admin-action";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const user = await currentUser();
  if (!user) redirect("/login?next=/admin");
  if (user.role !== "admin") redirect("/");

  const [pending, groups, bookings, commissions] = await Promise.all([
    query<{ id: string; business_name: string; gstin: string; trade_certificate: string; city: string; brands: string[]; contact_name: string; phone: string; created_at: Date }>(
      `SELECT d.id, d.business_name, d.gstin, d.trade_certificate, ci.name AS city, d.brands, d.contact_name, u.phone, d.created_at
         FROM dealers d JOIN cities ci ON ci.id = d.city_id JOIN users u ON u.id = d.user_id WHERE d.status = 'pending' ORDER BY d.created_at`,
    ),
    query<{ status: string; n: number }>("SELECT status, count(*)::int AS n FROM groups GROUP BY status ORDER BY status"),
    query<{ id: string; buyer: string; dealer: string; model: string; quoted_price: number; token_amount: number }>(
      `SELECT b.id, u.name AS buyer, d.business_name AS dealer, c.model, r.quoted_price, b.token_amount
         FROM bookings b JOIN group_members m ON m.id = b.group_member_id JOIN users u ON u.id = m.user_id
         JOIN rfps r ON r.id = b.rfp_id JOIN dealers d ON d.id = r.dealer_id JOIN groups g ON g.id = r.group_id JOIN cars c ON c.id = g.car_id
        WHERE b.status = 'paid' ORDER BY b.paid_at`,
    ),
    query<{ id: string; dealer: string; on_road_price: number; rate_bps: number; amount: number; gst_amount: number; status: string }>(
      `SELECT cm.id, d.business_name AS dealer, cm.on_road_price, cm.rate_bps, cm.amount, cm.gst_amount, cm.status
         FROM commissions cm JOIN dealers d ON d.id = cm.dealer_id ORDER BY cm.created_at DESC LIMIT 50`,
    ),
  ]);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Operations</h1>
      <section className="flex flex-wrap gap-2">
        {groups.map((g) => <Card key={g.status} className="flex items-center gap-2 p-3"><StatusBadge status={g.status} /><span className="font-bold">{g.n}</span></Card>)}
      </section>

      <section>
        <h2 className="text-lg font-bold">Dealer applications</h2>
        {pending.length === 0 && <p className="mt-2 text-sm text-muted-foreground">No pending applications.</p>}
        <div className="mt-3 space-y-2">
          {pending.map((d) => (
            <Card key={d.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm">
                <p className="font-semibold">{d.business_name} · {d.city}</p>
                <p className="text-muted-foreground">GSTIN {d.gstin} · TC {d.trade_certificate} · {d.brands.join(", ")} · {d.contact_name} {d.phone}</p>
              </div>
              <div className="flex gap-2">
                <AdminAction url={`/api/admin/dealers/${d.id}`} body={{ status: "approved", commissionBps: 75 }} label="Approve @ 0.75%" />
                <AdminAction url={`/api/admin/dealers/${d.id}`} body={{ status: "rejected" }} label="Reject" variant="ghost" />
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-bold">Paid bookings awaiting delivery</h2>
        {bookings.length === 0 && <p className="mt-2 text-sm text-muted-foreground">None.</p>}
        <div className="mt-3 space-y-2">
          {bookings.map((b) => (
            <Card key={b.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm"><strong>{b.buyer}</strong> · {b.model} via {b.dealer} · {formatInr(b.quoted_price)} · token {formatInr(b.token_amount)}</p>
              <div className="flex gap-2">
                <AdminAction url={`/api/bookings/${b.id}/deliver`} label="Mark delivered" />
                <AdminAction url={`/api/bookings/${b.id}/refund`} label="Refund token" variant="ghost" confirm="Refund the token (dealer couldn't deliver)?" />
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-bold">Commissions</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted-foreground"><tr><th className="py-2">Dealer</th><th>On-road</th><th>Rate</th><th>Commission</th><th>GST</th><th>Status</th><th /></tr></thead>
            <tbody>
              {commissions.map((c) => (
                <tr key={c.id} className="border-t">
                  <td className="py-2">{c.dealer}</td><td>{formatInr(c.on_road_price)}</td><td>{(c.rate_bps / 100).toFixed(2)}%</td>
                  <td>{formatInr(c.amount)}</td><td>{formatInr(c.gst_amount)}</td><td>{c.status}</td>
                  <td>{c.status === "pending" && <AdminAction url={`/api/admin/commissions/${c.id}`} label="Mark paid" variant="ghost" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {commissions.length === 0 && <p className="mt-2 text-sm text-muted-foreground">No commissions yet.</p>}
        </div>
      </section>
    </div>
  );
}
