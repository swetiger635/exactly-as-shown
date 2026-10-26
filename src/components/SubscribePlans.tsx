import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, Clock, CreditCard, RotateCcw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  cancelSubscription,
  goToCheckout,
  listSubscriptions,
  saveSubscription,
  type PlanName,
  type Subscription,
  type SubscriptionStatus,
} from "@/lib/flight-api";

const PLANS: { name: PlanName; title: string; route: string; hint: number }[] = [
  { name: "tokyo", title: "台北 ✈ 東京", route: "TPE-TYO", hint: 7600 },
  { name: "seoul", title: "台北 ✈ 首爾", route: "TPE-SEL", hint: 7100 },
  { name: "london", title: "台北 ✈ 倫敦", route: "TPE-LON", hint: 23000 },
];

const twd = (n: number) => `NT$${n.toLocaleString("en-US")}`;

const BADGE: Record<SubscriptionStatus, { label: string; icon: ReactNode; className: string }> = {
  active: {
    label: "已訂閱（有效）",
    icon: <Check className="h-3.5 w-3.5" />,
    className: "bg-accent text-accent-foreground",
  },
  pending_payment: {
    label: "未完成付款",
    icon: <Clock className="h-3.5 w-3.5" />,
    className: "bg-secondary text-secondary-foreground",
  },
  cancelled: {
    label: "已取消",
    icon: <XCircle className="h-3.5 w-3.5" />,
    className: "bg-muted text-muted-foreground",
  },
  expired: {
    label: "已結束",
    icon: <XCircle className="h-3.5 w-3.5" />,
    className: "bg-muted text-muted-foreground",
  },
};

export function SubscribePlans({
  email,
  awaitingPayment = false,
}: {
  email: string;
  awaitingPayment?: boolean;
}) {
  const queryClient = useQueryClient();
  const key = ["subscriptions", email];
  const [pollUntil] = useState(() => (awaitingPayment ? Date.now() + 60_000 : 0));
  const subs = useQuery({
    queryKey: key,
    queryFn: listSubscriptions,
    // Right after paying, ECPay's server-to-server callback may land a few seconds after the
    // browser returns: refresh while any card is still pending, for up to a minute.
    refetchInterval: (query) =>
      Date.now() < pollUntil &&
      query.state.data?.subscriptions.some((s) => s.subscription_status === "pending_payment")
        ? 3000
        : false,
  });
  const byRoute = new Map((subs.data?.subscriptions ?? []).map((s) => [s.route, s] as const));
  const price = subs.data?.monthly_price;

  return (
    <section className="w-full max-w-5xl">
      <div className="text-center">
        <h2 className="text-2xl font-bold">選一條航線，設定目標價</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {price
            ? `每條航線月費 ${twd(price)}，以信用卡定期定額扣款，隨時可取消。`
            : "以信用卡定期定額按月扣款，隨時可取消。"}
          我們每 30 分鐘查一次票價，降到目標價就寄信通知你。
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
            price={price}
            current={byRoute.get(plan.route)}
            loading={subs.isLoading}
            onChanged={() => queryClient.invalidateQueries({ queryKey: key })}
          />
        ))}
      </div>
    </section>
  );
}

