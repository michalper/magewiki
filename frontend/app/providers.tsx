"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";
import { OnboardingProvider } from "@/components/onboarding-wizard";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="dark">
        <OnboardingProvider>{children}</OnboardingProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
