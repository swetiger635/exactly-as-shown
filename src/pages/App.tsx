import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { SiteHeader, SiteFooter } from "@/components/SiteHeader";
import { useAuthUser } from "@/components/RequireAuth";
import { useHead } from "@/hooks/use-head";

export default function AppPage() {
  useHead({
    title: "Dashboard · Flight Price Notifier",
    meta: [
      { name: "description", content: "Your Flight Price Notifier dashboard." },
      { property: "og:title", content: "Dashboard · Flight Price Notifier" },
      { property: "og:description", content: "Your fare-tracking dashboard." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  });
  const user = useAuthUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function signOut() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate("/signin", { replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader right={<Button variant="outline" onClick={signOut}><LogOut /> Sign out</Button>} />
      <main className="relative flex flex-1 items-center justify-center px-5 py-20">
        <div className="pointer-events-none absolute inset-0 bg-gradient-glow" />
        <div className="fade-up relative max-w-xl rounded-2xl border border-border bg-card p-10 text-center">
          <h1 className="break-all text-3xl font-bold">Hi <span className="text-gradient">{user.email}</span></h1>
          <p className="mt-5 text-lg">你的航線追蹤儀表板即將上線 — 下一個里程碑會加上訂閱航線的功能。</p>
          <p className="mt-3 text-sm text-muted-foreground">Your dashboard is coming soon. Route-subscription will be added in the next milestone.</p>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