function PlanCard({
  plan,
  price,
  current,
  loading,
  onChanged,
}: {
  plan: (typeof PLANS)[number];
  price: number | undefined;
  current: Subscription | undefined;
  loading: boolean;
  onChanged: () => void;
}) {
  const status = current?.subscription_status;
  const paid = status === "active" || status === "cancelled";
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  const save = useMutation({
    mutationFn: (target: number) =>
      saveSubscription({ plan_name: plan.name, target_price: target }),
    onSuccess: (result) => {
      if (result.kind === "checkout") {
        setRedirecting(true);
        goToCheckout(result.html);
        return;
      }
      setEditing(false);
      setValue("");
      onChanged();
    },
    onError: (e: Error) => setError(e.message),
  });

  const cancel = useMutation({
    mutationFn: () => cancelSubscription(plan.route),
    onSuccess: () => {
      setConfirmCancel(false);
      onChanged();
    },
    onError: (e: Error) => setError(e.message),
  });

  const busy = loading || save.isPending || cancel.isPending || redirecting;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const target = Number(value);
    if (!Number.isFinite(target) || target <= 0) return setError("請輸入大於 0 的台幣金額。");
    save.mutate(Math.round(target));
  }

  function payWithCurrentTarget() {
    setError(null);
    if (current) save.mutate(current.target_price);
  }

  const showForm = !current || editing;
  const submitLabel = redirecting
    ? "前往付款頁面…"
    : save.isPending
      ? "處理中…"
      : paid
        ? "儲存新目標價"
        : `訂閱並付款${price ? ` ${twd(price)}/月` : ""}`;

  return (
    <div className="flex flex-col rounded-2xl border border-border bg-card p-6 text-left">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-semibold">{plan.title}</h3>
          <p className="text-sm text-primary-glow">{plan.route}</p>
        </div>
        {status && (
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${BADGE[status].className}`}
          >
            {BADGE[status].icon} {BADGE[status].label}
          </span>
        )}
      </div>

      {current && !editing && (
        <div className="mt-5 flex flex-1 flex-col">
          <p className="text-sm text-muted-foreground">目標價 Target</p>
          <p className="text-3xl font-bold">{twd(current.target_price)}</p>
          <StatusNote current={current} />
          {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

          <div className="mt-auto flex flex-wrap gap-2 pt-5">
            {status === "pending_payment" && (
              <Button variant="hero" onClick={payWithCurrentTarget} disabled={busy}>
                <CreditCard /> {redirecting ? "前往付款頁面…" : "完成付款"}
              </Button>
            )}
            {status === "expired" && (
              <Button variant="hero" onClick={payWithCurrentTarget} disabled={busy}>
                <RotateCcw /> {redirecting ? "前往付款頁面…" : "重新訂閱"}
              </Button>
            )}
            <Button variant="outline" onClick={() => setEditing(true)} disabled={busy}>
              更新目標價
            </Button>
            {status === "active" && !confirmCancel && (
              <Button variant="ghost" onClick={() => setConfirmCancel(true)} disabled={busy}>
                取消訂閱
              </Button>
            )}
          </div>

          {status === "active" && confirmCancel && (
            <div className="mt-4 rounded-xl border border-border bg-muted/60 p-4">
              <p className="text-sm">
                確定要取消嗎？之後不會再扣款，已付費的這一期
                {current.current_period_end_date ? `（到 ${current.current_period_end_date}）` : ""}
                仍會繼續通知你。
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => cancel.mutate()}
                  disabled={busy}
                >
                  {cancel.isPending ? "取消中…" : "確定取消"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmCancel(false)}
                  disabled={busy}
                >
                  先不要
                </Button>
              </div>
            </div>
          )}
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
            disabled={busy}
          />
          <p className="text-xs text-muted-foreground">
            目前最低價約 {twd(plan.hint)}，可以設定在這附近。
            {!paid && " 送出後會前往綠界付款頁面。"}
          </p>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="mt-auto flex gap-2 pt-2">
            <Button type="submit" variant="hero" disabled={busy}>
              <BellRing /> {submitLabel}
            </Button>
            {editing && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => setEditing(false)}
                disabled={busy}
              >
                取消
              </Button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

function StatusNote({ current }: { current: Subscription }) {
  const until = current.current_period_end_date;
  const text: Record<SubscriptionStatus, string> = {
    active: `票價低於或等於目標價時會寄信通知你。${until ? `本期有效至 ${until}，之後每月自動續訂。` : ""}`,
    pending_payment: "尚未完成付款，付款後才會開始通知。",
    cancelled: `已停止續訂。${until ? `${until} 之前仍會通知你。` : ""}`,
    expired: "訂閱已結束，不會再通知。重新訂閱即可恢復。",
  };
  return <p className="mt-2 text-xs text-muted-foreground">{text[current.subscription_status]}</p>;
}
