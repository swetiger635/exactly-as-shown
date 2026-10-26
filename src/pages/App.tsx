import { useNavigate, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, LogOut, X, XCircle } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { SiteHeader, SiteFooter } from "@/components/SiteHeader";
import { useAuthUser } from "@/components/RequireAuth";
import { useHead } from "@/hooks/use-head";
import { SubscribePlans } from "@/components/SubscribePlans";

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
  const [params, setParams] = useSearchParams();
  const purchase = params.get("purchase");

  function dismissPurchase() {
    params.delete("purchase");
    setParams(params, { replace: true });
  }

  async function signOut() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate("/signin", { replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader
        right={
          <Button variant="outline" onClick={signOut}>
            <LogOut /> Sign out
          </Button>
        }
      />
      <main className="relative flex flex-1 flex-col items-center px-5 py-16">
        <div className="pointer-events-none absolute inset-0 bg-gradient-glow" />
        <div className="fade-up relative flex w-full flex-col items-center gap-12">
          <h1 className="break-all text-center text-3xl font-bold">
            Hi <span className="text-gradient">{user.email}</span>
          </h1>
          {(purchase === "success" || purchase === "failed") && (
            <div
              role="status"
              className={`flex w-full max-w-5xl items-start gap-3 rounded-2xl border p-4 text-left ${
                purchase === "success"
                  ? "border-accent bg-accent/40"
                  : "border-destructive/40 bg-destructive/10"
              }`}
            >
              {purchase === "success" ? (
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary-glow" />
              ) : (
                <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
              )}
              <p className="flex-1 text-sm">
                {purchase === "success"
                  ? "付款完成，謝謝！訂閱狀態會在幾秒內更新為「已訂閱」，我們也會寄一封確認信給你。"
                  : "這次付款沒有成功，沒有扣款。你可以在下方按「完成付款」再試一次。"}
              </p>
              <button
                type="button"
                onClick={dismissPurchase}
                aria-label="關閉"
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )}
          {user.email && (
            <SubscribePlans email={user.email} awaitingPayment={purchase === "success"} />
          )}
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
