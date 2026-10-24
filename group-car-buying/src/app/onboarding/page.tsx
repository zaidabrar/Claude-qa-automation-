import { redirect } from "next/navigation";
import { listCities } from "@/lib/catalog";
import { currentUser } from "@/lib/session";
import { ProfileForm } from "./profile-form";

export default async function OnboardingPage() {
  const user = await currentUser();
  if (!user) redirect("/login?next=/onboarding");
  const cities = await listCities();
  return (
    <div className="mx-auto max-w-md pt-6">
      <h1 className="text-2xl font-bold">Verify yourself</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Dealers bid harder on real buyers. Your PAN is checked once, never shown to anyone, and we only keep its last 4 characters.
      </p>
      <ProfileForm cities={cities.map((c) => ({ id: c.id, name: c.name }))} initial={{ name: user.name ?? "", cityId: user.city_id, panVerified: user.pan_verified }} />
    </div>
  );
}
