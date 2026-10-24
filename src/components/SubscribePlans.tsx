import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  listSubscriptions,
  saveSubscription,
  type PlanName,
  type Subscription,
} from "@/lib/flight-api";

const PLANS: { name: PlanName; title: string; route: string; hint: number }[] = [
  { name: "tokyo", title: "台北 ✈ 東京", route: "TPE-TYO", hint: 7600 },
  { name: "seoul", title: "台北 ✈ 首爾", route: "TPE-SEL", hint: 7100 },
  { name: "london", title: "台北 ✈ 倫敦", route: "TPE-LON", hint: 23000 },
];

const twd = (n: number) => `NT$${n.toLocaleString("en-US")}`;

export function SubscribePlans({ email }: { email: string }) {
  const queryClient = useQueryClient();
  const key = ["subscriptions", email];
  const subs = useQuery({ queryKey: key, queryFn: () => listSubscriptions(email) });

  const byRoute = new Map((subs.data ?? []).map((s) => [s.route, s] as const));

  return (
    <section className="w-full max-w-5xl">
      <div className="text-center">
        <h2 className="text-2xl font-bold">選一條航線，設定目標價</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Pick a route and a TWD budget — we check fares every 30 minutes and email you when it
          drops to your target.
        </p>
      </div>
      {subs.isError && (
        <p className="mt-6 text-center text-sm text-destructive">
          無法載入你的訂閱：{(subs.error as Error).message}
        </p>
      )}
      <div className="mt-8 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        {PLANS.map((plan) => (
          <PlanCard
            key={plan.name}
            plan={plan}
            email={email}
            current={byRoute.get(plan.route)}
            loading={subs.isLoading}
            onSaved={() => queryClient.invalidateQueries({ queryKey: key })}
          />
        ))}
      </div>
    </section>
  );
}

function PlanCard({
  plan,
  email,
  current,
  loading,
  onSaved,
}: {
  plan: (typeof PLANS)[number];
  email: string;
  current: Subscription | undefined;
  loading: boolean;
  onSaved: () => void;
}) {
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const subscribed = Boolean(current);
  const showForm = !subscribed || editing;

  const mutation = useMutation({
    mutationFn: (target: number) =>
      saveSubscription({ email, plan_name: plan.name, target_price: target }),
    onSuccess: () => {
      setEditing(false);
      setValue("");
      onSaved();
    },
    onError: (e: Error) => setError(e.message),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const target = Number(value);
    if (!Number.isFinite(target) || target <= 0) return setError("請輸入大於 0 的台幣金額。");
    mutation.mutate(Math.round(target));
  }

  return (
    <div className="flex flex-col rounded-2xl border border-border bg-card p-6 text-left">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-semibold">{plan.title}</h3>
          <p className="text-sm text-primary-glow">{plan.route}</p>
        </div>
        {subscribed && (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground">
            <Check className="h-3.5 w-3.5" /> 已訂閱
          </span>
        )}
      </div>

      {subscribed && current && !editing && (
        <div className="mt-5 flex flex-1 flex-col">
          <p className="text-sm text-muted-foreground">目標價 Target</p>
          <p className="text-3xl font-bold">{twd(current.target_price)}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            票價低於或等於這個金額時，我們會寄信通知你。
          </p>
          <Button className="mt-5 self-start" variant="outline" onClick={() => setEditing(true)}>
            更新目標價
          </Button>
        </div>
      )}

      {showForm && (
        <form onSubmit={onSubmit} className="mt-5 flex flex-1 flex-col gap-3">
          <Label htmlFor={`target-${plan.name}`}>目標價（台幣） Target price (TWD)</Label>
          <Input
            id={`target-${plan.name}`}
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            required
            placeholder={`例如 ${plan.hint}`}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={loading || mutation.isPending}
          />
          <p className="text-xs text-muted-foreground">
            目前最低價約 {twd(plan.hint)}，可以設定在這附近。
          </p>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="mt-auto flex gap-2 pt-2">
            <Button type="submit" variant="hero" disabled={loading || mutation.isPending}>
              <BellRing />{" "}
              {mutation.isPending ? "儲存中…" : subscribed ? "儲存新目標價" : "開始追蹤"}
            </Button>
            {editing && (
              <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                取消
              </Button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
