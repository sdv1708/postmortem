"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

// App-wide TanStack Query provider (ADR 0001). The status page polls run state
// through this client rather than using SSE or token streaming (ADR 0005).
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Run status is fetched fresh on demand; polling is configured per
            // query (see the run status hook) so terminal runs stop polling.
            staleTime: 0,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
