import { matchRoutes } from "react-router";
import { describe, expect, it } from "vitest";

import { routes } from "@/routes";
import Index from "@/pages/Index";
import SignIn from "@/pages/SignIn";
import SignUp from "@/pages/SignUp";
import AppPage from "@/pages/App";
import { NotFoundComponent } from "@/pages/RootLayout";
import { RequireAuth } from "@/components/RequireAuth";

// Match routes without rendering: rendering would need Supabase and a network.
function leafElementType(path: string) {
  const matches = matchRoutes(routes, path);
  return (matches?.at(-1)?.route.element as { type?: unknown } | undefined)?.type;
}

describe("App routing", () => {
  it.each([
    ["/", Index],
    ["/signin", SignIn],
    ["/signup", SignUp],
    ["/app", AppPage],
  ])("matches %s to its page", (path, component) => {
    expect(leafElementType(path)).toBe(component);
  });

  it("guards /app behind RequireAuth", () => {
    const matches = matchRoutes(routes, "/app") ?? [];
    const types = matches.map((m) => (m.route.element as { type?: unknown } | undefined)?.type);
    expect(types).toContain(RequireAuth);
  });

  it("falls back to the 404 page for unknown paths", () => {
    expect(leafElementType("/does-not-exist")).toBe(NotFoundComponent);
  });
});
