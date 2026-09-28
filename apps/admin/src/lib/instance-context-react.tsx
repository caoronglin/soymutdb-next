import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { listSpeciesInstances, type SpeciesInstance } from "@soymutdb/api-client";

export const ADMIN_INSTANCES_QUERY_KEY = ["admin", "species-instances"] as const;

export interface AdminInstanceContextValue {
  instances: SpeciesInstance[];
  localInstance: SpeciesInstance | null;
  currentInstance: SpeciesInstance | null;
  isRemote: boolean;
  isLoading: boolean;
  isError: boolean;
  selectInstance: (code: string | null) => void;
}

const InstanceContext = React.createContext<AdminInstanceContextValue | null>(null);

export function InstanceContextProvider({ children }: React.PropsWithChildren) {
  const [selectedCode, setSelectedCode] = React.useState<string | null>(null);
  const query = useQuery({
    queryKey: ADMIN_INSTANCES_QUERY_KEY,
    queryFn: listSpeciesInstances,
    staleTime: 30_000,
    retry: false,
  });

  const instances = React.useMemo(() => query.data?.items ?? [], [query.data]);
  const localInstance = React.useMemo(
    () => instances.find((instance) => instance.is_local) ?? null,
    [instances],
  );
  const currentInstance = React.useMemo(
    () => instances.find((instance) => instance.code === selectedCode) ?? localInstance,
    [instances, localInstance, selectedCode],
  );
  const value = React.useMemo<AdminInstanceContextValue>(
    () => ({
      instances,
      localInstance,
      currentInstance,
      isRemote: Boolean(currentInstance && !currentInstance.is_local),
      isLoading: query.isLoading,
      isError: query.isError,
      selectInstance: setSelectedCode,
    }),
    [instances, localInstance, currentInstance, query.isLoading, query.isError],
  );

  return <InstanceContext.Provider value={value}>{children}</InstanceContext.Provider>;
}

export function useInstanceContext(): AdminInstanceContextValue {
  const value = React.useContext(InstanceContext);
  if (!value) throw new Error("useInstanceContext must be used within InstanceContextProvider");
  return value;
}
