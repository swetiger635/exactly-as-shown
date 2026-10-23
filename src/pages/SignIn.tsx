import { AuthForm } from "@/components/AuthForm";
import { useHead } from "@/hooks/use-head";

export default function SignIn() {
  useHead({
    title: "Sign in · Flight Price Notifier",
    meta: [
      {
        name: "description",
        content: "Sign in to Flight Price Notifier to manage your fare alerts.",
      },
      { property: "og:title", content: "Sign in · Flight Price Notifier" },
      { property: "og:description", content: "Sign in to manage your fare alerts." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  });
  return <AuthForm mode="signin" />;
}
