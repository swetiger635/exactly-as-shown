import { createFileRoute, Link } from "@tanstack/react-router";
import { Radar, BellRing, CircleX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SiteHeader, SiteFooter } from "@/components/SiteHeader";
import { Reveal } from "@/components/Reveal";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Flight Price Notifier 機票降價通知" },
      { name: "description", content: "設定航線與目標價，機票降價就通知你。Set a route and a target price — we email you when the fare drops." },
      { property: "og:title", content: "Flight Price Notifier 機票降價通知" },
      { property: "og:description", content: "Set a route and a target price — we email you when the fare drops." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

const features = [
  { icon: Radar, title: "盯緊熱門航線", en: "Always-on route watching", body: "持續監控台北出發的熱門航線（東京、首爾），自動抓最低票價。" },
  { icon: BellRing, title: "達標自動通知", en: "Target-price email alerts", body: "低於你設定的目標價，就寄 email 提醒你，附上立即訂購連結。" },
  { icon: CircleX, title: "隨時取消", en: "Cancel anytime", body: "月訂閱制，不想用隨時停，沒有綁約。" },
];

function Index() {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader right={<Button asChild variant="hero"><Link to="/signin">Sign in / 登入</Link></Button>} />
      <main className="flex-1">
        <section className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-0 bg-gradient-glow" />
          <div className="relative mx-auto max-w-4xl px-5 pb-24 pt-24 text-center md:pt-32">
            <p className="fade-up mb-6 inline-block rounded-full border border-border bg-card px-4 py-1 text-xs text-muted-foreground">
              TPE → NRT · HND · ICN
            </p>
            <h1 className="fade-up text-5xl font-extrabold tracking-tight md:text-7xl">
              <span className="text-gradient">Flight Price</span> Notifier
            </h1>
            <p className="fade-up mt-6 text-xl font-medium md:text-2xl">設定航線與目標價，機票降價就通知你</p>
            <p className="fade-up mt-3 text-muted-foreground">Set a route and a target price — we email you when the fare drops.</p>
            <div className="fade-up mt-10">
              <Button asChild variant="hero" size="lg"><Link to="/signup">免費開始 Get started</Link></Button>
            </div>
          </div>
        </section>
        <section className="mx-auto grid max-w-6xl gap-5 px-5 pb-28 md:grid-cols-3">
          {features.map((f, i) => (
            <Reveal key={f.title} delay={i * 100}>
              <div className="h-full rounded-2xl border border-border bg-card p-7 transition-colors hover:border-primary/50">
                <span className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-accent">
                  <f.icon className="h-5 w-5 text-primary-glow" />
                </span>
                <h3 className="text-lg font-semibold">{f.title}</h3>
                <p className="text-sm text-primary-glow">{f.en}</p>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{f.body}</p>
              </div>
            </Reveal>
          ))}
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
