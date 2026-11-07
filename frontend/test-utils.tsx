import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

// Matches app/providers.tsx's real QueryClient, except retry:false and no
// garbage-collection delay -- a failed test query shouldn't actually retry
// (slow, flaky) and each test gets a fresh client, so nothing needs to
// survive past one render.
export function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}
