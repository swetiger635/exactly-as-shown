import { AuthForm } from "@/components/AuthForm";
import { useHead } from "@/hooks/use-head";

export default function SignUp() {
  useHead({
    title: "Sign up · Flight Price Notifier",
    meta: [
      {
        name: "description",
        content: "Create a Flight Price Notifier account and get emailed when fares drop.",
      },
      { property: "og:title", content: "Sign up · Flight Price Notifier" },
      { property: "og:description", content: "Create an account and get emailed when fares drop." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  });
  return <AuthForm mode="signup" />;
}
