import type { RouteObject } from "react-router";

import { RootLayout, NotFoundComponent, ErrorComponent } from "@/pages/RootLayout";
import { RequireAuth } from "@/components/RequireAuth";
import Index from "@/pages/Index";
import SignIn from "@/pages/SignIn";
import SignUp from "@/pages/SignUp";
import AppPage from "@/pages/App";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <RootLayout />,
    errorElement: <ErrorComponent />,
    children: [
      { index: true, element: <Index /> },
      { path: "signin", element: <SignIn /> },
      { path: "signup", element: <SignUp /> },
      {
        element: <RequireAuth />,
        children: [{ path: "app", element: <AppPage /> }],
      },
      { path: "*", element: <NotFoundComponent /> },
    ],
  },
];
