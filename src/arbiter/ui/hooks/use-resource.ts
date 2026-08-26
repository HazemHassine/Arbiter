"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

export interface ResourceState<T> {
  data: T;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<T | undefined>;
}

export function useResource<T>(path: string | null, initial: T, refreshKey = 0): ResourceState<T> {
  const [data, setData] = useState<T>(initial);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));

  const refresh = useCallback(async () => {
    if (!path) return undefined;
    setLoading(true);
    setError(null);
    try {
      const result = await api<T>(path);
      setData(result);
      return result;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load data");
      return undefined;
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  return { data, error, loading, refresh };
}
