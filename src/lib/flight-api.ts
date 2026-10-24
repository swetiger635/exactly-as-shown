// Client for the Flight Price Notifier API (AWS API Gateway → Lambda → DynamoDB).
// The browser holds no AWS credentials; it only calls these public HTTP endpoints.
const API_URL: string = (import.meta.env["VITE_FLIGHT_API_URL"] ?? "").replace(/\/+$/, "");

export type PlanName = "tokyo" | "seoul";

export type Subscription = {
  email: string;
  route: string;
  plan_name: PlanName;
  origin: string;
  destination: string;
  target_price: number;
  currency: "TWD";
  created_at: string;
  updated_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_URL) throw new Error("Missing VITE_FLIGHT_API_URL.");
  const res = await fetch(`${API_URL}${path}`, init);
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new Error(data.error ?? `Request failed (${res.status})`);
  return data;
}

export async function listSubscriptions(email: string): Promise<Subscription[]> {
  const data = await request<{ subscriptions: Subscription[] }>(
    `/subscriptions?email=${encodeURIComponent(email)}`,
  );
  return data.subscriptions;
}

export async function saveSubscription(input: {
  email: string;
  plan_name: PlanName;
  target_price: number;
}): Promise<void> {
  await request("/subscribe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
}
