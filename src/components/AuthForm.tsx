import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SiteHeader } from "@/components/SiteHeader";

export function AuthForm({ mode }: { mode: "signin" | "signup" }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const isUp = mode === "signup";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { data, error } = isUp
      ? await supabase.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin + "/app" } })
      : await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) return setError(error.message);
    if (!data.session) return setError("請到信箱確認後再登入。Check your email to confirm.");
    navigate("/app");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader right={null} />
      <main className="relative flex flex-1 items-center justify-center px-5 py-16">
        <div className="pointer-events-none absolute inset-0 bg-gradient-glow" />
        <form onSubmit={onSubmit} className="fade-up relative w-full max-w-sm space-y-5 rounded-2xl border border-border bg-card p-8">
          <div>
            <h1 className="text-2xl font-bold">{isUp ? "Sign up / 註冊" : "Sign in / 登入"}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{isUp ? "建立帳號開始追蹤票價" : "歡迎回來"}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" variant="hero" className="w-full" disabled={loading}>
            {loading ? "…" : isUp ? "Create account" : "Sign in"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            {isUp ? "已經有帳號？ " : "還沒有帳號？ "}
            <Link to={isUp ? "/signin" : "/signup"} className="text-primary-glow hover:underline">
              {isUp ? "Sign in" : "Sign up"}
            </Link>
          </p>
        </form>
      </main>
    </div>
  );
}
