// Client for the Flight Price Notifier API (AWS API Gateway → Lambda → DynamoDB).
// The browser holds no AWS credentials. Every call carries the signed-in user's Supabase access
// token; the Lambdas verify it and use that account's email (never an email sent by the client).
import { supabase } from "@/integrations/supabase/client";

const API_URL: string = (import.meta.env["VITE_FLIGHT_API_URL"] ?? "").replace(/\/+$/, "");

export type PlanName = "tokyo" | "seoul" | "london";

export type SubscriptionStatus = "pending_payment" | "active" | "cancelled" | "expired";

export type Subscription = {
  email: string;
  route: string;
  plan_name: PlanName;
  origin: string;
  destination: string;
  target_price: number;
  currency: "TWD";
  subscription_status: SubscriptionStatus;
  current_period_end?: string;
  current_period_end_date?: string;
  created_at: string;
  updated_at: string;
};

export type SubscriptionList = { subscriptions: Subscription[]; monthly_price: number };

/** `checkout`: hand the browser to ECPay. `updated`: target changed in place (already paid). */
export type SaveResult = { kind: "checkout"; html: string } | { kind: "updated" };

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("請重新登入。Please sign in again.");
  return { Authorization: `Bearer ${token}` };
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  if (!API_URL) throw new Error("Missing VITE_FLIGHT_API_URL.");
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...(init.headers as Record<string, string>), ...(await authHeaders()) },
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(data.error ?? `Request failed (${res.status})`);
  }
  return res;
}

export async function listSubscriptions(): Promise<SubscriptionList> {
  return (await call("/subscriptions")).json() as Promise<SubscriptionList>;
}

export async function saveSubscription(input: {
  plan_name: PlanName;
  target_price: number;
}): Promise<SaveResult> {
  const res = await call("/subscribe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  // text/html = auto-submitting ECPay checkout form; application/json = in-place update.
  if ((res.headers.get("content-type") ?? "").includes("text/html")) {
    return { kind: "checkout", html: await res.text() };
  }
  return { kind: "updated" };
}

export async function cancelSubscription(
  route: string,
): Promise<{ current_period_end_date?: string }> {
  const res = await call("/cancel", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ route }),
  });
  return res.json() as Promise<{ current_period_end_date?: string }>;
}

/** Replace the page with ECPay's checkout form; its inline script posts the browser to the cashier. */
export function goToCheckout(html: string) {
  document.open();
  document.write(html);
  document.close();
}
